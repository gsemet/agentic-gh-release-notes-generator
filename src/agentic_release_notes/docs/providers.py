"""Built-in documentation providers and auto-detection."""

from __future__ import annotations

import posixpath
import re
from typing import Any

import yaml

from agentic_release_notes.docs import DocPage, DocsContext, DocsSite, matches
from agentic_release_notes.docs.headings import (
    SLUGGERS,
    anchors_for,
    markdown_headings,
    rst_headings,
)
from agentic_release_notes.git import path_matches

SPHINX_CONF_CANDIDATES = [
    "docs/conf.py",
    "docs/source/conf.py",
    "doc/conf.py",
    "doc/source/conf.py",
    "documentation/conf.py",
    "sphinx/conf.py",
    "conf.py",
]
MKDOCS_CANDIDATES = ["mkdocs.yml", "mkdocs.yaml", "docs/mkdocs.yml"]
NOT_USER_DOCS = [
    "CHANGELOG*",
    "**/CHANGELOG*",
    "AGENTS.md",
    "**/AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING*",
    "CODE_OF_CONDUCT*",
    "SECURITY*",
    "LICENSE*",
    ".github/**",
    ".agents/**",
    ".claude/**",
    "**/node_modules/**",
    "**/fixtures/**",
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "**/testdata/**",
    "**/_build/**",
    "**/_static/**",
    "**/_templates/**",
]


def _page(ctx, source, url, slug, dedupe, title_fallback) -> DocPage:
    text = ctx.tree.read(source) or ""
    headings = rst_headings(text) if source.endswith(".rst") else markdown_headings(text)
    titled = [h for h in headings if h.level <= 6]
    title = titled[0].text if titled else title_fallback
    return DocPage(source=source, url=url, title=title, anchors=anchors_for(headings, slug, dedupe))


def _join(base: str, rel: str) -> str:
    return base.rstrip("/") + "/" + rel.lstrip("/") if rel else base.rstrip("/") + "/"


def _site_url(rel_without_ext: str, style: str) -> str:
    """Map ``guide/install`` to the URL suffix of a given site URL style."""
    head, name = posixpath.split(rel_without_ext)
    is_index = name in ("index", "README", "readme", "_index")
    if style == "html":
        return (
            f"{head}/index.html".lstrip("/")
            if is_index and head
            else ("" if is_index else f"{rel_without_ext}.html")
        )
    if style == "dir":
        if is_index:
            return f"{head}/" if head else ""
        return f"{rel_without_ext}/"
    # "clean": no suffix
    if is_index:
        return head
    return rel_without_ext


# --------------------------------------------------------------------------------------------
# Sphinx


def _conf_value(conf: str, name: str) -> str | None:
    match = re.search(rf"^{name}\s*=\s*['\"]([^'\"]+)['\"]", conf, re.M)
    return match.group(1) if match else None


def sphinx(ctx: DocsContext, options: dict[str, Any]) -> DocsSite | None:
    conf_path = options.get("conf") or ctx.tree.first(*SPHINX_CONF_CANDIDATES)
    if not conf_path:
        ctx.warnings.append("sphinx: no conf.py found")
        return None
    root = options.get("root") or posixpath.dirname(conf_path)
    conf = ctx.tree.read(conf_path) or ""
    base_url = options.get("base_url") or _conf_value(conf, "html_baseurl") or ctx.project.docs_url
    if not base_url and ctx.tree.glob(".readthedocs.y*ml") and ctx.project.name:
        slug = re.sub(r"[^a-z0-9]+", "-", ctx.project.name.lower())
        base_url = f"https://{slug}.readthedocs.io/en/stable/"
        ctx.warnings.append(
            f"sphinx: guessed Read the Docs URL {base_url}; set [[docs]] base_url to confirm"
        )
    if not base_url:
        ctx.warnings.append(
            f"sphinx: no public URL for {root}/ (set html_baseurl, a 'Documentation' project "
            "URL or [[docs]] base_url); its sources are linked on the forge instead"
        )
        return None
    style = options.get("url_style", "html")  # html | dir (dirhtml builder)
    suffixes = [".rst"]
    if "myst" in conf or ".md" in conf:
        suffixes.append(".md")
    exclude = [*NOT_USER_DOCS, *options.get("exclude", [])]
    site = DocsSite(name=options.get("name", "docs"), kind="sphinx", base_url=base_url)
    prefix = f"{root}/" if root else ""
    for source in ctx.tree.under(root):
        rel = source[len(prefix) :]
        stem, ext = posixpath.splitext(rel)
        if ext not in suffixes or path_matches(source, exclude):
            continue
        if rel.split("/")[0].startswith(("_", ".")):
            continue
        url = _join(base_url, _site_url(stem, "dir" if style == "dir" else "html"))
        site.pages.append(_page(ctx, source, url, SLUGGERS["docutils"], "none", stem))
    return site


# --------------------------------------------------------------------------------------------
# MkDocs


class _TolerantLoader(yaml.SafeLoader):
    """mkdocs.yml often uses ``!!python/name`` or ``!ENV`` tags: ignore them."""


_TolerantLoader.add_multi_constructor("", lambda loader, suffix, node: None)


def mkdocs(ctx: DocsContext, options: dict[str, Any]) -> DocsSite | None:
    config_path = options.get("config") or ctx.tree.first(*MKDOCS_CANDIDATES)
    if not config_path:
        return None
    config = yaml.load(ctx.tree.read(config_path) or "", Loader=_TolerantLoader) or {}
    base_url = options.get("base_url") or config.get("site_url") or ctx.project.docs_url
    if not base_url:
        ctx.warnings.append("mkdocs: no site_url; set it in mkdocs.yml or [[docs]] base_url")
        return None
    docs_dir = posixpath.normpath(
        posixpath.join(posixpath.dirname(config_path), config.get("docs_dir", "docs"))
    )
    style = "dir" if config.get("use_directory_urls", True) else "html"
    site = DocsSite(name=options.get("name", "docs"), kind="mkdocs", base_url=base_url)
    for source in ctx.tree.under(docs_dir):
        rel = source[len(docs_dir) + 1 :]
        stem, ext = posixpath.splitext(rel)
        if ext != ".md" or path_matches(source, NOT_USER_DOCS):
            continue
        url = _join(base_url, _site_url(stem, style))
        site.pages.append(_page(ctx, source, url, SLUGGERS["python-markdown"], "_", stem))
    return site


# --------------------------------------------------------------------------------------------
# Markdown rendered by the forge (GitHub, GitLab)

DEFAULT_MARKDOWN_INCLUDE = ["*.md", "docs/**/*.md", "doc/**/*.md", "**/README.md"]


def markdown(ctx: DocsContext, options: dict[str, Any]) -> DocsSite | None:
    forge = ctx.project.forge
    if (not forge or forge.kind == "other") and not options.get("base_url"):
        return None
    release = ctx.release
    ref = (
        options.get("ref")
        or release.target_tag
        or (release.label if release.label != "Unreleased" else ctx.project.default_branch)
    )
    include = options.get("include", DEFAULT_MARKDOWN_INCLUDE)
    exclude = [*NOT_USER_DOCS, *options.get("exclude", [])]
    site = DocsSite(
        name=options.get("name", "repository"),
        kind=f"{forge.kind if forge else 'markdown'} markdown at {ref}",
        base_url=options.get("base_url") or forge.blob_url(ref, ""),
    )
    for source in ctx.tree.files:
        if source in ctx.covered or not matches(source, include, exclude):
            continue
        url = (
            _join(options["base_url"], source)
            if options.get("base_url")
            else forge.blob_url(ref, source)
        )
        site.pages.append(_page(ctx, source, url, SLUGGERS["github"], "-", source))
    return site


# --------------------------------------------------------------------------------------------
# Any static site generator (Docusaurus, VitePress, Hugo, Jekyll, Zensical...)


def static(ctx: DocsContext, options: dict[str, Any]) -> DocsSite | None:
    for key in ("root", "base_url"):
        if key not in options:
            raise ValueError(f"static docs provider requires '{key}'")
    root = options["root"].strip("/")
    style = options.get("url_style", "html")  # html | dir | clean
    slug = SLUGGERS[options.get("slug", "github")]
    extensions = options.get("extensions", [".md", ".mdx"])
    exclude = [*NOT_USER_DOCS, *options.get("exclude", [])]
    site = DocsSite(name=options.get("name", "docs"), kind="static", base_url=options["base_url"])
    for source in ctx.tree.under(root):
        rel = source[len(root) + 1 :] if root else source
        stem, ext = posixpath.splitext(rel)
        if ext not in extensions or path_matches(source, exclude):
            continue
        url = _join(options["base_url"], _site_url(stem, style))
        site.pages.append(_page(ctx, source, url, slug, options.get("dedupe", "-"), stem))
    return site


BUILTIN = {"sphinx": sphinx, "mkdocs": mkdocs, "markdown": markdown, "static": static}


def detect(ctx: DocsContext) -> list[dict[str, Any]]:
    """Zero-configuration guess: a docs site if any, then forge Markdown for the rest."""
    specs: list[dict[str, Any]] = []
    if ctx.tree.first(*MKDOCS_CANDIDATES):
        specs.append({"type": "mkdocs"})
    elif ctx.tree.first(*SPHINX_CONF_CANDIDATES):
        specs.append({"type": "sphinx"})
    specs.append({"type": "markdown"})
    return specs
