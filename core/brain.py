"""Request routing for the Seesam terminal assistant."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.commands import handle_local_command
from core.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, OllamaError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERSONALITY_PATH = PROJECT_ROOT / "personality" / "seesam.txt"
ENV_PATH = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_PATH) -> None:
    """Load simple KEY=VALUE entries from .env without external dependencies."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_personality(path: Path = PERSONALITY_PATH) -> str:
    """Load Seesam's Finnish personality prompt."""
    return path.read_text(encoding="utf-8").strip()


def build_client() -> OllamaClient:
    """Create an Ollama client from environment configuration."""
    return OllamaClient(
        model=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        host=os.environ.get("OLLAMA_HOST", DEFAULT_HOST),
    )


@dataclass
class Brain:
    """Route terminal-chat input to local commands or the Ollama model."""

    client: OllamaClient
    personality: str

    @classmethod
    def from_environment(cls) -> "Brain":
        """Create the assistant brain from local configuration files and env vars."""
        load_env_file()
        return cls(client=build_client(), personality=load_personality())

    def respond(self, user_input: str) -> str:
        """Return Seesam's response to one terminal-chat input."""
        local_response = handle_local_command(user_input)
        if local_response is not None:
            return local_response

        try:
            return self.client.generate(user_input, self.personality)
        except OllamaError as exc:
            return str(exc)
