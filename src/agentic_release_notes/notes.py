"""Structured release notes: the contract between the agent and the renderers.

The agent never writes the final Markdown. It returns JSON that is validated against the
evidence (every item cites commits of the range, every example names a file that exists at the
release, every link resolves to a documentation page and anchor), then rendered. This keeps
formatting consistent and turns hallucinations into precise, retryable validation errors.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

SECTION_ORDER = [
    "breaking",
    "security",
    "features",
    "improvements",
    "fixes",
    "deprecations",
    "documentation",
]
DEFAULT_TITLES = {
    "breaking": "Breaking changes",
    "security": "Security",
    "features": "New features",
    "improvements": "Improvements",
    "fixes": "Bug fixes",
    "deprecations": "Deprecations",
    "documentation": "Documentation",
}
SECTION_GUIDE = {
    "breaking": "users must change something (code, config, command, data) when upgrading",
    "security": "vulnerability fixes and security-relevant hardening",
    "features": "new capabilities users can now use",
    "improvements": "existing capabilities that work better (UX, performance, output, limits)",
    "fixes": "defects users could hit before this release",
    "deprecations": "still working but scheduled for removal; say what to use instead",
    "documentation": "new or significantly improved user documentation worth reading",
}
REQUIRES_ACTION = {"breaking", "deprecations"}
TRACE_MARKERS = ("<thinking", "</thinking", "<function_call", "assistant.reasoning", "<tool_")


@dataclass
class Link:
    label: str
    url: str


@dataclass
class Example:
    code: str
    language: str = ""
    source: str | None = None  # repository file the example comes from
    caption: str | None = None


@dataclass
class Item:
    title: str
    description: str = ""
    action: str | None = None
    example: Example | None = None
    links: list[Link] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    pull_requests: list[int] = field(default_factory=list)  # filled from commits, not by agent


@dataclass
class ReleaseNotes:
    sections: dict[str, list[Item]] = field(default_factory=dict)
    highlights: str | None = None
    maintenance: str | None = None  # set when nothing is user-facing
    label: str | None = None  # release label, filled by the pipeline
    generator: str | None = None

    @property
    def user_facing(self) -> bool:
        return any(self.sections.values())

    def ordered_sections(self) -> list[tuple[str, list[Item]]]:
        return [(k, self.sections[k]) for k in SECTION_ORDER if self.sections.get(k)]

    def items(self) -> list[Item]:
        return [i for _, items in self.ordered_sections() for i in items]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sections"] = {k: [asdict(i) for i in v] for k, v in self.ordered_sections()}
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------------------------
# Parsing


class NotesError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(f"- {e}" for e in errors))
        self.errors = errors


def extract_json(answer: str) -> dict[str, Any]:
    """Find the JSON object in an agent's final answer (bare, or in a fenced block)."""
    text = answer.strip()
    fenced = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    candidates = [*reversed(fenced), text]
    if "{" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise NotesError(["The final answer must be a single JSON object (no prose around it)"])


def _expect(data: Any, kind: type, where: str, errors: list[str]) -> bool:
    if not isinstance(data, kind):
        errors.append(f"{where} must be a {kind.__name__}")
        return False
    return True


def _unknown(data: dict, allowed: set[str], where: str, errors: list[str]) -> None:
    for key in data:
        if key not in allowed:
            errors.append(f"{where}: unknown key {key!r} (allowed: {', '.join(sorted(allowed))})")


def parse_notes(data: dict[str, Any]) -> ReleaseNotes:
    """Build ``ReleaseNotes`` from agent JSON, reporting every shape error at once."""
    errors: list[str] = []
    _unknown(data, {"sections", "highlights", "maintenance", "label", "generator"}, "root", errors)
    notes = ReleaseNotes(
        highlights=data.get("highlights") or None,
        maintenance=data.get("maintenance") or None,
        label=data.get("label"),
        generator=data.get("generator"),
    )
    sections = data.get("sections", {})
    if _expect(sections, dict, "sections", errors):
        for kind, raw_items in sections.items():
            if kind not in SECTION_ORDER:
                errors.append(f"Unknown section {kind!r}; use: {', '.join(SECTION_ORDER)}")
                continue
            if not _expect(raw_items, list, f"sections.{kind}", errors):
                continue
            items = []
            for n, raw in enumerate(raw_items):
                where = f"sections.{kind}[{n}]"
                if not _expect(raw, dict, where, errors):
                    continue
                _unknown(
                    raw,
                    {
                        "title",
                        "description",
                        "action",
                        "example",
                        "links",
                        "commits",
                        "pull_requests",
                    },
                    where,
                    errors,
                )
                example = None
                if raw.get("example"):
                    ex = raw["example"]
                    if _expect(ex, dict, f"{where}.example", errors):
                        _unknown(ex, {"code", "language", "source", "caption"}, where, errors)
                        example = Example(
                            code=str(ex.get("code", "")),
                            language=str(ex.get("language") or ""),
                            source=ex.get("source") or None,
                            caption=ex.get("caption") or None,
                        )
                links = []
                for link in raw.get("links") or []:
                    if _expect(link, dict, f"{where}.links[]", errors):
                        links.append(Link(str(link.get("label", "")), str(link.get("url", ""))))
                items.append(
                    Item(
                        title=str(raw.get("title", "")).strip(),
                        description=str(raw.get("description", "")).strip(),
                        action=(str(raw["action"]).strip() or None) if raw.get("action") else None,
                        example=example,
                        links=links,
                        commits=[str(c) for c in raw.get("commits") or []],
                        pull_requests=[int(p) for p in raw.get("pull_requests") or []],
                    )
                )
            notes.sections[kind] = items
    if errors:
        raise NotesError(errors)
    return notes


# --------------------------------------------------------------------------------------------
# Validation


@dataclass
class ValidationContext:
    commits: list[str]  # full shas in the release range
    link_checker: Any = None  # callable(url) -> error | None, from the docs index
    allowed_prefixes: list[str] = field(default_factory=list)
    has_docs: bool = False
    file_exists: Any = None  # callable(path) -> bool, at the release commit
    require_links: bool = False


def _text_errors(text: str, where: str) -> list[str]:
    errors = []
    if "```" in text:
        errors.append(f"{where}: no code fences in text, use the example field")
    if re.search(r"https?://", text):
        errors.append(f"{where}: no URLs in text, use the links field")
    if re.search(r"^\s*#{1,6}\s", text, re.M):
        errors.append(f"{where}: no Markdown headings in text")
    if any(marker in text for marker in TRACE_MARKERS):
        errors.append(f"{where}: contains agent execution traces")
    return errors


def validate_notes(notes: ReleaseNotes, ctx: ValidationContext) -> list[str]:
    errors: list[str] = []
    if not notes.user_facing and not notes.maintenance:
        errors.append(
            "No user-facing items: either add items, or set 'maintenance' to one sentence "
            "explaining the release only contains internal changes"
        )
    if notes.user_facing and notes.maintenance:
        errors.append("'maintenance' must be empty when there are user-facing items")
    for field_name in ("highlights", "maintenance"):
        value = getattr(notes, field_name)
        if value:
            errors += _text_errors(value, field_name)
            if len(value) > 500:
                errors.append(f"{field_name}: keep it under 500 characters")
    titles: set[str] = set()
    for kind, items in notes.ordered_sections():
        for n, item in enumerate(items):
            where = f"sections.{kind}[{n}] ({item.title[:40]!r})"
            if not item.title or "\n" in item.title or len(item.title) > 100:
                errors.append(f"{where}: title must be one line of at most 100 characters")
            if item.title.lower() in titles:
                errors.append(f"{where}: duplicate title, merge the two items")
            titles.add(item.title.lower())
            if not item.description:
                errors.append(f"{where}: description is required")
            if len(item.description) > 700:
                errors.append(f"{where}: description too long, keep 1-3 sentences")
            errors += _text_errors(item.title, where) + _text_errors(item.description, where)
            if item.action:
                errors += _text_errors(item.action, f"{where}.action")
            elif kind in REQUIRES_ACTION:
                errors.append(f"{where}: 'action' (what users must do) is required for {kind}")
            errors += _commit_errors(item, ctx, where)
            errors += _example_errors(item, ctx, where)
            errors += _link_errors(item, ctx, where)
            if (
                ctx.require_links
                and ctx.has_docs
                and kind in {"features", "improvements", "breaking"}
                and not item.links
            ):
                errors.append(f"{where}: link the documentation section users should read")
    return errors


def _commit_errors(item: Item, ctx: ValidationContext, where: str) -> list[str]:
    if not item.commits:
        return [f"{where}: cite the commits this item is based on in 'commits'"]
    errors = []
    resolved = []
    for ref in item.commits:
        if not re.fullmatch(r"[0-9a-f]{7,64}", ref):
            errors.append(f"{where}: {ref!r} is not a commit sha (7+ hex characters)")
            continue
        found = [c for c in ctx.commits if c.startswith(ref)]
        if len(found) != 1:
            errors.append(f"{where}: commit {ref} is not part of this release range")
        else:
            resolved.append(found[0])
    item.commits = resolved if not errors else item.commits
    return errors


def _example_errors(item: Item, ctx: ValidationContext, where: str) -> list[str]:
    example = item.example
    if not example:
        return []
    errors = []
    if not example.code.strip():
        errors.append(f"{where}.example: code is empty")
    if "```" in example.code:
        errors.append(f"{where}.example: code must not contain fences")
    if example.code.count("\n") >= 25:
        errors.append(f"{where}.example: keep examples under 25 lines")
    if example.language and not re.fullmatch(r"[\w+#.-]+", example.language):
        errors.append(f"{where}.example: language must be a single word such as bash")
    if example.source and ctx.file_exists and not ctx.file_exists(example.source):
        errors.append(f"{where}.example: source {example.source!r} does not exist at the release")
    return errors


def _link_errors(item: Item, ctx: ValidationContext, where: str) -> list[str]:
    errors = []
    for link in item.links:
        if not link.label.strip():
            errors.append(f"{where}: link label is empty")
        if not link.url.startswith("https://"):
            errors.append(f"{where}: {link.url!r} must be an absolute https:// URL")
            continue
        if any(link.url.startswith(p) for p in ctx.allowed_prefixes):
            continue
        if ctx.link_checker is None:
            continue  # link checking disabled
        if not ctx.has_docs:
            errors.append(f"{where}: {link.url} is not allowed, no documentation is published")
            continue
        if problem := ctx.link_checker(link.url):
            errors.append(f"{where}: {problem}")
    return errors
