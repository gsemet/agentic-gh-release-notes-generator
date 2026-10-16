import pytest

from agentic_release_notes.commits import Commit, parse_message
from agentic_release_notes.deterministic import deterministic_notes
from agentic_release_notes.notes import (
    NotesError,
    ValidationContext,
    extract_json,
    parse_notes,
    validate_notes,
)

SHA = "a" * 40
DOC = "https://docs.example.org/guide.html"


def ctx(**kwargs):
    def check(url):
        if url.split("#")[0] != DOC:
            return f"{url} is not a page of the documentation index"
        if "#" in url and url.split("#")[1] != "usage":
            return "anchor does not exist"
        return None

    defaults = dict(
        commits=[SHA, "b" * 40],
        link_checker=check,
        allowed_prefixes=["https://github.com/o/r/issues/"],
        has_docs=True,
        file_exists=lambda p: p == "docs/guide.md",
    )
    return ValidationContext(**{**defaults, **kwargs})


def item(**kwargs):
    return {
        "title": "Export to PDF",
        "description": "Export reports as PDF.",
        "commits": ["aaaaaaa"],
        **kwargs,
    }


def errors_for(data, **kwargs):
    return validate_notes(parse_notes(data), ctx(**kwargs))


def test_valid_notes():
    data = {
        "highlights": "PDF export.",
        "sections": {
            "features": [
                item(
                    links=[{"label": "Guide", "url": DOC + "#usage"}],
                    example={
                        "language": "bash",
                        "code": "tool export --pdf",
                        "source": "docs/guide.md",
                    },
                )
            ]
        },
    }
    assert errors_for(data) == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"sections": {"features": [item(commits=["ccccccc"])]}}, "not part of this release"),
        ({"sections": {"features": [item(commits=[])]}}, "cite the commits"),
        (
            {"sections": {"features": [item(links=[{"label": "x", "url": DOC + "#nope"}])]}},
            "anchor",
        ),
        (
            {"sections": {"features": [item(links=[{"label": "x", "url": "docs/guide.md"}])]}},
            "https://",
        ),
        (
            {
                "sections": {
                    "features": [item(links=[{"label": "x", "url": "https://evil.example"}])]
                }
            },
            "not a page",
        ),
        ({"sections": {"breaking": [item()]}}, "'action'"),
        ({"sections": {"features": [item(), item()]}}, "duplicate title"),
        ({"sections": {"features": [item(description="See https://x.org")]}}, "no URLs"),
        (
            {"sections": {"features": [item(example={"code": "x", "source": "nope.md"})]}},
            "does not exist",
        ),
        ({"sections": {}}, "maintenance"),
        ({"sections": {"features": [item()]}, "maintenance": "x"}, "must be empty"),
    ],
)
def test_validation_errors(data, message):
    errors = errors_for(data)
    assert any(message in e for e in errors), errors


def test_forge_links_are_allowed_without_docs_entry():
    data = {
        "sections": {
            "fixes": [item(links=[{"label": "#4", "url": "https://github.com/o/r/issues/4"}])]
        }
    }
    assert errors_for(data) == []


def test_no_docs_means_no_links():
    data = {"sections": {"features": [item(links=[{"label": "x", "url": DOC}])]}}
    assert any("no documentation" in e for e in errors_for(data, has_docs=False))


def test_shape_errors_are_reported_together():
    with pytest.raises(NotesError) as error:
        parse_notes({"sections": {"misc": [], "features": [{"titel": "x"}]}, "extra": 1})
    assert len(error.value.errors) == 3


def test_extract_json_from_fenced_answer():
    answer = 'Here you go:\n```json\n{"sections": {}, "maintenance": "x"}\n```\nDone.'
    assert extract_json(answer)["maintenance"] == "x"
    with pytest.raises(NotesError):
        extract_json("no json at all")


def commit(subject, body=""):
    return parse_message(
        Commit(
            sha=subject[:7].ljust(40, "0"),
            short=subject[:7],
            author="a",
            date="d",
            subject=subject,
            body=body,
            parents=["p"],
        )
    )


def test_conventional_parsing():
    c = commit("feat(cli)!: drop --legacy (#42)", "Closes #7\n\nBREAKING CHANGE: use --new")
    assert (c.type, c.scope, c.breaking, c.pull_request, c.closes) == ("feat", "cli", True, 42, [7])
    assert c.breaking_notes == ["use --new"]


def test_deterministic_baseline():
    notes = deterministic_notes(
        [commit("fix: crash on empty file"), commit("feat(ui): dark mode"), commit("chore: ci")]
    )
    assert [k for k, _ in notes.ordered_sections()] == ["features", "fixes"]
    assert notes.sections["features"][0].title == "ui: Dark mode"
    assert deterministic_notes([commit("chore: ci")]).maintenance
