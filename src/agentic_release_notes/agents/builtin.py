"""Built-in backends: GitHub Copilot CLI, Claude Code, Codex CLI and any stdin/stdout command."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from agentic_release_notes.agents import READ_ONLY_GIT, Agent, AgentError


class CopilotAgent(Agent):
    """GitHub Copilot CLI (``copilot``, or ``gh copilot``). Auth: COPILOT_GITHUB_TOKEN."""

    name = "copilot"
    supports_resume = True
    executables = ("copilot", "gh")

    def command(self, session_id: str) -> list[str]:
        base = ["copilot"] if shutil.which("copilot") else ["gh", "copilot", "--"]
        command = [
            *base,
            "--silent",
            "--no-ask-user",
            "--no-auto-update",
            "--no-color",
            "--output-format",
            "json",
            "--disable-builtin-mcps",
            "--available-tools=view,glob,grep,bash",
            "--allow-tool=read",
            *[f"--allow-tool=shell(git {sub}:*)" for sub in READ_ONLY_GIT],
            "--deny-tool=write",
            "--secret-env-vars=COPILOT_GITHUB_TOKEN,GH_TOKEN,GITHUB_TOKEN",
            "--session-id",
            session_id,  # creates the session, or resumes it on retries
        ]
        if self.config.model:
            command += ["--model", self.config.model]
        return command + list(self.config.extra_args)

    def ask(self, prompt: str, cwd: Path, session_id: str, resume: bool) -> str:
        result = self._run(self.command(session_id), prompt, cwd)
        return parse_copilot_events(result.stdout)


def parse_copilot_events(stdout: str) -> str:
    answer = None
    completed = False
    for line in stdout.splitlines():
        if not line.strip().startswith("{"):
            continue
        event = json.loads(line)
        data = event.get("data") or {}
        if event.get("type") == "result":
            if event.get("exitCode") != 0:
                raise AgentError(f"copilot reported exit code {event.get('exitCode')}")
            modified = event.get("usage", {}).get("codeChanges", {}).get("filesModified")
            if modified:
                raise AgentError(f"copilot modified files despite read-only mode: {modified}")
            completed = True
        if (
            event.get("type") == "assistant.message"
            and data.get("phase") == "final_answer"
            and not data.get("toolRequests")
        ):
            answer = data.get("content")
    if not completed or not isinstance(answer, str) or not answer.strip():
        raise AgentError("copilot did not return a completed final answer")
    return answer


class ClaudeAgent(Agent):
    """Claude Code in print mode. Auth: ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN."""

    name = "claude"
    supports_resume = True
    executables = ("claude",)

    def ask(self, prompt: str, cwd: Path, session_id: str, resume: bool) -> str:
        allowed = ["Read", "Grep", "Glob", *[f"Bash(git {sub}:*)" for sub in READ_ONLY_GIT]]
        command = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--allowedTools",
            ",".join(allowed),
            "--disallowedTools",
            "Write,Edit,NotebookEdit,WebFetch,WebSearch",
            "--resume" if resume else "--session-id",
            session_id,
        ]
        if self.config.model:
            command += ["--model", self.config.model]
        result = self._run(command + list(self.config.extra_args), prompt, cwd)
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AgentError(f"claude returned non-JSON output: {result.stdout[:500]}") from error
        if data.get("is_error") or not isinstance(data.get("result"), str):
            raise AgentError(f"claude failed: {str(data)[:1000]}")
        return data["result"]


class CodexAgent(Agent):
    """OpenAI Codex CLI in a read-only sandbox. Auth: OPENAI_API_KEY or codex login."""

    name = "codex"
    executables = ("codex",)

    def ask(self, prompt: str, cwd: Path, session_id: str, resume: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "answer.md"
            command = [
                "codex",
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-last-message",
                str(out),
            ]
            if self.config.model:
                command += ["--model", self.config.model]
            self._run([*command, *self.config.extra_args, "-"], prompt, cwd)
            if not out.is_file():
                raise AgentError("codex did not write a final answer")
            return out.read_text()


class CommandAgent(Agent):
    """Any command: receives the brief on stdin (or as ``{prompt_file}``), answers on stdout.

    Example: ``command = ["llm", "-m", "my-model"]`` or a wrapper script around an in-house agent.
    """

    name = "command"

    @classmethod
    def available(cls) -> bool:
        return True

    def ask(self, prompt: str, cwd: Path, session_id: str, resume: bool) -> str:
        if not self.config.command:
            raise AgentError("agent.command must be set for the 'command' backend")
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.md"
            prompt_file.write_text(prompt)
            command = [
                part.replace("{prompt_file}", str(prompt_file)).replace("{cwd}", str(cwd))
                for part in self.config.command
            ]
            uses_file = any("{prompt_file}" in part for part in self.config.command)
            result = self._run(command, "" if uses_file else prompt, cwd)
        return result.stdout


BUILTIN = {
    "copilot": CopilotAgent,
    "claude": ClaudeAgent,
    "codex": CodexAgent,
    "command": CommandAgent,
}
