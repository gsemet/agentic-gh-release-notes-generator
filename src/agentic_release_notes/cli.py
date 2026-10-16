"""Command line interface.

Every stage of the pipeline is a subcommand, so the tool composes with CI jobs, IDE agents
(through the packaged skill) and humans alike:

    range     which commits a release covers
    docs      the documentation index (public URLs and anchors)
    context   the full agent brief, for an agent you drive yourself
    generate  brief an agent, validate its answer, render the notes
    validate  check notes JSON against the evidence and the docs index
    render    render notes JSON as GitHub release, changelog entry or JSON
    publish   create or update the GitHub release with the notes
    init      print a starter configuration with what was detected
    skill     print or install the agent skill for interactive use
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib import resources
from pathlib import Path

from agentic_release_notes import __version__
from agentic_release_notes.agents import AgentError, get_agent
from agentic_release_notes.config import Config, load_config
from agentic_release_notes.context import ReleaseContext, build_context
from agentic_release_notes.git import Git, GitError
from agentic_release_notes.notes import NotesError, extract_json, parse_notes
from agentic_release_notes.pipeline import GenerationError, generate, log
from agentic_release_notes.prompt import build_prompt
from agentic_release_notes.render import render, renderers


def _range_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository (default: .)")
    parser.add_argument("--config", type=Path, help="configuration file (TOML)")
    parser.add_argument(
        "--to",
        dest="target",
        help="release ref: tag, branch or sha (default: tag on HEAD, else HEAD)",
    )
    parser.add_argument(
        "--from", dest="previous", help="previous release ref (default: previous release tag)"
    )
    parser.add_argument(
        "--version",
        dest="version_label",
        help="label an untagged target, e.g. v1.4.0 before tagging it",
    )
    parser.add_argument(
        "--path", action="append", default=[], help="limit to a path (monorepo), repeatable"
    )


def _load(args: argparse.Namespace) -> tuple[Config, ReleaseContext]:
    root = Git(args.repo).toplevel()
    config = load_config(root, args.config)
    config.paths += args.path
    for key in ("agent", "model", "attempts", "fallback"):
        value = getattr(args, key, None)
        if value is not None:
            setattr(config.agent, "backend" if key == "agent" else key, value)
    if getattr(args, "lenient_links", False):
        config.links.strict = False
    if getattr(args, "require_links", False):
        config.links.require = True
    ctx = build_context(root, config, args.target, args.previous, args.version_label)
    for warning in ctx.warnings:
        log(f"warning: {warning}")
    return config, ctx


def _write(text: str, output: Path | None) -> None:
    if output is None or str(output) == "-":
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        log(f"wrote {output}")


def _read_notes(path: str):
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    return parse_notes(extract_json(text))


# --------------------------------------------------------------------------------------------


def cmd_range(args: argparse.Namespace) -> int:
    _, ctx = _load(args)
    data = ctx.release.as_dict()
    data["commits"] = [c.summary_line() for c in ctx.commits]
    data["ignored_commits"] = [c.summary_line() for c in ctx.ignored_commits]
    print(json.dumps(data, indent=2))
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    _, ctx = _load(args)
    if args.json:
        data = [
            {
                "site": s.name,
                "kind": s.kind,
                "base_url": s.base_url,
                "pages": [p.__dict__ for p in s.pages],
            }
            for s in ctx.docs.sites
        ]
        print(json.dumps(data, indent=2))
    else:
        print(ctx.docs.render(max_chars=10**9))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    _, ctx = _load(args)
    _write(build_prompt(ctx), args.output)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    config, ctx = _load(args)
    agent = get_agent(config.agent)
    notes = generate(ctx, agent, use_worktree=not args.no_worktree, debug_dir=args.debug_dir)
    if args.json_output:
        _write(notes.to_json(), args.json_output)
    _write(render(notes, args.format or config.format, ctx.render_options()), args.output)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    _, ctx = _load(args)
    try:
        notes = _read_notes(args.notes)
        errors = ctx.validate(notes)
    except NotesError as error:
        errors = error.errors
    if errors:
        print("Invalid release notes:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    log("release notes are valid")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    config, ctx = _load(args)
    notes = _read_notes(args.notes)
    if not args.no_validate:
        errors = ctx.validate(notes)
        if errors:
            print("Invalid release notes:\n- " + "\n- ".join(errors), file=sys.stderr)
            return 1
    ctx.attach_pull_requests(notes)
    notes.label = notes.label or ctx.release.label
    _write(render(notes, args.format or config.format, ctx.render_options()), args.output)
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    exists = (
        subprocess.run(
            ["gh", "release", "view", args.tag], capture_output=True, cwd=args.repo
        ).returncode
        == 0
    )
    if exists and not args.update:
        print(f"Release {args.tag} exists; pass --update to replace its notes", file=sys.stderr)
        return 1
    if exists:
        command = ["gh", "release", "edit", args.tag, "--notes-file", str(args.notes)]
    else:
        command = [
            "gh",
            "release",
            "create",
            args.tag,
            "--verify-tag",
            "--title",
            args.title or args.tag,
            "--notes-file",
            str(args.notes),
        ]
        if args.draft:
            command.append("--draft")
        if args.prerelease:
            command.append("--prerelease")
    return subprocess.run(command, cwd=args.repo).returncode


def cmd_init(args: argparse.Namespace) -> int:
    _, ctx = _load(args)
    lines = [
        "# .release-notes.toml (or [tool.agentic-release-notes] in pyproject.toml)",
        f'product = "{ctx.project.name or "my-project"}: {ctx.project.description or "..."}"',
        'audience = "people who use ... to ..."',
        f'tag_pattern = "{ctx.config.tag_pattern}"',
        '# guidance = """Project-specific editorial rules for the agent."""',
        "",
        "[agent]",
        'backend = "auto"  # copilot | claude | codex | command | none',
        'fallback = "error"  # or "deterministic"',
        "",
        "[links]",
        "strict = true",
        "require = false",
        "",
    ]
    for site in ctx.docs.sites:
        lines += [f"# detected: {len(site.pages)} pages", "[[docs]]", f'type = "{site.provider}"']
        if site.provider != "markdown":
            lines.append(f'base_url = "{site.base_url}"')
        lines.append("")
    for warning in ctx.docs.warnings:
        lines.append(f"# warning: {warning}")
    print("\n".join(lines))
    return 0


def cmd_skill(args: argparse.Namespace) -> int:
    text = resources.files("agentic_release_notes").joinpath("data/SKILL.md").read_text()
    if args.install:
        target = args.install / "release-notes" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        log(f"installed {target}")
    else:
        sys.stdout.write(text)
    return 0


# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-release-notes",
        description="Agentic, evidence-checked, user-facing release notes.",
        epilog="Run '<command> --help' for details. Docs: "
        "https://github.com/gsemet/agentic-gh-release-notes-generator",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("range", help="show the resolved release range and its commits")
    _range_args(p)
    p.set_defaults(func=cmd_range)

    p = sub.add_parser("docs", help="show the documentation index used for links")
    _range_args(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("context", help="print the agent brief (to drive an agent yourself)")
    _range_args(p)
    p.add_argument("-o", "--output", type=Path)
    p.set_defaults(func=cmd_context)

    formats = sorted(renderers())
    p = sub.add_parser("generate", help="generate validated release notes with an agent")
    _range_args(p)
    p.add_argument("--agent", help="auto, copilot, claude, codex, command or none")
    p.add_argument("--model")
    p.add_argument("--attempts", type=int)
    p.add_argument("--fallback", choices=["error", "deterministic"])
    p.add_argument("--format", choices=formats)
    p.add_argument("-o", "--output", type=Path, help="rendered notes (default: stdout)")
    p.add_argument("--json-output", type=Path, help="also write the structured notes")
    p.add_argument("--lenient-links", action="store_true", help="do not check links against docs")
    p.add_argument("--require-links", action="store_true", help="features must link docs")
    p.add_argument("--no-worktree", action="store_true", help="run the agent in the repo itself")
    p.add_argument("--debug-dir", type=Path, help="save prompt, answers and errors there")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("validate", help="validate notes JSON (file or -) for a release")
    _range_args(p)
    p.add_argument("notes")
    p.add_argument("--lenient-links", action="store_true")
    p.add_argument("--require-links", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("render", help="render notes JSON (file or -)")
    _range_args(p)
    p.add_argument("notes")
    p.add_argument("--format", choices=formats)
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("publish", help="create or update a GitHub release (needs gh)")
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--tag", required=True)
    p.add_argument("--notes", type=Path, required=True, help="rendered notes file")
    p.add_argument("--title")
    p.add_argument("--draft", action="store_true")
    p.add_argument("--prerelease", action="store_true")
    p.add_argument("--update", action="store_true", help="replace notes of an existing release")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("init", help="print a starter configuration from what is detected")
    _range_args(p)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("skill", help="print or install the interactive agent skill")
    p.add_argument("--install", type=Path, help="skills directory, e.g. .github/skills")
    p.set_defaults(func=cmd_skill)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except (GitError, AgentError, GenerationError, NotesError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
