"""Computational baseline: notes from conventional commits only, no agent involved.

Used with ``--agent none``, as an optional fallback when the agent fails, and as a preview of
what the evidence alone says.
"""

from __future__ import annotations

from agentic_release_notes.commits import Commit
from agentic_release_notes.notes import Item, ReleaseNotes

TYPE_TO_SECTION = {
    "feat": "features",
    "feature": "features",
    "fix": "fixes",
    "bugfix": "fixes",
    "perf": "improvements",
    "improve": "improvements",
    "security": "security",
    "sec": "security",
    "deprecate": "deprecations",
    "docs": "documentation",
}


def _title(commit: Commit) -> str:
    text = commit.description or commit.subject
    text = text[:1].upper() + text[1:]
    return f"{commit.scope}: {text}" if commit.scope else text


def deterministic_notes(commits: list[Commit]) -> ReleaseNotes:
    notes = ReleaseNotes(generator="deterministic")
    conventional = any(c.type for c in commits)
    seen: set[str] = set()
    for commit in reversed(commits):  # oldest first reads naturally
        if commit.is_merge and not commit.type:
            continue
        if commit.breaking:
            kind = "breaking"
        elif conventional:
            kind = TYPE_TO_SECTION.get(commit.type or "")
            if commit.scope and commit.scope.lower() in {"security", "sec"}:
                kind = "security"
        else:
            kind = "improvements"  # no convention: list everything, unsorted
        if not kind:
            continue
        title = _title(commit)
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        action = "; ".join(commit.breaking_notes) or None
        if kind == "breaking" and not action:
            action = "See the linked change for migration details."
        notes.sections.setdefault(kind, []).append(
            Item(
                title=title,
                action=action,
                commits=[commit.sha],
                pull_requests=[commit.pull_request] if commit.pull_request else [],
            )
        )
    if not notes.user_facing:
        notes.maintenance = f"Internal maintenance only ({len(commits)} commits)."
    return notes
