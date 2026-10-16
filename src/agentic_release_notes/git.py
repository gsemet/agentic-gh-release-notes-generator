"""Thin, read-only git access: commands, ref resolution and file access at a given commit."""

from __future__ import annotations

import fnmatch
import functools
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed or the repository is not in a usable state."""


class Git:
    """Run git commands in one repository."""

    def __init__(self, cwd: Path | str = ".") -> None:
        self.cwd = Path(cwd)

    def run(self, *args: str, check: bool = True, strip: bool = True) -> str:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        if check and result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip() if strip else result.stdout

    def ok(self, *args: str) -> bool:
        return (
            subprocess.run(
                ["git", *args], cwd=self.cwd, capture_output=True, stdin=subprocess.DEVNULL
            ).returncode
            == 0
        )

    def toplevel(self) -> Path:
        return Path(self.run("rev-parse", "--show-toplevel"))

    def commit(self, ref: str) -> str | None:
        """Resolve any ref (tag, branch, sha, HEAD~2) to a commit sha, or None."""
        if not self.ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            return None
        return self.run("rev-parse", f"{ref}^{{commit}}")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.ok("merge-base", "--is-ancestor", ancestor, descendant)

    def is_shallow(self) -> bool:
        return self.run("rev-parse", "--is-shallow-repository", check=False) == "true"

    @functools.cached_property
    def empty_tree(self) -> str:
        """Object id of the empty tree (works for sha1 and sha256 repositories)."""
        return subprocess.run(
            ["git", "hash-object", "-t", "tree", "--stdin"],
            cwd=self.cwd,
            input="",
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def remote_url(self, name: str = "origin") -> str | None:
        url = self.run("remote", "get-url", name, check=False)
        return url or None


@dataclass(frozen=True)
class Tag:
    name: str
    commit: str
    date: str  # ISO creator date, used as a tie breaker for unparseable versions


def list_tags(git: Git) -> list[Tag]:
    """All tags with the commit they point to (annotated tags are peeled)."""
    output = git.run(
        "for-each-ref",
        "refs/tags",
        "--format=%(refname:short)%09%(objectname)%09%(*objectname)%09%(creatordate:iso-strict)",
    )
    tags = []
    for line in output.splitlines():
        name, obj, peeled, date = (line.split("\t") + ["", "", ""])[:4]
        tags.append(Tag(name=name, commit=peeled or obj, date=date))
    return tags


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob with ``**`` support into a regex matching POSIX paths."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "{" and "}" in pattern[i:]:
            end = pattern.index("}", i)
            options = pattern[i + 1 : end].split(",")
            out.append("(?:" + "|".join(re.escape(o) for o in options) + ")")
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


class GitTree:
    """Read-only view of the repository files at one commit (no checkout needed).

    Reading documentation and configuration at the release commit, rather than from the
    working tree, keeps the notes reproducible whatever is currently checked out.
    """

    def __init__(self, git: Git, commit: str) -> None:
        self.git = git
        self.commit = commit
        self._cache: dict[str, str | None] = {}

    @functools.cached_property
    def files(self) -> list[str]:
        out = self.git.run("ls-tree", "-r", "-z", "--name-only", self.commit, strip=False)
        return [f for f in out.split("\0") if f]

    @functools.cached_property
    def _fileset(self) -> frozenset[str]:
        return frozenset(self.files)

    def exists(self, path: str) -> bool:
        return path in self._fileset

    def read(self, path: str) -> str | None:
        if path not in self._cache:
            if not self.exists(path):
                self._cache[path] = None
            else:
                self._cache[path] = self.git.run("show", f"{self.commit}:{path}", strip=False)
        return self._cache[path]

    def glob(self, *patterns: str) -> list[str]:
        regexes = [glob_to_regex(p) for p in patterns]
        return [f for f in self.files if any(r.match(f) for r in regexes)]

    def under(self, directory: str) -> list[str]:
        prefix = directory.strip("/") + "/" if directory.strip("/") else ""
        return [f for f in self.files if f.startswith(prefix)]

    def first(self, *candidates: str) -> str | None:
        return next((c for c in candidates if self.exists(c)), None)


def fnmatch_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)
