# List the available development commands.
default:
    @just --list

# Set up or restore the development environment from the lockfile.
dev:
    uv sync --locked --group dev

alias install := dev

# Upgrade dependencies and refresh the development environment.
update:
    uv lock --upgrade
    uv sync --locked --group dev

# Format Python sources, tests, and the justfile.
format:
    uv run --locked --group dev ruff format src tests
    just --unstable --fmt

# Check Python lint rules.
lint:
    uv run --locked --group dev ruff check src tests

# Check Python and justfile formatting without changing files.
format-check:
    uv run --locked --group dev ruff format --check src tests
    just --unstable --fmt --check

# Run lint and formatting checks without changing files.
check: lint format-check

# Run tests; additional arguments are passed to pytest.
[positional-arguments]
test *args:
    uv run --locked --group dev pytest "$@"

# Build the wheel and source distribution in dist/.
build:
    uv build

# Generate notes for this repository without an agent or publishing.
smoke:
    uv run --locked agentic-release-notes generate --agent none --version v0.0.0-ci

# Run any CLI command, e.g. just run range or just run generate --agent none.
[positional-arguments]
run *args:
    uv run --locked agentic-release-notes "$@"

# Run all local validation without publishing releases.
preflight: check test build smoke

# Remove build output and tool caches, keeping the virtual environment.
clean:
    rm -rf dist .pytest_cache .ruff_cache
