"""Documentation index: every public page and anchor, as the user will see it.

Providers turn documentation sources at the release commit into ``DocsSite`` objects mapping
each source file to its public URL and anchors. The index serves two purposes: it tells the
agent where users can read more, and it lets the validator reject any link that does not
resolve to an existing page and section. Links in the notes are therefore verifiable, not
plausible-looking guesses.

Built-in providers: ``sphinx`` (including Read the Docs), ``mkdocs``, ``markdown`` (files
rendered by GitHub/GitLab, pinned to the release tag) and ``static`` (any static site generator
given a base URL, URL suffix and slug style). Third-party providers register a callable
``build(context, options) -> DocsSite | None`` under the ``agentic_release_notes.docs``
entry-point group.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any
from urllib.parse import urldefrag

from agentic_release_notes.git import GitTree, path_matches
from agentic_release_notes.project import ProjectInfo
from agentic_release_notes.range import ReleaseRange


@dataclass
class DocPage:
    source: str  # path in the repository
    url: str  # public URL, without fragment
    title: str
    anchors: dict[str, str] = field(default_factory=dict)  # id -> heading text
    changed: bool = False  # touched by the release


@dataclass
class DocsSite:
    name: str
    kind: str
    base_url: str
    pages: list[DocPage] = field(default_factory=list)
    provider: str = ""  # registry name, set by build_docs_index


@dataclass
class DocsContext:
    tree: GitTree
    project: ProjectInfo
    release: ReleaseRange
    changed_files: set[str]
    warnings: list[str] = field(default_factory=list)
    covered: set[str] = field(default_factory=set)  # sources already published by a site


Provider = Callable[[DocsContext, dict[str, Any]], "DocsSite | None"]


def _normalize(url: str) -> str:
    url = urldefrag(url)[0]
    for suffix in ("/index.html", "/index"):
        if url.endswith(suffix):
            url = url[: -len(suffix) + 1]
    return url.rstrip("/") or url


@dataclass
class DocsIndex:
    sites: list[DocsSite] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pages(self) -> list[DocPage]:
        return [p for s in self.sites for p in s.pages]

    def find(self, url: str) -> DocPage | None:
        wanted = _normalize(url)
        return next((p for p in self.pages if _normalize(p.url) == wanted), None)

    def check(self, url: str) -> str | None:
        """Return an error message when ``url`` is not a known page and anchor."""
        page = self.find(url)
        if page is None:
            return f"{url} is not a page of the documentation index"
        fragment = urldefrag(url)[1]
        if fragment and fragment not in page.anchors:
            return f"{url}: anchor #{fragment} does not exist on {page.url}"
        return None

    def render(self, max_chars: int = 25_000) -> str:
        """Compact listing for the prompt, changed pages (with all anchors) first."""
        if not self.sites:
            return "(no published documentation found: do not add documentation links)"
        out: list[str] = []
        used = 0
        for site in self.sites:
            out.append(f"Site {site.name!r} ({site.kind}) at {site.base_url}")
            pages = sorted(site.pages, key=lambda p: (not p.changed, p.source))
            for page in pages:
                mark = "  [changed in this release]" if page.changed else ""
                lines = [f"- {page.url}  — {page.title}{mark}  (source: {page.source})"]
                if page.changed or used < max_chars * 0.6:
                    lines += [f"    #{a} — {t}" for a, t in page.anchors.items()]
                block = "\n".join(lines)
                if used + len(block) > max_chars:
                    out.append(f"- {page.url}  — {page.title}{mark}")
                    used += len(out[-1])
                    continue
                out.append(block)
                used += len(block)
        return "\n".join(out)


def _registry() -> dict[str, Provider]:
    from agentic_release_notes.docs import providers

    registry: dict[str, Provider] = dict(providers.BUILTIN)
    for ep in entry_points(group="agentic_release_notes.docs"):
        registry[ep.name] = ep.load()
    return registry


def build_docs_index(ctx: DocsContext, configured: list[dict[str, Any]]) -> DocsIndex:
    from agentic_release_notes.docs import providers

    registry = _registry()
    specs = configured or providers.detect(ctx)
    index = DocsIndex()
    for spec in specs:
        options = dict(spec)
        kind = options.pop("type", None)
        if kind not in registry:
            raise ValueError(f"Unknown docs provider {kind!r}; known: {', '.join(registry)}")
        site = registry[kind](ctx, options)
        if site and site.pages:
            site.provider = kind
            for page in site.pages:
                page.changed = page.source in ctx.changed_files
            index.sites.append(site)
            ctx.covered.update(p.source for p in site.pages)
    index.warnings = ctx.warnings
    return index


def matches(path: str, include: list[str], exclude: list[str]) -> bool:
    return path_matches(path, include) and not path_matches(path, exclude)
