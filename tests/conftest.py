from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


class Repo:
    """A throwaway git repository with deterministic dates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tick = 0
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        self.tick += 1
        date = f"2026-01-01T00:{self.tick // 60:02d}:{self.tick % 60:02d}+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ada",
            "GIT_AUTHOR_EMAIL": "ada@example.org",
            "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org",
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        return subprocess.run(
            ["git", *args], cwd=self.path, env=env, check=True, capture_output=True, text=True
        ).stdout.strip()

    def write(self, path: str, content: str) -> None:
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message: str, files: dict[str, str] | None = None) -> str:
        for path, content in (files or {f"file-{self.tick}.txt": message}).items():
            self.write(path, content)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def tag(self, name: str, annotated: bool = False) -> None:
        if annotated:
            self.git("tag", "-a", name, "-m", name)
        else:
            self.git("tag", name)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")
