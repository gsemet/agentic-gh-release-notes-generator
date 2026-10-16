import subprocess

import pytest

from agentic_release_notes.commits import collect_commits
from agentic_release_notes.config import DEFAULT_IGNORE_COMMITS, load_config
from agentic_release_notes.git import Git, GitError
from agentic_release_notes.range import resolve_range
from agentic_release_notes.versions import TagScheme


def resolve(repo, **kwargs):
    scheme = kwargs.pop("scheme", TagScheme())
    return resolve_range(Git(repo.path), scheme, **kwargs)


def test_first_release_covers_whole_history(repo):
    repo.commit("feat: initial")
    repo.commit("feat: more")
    repo.tag("v1.0.0")
    release = resolve(repo)
    assert release.target_tag == "v1.0.0"
    assert release.first_release
    assert release.previous_commit is None


def test_default_target_is_tag_on_head_else_unreleased(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("fix: b")
    release = resolve(repo)
    assert release.label == "Unreleased"
    assert release.target_tag is None
    assert release.previous_tag == "v1.0.0"


def test_version_override_labels_untagged_target(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("feat: b")
    release = resolve(repo, version="v1.1.0")
    assert release.label == "v1.1.0"
    assert release.version == "1.1.0"
    assert release.previous_tag == "v1.0.0"


def test_stable_release_skips_release_candidates(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("feat: b")
    repo.tag("v1.1.0rc1")
    repo.commit("fix: c")
    repo.tag("v1.1.0", annotated=True)
    assert resolve(repo, target="v1.1.0").previous_tag == "v1.0.0"
    assert resolve(repo, target="v1.1.0", prerelease_baseline="any").previous_tag == "v1.1.0rc1"
    assert resolve(repo, target="v1.1.0rc1").previous_tag == "v1.0.0"


def test_semver_prerelease_spelling(repo):
    repo.commit("feat: a")
    repo.tag("v2.0.0")
    repo.commit("feat: b")
    repo.tag("v2.1.0-beta.1")
    repo.commit("feat: c")
    repo.tag("v2.1.0")
    assert resolve(repo, target="v2.1.0").previous_tag == "v2.0.0"


def test_version_order_not_tag_date(repo):
    repo.commit("feat: a")
    repo.tag("v1.9.0")
    repo.commit("feat: b")
    repo.tag("v1.10.0")
    repo.commit("feat: c")
    repo.tag("v1.11.0")
    assert resolve(repo, target="v1.11.0").previous_tag == "v1.10.0"


def test_monorepo_tag_pattern(repo):
    repo.commit("feat(a): one")
    repo.tag("pkg-a@1.0.0")
    repo.commit("feat(b): two")
    repo.tag("pkg-b@3.0.0")
    repo.commit("feat(a): three")
    repo.tag("pkg-a@1.1.0")
    release = resolve(repo, target="pkg-a@1.1.0", scheme=TagScheme("pkg-a@{version}"))
    assert release.previous_tag == "pkg-a@1.0.0"
    assert release.version == "1.1.0"


def test_other_tags_on_same_commit_are_ignored(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("feat: b")
    repo.tag("v1.1.0")
    repo.tag("latest")
    release = resolve(repo, target="v1.1.0")
    assert release.previous_tag == "v1.0.0"


def test_tag_without_release_commit_and_bump_commits_filtered(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("feat: useful")
    repo.commit("bump: version 1.0.0 → 1.1.0")
    repo.tag("v1.1.0")
    release = resolve(repo, target="v1.1.0")
    kept, ignored = collect_commits(Git(repo.path), release.log_range, [], DEFAULT_IGNORE_COMMITS)
    assert [c.subject for c in kept] == ["feat: useful"]
    assert [c.subject for c in ignored] == ["bump: version 1.0.0 → 1.1.0"]


def test_backport_branch_uses_closest_lower_ancestor(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.git("checkout", "-q", "-b", "release-1.0")
    repo.commit("fix: backport")
    repo.tag("v1.0.1")
    repo.git("checkout", "-q", "main")
    repo.commit("feat: new")
    repo.tag("v1.1.0")
    assert resolve(repo, target="v1.0.1").previous_tag == "v1.0.0"
    assert resolve(repo, target="v1.1.0").previous_tag == "v1.0.0"
    explicit = resolve(repo, target="v1.1.0", previous="v1.0.1")
    assert any("not an ancestor" in w for w in explicit.warnings)


def test_errors_for_inverted_or_identical_ranges(repo):
    repo.commit("feat: a")
    repo.tag("v1.0.0")
    repo.commit("feat: b")
    repo.tag("v1.1.0")
    with pytest.raises(GitError, match="older"):
        resolve(repo, target="v1.0.0", previous="v1.1.0")
    with pytest.raises(GitError, match="same commit"):
        resolve(repo, target="v1.1.0", previous="v1.1.0")
    with pytest.raises(GitError, match="Unknown target"):
        resolve(repo, target="v9.9.9")


def test_shallow_clone_is_refused(repo, tmp_path):
    repo.commit("feat: a")
    repo.commit("feat: b")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo.path}", str(clone)], check=True
    )
    with pytest.raises(GitError, match="Shallow"):
        resolve_range(Git(clone), TagScheme())


def test_commitizen_tag_format_is_reused(repo):
    repo.write(
        "pyproject.toml",
        '[project]\nname="x"\n[tool.commitizen]\ntag_format = "release-$version"\n',
    )
    config = load_config(repo.path)
    assert config.tag_pattern == "release-{version}"
