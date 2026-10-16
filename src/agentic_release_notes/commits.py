"""Commits of a release range, with conventional-commit and forge metadata parsed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentic_release_notes.git import Git

_CONVENTIONAL = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)
_BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:\s*(?P<text>.+)", re.M)
_PR_SUBJECT = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)|See merge request !(\d+)")
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)


@dataclass
class Commit:
    sha: str
    short: str
    author: str
    date: str
    subject: str
    body: str
    parents: list[str]
    files: list[str] = field(default_factory=list)
    type: str | None = None
    scope: str | None = None
    description: str | None = None
    breaking: bool = False
    breaking_notes: list[str] = field(default_factory=list)
    pull_request: int | None = None
    closes: list[int] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    def summary_line(self) -> str:
        flags = []
        if self.breaking:
            flags.append("BREAKING")
        if self.pull_request:
            flags.append(f"PR #{self.pull_request}")
        if self.closes:
            flags.append("closes " + ", ".join(f"#{n}" for n in self.closes))
        if self.is_merge:
            flags.append("merge")
        suffix = f"  [{'; '.join(flags)}]" if flags else ""
        return f"{self.short} {self.subject}{suffix}"


def parse_message(commit: Commit) -> Commit:
    match = _CONVENTIONAL.match(commit.subject)
    if match:
        commit.type = match["type"].lower()
        commit.scope = match["scope"] or None
        commit.description = match["subject"].strip()
        commit.breaking = bool(match["bang"])
    notes = [m["text"].strip() for m in _BREAKING_FOOTER.finditer(commit.body)]
    if notes:
        commit.breaking = True
        commit.breaking_notes = notes
    pr = _PR_SUBJECT.search(commit.subject) or _PR_SUBJECT.search(commit.body)
    if pr:
        commit.pull_request = int(next(g for g in pr.groups() if g))
    commit.closes = sorted({int(n) for n in _CLOSES.findall(f"{commit.subject}\n{commit.body}")})
    return commit


def collect_commits(
    git: Git, log_range: str, paths: list[str], ignore: list[str]
) -> tuple[list[Commit], list[Commit]]:
    """Return (kept, ignored) commits, newest first. Ignored ones are release/bump noise."""
    fmt = "%x1e%H%x1f%h%x1f%an%x1f%aI%x1f%P%x1f%s%x1f%b%x1f"
    raw = git.run(
        "log",
        f"--format={fmt}",
        "--name-only",
        "--no-renames",
        log_range,
        "--",
        *paths,
        strip=False,
    )
    ignore_re = [re.compile(p) for p in ignore]
    kept, ignored = [], []
    for record in raw.split("\x1e")[1:]:
        parts = record.split("\x1f")
        sha, short, author, date, parents, subject, body = parts[:7]
        files = [f for f in (parts[7] if len(parts) > 7 else "").splitlines() if f.strip()]
        commit = parse_message(
            Commit(
                sha=sha,
                short=short,
                author=author,
                date=date,
                subject=subject.strip(),
                body=body.strip(),
                parents=parents.split(),
                files=files,
            )
        )
        is_noise = any(r.search(commit.subject) for r in ignore_re)
        # Merge commits without their own content only matter for their PR title.
        (ignored if is_noise else kept).append(commit)
    return kept, ignored
