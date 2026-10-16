# Agentic Release Notes

This repository is the standalone, MIT-licensed Python CLI and GitHub Action for generating
user-facing release notes from release evidence. The installed commands are
`agentic-release-notes` and its short alias `arn`.

## Start here

- [README.md](README.md): installation, user commands, supported agents, and extension points.
- [examples/release-notes.toml](examples/release-notes.toml): configuration options.
- [action.yml](action.yml) and [examples/release-notes-on-tag.yml](examples/release-notes-on-tag.yml):
  GitHub Action inputs and integration.
- [justfile](justfile): development commands and completion checks.

## Structure

All implementation modules below live in `src/agentic_release_notes/`.

- `cli.py`, `__main__.py`: CLI commands and entry point.
- `config.py`, `project.py`: configuration and project/forge discovery.
- `git.py`, `versions.py`, `range.py`, `commits.py`: Git access, release selection, and commit parsing.
- `evidence.py`, `context.py`, `prompt.py`: prioritized diffs, release context, and agent briefs.
- `docs/`: documentation providers, public URLs, and renderer-specific heading anchors.
- `agents/`: backend interface and built-in Copilot, Claude, Codex, and command adapters.
- `pipeline.py`: release worktree lifecycle, agent retries, and fallback behavior.
- `notes.py`, `deterministic.py`, `render.py`: notes schema, validation, agent-free notes, and rendering.
- `data/SKILL.md`: packaged skill for interactive use; keep it aligned with the CLI.

Other important paths:

- `tests/`: pytest tests, including isolated Git fixtures and a scripted agent pipeline.
- `pyproject.toml`, `uv.lock`: package metadata, Python requirements, and locked dependencies.
- `.github/workflows/ci.yml`: lint, formatting, tests on Python 3.11/3.13, and deterministic smoke test.
- `.github/workflows/release-notes.yml`: tag-triggered draft releases using this project's action.

## Design direction

- Write for users: explain changed behavior, the benefit, and any required action. Use examples
  and documentation from the release rather than treating commit titles as the whole story.
- Preserve the pipeline: computed evidence, agent interpretation as JSON, computed validation,
  then rendering. Agents do not write the final Markdown.
- Read release content at the selected Git commit. Keep agent runs isolated in a disposable
  release worktree and preserve each built-in backend's read-only restrictions.
- Validate agent notes against release commits, indexed documentation pages and anchors, and
  example source paths. Feed validation errors back into bounded retries; respect the configured
  fallback rather than silently accepting an invalid answer.
- Keep deterministic generation usable without an agent CLI, credentials, or network access.
- Extend documentation providers, agents, and renderers through the existing entry-point groups.
  Keep renderer-specific URL and anchor behavior in `docs/`.
- Keep this package independent of other local repositories. Examples and tests must work from
  a standalone clone.

## Development workflow

Use Python 3.11 or newer, `uv`, and `just`. Run Python tools through `uv run`; `just` recipes use
the committed lockfile. No Node.js setup or authenticated agent is needed for local checks.

- List commands: `just` or `just --list`.
- Set up or restore dependencies: `just dev` (`just install` is an alias).
- Upgrade dependencies and refresh `uv.lock`: `just update`.
- Format Python and the justfile: `just format`.
- Check lint and formatting: `just check`.
- Run tests: `just test`; pass pytest options with `just test -q`.
- Build the wheel and source distribution in `dist/`: `just build`.
- Exercise generation on this repository without an agent: `just smoke`.
- Run the CLI: `just run --help` or `just run range`.
- Remove build output and tool caches: `just clean`.
- Run all validation: `just preflight`.

When changing CLI flags, configuration, or Action behavior, update the README, examples, and
packaged skill where relevant. Keep tests isolated from real agent services and GitHub writes;
use temporary repositories and scripted agents as in `tests/test_pipeline.py`.

## Completion gate

Run `just preflight` after changes and before committing. It checks lint and formatting, runs
pytest, builds the package, and exercises deterministic generation. It does not publish releases.
Do not commit virtual environments, caches, `dist/`, generated notes, or credentials.

Use Conventional Commit subjects that describe user impact. Explain what users can now do or
which limitation is resolved in the body; avoid WIP messages and lists of changed files.
