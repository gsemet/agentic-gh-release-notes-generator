"""Diff evidence: classify changed files by user relevance and fit diffs in a budget.

Documentation, examples and public source come first because they carry user impact and
ready-made examples; tests come next as a source of realistic usage; internal files (CI, agent
guidance, lockfiles) are only listed. Anything cut is listed with the exact command to inspect
it, since the agent can run read-only git commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentic_release_notes.config import EvidenceConfig
from agentic_release_notes.git import Git, glob_to_regex

CATEGORY_ORDER = ["docs", "examples", "source", "manifest", "tests", "internal", "excluded"]

DEFAULT_GLOBS: dict[str, list[str]] = {
    "excluded": [
        "**/*.lock",
        "**/package-lock.json",
        "**/pnpm-lock.yaml",
        "**/go.sum",
        "**/*.min.js",
        "**/*.min.css",
        "**/*.map",
        "**/dist/**",
        "**/node_modules/**",
        "**/vendor/**",
        "**/__snapshots__/**",
        "**/*.snap",
        "**/*.{png,jpg,jpeg,gif,ico,webp}",
        "**/*.{pdf,zip,gz,woff,woff2,ttf,otf,vsix,whl}",
        "**/coverage*",
        "**/htmlcov/**",
    ],
    "internal": [
        ".github/**",
        ".gitlab-ci.yml",
        ".gitlab/**",
        ".circleci/**",
        ".azure-pipelines*",
        ".pre-commit-config.yaml",
        ".editorconfig",
        ".gitignore",
        ".gitattributes",
        ".vscode/**",
        ".devcontainer/**",
        ".agents/**",
        ".claude/**",
        ".cursor/**",
        "AGENTS.md",
        "CLAUDE.md",
        "**/AGENTS.md",
        "CHANGELOG*",
        "**/CHANGELOG*",
        "CONTRIBUTING*",
        "CODE_OF_CONDUCT*",
        "SECURITY*",
        "justfile",
        "Makefile",
        "noxfile.py",
        "tox.ini",
        ".readthedocs.y*ml",
        "renovate.json",
        ".release-notes.toml",
        "**/.*rc",
        "**/.*rc.{js,json,cjs,yml,yaml}",
        "*.config.{js,cjs,mjs,ts}",
        "scripts/**",
    ],
    "tests": [
        "test/**",
        "tests/**",
        "**/test/**",
        "**/tests/**",
        "**/__tests__/**",
        "e2e/**",
        "**/test_*.py",
        "**/*_test.py",
        "**/*_test.go",
        "**/*.test.*",
        "**/*.spec.*",
        "**/conftest.py",
        "**/fixtures/**",
        "spec/**",
    ],
    "examples": ["examples/**", "example/**", "samples/**", "demo/**", "**/examples/**"],
    "docs": [
        "docs/**",
        "doc/**",
        "documentation/**",
        "website/**",
        "sphinx/**",
        "mkdocs.yml",
        "README*",
        "**/README*",
        "**/*.md",
        "**/*.rst",
        "**/*.adoc",
    ],
    "manifest": [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "**/package.json",
        "Cargo.toml",
        "**/Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle*",
        "*.gemspec",
        "composer.json",
        "**/pyproject.toml",
        "requirements*.txt",
        "Dockerfile",
        "action.yml",
    ],
}


@dataclass
class FileChange:
    path: str
    category: str
    added: int | None  # None for binary files
    removed: int | None
    diff: str = ""


@dataclass
class Evidence:
    base: str  # commit or empty tree the diff starts from
    head: str
    files: list[FileChange] = field(default_factory=list)
    included: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)

    def by_category(self, category: str) -> list[FileChange]:
        return [f for f in self.files if f.category == category]

    def changed(self, path: str) -> bool:
        return any(f.path == path for f in self.files)

    def stat_table(self) -> str:
        lines = []
        for category in CATEGORY_ORDER:
            changes = self.by_category(category)
            if not changes:
                continue
            lines.append(f"{category} ({len(changes)} files):")
            for change in changes:
                delta = "binary" if change.added is None else f"+{change.added} -{change.removed}"
                lines.append(f"  {change.path}  {delta}")
        return "\n".join(lines)

    def diff_text(self) -> str:
        parts = [f.diff for f in self.files if f.path in self.included]
        return "\n".join(parts)


class Classifier:
    def __init__(self, config: EvidenceConfig) -> None:
        # User globs win over every built-in default; within each group, first match wins.
        self.rules: list[tuple[str, list[re.Pattern[str]]]] = []
        for category in ["excluded", "internal", "tests", "examples", "docs", "manifest", "source"]:
            globs = getattr(config, "exclude" if category == "excluded" else category)
            if globs:
                self.rules.append((category, [glob_to_regex(g) for g in globs]))
        for category in ["excluded", "internal", "tests", "examples", "docs", "manifest"]:
            self.rules.append((category, [glob_to_regex(g) for g in DEFAULT_GLOBS[category]]))

    def classify(self, path: str) -> str:
        for category, regexes in self.rules:
            if any(r.match(path) for r in regexes):
                return category
        return "source"


def _split_diff(raw: str) -> dict[str, str]:
    chunks: dict[str, str] = {}
    for chunk in re.split(r"(?m)^(?=diff --git )", raw):
        if not chunk.startswith("diff --git "):
            continue
        header = chunk.splitlines()[0]
        match = re.match(r'diff --git "?a/(.+?)"? "?b/(.+?)"?$', header)
        if match:
            chunks[match.group(2)] = chunk
    return chunks


def collect_evidence(
    git: Git, base: str | None, head: str, paths: list[str], config: EvidenceConfig
) -> Evidence:
    base = base or git.empty_tree
    evidence = Evidence(base=base, head=head)
    classifier = Classifier(config)
    numstat = git.run("diff", "--numstat", "--no-renames", base, head, "--", *paths)
    for line in numstat.splitlines():
        added, removed, path = line.split("\t", 2)
        binary = added == "-"
        evidence.files.append(
            FileChange(
                path=path,
                category=classifier.classify(path),
                added=None if binary else int(added),
                removed=None if binary else int(removed),
            )
        )
    relevant = [f for f in evidence.files if f.category not in {"internal", "excluded"}]
    relevant = [f for f in relevant if f.added is not None]
    if relevant:
        raw = git.run(
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--no-renames",
            "--unified=3",
            base,
            head,
            "--",
            *[f.path for f in relevant],
            strip=False,
        )
        chunks = _split_diff(raw)
        for change in relevant:
            change.diff = chunks.get(change.path, "")
    budget = config.max_chars
    for category in CATEGORY_ORDER[:5]:
        for change in evidence.by_category(category):
            if not change.diff:
                continue
            if budget < 2_000:
                evidence.omitted.append(change.path)
                continue
            limit = min(config.max_file_chars, budget)
            if len(change.diff) > limit:
                cut = change.diff[:limit].rsplit("\n", 1)[0]
                hint = f"git diff {base[:12]} {head[:12]} -- {change.path}"
                change.diff = f"{cut}\n... [truncated, run: {hint}]\n"
                evidence.truncated.append(change.path)
            evidence.included.append(change.path)
            budget -= len(change.diff)
    return evidence
