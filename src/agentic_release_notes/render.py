"""Render structured notes. Third-party renderers register ``render(notes, options) -> str``
under the ``agentic_release_notes.renderers`` entry-point group."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points

from agentic_release_notes.notes import DEFAULT_TITLES, Item, ReleaseNotes
from agentic_release_notes.project import Forge


@dataclass
class RenderOptions:
    titles: dict[str, str] = field(default_factory=dict)
    forge: Forge | None = None
    show_commits: bool = True
    previous: str | None = None  # previous tag, for the compare link
    target: str | None = None  # target tag (only when it exists)
    date: str | None = None  # YYYY-MM-DD, for changelog headings

    def title(self, kind: str) -> str:
        return self.titles.get(kind, DEFAULT_TITLES[kind])


def _refs(item: Item, options: RenderOptions) -> str:
    if not options.show_commits:
        return ""
    refs = []
    forge = options.forge
    for number in item.pull_requests:
        refs.append(f"[#{number}]({forge.pr_url(number)})" if forge else f"#{number}")
    if not refs:
        for sha in item.commits[:3]:
            refs.append(f"[{sha[:7]}]({forge.commit_url(sha)})" if forge else sha[:7])
    return f" ({', '.join(refs)})" if refs else ""


def _item(item: Item, options: RenderOptions) -> list[str]:
    line = f"- **{item.title}**"
    if item.description:
        line += f": {item.description}"
    if item.links:
        line += " → " + " · ".join(f"[{link.label}]({link.url})" for link in item.links)
    lines = [line + _refs(item, options)]
    if item.action:
        lines += ["", f"  **What to do:** {item.action}"]
    if item.example:
        example = item.example
        if example.caption:
            lines += ["", f"  {example.caption}"]
        lines += ["", f"  ```{example.language}"]
        lines += [f"  {code}".rstrip() for code in example.code.strip("\n").splitlines()]
        lines += ["  ```"]
    return lines


def _body(notes: ReleaseNotes, options: RenderOptions, heading: str) -> list[str]:
    out: list[str] = []
    if notes.highlights:
        out += [notes.highlights, ""]
    if not notes.user_facing:
        out += [f"This release contains no user-facing changes. {notes.maintenance or ''}".strip()]
        out.append("")
    for kind, items in notes.ordered_sections():
        out += [f"{heading} {options.title(kind)}", ""]
        loose = any(i.action or i.example for i in items)
        for item in items:
            out += _item(item, options)
            if loose:
                out.append("")
        if not loose:
            out.append("")
    return out


def render_github(notes: ReleaseNotes, options: RenderOptions) -> str:
    out = _body(notes, options, "##")
    if options.forge and options.previous and options.target:
        url = options.forge.compare_url(options.previous, options.target)
        out += [f"**Full changelog**: {url}", ""]
    return "\n".join(out).rstrip() + "\n"


CHANGELOG_TITLES = {
    "breaking": "Breaking changes",
    "security": "Security",
    "features": "Added",
    "improvements": "Changed",
    "fixes": "Fixed",
    "deprecations": "Deprecated",
    "documentation": "Documentation",
}


def render_changelog(notes: ReleaseNotes, options: RenderOptions) -> str:
    """A Keep a Changelog style entry, to prepend to CHANGELOG.md."""
    titles = {**CHANGELOG_TITLES, **options.titles}
    options = RenderOptions(**{**options.__dict__, "titles": titles})
    date = f" - {options.date}" if options.date else ""
    out = [f"## {notes.label or 'Unreleased'}{date}", ""] + _body(notes, options, "###")
    return "\n".join(out).rstrip() + "\n"


def render_json(notes: ReleaseNotes, options: RenderOptions) -> str:
    return notes.to_json()


Renderer = Callable[[ReleaseNotes, RenderOptions], str]
BUILTIN: dict[str, Renderer] = {
    "github": render_github,
    "markdown": render_github,
    "changelog": render_changelog,
    "json": render_json,
}


def renderers() -> dict[str, Renderer]:
    registry = dict(BUILTIN)
    for ep in entry_points(group="agentic_release_notes.renderers"):
        registry[ep.name] = ep.load()
    return registry


def render(notes: ReleaseNotes, fmt: str, options: RenderOptions) -> str:
    registry = renderers()
    if fmt not in registry:
        raise ValueError(f"Unknown format {fmt!r}; known: {', '.join(registry)}")
    return registry[fmt](notes, options)
