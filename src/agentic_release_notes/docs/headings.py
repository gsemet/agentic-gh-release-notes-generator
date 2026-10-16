"""Heading and anchor extraction, with the slug rules of each documentation renderer."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Heading:
    level: int
    text: str
    explicit_id: str | None = None  # {#id} attribute or label/target preceding the heading


def _strip_markup(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)  # raw HTML tags, outside code spans only
    return re.sub(r"(\*\*|__|\*|_)(\S.*?\S|\S)\1", r"\2", text)


def _role_text(content: str) -> str:
    """``title <target>`` -> ``title``; ``target`` alone is kept."""
    return re.sub(r"\s*<[^>]*>$", "", content) or content


def _plain(text: str) -> str:
    """Strip inline Markdown/RST markup the way renderers do before slugifying.

    Code span content is kept verbatim: ``playbooks/<name>.md`` is text, not an HTML tag.
    """
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links / images
    text = re.sub(r"\{[\w:-]+\}`([^`]*)`", lambda m: _role_text(m[1]), text)  # MyST roles
    text = re.sub(r":[\w:-]+:`([^`]*)`", lambda m: _role_text(m[1]), text)  # RST roles
    out, pos = [], 0
    for code in re.finditer(r"(`+)(.+?)\1", text):
        out += [_strip_markup(text[pos : code.start()]), code.group(2)]
        pos = code.end()
    out.append(_strip_markup(text[pos:]))
    return "".join(out).strip()


def slug_github(text: str) -> str:
    """GitHub / GitLab rendered Markdown (github-slugger)."""
    text = _plain(text).lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def slug_docutils(text: str) -> str:
    """Sphinx / docutils section ids (``docutils.nodes.make_id``), also used for MyST."""
    text = unicodedata.normalize("NFKD", _plain(text)).encode("ascii", "ignore").decode()
    text = "-".join(re.split(r"[^a-z0-9]+", text.lower()))
    return re.sub(r"^[-0-9]+|-+$", "", text)


def slug_python_markdown(text: str) -> str:
    """MkDocs (Python-Markdown toc extension default slugify)."""
    text = unicodedata.normalize("NFKD", _plain(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


SLUGGERS: dict[str, Callable[[str], str]] = {
    "github": slug_github,
    "gitlab": slug_github,
    "docutils": slug_docutils,
    "sphinx": slug_docutils,
    "python-markdown": slug_python_markdown,
    "mkdocs": slug_python_markdown,
}

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_ATTR_ID = re.compile(r"\s*\{[^}]*#([\w:.-]+)[^}]*\}\s*$")
_MYST_LABEL = re.compile(r"^\(([^)\s]+)\)=\s*$")
_HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")


def markdown_headings(text: str) -> list[Heading]:
    headings: list[Heading] = []
    fence: str | None = None
    pending_label: str | None = None
    lines = text.splitlines()
    if lines and lines[0].strip() == "---" and "---" in [x.strip() for x in lines[1:]]:
        end = 1 + [x.strip() for x in lines[1:]].index("---")
        lines = [""] * (end + 1) + lines[end + 1 :]  # keep line numbers stable
    for i, line in enumerate(lines):
        fence_match = _FENCE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0] * len(marker)
            elif marker.startswith(fence):
                fence = None
            continue
        if fence:
            continue
        if label := _MYST_LABEL.match(line):
            pending_label = label.group(1)
            continue
        for anchor in _HTML_ANCHOR.findall(line):
            headings.append(Heading(level=7, text=anchor, explicit_id=anchor))
        match = _ATX.match(line)
        if not match and i + 1 < len(lines) and line.strip() and not line.startswith(" " * 4):
            underline = lines[i + 1].strip()
            if (
                underline
                and set(underline) in ({"="}, {"-"})
                and not line.lstrip().startswith(("-", "*", ">", "|"))
            ):
                match_level, match_text = (1 if underline[0] == "=" else 2), line.strip()
                headings.append(Heading(match_level, match_text, pending_label))
                pending_label = None
                continue
        if match:
            raw = match.group(2)
            explicit = None
            if attr := _ATTR_ID.search(raw):
                explicit = attr.group(1)
                raw = raw[: attr.start()]
            headings.append(Heading(len(match.group(1)), raw.strip(), explicit or pending_label))
            pending_label = None
        elif line.strip():
            pending_label = None
    return headings


_RST_TARGET = re.compile(r"^\.\.\s+_([^:]+):\s*$")
_RST_ADORN = re.compile(r"^([=\-`:'\"~^_*+#<>.])\1+\s*$")


def rst_headings(text: str) -> list[Heading]:
    headings: list[Heading] = []
    levels: list[tuple[str, bool]] = []
    lines = text.splitlines()
    pending_label = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if target := _RST_TARGET.match(line):
            pending_label = target.group(1).strip()
            i += 1
            continue
        overline = bool(_RST_ADORN.match(line)) and i + 2 < len(lines)
        if overline and lines[i + 1].strip() and _RST_ADORN.match(lines[i + 2]):
            title, char, consumed = lines[i + 1].strip(), line.strip()[0], 3
        elif (
            line.strip()
            and not _RST_ADORN.match(line)
            and i + 1 < len(lines)
            and _RST_ADORN.match(lines[i + 1])
            and len(lines[i + 1].strip()) >= len(line.strip())
        ):
            title, char, consumed, overline = line.strip(), lines[i + 1].strip()[0], 2, False
        else:
            if line.strip():
                pending_label = None
            i += 1
            continue
        style = (char, overline)
        if style not in levels:
            levels.append(style)
        headings.append(Heading(levels.index(style) + 1, title, pending_label))
        pending_label = None
        i += consumed
    return headings


def anchors_for(headings: list[Heading], slugger: Callable[[str], str], dedupe: str) -> dict:
    """Map anchor id -> heading text. ``dedupe`` is the suffix style of repeated slugs."""
    anchors: dict[str, str] = {}
    seen: dict[str, int] = {}
    for heading in headings:
        if heading.explicit_id:
            anchors[heading.explicit_id] = heading.text
            if slugger is slug_docutils:  # Sphinx labels become ids via make_id
                anchors[slug_docutils(heading.explicit_id)] = heading.text
            if heading.level == 7:
                continue
        slug = slugger(heading.text)
        if not slug:
            continue
        if slug in seen:
            seen[slug] += 1
            if dedupe == "none":
                continue
            slug = f"{slug}{dedupe}{seen[slug]}"
        else:
            seen[slug] = 0
        anchors.setdefault(slug, heading.text)
    return anchors
