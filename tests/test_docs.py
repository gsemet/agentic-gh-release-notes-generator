from agentic_release_notes.docs import DocsContext, build_docs_index
from agentic_release_notes.git import Git, GitTree
from agentic_release_notes.project import discover_project, parse_forge
from agentic_release_notes.range import resolve_range
from agentic_release_notes.versions import TagScheme


def index_for(repo, configured=None):
    git = Git(repo.path)
    release = resolve_range(git, TagScheme())
    tree = GitTree(git, release.target_commit)
    ctx = DocsContext(
        tree=tree, project=discover_project(git, tree), release=release, changed_files=set()
    )
    return build_docs_index(ctx, configured or [])


def test_forge_url_parsing():
    assert parse_forge("git@github.com:o/r.git").web_url == "https://github.com/o/r"
    assert parse_forge("https://gitlab.com/g/sub/r.git").blob_url("v1", "a.md") == (
        "https://gitlab.com/g/sub/r/-/blob/v1/a.md"
    )


def test_sphinx_with_read_the_docs_url_and_forge_markdown(repo):
    repo.git("remote", "add", "origin", "git@github.com:acme/tool.git")
    repo.commit(
        "docs: add",
        {
            "pyproject.toml": '[project]\nname = "tool"\n'
            '[project.urls]\nDocumentation = "https://tool.readthedocs.io/en/stable/"\n',
            "docs/conf.py": 'extensions = ["myst_parser"]\n',
            "docs/index.md": "# Tool\n\n## Install\n",
            "docs/how-to/export.md": "# Export\n\n(pdf-export)=\n## PDF export\n",
            "docs/_templates/x.md": "# internal\n",
            "README.md": "# Tool\n\n## Quick start\n",
            "CHANGELOG.md": "# Changelog\n",
            "tests/fixtures/README.md": "# fixture\n",
        },
    )
    repo.tag("v1.0.0")
    index = index_for(repo)
    assert [s.provider for s in index.sites] == ["sphinx", "markdown"]
    urls = {p.url for p in index.pages}
    assert "https://tool.readthedocs.io/en/stable/how-to/export.html" in urls
    assert "https://github.com/acme/tool/blob/v1.0.0/README.md" in urls
    assert not any("CHANGELOG" in u or "fixtures" in u or "_templates" in u for u in urls)
    base = "https://tool.readthedocs.io/en/stable/"
    assert index.check(base + "how-to/export.html#pdf-export") is None
    assert index.check(base + "how-to/export.html#pdf-export-label") is not None
    assert index.check(base + "#install") is None  # root index page
    assert index.check(base + "index.html#install") is None
    assert "not a page" in index.check(base + "missing.html")
    assert index.check("https://github.com/acme/tool/blob/v1.0.0/README.md#quick-start") is None


def test_mkdocs_directory_urls(repo):
    repo.commit(
        "docs",
        {
            "mkdocs.yml": "site_url: https://acme.github.io/tool/\n"
            "markdown_extensions:\n  - !!python/name:material.extensions.emoji.twemoji\n",
            "docs/index.md": "# Home\n",
            "docs/guide/setup.md": "# Setup\n\n## What's new?\n",
        },
    )
    index = index_for(repo)
    assert index.check("https://acme.github.io/tool/guide/setup/#whats-new") is None
    assert index.check("https://acme.github.io/tool/") is None


def test_static_provider_for_other_generators(repo):
    repo.commit("docs", {"website/docs/intro.mdx": "# Intro\n\n## Getting started {#start}\n"})
    index = index_for(
        repo,
        [
            {
                "type": "static",
                "root": "website/docs",
                "base_url": "https://acme.dev/docs/",
                "url_style": "clean",
            }
        ],
    )
    assert index.check("https://acme.dev/docs/intro#start") is None


def test_sphinx_without_public_url_falls_back_to_forge(repo):
    repo.git("remote", "add", "origin", "https://github.com/acme/tool")
    repo.commit(
        "docs",
        {"docs/conf.py": "", "docs/index.rst": "Title\n=====\n", "docs/guide.md": "# Guide\n"},
    )
    repo.tag("v1.0.0")
    index = index_for(repo)
    assert [s.provider for s in index.sites] == ["markdown"]
    assert index.pages[0].url == "https://github.com/acme/tool/blob/v1.0.0/docs/guide.md"
    assert any("no public URL" in w for w in index.warnings)
