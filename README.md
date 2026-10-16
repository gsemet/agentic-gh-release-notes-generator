# agentic-release-notes

Release notes that tell users what matters to them, written by a coding agent from the actual
changes, and checked by code before anyone reads them.

There are three levels of release-notes automation:

1. **Computed**: commitizen, release-please, git-cliff. Conventional commits grouped by type.
   Fast and reliable, but it is the developer's changelog, not the user's.
2. **Reworded**: an LLM polishes commit messages using a glossary or a few docs. Nicer prose,
   same blind spots: if the commit message is vague or wrong, so is the note.
3. **Interpreted**: what this tool does. An agent reads the diffs, the documentation and the
   tests of the release, decides what changes things for *users* following the project's
   conventions, shows an example taken from the docs or tests, and links each item to the exact
   documentation section where users can act on it.

Level 3 alone makes things up. Here the agent is boxed in by computation on both sides:

```text
 computed evidence            agent interpretation          computed validation
┌─────────────────────┐      ┌──────────────────────┐      ┌──────────────────────────┐
│ release range       │      │ reads diffs, docs,   │      │ every item cites commits │
│ commits (parsed)    │ ───▶ │ tests (read-only     │ ───▶ │ of the range             │
│ prioritized diff    │      │ worktree at the tag) │      │ every link = existing    │
│ docs index: public  │      │ answers JSON         │      │ page + anchor            │
│ URLs + anchors      │      │                      │ ◀─── │ examples come from files │
│ glossary, AGENTS.md │      │                      │ errors│ of the release           │
└─────────────────────┘      └──────────────────────┘      └────────────┬─────────────┘
                                                                         ▼
                                                     render: GitHub release, changelog, JSON
```

The agent never writes the final Markdown, so formatting is consistent and a hallucinated
link or commit becomes a precise error message fed back to the agent, not a broken release
page.

## Install

No installation is needed in a project: run it from git with `uv`.

```bash
# one-off
uvx --from git+https://github.com/gsemet/agentic-gh-release-notes-generator agentic-release-notes --help

# installed (also provides the short alias `arn`)
uv tool install git+https://github.com/gsemet/agentic-gh-release-notes-generator
```

You also need one coding agent CLI, authenticated: GitHub Copilot CLI (`copilot`, or
`gh copilot`), Claude Code (`claude`) or Codex (`codex`). Without one, `--agent none` still
produces notes from conventional commits.

## Quick start

```bash
cd my-project
agentic-release-notes range                # which release, which commits?
agentic-release-notes docs                 # which documentation pages can be linked?
agentic-release-notes generate -o release-notes.md
```

`generate` without `--to` uses the tag on `HEAD`, or `HEAD` itself as "Unreleased". Typical
variants:

```bash
agentic-release-notes generate --to v1.4.0                 # an existing tag
agentic-release-notes generate --version v1.4.0            # HEAD, before tagging it
agentic-release-notes generate --to v1.4.0 --from v1.2.0   # explicit range
agentic-release-notes generate --format changelog          # entry for CHANGELOG.md
agentic-release-notes generate --agent claude --model claude-sonnet-5-5
agentic-release-notes generate --debug-dir .notes-debug    # keep prompt, answers, errors
```

## In GitHub Actions

```yaml
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  notes:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # full history and tags
      - uses: gsemet/agentic-gh-release-notes-generator@main
        with:
          copilot-token: ${{ secrets.COPILOT_GITHUB_TOKEN }}
          publish: draft
```

The action installs the agent CLI, writes `release-notes.md`, adds it to the job summary and,
with `publish`, creates a draft release (`draft`), a published release (`release`) or replaces
the notes of an existing one (`update`). See [action.yml](action.yml) for all inputs and
[examples/release-notes-on-tag.yml](examples/release-notes-on-tag.yml) for a complete workflow.
Other CI systems run the same CLI command.

## Interactive use from an IDE agent

```bash
agentic-release-notes skill --install .github/skills   # or .claude/skills, .agents/skills
```

The skill makes your IDE agent (Copilot, Claude Code...) do the writing while the tool
supplies the brief (`context`) and checks the result (`validate`, `render`). The same
guarantees apply, and you can steer the agent in the conversation.

## Releases it understands

| Situation | Behaviour |
| --- | --- |
| Tag on a release/bump commit (commitizen, semantic-release) | bump/release commits are filtered from the evidence |
| Tag on any commit (scm versioning, manual tags) | works as is |
| `v1.2.3`, `1.2.3`, calver, PEP 440, semver prereleases | ordered by version, not by date |
| Prefixed or monorepo tags (`pkg@1.2.3`) | `tag_pattern = "pkg@{version}"` plus `paths = ["packages/pkg"]` |
| commitizen `tag_format` | reused automatically |
| Stable after release candidates | compared with the previous *stable* release (`prerelease_baseline`) |
| Untagged HEAD, branch or sha | "Unreleased", or `--version vX.Y.Z` to label it before tagging |
| First release | the whole history; the agent describes the project overall |
| Release branches and backports | closest lower version that is an ancestor; explicit non-ancestor `--from` is supported with a warning |
| Several tags on one commit | the highest matching version names the release |
| Shallow CI clone | refused with the fix (`fetch-depth: 0`) |

## Documentation it links to

The docs index maps documentation *sources at the release commit* to their public URLs and
anchors, with each renderer's slug rules. With no configuration, it detects MkDocs or Sphinx,
then indexes the remaining Markdown as rendered by the forge.

| Provider | Covers | Public URL from |
| --- | --- | --- |
| `sphinx` | Sphinx, MyST, reStructuredText, Read the Docs | `html_baseurl`, `Documentation` project URL, `.readthedocs.yaml` guess |
| `mkdocs` | MkDocs, Material for MkDocs | `site_url`, `use_directory_urls` |
| `markdown` | README and docs rendered by GitHub or GitLab | forge URL, **pinned to the release tag** |
| `static` | Docusaurus, VitePress, Hugo, Jekyll... | `base_url`, `url_style`, `slug` options |

Anchors are verified against the real renderers: on okf-schema, all 311 anchors computed for
its Read the Docs site exist in the published HTML, and GitHub-rendered READMEs match too.

Check what was found with `agentic-release-notes docs`, and print a starter configuration with
`agentic-release-notes init`.

## Configuration

Optional. Put it in `.release-notes.toml`, `.github/release-notes.toml`, or under
`[tool.agentic-release-notes]` in `pyproject.toml`. The most useful keys:

```toml
product = "acme: a CLI to sync calendars"            # default: from pyproject/package.json
audience = "people who run acme from cron jobs"
guidance = "Always name the config key when behaviour depends on one."

[agent]
backend = "copilot"     # auto | copilot | claude | codex | command | none
fallback = "error"      # or "deterministic"

[links]
require = true          # features/improvements/breaking must link the docs

[[docs]]
type = "sphinx"
base_url = "https://acme.readthedocs.io/en/stable/"
```

[examples/release-notes.toml](examples/release-notes.toml) documents every key.

## Agents

| Backend | CLI | Authentication | Read-only enforcement |
| --- | --- | --- | --- |
| `copilot` | `copilot` or `gh copilot` | `COPILOT_GITHUB_TOKEN` or `copilot login` | read tools and read-only git subcommands only, writes denied, modified files rejected |
| `claude` | `claude` | `ANTHROPIC_API_KEY` or `claude login` | `Read`, `Grep`, `Glob`, read-only git subcommands |
| `codex` | `codex` | `OPENAI_API_KEY` or `codex login` | `--sandbox read-only` |
| `command` | anything | yours | yours: the brief comes on stdin (or `{prompt_file}`), the answer goes to stdout |
| `none` | | | no agent: conventional-commit notes |

Every agent runs in a temporary `git worktree` of the release commit, so it reads the files
that were actually released and cannot touch your working tree. On a rejected answer, Copilot
and Claude resume their session and only receive the errors.

## Commands

| Command | Purpose |
| --- | --- |
| `range` | resolved release range and commits (JSON) |
| `docs` | documentation index: pages, URLs, anchors |
| `context` | the full agent brief, to drive any agent yourself |
| `generate` | brief an agent, validate, retry with feedback, render |
| `validate` | check a notes JSON against the release evidence |
| `render` | render a notes JSON (`github`, `changelog`, `json`) |
| `publish` | create or update the GitHub release (uses `gh`) |
| `init` | print a starter configuration from what was detected |
| `skill` | print or install the interactive agent skill |

## Extending

Three entry-point groups let a package add capabilities without touching this one:

```toml
[project.entry-points."agentic_release_notes.docs"]
antora = "my_pkg.docs:antora"          # build(context, options) -> DocsSite | None

[project.entry-points."agentic_release_notes.agents"]
inhouse = "my_pkg.agent:InHouseAgent"  # subclass of agentic_release_notes.agents.Agent

[project.entry-points."agentic_release_notes.renderers"]
slack = "my_pkg.render:slack"          # render(notes, options) -> str
```

Then use `[[docs]] type = "antora"`, `--agent inhouse` or `--format slack`. Install them
together with `uv tool install --with my-pkg git+https://...`.

## Development

Use Python 3.11 or newer, `uv`, and `just`. Start with `just dev` to install the locked
dependencies, then run `just preflight` before committing. Local validation needs no agent
authentication and does not publish releases.

```bash
just dev
just preflight
```

| Command | Purpose |
| --- | --- |
| `just` | list available commands |
| `just dev` / `just install` | set up or restore the development environment |
| `just update` | upgrade dependencies and refresh `uv.lock` |
| `just format` | format Python and the justfile |
| `just check` | check lint and formatting without changing files |
| `just test` | run pytest; accepts options such as `just test -q` |
| `just build` | build the wheel and source distribution in `dist/` |
| `just smoke` | generate notes for this repository without an agent |
| `just run --help` | run the CLI from the checkout |
| `just preflight` | run checks, tests, packaging, and the smoke test |
| `just clean` | remove build output and tool caches |

See [AGENTS.md](AGENTS.md) for the code map, design direction, and contribution workflow.
The underlying Python commands remain available without `just`:

```bash
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

## Origin

This generalizes two earlier versions of the same idea: the prompt-only `gh-release-notes`
skill of [okf-schema](https://github.com/gsemet/okf-schema), and the validated Copilot script
of [markdown-okf-schema-studio](https://github.com/gsemet/markdown-okf-schema-studio).
