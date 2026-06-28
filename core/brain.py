"""Request routing for the Seesam terminal assistant."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from core.commands import handle_local_command
from core.memory import Memory
from core.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, OllamaError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERSONALITY_PATH = PROJECT_ROOT / "personality" / "seesam.txt"
ENV_PATH = PROJECT_ROOT / ".env"
MEMORY_PATH = PROJECT_ROOT / "memory" / "marko.txt"
MEMORY_COMMAND_PATTERN = re.compile(r"^\s*muista\s+(?:tämä|tama|tamä)\s*:\s*(.*)$", re.IGNORECASE)
MEMORY_RESPONSE = "Muistan tämän."
EMPTY_MEMORY_RESPONSE = "En saanut tallennettavaa muistettavaa."


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
    memory: Memory | None = None

    @classmethod
    def from_environment(cls) -> "Brain":
        """Create the assistant brain from local configuration files and env vars."""
        load_env_file()
        return cls(client=build_client(), personality=load_personality(), memory=Memory(MEMORY_PATH))

    def respond(self, user_input: str) -> str:
        """Return Seesam's response to one terminal-chat input."""
        memory_response = self._handle_memory_command(user_input)
        if memory_response is not None:
            return memory_response

        local_response = handle_local_command(user_input)
        if local_response is not None:
            return local_response

        try:
            return self.client.generate(user_input, self._system_context())
        except OllamaError as exc:
            return str(exc)

    def _handle_memory_command(self, user_input: str) -> str | None:
        """Save memory from a local command when requested."""
        match = MEMORY_COMMAND_PATTERN.match(user_input)
        if match is None:
            return None

        memory_text = match.group(1).strip()
        if not memory_text:
            return EMPTY_MEMORY_RESPONSE

        if self.memory is not None:
            self.memory.append(memory_text)

        return MEMORY_RESPONSE

    def _system_context(self) -> str:
        """Return the personality prompt enriched with local memories."""
        if self.memory is None:
            return self.personality

        memories = self.memory.text()
        if not memories:
            return self.personality

        return f"{self.personality}\n\nMuistettavaa Markosta:\n{memories}"
