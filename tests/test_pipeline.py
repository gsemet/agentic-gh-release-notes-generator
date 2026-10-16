"""End to end through the CLI, with a scripted agent behind the 'command' backend."""

import json
import sys
import textwrap

import pytest

from agentic_release_notes.cli import main

FAKE_AGENT = textwrap.dedent(
    """
    import json, pathlib, subprocess, sys
    prompt = sys.stdin.read()
    state = pathlib.Path(sys.argv[1])
    calls = int(state.read_text()) if state.exists() else 0
    state.write_text(str(calls + 1))
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    head = head.strip()
    pathlib.Path(sys.argv[1] + ".head").write_text(head)
    pathlib.Path(sys.argv[1] + f".prompt{calls}").write_text(prompt)
    commit = "deadbeef" if calls == 0 else sys.argv[2]
    print(json.dumps({"sections": {"features": [{
        "title": "Export reports as PDF",
        "description": "Choose PDF in the export dialog.",
        "commits": [commit],
        "links": [{"label": "Export guide",
                   "url": "https://github.com/acme/tool/blob/v1.1.0/docs/export.md#pdf"}],
        "example": {"language": "bash", "code": "tool export --pdf", "source": "docs/export.md"},
    }]}}))
    """
)


@pytest.fixture
def project(repo, tmp_path):
    repo.git("remote", "add", "origin", "git@github.com:acme/tool.git")
    repo.commit("feat: initial", {"README.md": "# Tool\n"})
    repo.tag("v1.0.0")
    sha = repo.commit(
        "feat(export): pdf export (#12)",
        {
            "docs/export.md": "# Export\n\n## PDF\n\n```bash\ntool export --pdf\n```\n",
            "src/export.py": "def export(): ...\n",
        },
    )
    repo.commit("bump: version 1.0.0 → 1.1.0")
    repo.tag("v1.1.0")
    script = tmp_path / "agent.py"
    script.write_text(FAKE_AGENT)
    state = tmp_path / "state"
    repo.write(
        ".release-notes.toml",
        f'[agent]\nbackend = "command"\ncommand = ["{sys.executable}", "{script}", "{state}", '
        f'"{sha[:10]}"]\n',
    )
    return repo, state, sha


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        main(list(argv))
    captured = capsys.readouterr()
    return exit_info.value.code, captured.out, captured.err


def test_generate_retries_with_validation_feedback(project, capsys, tmp_path):
    repo, state, sha = project
    out_json = tmp_path / "notes.json"
    code, out, err = run(
        capsys,
        "generate",
        "--repo",
        str(repo.path),
        "--to",
        "v1.1.0",
        "--json-output",
        str(out_json),
    )
    assert code == 0, err
    assert state.read_text() == "2"
    assert "deadbeef is not part of this release" in err
    retry_prompt = (tmp_path / "state.prompt1").read_text()
    assert "rejected by the validator" in retry_prompt
    # the agent ran in a checkout of the release, not in the working tree
    assert (tmp_path / "state.head").read_text() == repo.git("rev-parse", "v1.1.0")
    assert "worktree" not in repo.git("worktree", "list").split("\n", 1)[-1]
    assert "## New features" in out
    assert "→ [Export guide](https://github.com/acme/tool/blob/v1.1.0/docs/export.md#pdf)" in out
    assert "([#12](https://github.com/acme/tool/pull/12))" in out
    assert "  tool export --pdf" in out
    assert "compare/v1.0.0...v1.1.0" in out
    notes = json.loads(out_json.read_text())
    assert notes["sections"]["features"][0]["commits"] == [sha]
    assert notes["label"] == "v1.1.0"


def test_brief_contains_evidence_and_docs_index(project, capsys):
    repo, _, _ = project
    code, out, _ = run(capsys, "context", "--repo", str(repo.path), "--to", "v1.1.0")
    assert code == 0
    assert "#pdf — PDF" in out
    assert "[changed in this release]" in out
    assert "feat(export): pdf export (#12)" in out
    assert "bump: version" not in out.split("## Commits")[1].split("(ignored")[0]
    assert "+def export(): ..." in out


def test_validate_and_render_commands(project, capsys, tmp_path):
    repo, _, sha = project
    notes = tmp_path / "n.json"
    notes.write_text(
        json.dumps(
            {
                "sections": {
                    "fixes": [{"title": "Fix", "description": "Fixed.", "commits": [sha[:7]]}]
                }
            }
        )
    )
    assert run(capsys, "validate", "--repo", str(repo.path), "--to", "v1.1.0", str(notes))[0] == 0
    code, out, _ = run(
        capsys,
        "render",
        "--repo",
        str(repo.path),
        "--to",
        "v1.1.0",
        str(notes),
        "--format",
        "changelog",
    )
    assert code == 0
    assert out.startswith("## v1.1.0 - 20")
    assert "### Fixed" in out
    notes.write_text(
        json.dumps(
            {
                "sections": {
                    "fixes": [{"title": "Fix", "description": "Fixed.", "commits": ["0000000"]}]
                }
            }
        )
    )
    code, _, err = run(capsys, "validate", "--repo", str(repo.path), "--to", "v1.1.0", str(notes))
    assert code == 1
    assert "not part of this release" in err


def test_deterministic_mode_needs_no_agent(project, capsys):
    repo, _, _ = project
    code, out, _ = run(
        capsys, "generate", "--repo", str(repo.path), "--to", "v1.1.0", "--agent", "none"
    )
    assert code == 0
    assert "**export: Pdf export (#12)**" in out


def test_fallback_after_failed_attempts(project, capsys):
    repo, state, _ = project
    config = repo.path / ".release-notes.toml"
    config.write_text(config.read_text().replace('"command"', '"command"\nattempts = 1', 1))
    code, _, err = run(capsys, "generate", "--repo", str(repo.path), "--to", "v1.1.0")
    assert code == 1
    assert "no valid notes after 1 attempts" in err
    state.unlink()
    code, out, _ = run(
        capsys,
        "generate",
        "--repo",
        str(repo.path),
        "--to",
        "v1.1.0",
        "--fallback",
        "deterministic",
    )
    assert code == 0
    assert "Pdf export" in out
