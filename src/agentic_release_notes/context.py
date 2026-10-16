"""Assemble everything known about a release before any agent is involved."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentic_release_notes.commits import Commit, collect_commits
from agentic_release_notes.config import Config
from agentic_release_notes.docs import DocsContext, DocsIndex, build_docs_index
from agentic_release_notes.evidence import Evidence, collect_evidence
from agentic_release_notes.git import Git, GitTree, path_matches
from agentic_release_notes.notes import ReleaseNotes, ValidationContext, validate_notes
from agentic_release_notes.project import ProjectInfo, discover_project
from agentic_release_notes.range import ReleaseRange, resolve_range
from agentic_release_notes.render import RenderOptions


@dataclass
class ReleaseContext:
    root: Path
    git: Git
    config: Config
    release: ReleaseRange
    tree: GitTree
    project: ProjectInfo
    commits: list[Commit]
    ignored_commits: list[Commit]
    evidence: Evidence
    docs: DocsIndex
    context_files: dict[str, str] = field(default_factory=dict)

    @property
    def warnings(self) -> list[str]:
        return [*self.release.warnings, *self.docs.warnings]

    def commit(self, sha: str) -> Commit | None:
        return next((c for c in self.commits if c.sha == sha), None)

    def validation_context(self) -> ValidationContext:
        links = self.config.links
        allowed = list(links.allow)
        if self.project.forge:
            allowed += self.project.forge.link_prefixes
        return ValidationContext(
            commits=[c.sha for c in self.commits],
            link_checker=self.docs.check if links.strict else None,
            allowed_prefixes=allowed,
            has_docs=bool(self.docs.pages),
            file_exists=self.tree.exists,
            require_links=links.require,
        )

    def validate(self, notes: ReleaseNotes) -> list[str]:
        errors = validate_notes(notes, self.validation_context())
        if not errors:
            self.attach_pull_requests(notes)
        return errors

    def attach_pull_requests(self, notes: ReleaseNotes) -> None:
        for item in notes.items():
            prs = {c.pull_request for sha in item.commits if (c := self.commit(sha))}
            item.pull_requests = sorted({*item.pull_requests, *(p for p in prs if p)})

    def render_options(self) -> RenderOptions:
        date = self.git.run("show", "-s", "--format=%cs", self.release.target_commit)
        return RenderOptions(
            titles=self.config.sections,
            forge=self.project.forge,
            show_commits=self.config.show_commits,
            previous=self.release.previous_tag,
            target=self.release.target_tag,
            date=date,
        )


def _read_context_files(tree: GitTree, config: Config) -> dict[str, str]:
    files = [
        f
        for f in tree.glob(*config.all_context_files)
        if not path_matches(f, ["**/node_modules/**", "**/_build/**", "**/.venv/**"])
    ]
    budget = config.context_max_chars
    out: dict[str, str] = {}
    for path in files:
        if budget <= 0:
            break
        text = tree.read(path) or ""
        cap = min(budget, 12_000)
        if len(text) > cap:
            text = text[:cap] + "\n... [truncated]"
        out[path] = text
        budget -= len(text)
    return out


def build_context(
    root: Path,
    config: Config,
    target: str | None = None,
    previous: str | None = None,
    version: str | None = None,
) -> ReleaseContext:
    git = Git(root)
    root = git.toplevel()
    git = Git(root)
    release = resolve_range(
        git,
        config.tag_scheme,
        target=target,
        previous=previous,
        version=version,
        prerelease_baseline=config.prerelease_baseline,
    )
    tree = GitTree(git, release.target_commit)
    project = discover_project(git, tree)
    commits, ignored = collect_commits(
        git, release.log_range, config.paths, config.all_ignore_commits
    )
    if not commits:
        release.warnings.append("No commits besides release/bump commits in this range")
    evidence = collect_evidence(
        git, release.previous_commit, release.target_commit, config.paths, config.evidence
    )
    docs = build_docs_index(
        DocsContext(
            tree=tree,
            project=project,
            release=release,
            changed_files={f.path for f in evidence.files},
        ),
        config.docs,
    )
    return ReleaseContext(
        root=root,
        git=git,
        config=config,
        release=release,
        tree=tree,
        project=project,
        commits=commits,
        ignored_commits=ignored,
        evidence=evidence,
        docs=docs,
        context_files=_read_context_files(tree, config),
    )
