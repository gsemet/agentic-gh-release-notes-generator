"""Generate validated notes: brief the agent, validate, feed errors back, render."""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agentic_release_notes.agents import Agent, AgentError
from agentic_release_notes.context import ReleaseContext
from agentic_release_notes.deterministic import deterministic_notes
from agentic_release_notes.git import Git
from agentic_release_notes.notes import NotesError, ReleaseNotes, extract_json, parse_notes
from agentic_release_notes.prompt import build_prompt, retry_prompt


class GenerationError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[release-notes] {message}", file=sys.stderr)


@contextmanager
def release_checkout(git: Git, commit: str, enabled: bool = True) -> Iterator[Path]:
    """A disposable worktree at the release commit: the agent sees exactly the released files
    and cannot touch the user's working tree."""
    if not enabled:
        yield git.cwd
        return
    tmp = Path(tempfile.mkdtemp(prefix="release-notes-"))
    path = tmp / "release"
    git.run("worktree", "add", "--detach", "--quiet", str(path), commit)
    try:
        yield path
    finally:
        git.run("worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def generate(
    ctx: ReleaseContext,
    agent: Agent | None,
    *,
    use_worktree: bool = True,
    debug_dir: Path | None = None,
) -> ReleaseNotes:
    if not ctx.commits:
        notes = ReleaseNotes(maintenance="No changes besides the release itself.")
    elif agent is None:
        notes = deterministic_notes(ctx.commits)
    else:
        notes = _agentic(ctx, agent, use_worktree, debug_dir)
    notes.label = ctx.release.label
    if notes.generator is None:
        notes.generator = agent.name if agent else "deterministic"
    ctx.attach_pull_requests(notes)
    return notes


def _agentic(
    ctx: ReleaseContext, agent: Agent, use_worktree: bool, debug_dir: Path | None
) -> ReleaseNotes:
    brief = build_prompt(ctx)
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "prompt.md").write_text(brief)
    attempts = max(1, ctx.config.agent.attempts)
    session = str(uuid.uuid4())
    resumable = False  # True once a session with the full brief exists
    errors: list[str] = []
    with release_checkout(ctx.git, ctx.release.target_commit, use_worktree) as cwd:
        for attempt in range(1, attempts + 1):
            if attempt == 1 or not errors:
                prompt = brief
            elif resumable and agent.supports_resume:
                prompt = retry_prompt(errors)
            else:
                prompt = f"{brief}\n\n{retry_prompt(errors)}"
            log(f"{agent.name}: attempt {attempt}/{attempts} ({len(prompt):,} characters)")
            try:
                answer = agent.ask(prompt, cwd, session, resume=resumable)
            except AgentError as error:
                log(str(error))
                errors = [str(error)]
                session, resumable = str(uuid.uuid4()), False
                continue
            resumable = True
            if debug_dir:
                (debug_dir / f"answer-{attempt}.txt").write_text(answer)
            try:
                notes = parse_notes(extract_json(answer))
                errors = ctx.validate(notes)
            except NotesError as error:
                errors = error.errors
            if not errors:
                return notes
            log(f"answer rejected ({len(errors)} problems):\n  " + "\n  ".join(errors))
            if debug_dir:
                (debug_dir / f"errors-{attempt}.txt").write_text("\n".join(errors))
    if ctx.config.agent.fallback == "deterministic":
        log("falling back to deterministic conventional-commit notes")
        notes = deterministic_notes(ctx.commits)
        notes.generator = "deterministic (fallback)"
        return notes
    raise GenerationError(
        f"{agent.name} gave no valid notes after {attempts} attempts:\n- " + "\n- ".join(errors)
    )
