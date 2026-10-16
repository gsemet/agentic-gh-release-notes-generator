"""Resolve which commits a release covers, for any tagging habit.

Handled cases:

- tags created by a release commit (commitizen, semantic-release) or on any commit (scm
  versioning, manual tags); release/bump commits are filtered later from the evidence;
- several tags on the same commit, prefixed or monorepo tags (via the tag scheme);
- a stable release compared with the previous *stable* release, skipping release candidates;
- an untagged target (``HEAD``, a branch, a sha), optionally labelled with ``--version`` to
  generate notes before tagging;
- the first release (no previous tag: the whole history up to the target);
- a previous tag that is not an ancestor (release / backport branches): commits are those
  reachable from the target only, and the diff is the user-visible difference between the
  two releases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from agentic_release_notes.git import Git, GitError, list_tags
from agentic_release_notes.versions import TagScheme, is_prerelease, parse_version


@dataclass
class ReleaseRange:
    target: str  # ref as requested
    target_commit: str
    target_tag: str | None  # tag naming the release, when it exists
    label: str  # human label: tag, --version override or "Unreleased"
    version: str | None
    previous_tag: str | None
    previous_commit: str | None
    first_release: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def log_range(self) -> str:
        return (
            f"{self.previous_commit}..{self.target_commit}"
            if self.previous_commit
            else (self.target_commit)
        )

    @property
    def display(self) -> str:
        start = self.previous_tag or (self.previous_commit or "")[:12] or "(first commit)"
        return f"{start}..{self.target_tag or self.label}"

    def as_dict(self) -> dict:
        return asdict(self)


def _sort_key(version_text: str | None, date: str):
    version = parse_version(version_text)
    return (version is not None, version or parse_version("0"), date)


def resolve_range(
    git: Git,
    scheme: TagScheme,
    target: str | None = None,
    previous: str | None = None,
    version: str | None = None,
    prerelease_baseline: str = "stable",
) -> ReleaseRange:
    warnings: list[str] = []
    if git.is_shallow():
        raise GitError(
            "Shallow clone: release ranges need the full history and tags "
            "(actions/checkout: fetch-depth: 0, or `git fetch --unshallow --tags`)."
        )
    tags = list_tags(git)
    matching = [(t, scheme.version_of(t.name)) for t in tags]
    matching = [(t, v) for t, v in matching if v is not None]

    target = target or _default_target(git, matching)
    target_commit = git.commit(target)
    if not target_commit:
        raise GitError(f"Unknown target ref {target!r}")

    # The tag naming the release: the requested tag, or the highest matching tag on the commit.
    target_tag = None
    target_version = None
    requested = next((t for t, _ in matching if t.name == target), None)
    if requested:
        target_tag, target_version = requested.name, scheme.version_of(requested.name)
    else:
        on_commit = [(t, v) for t, v in matching if t.commit == target_commit]
        if on_commit:
            best = max(on_commit, key=lambda tv: _sort_key(tv[1], tv[0].date))
            target_tag, target_version = best[0].name, best[1]
            if target not in {"HEAD", target_commit}:
                warnings.append(f"{target} points at release tag {target_tag}")
        elif any(t.name == target for t in tags):
            warnings.append(f"Tag {target!r} does not match the tag pattern {scheme.pattern!r}")
    if version:
        target_version = scheme.version_of(version) or version.lstrip("v")
    label = version or target_tag or "Unreleased"

    previous_tag = previous_commit = None
    if previous:
        previous_commit = git.commit(previous)
        if not previous_commit:
            raise GitError(f"Unknown previous ref {previous!r}")
        previous_tag = previous if git.commit(f"refs/tags/{previous}") else None
    else:
        previous_tag, previous_commit = _previous_release(
            git, matching, target_commit, target_tag, target_version, prerelease_baseline, warnings
        )

    if previous_commit:
        if previous_commit == target_commit:
            raise GitError(f"{previous_tag or previous} and {target} are the same commit")
        if git.is_ancestor(target_commit, previous_commit):
            raise GitError(f"{target} is older than {previous_tag or previous}")
        if not git.is_ancestor(previous_commit, target_commit):
            warnings.append(
                f"{previous_tag or previous} is not an ancestor of {target}: commits are those "
                "only reachable from the target, the diff is the difference between releases"
            )
    return ReleaseRange(
        target=target,
        target_commit=target_commit,
        target_tag=target_tag,
        label=label,
        version=target_version,
        previous_tag=previous_tag,
        previous_commit=previous_commit,
        first_release=previous_commit is None,
        warnings=warnings,
    )


def _default_target(git: Git, matching) -> str:
    head = git.commit("HEAD")
    on_head = [(t, v) for t, v in matching if t.commit == head]
    if on_head:
        return max(on_head, key=lambda tv: _sort_key(tv[1], tv[0].date))[0].name
    return "HEAD"


def _previous_release(git, matching, target_commit, target_tag, target_version, baseline, warnings):
    target_parsed = parse_version(target_version)
    want_stable = baseline == "stable" and target_version and not is_prerelease(target_version)
    candidates = []
    for tag, tag_version in matching:
        if tag.name == target_tag or tag.commit == target_commit:
            continue
        parsed = parse_version(tag_version)
        if target_parsed and parsed and parsed >= target_parsed:
            continue
        if want_stable and is_prerelease(tag_version):
            continue
        candidates.append((tag, tag_version))
    if not candidates:
        return None, None
    merged = set(git.run("tag", "--merged", target_commit).splitlines())
    ancestors = [(t, v) for t, v in candidates if t.name in merged]
    pool = ancestors
    if not pool:
        if not target_parsed:
            return None, None  # untagged history unrelated to any release tag
        pool = candidates  # release branch: closest lower version, even if not an ancestor
    best_tag, _ = max(pool, key=lambda tv: _sort_key(tv[1], tv[0].date))
    return best_tag.name, best_tag.commit
