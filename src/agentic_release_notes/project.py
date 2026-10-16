"""Project metadata discovered at the release commit: forge URLs, description, docs URLs."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field

from agentic_release_notes.git import Git, GitTree


@dataclass
class Forge:
    kind: str  # github | gitlab | other
    web_url: str  # https://github.com/owner/repo

    def blob_url(self, ref: str, path: str) -> str:
        sep = "/-/blob/" if self.kind == "gitlab" else "/blob/"
        return f"{self.web_url}{sep}{ref}/{path}"

    def commit_url(self, sha: str) -> str:
        sep = "/-/commit/" if self.kind == "gitlab" else "/commit/"
        return f"{self.web_url}{sep}{sha}"

    def pr_url(self, number: int) -> str:
        if self.kind == "gitlab":
            return f"{self.web_url}/-/merge_requests/{number}"
        return f"{self.web_url}/pull/{number}"

    def compare_url(self, base: str, head: str) -> str:
        sep = "/-/compare/" if self.kind == "gitlab" else "/compare/"
        return f"{self.web_url}{sep}{base}...{head}"

    @property
    def link_prefixes(self) -> list[str]:
        """Forge URLs that are always acceptable as links in notes (issues, PRs, commits)."""
        if self.kind == "gitlab":
            parts = ["/-/issues/", "/-/merge_requests/", "/-/commit/", "/-/compare/"]
        else:
            parts = ["/issues/", "/pull/", "/commit/", "/compare/", "/discussions/"]
        return [self.web_url + p for p in parts]


def parse_forge(remote: str | None) -> Forge | None:
    if not remote:
        return None
    match = re.match(
        r"^(?:git@|ssh://git@|https?://(?:[^@/]+@)?)([^/:]+)[:/](.+?)(?:\.git)?/?$", remote
    )
    if not match:
        return None
    host, path = match.groups()
    kind = "github" if "github" in host else "gitlab" if "gitlab" in host else "other"
    return Forge(kind=kind, web_url=f"https://{host}/{path}")


@dataclass
class ProjectInfo:
    name: str | None = None
    description: str | None = None
    kind: str | None = None  # python package, npm package, VS Code extension, rust crate...
    urls: dict[str, str] = field(default_factory=dict)  # label -> url
    forge: Forge | None = None
    default_branch: str = "main"

    @property
    def docs_url(self) -> str | None:
        for label, url in self.urls.items():
            if re.search(r"doc", label, re.I) and url.startswith("https://"):
                return url
        return None


def discover_project(git: Git, tree: GitTree) -> ProjectInfo:
    info = ProjectInfo(forge=parse_forge(git.remote_url()))
    head = git.run("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if head:
        info.default_branch = head.split("/", 1)[-1]
    if text := tree.read("pyproject.toml"):
        data = tomllib.loads(text)
        project = data.get("project", {}) or data.get("tool", {}).get("poetry", {})
        info.name = project.get("name")
        info.description = project.get("description")
        info.kind = "Python package"
        urls = project.get("urls", {})
        info.urls.update({k: v for k, v in urls.items() if isinstance(v, str)})
        if project.get("scripts"):
            info.kind = "Python package with a command line interface"
    if text := tree.read("package.json"):
        data = json.loads(text)
        info.name = info.name or data.get("name")
        info.description = data.get("description") or info.description
        info.kind = (
            "VS Code extension"
            if "vscode" in data.get("engines", {})
            else ("npm package with a command line interface" if data.get("bin") else "npm package")
        )
        if homepage := data.get("homepage"):
            info.urls.setdefault("Homepage", homepage)
    if text := tree.read("Cargo.toml"):
        package = tomllib.loads(text).get("package", {})
        info.name = info.name or package.get("name")
        info.description = info.description or package.get("description")
        info.kind = info.kind or "Rust crate"
        if package.get("documentation"):
            info.urls.setdefault("Documentation", package["documentation"])
    if not info.name and info.forge:
        info.name = info.forge.web_url.rsplit("/", 1)[-1]
    return info
