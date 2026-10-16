"""Slug rules, checked against what the real renderers produce.

The docutils cases were verified against okf-schema on Read the Docs, the github cases against
GitHub's rendered HTML.
"""

import pytest

from agentic_release_notes.docs.headings import (
    anchors_for,
    markdown_headings,
    rst_headings,
    slug_docutils,
    slug_github,
    slug_python_markdown,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Playbooks: `playbooks/<name>.md`", "playbooks-playbooks-name-md"),
        (
            "Active Navigation: `search` / `get` / `read` / `query`",
            "active-navigation-search-get-read-query",
        ),
        ("log.md: Temporal Entry Point", "log-md-temporal-entry-point"),
        ("What is a Knowledge Base?", "what-is-a-knowledge-base"),
        ("1. Install", "install"),
        ("Café & crème", "cafe-creme"),
        ("{ref}`Setup <setup-label>`", "setup"),
    ],
)
def test_docutils(text, expected):
    assert slug_docutils(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Playbooks: `playbooks/<name>.md`", "playbooks-playbooksnamemd"),
        ("What's new in v1.2?", "whats-new-in-v12"),
        ("Install with `uv tool`", "install-with-uv-tool"),
        ("snake_case stays", "snake_case-stays"),
        ("A  --  B", "a------b"),  # each space becomes a dash
        ("[Linked](https://x) title", "linked-title"),
        ("**Bold** move", "bold-move"),
    ],
)
def test_github(text, expected):
    assert slug_github(text) == expected


def test_python_markdown():
    assert slug_python_markdown("What's new in v1.2?") == "whats-new-in-v12"
    assert slug_python_markdown("A  --  B") == "a-b"


def test_markdown_headings_skip_code_and_front_matter():
    text = """---
title: x
---
# Title

```bash
# not a heading
```

(my-label)=
## Section {#custom}

Setext
------
"""
    headings = markdown_headings(text)
    assert [(h.level, h.text, h.explicit_id) for h in headings] == [
        (1, "Title", None),
        (2, "Section", "custom"),
        (2, "Setext", None),
    ]


def test_myst_label_becomes_anchor_too():
    headings = markdown_headings("(install-guide)=\n## Install\n")
    anchors = anchors_for(headings, slug_docutils, "none")
    assert set(anchors) == {"install-guide", "install"}


def test_github_duplicate_suffixes():
    headings = markdown_headings("## Usage\n## Usage\n## Usage\n")
    assert list(anchors_for(headings, slug_github, "-")) == ["usage", "usage-1", "usage-2"]


def test_rst_headings_and_targets():
    text = """
=====
Title
=====

.. _config-ref:

Configuration
-------------

Sub
~~~
"""
    headings = rst_headings(text)
    assert [(h.level, h.text, h.explicit_id) for h in headings] == [
        (1, "Title", None),
        (2, "Configuration", "config-ref"),
        (3, "Sub", None),
    ]
