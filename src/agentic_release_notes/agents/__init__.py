"""Coding-agent backends.

A backend sends the brief to a coding agent running read-only in a checkout of the release and
returns its final answer. Backends that can resume a session receive only the validation
feedback on retries; others receive the full brief again.

Third-party backends register an ``Agent`` subclass under the ``agentic_release_notes.agents``
entry-point group.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from importlib.metadata import entry_points
from pathlib import Path

from agentic_release_notes.config import AgentConfig

# git subcommands an agent may run: inspection only, nothing that writes refs or the worktree.
READ_ONLY_GIT = [
    "log",
    "show",
    "diff",
    "grep",
    "ls-files",
    "ls-tree",
    "cat-file",
    "rev-parse",
    "blame",
    "shortlog",
    "merge-base",
    "for-each-ref",
    "describe",
    "status",
    "rev-list",
]


class AgentError(RuntimeError):
    """The agent could not produce an answer (not a validation problem)."""


class Agent(ABC):
    name: str = ""
    supports_resume = False
    executables: tuple[str, ...] = ()

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @classmethod
    def available(cls) -> bool:
        return any(shutil.which(e) for e in cls.executables)

    @abstractmethod
    def ask(self, prompt: str, cwd: Path, session_id: str, resume: bool) -> str:
        """Return the agent's final answer text."""

    def _run(self, command: list[str], prompt: str, cwd: Path) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                command,
                input=prompt,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.timeout,
            )
        except FileNotFoundError as error:
            raise AgentError(f"{self.name}: {command[0]} is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise AgentError(f"{self.name}: no answer within {self.config.timeout}s") from error
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip()[-2000:]
            raise AgentError(f"{self.name} exited with {result.returncode}: {tail}")
        return result


def agents() -> dict[str, type[Agent]]:
    from agentic_release_notes.agents import builtin

    registry: dict[str, type[Agent]] = dict(builtin.BUILTIN)
    for ep in entry_points(group="agentic_release_notes.agents"):
        registry[ep.name] = ep.load()
    return registry


def get_agent(config: AgentConfig) -> Agent | None:
    """Instantiate the configured backend; ``None`` means the deterministic generator."""
    name = config.backend
    if name == "none":
        return None
    registry = agents()
    if name == "auto":
        for candidate in ("copilot", "claude", "codex"):
            if registry[candidate].available():
                return registry[candidate](config)
        raise AgentError(
            "No coding agent found (copilot, claude, codex). Install one, configure "
            "agent.backend = 'command', or use --agent none for conventional-commit notes."
        )
    if name not in registry:
        raise AgentError(f"Unknown agent {name!r}; known: {', '.join(registry)}, none")
    return registry[name](config)
