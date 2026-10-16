"""Configuration: defaults that work with zero configuration, overridable per project.

Looked up, first match wins:

- ``--config FILE``
- ``.release-notes.toml`` or ``.github/release-notes.toml`` (top-level keys)
- ``pyproject.toml`` under ``[tool.agentic-release-notes]``

Configuration is read from the working tree, not from the release commit, so that a project can
tune generation of older releases.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from agentic_release_notes.versions import TagScheme, from_commitizen

CONFIG_FILES = (".release-notes.toml", ".github/release-notes.toml")

DEFAULT_IGNORE_COMMITS = [
    r"^bump(\(.*\))?:",  # commitizen
    r"^chore\(release\)",  # semantic-release, release-please
    r"^chore: release",
    r"^release(\(.*\))?:",
    r"^Release v?\d",
    r"^Merge (branch|remote-tracking branch) ",
]

DEFAULT_CONTEXT_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    "CONTRIBUTING.md",
    "**/glossary*.{md,rst,yml,yaml,txt}",
    "**/GLOSSARY*.md",
    "**/terminology*.md",
]


@dataclass
class EvidenceConfig:
    max_chars: int = 150_000
    max_file_chars: int = 12_000
    # Extra globs per category; built-in defaults are always applied after these.
    exclude: list[str] = field(default_factory=list)
    internal: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    manifest: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    backend: str = "auto"  # auto, copilot, claude, codex, command, none
    model: str | None = None
    attempts: int = 3
    timeout: int = 900
    fallback: str = "error"  # error | deterministic
    command: list[str] = field(default_factory=list)  # for backend = "command"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class LinksConfig:
    strict: bool = True  # links must resolve to the docs index (page and anchor)
    allow: list[str] = field(default_factory=list)  # extra URL prefixes always accepted
    require: bool = False  # every feature/improvement item must carry a docs link


@dataclass
class Config:
    product: str | None = None  # what the project is, e.g. "a VS Code extension for ..."
    audience: str | None = None  # who reads the notes, e.g. "data engineers using the CLI"
    language: str = "English"
    guidance: str | None = None  # free-form project-specific editorial rules
    tag_pattern: str = "auto"  # "v{version}", "{version}", "pkg@{version}", ...
    prerelease_baseline: str = "stable"  # stable | any
    paths: list[str] = field(default_factory=list)  # monorepo scope (git pathspecs)
    ignore_commits: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    context_max_chars: int = 30_000
    sections: dict[str, str] = field(default_factory=dict)  # section kind -> title
    format: str = "github"
    show_commits: bool = True  # append commit / PR references to rendered items
    docs: list[dict[str, Any]] = field(default_factory=list)  # empty: auto detect
    evidence: EvidenceConfig = field(default_factory=EvidenceConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    links: LinksConfig = field(default_factory=LinksConfig)
    source: str | None = None  # where the configuration came from

    @property
    def tag_scheme(self) -> TagScheme:
        return TagScheme(self.tag_pattern)

    @property
    def all_ignore_commits(self) -> list[str]:
        return [*DEFAULT_IGNORE_COMMITS, *self.ignore_commits]

    @property
    def all_context_files(self) -> list[str]:
        return [*DEFAULT_CONTEXT_FILES, *self.context_files]


def _build(cls: type, data: dict[str, Any], where: str) -> Any:
    known = {f.name: f for f in fields(cls)}
    kwargs = {}
    for key, value in data.items():
        name = key.replace("-", "_")
        if name not in known:
            raise ValueError(f"Unknown configuration key {key!r} in {where}")
        nested = {"evidence": EvidenceConfig, "agent": AgentConfig, "links": LinksConfig}
        if cls is Config and name in nested:
            value = _build(nested[name], value, f"{where}.{key}")
        kwargs[name] = value
    return cls(**kwargs)


def load_config(root: Path, explicit: Path | None = None) -> Config:
    data: dict[str, Any] | None = None
    source = None
    if explicit:
        data, source = tomllib.loads(explicit.read_text()), str(explicit)
    else:
        for name in CONFIG_FILES:
            if (root / name).is_file():
                data, source = tomllib.loads((root / name).read_text()), name
                break
    pyproject = root / "pyproject.toml"
    py_data = tomllib.loads(pyproject.read_text()) if pyproject.is_file() else {}
    if data is None:
        data = py_data.get("tool", {}).get("agentic-release-notes")
        source = "pyproject.toml [tool.agentic-release-notes]" if data is not None else None
    config = _build(Config, data or {}, source or "defaults")
    config.source = source
    if config.tag_pattern == "auto":
        config.tag_pattern = _detect_tag_pattern(root, py_data)
    _ = TagScheme(config.tag_pattern).regex  # fail early on an invalid pattern
    return config


def _detect_tag_pattern(root: Path, pyproject: dict[str, Any]) -> str:
    """Reuse the tag format of release tooling already configured in the project."""
    candidates = [pyproject.get("tool", {}).get("commitizen", {})]
    for name in (".cz.toml", "cz.toml"):
        if (root / name).is_file():
            candidates.append(
                tomllib.loads((root / name).read_text()).get("tool", {}).get("commitizen", {})
            )
    for cz in candidates:
        if fmt := cz.get("tag_format"):
            scheme = from_commitizen(fmt)
            if scheme:
                return scheme.pattern
    return "auto"
