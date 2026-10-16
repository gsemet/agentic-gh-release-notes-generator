---
name: release-notes
description: >-
  Write user-facing release notes for a git release (tag, branch or HEAD) that explain what
  matters to users, with examples from the docs or tests and links to the exact documentation
  sections. Use when asked for release notes, a changelog entry or "what changed since vX".
---

# Release notes

You write the notes; the `agentic-release-notes` tool computes the evidence and checks your
work. Never skip the validation step: it is what guarantees that every claim is backed by a
commit of the release and that every link opens an existing documentation section.

If the tool is missing, run it with
`uvx --from git+https://github.com/gsemet/agentic-gh-release-notes-generator agentic-release-notes`
in place of `agentic-release-notes` below.

## Steps

1. Resolve the range and check it is the one the user means:

   ```bash
   agentic-release-notes range --to <tag-or-ref> [--from <previous>] [--version vX.Y.Z]
   ```

   Without `--to`, the tag on HEAD is used, else HEAD ("Unreleased"). Use `--version` to label
   an untagged target before tagging it.

2. Produce the brief and read it entirely. It contains the editorial rules, the JSON output
   contract, the documentation index (the only URLs you may link), project terminology,
   commits and prioritized diffs:

   ```bash
   agentic-release-notes context --to <ref> -o /tmp/release-brief.md
   ```

3. Investigate like the brief says: read the diffs and the documentation at the release
   (`git show <tag>:<path>`), not only commit messages. Decide what matters to users.

4. Write the JSON answer described by the brief to `release-notes.json`.

5. Validate, fix every reported error, and repeat until it passes:

   ```bash
   agentic-release-notes validate --to <ref> release-notes.json
   ```

6. Render and show the result to the user:

   ```bash
   agentic-release-notes render --to <ref> release-notes.json --format github -o release-notes.md
   ```

   Formats: `github` (release body), `changelog` (entry for CHANGELOG.md), `json`.

7. Only if the user asks, publish: `agentic-release-notes publish --tag <tag> --notes
   release-notes.md --draft`.

## Non-interactive alternative

`agentic-release-notes generate --to <ref> --agent copilot|claude|codex -o release-notes.md`
runs the same loop headlessly (used in CI).
