"""Request routing for the Seesam terminal assistant."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.commands import handle_local_command
from core.config import PROJECT_ROOT, load_env_file
from core.memory import Memory
from core.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, OllamaError

PERSONALITY_PATH = PROJECT_ROOT / "personality" / "seesam.txt"
MEMORY_PATH = PROJECT_ROOT / "memory" / "marko.local.txt"
MEMORY_COMMAND_PATTERN = re.compile(r"^\s*muista\s+(?:tämä|tama|tamä)\s*:\s*(.*)$", re.IGNORECASE)
MEMORY_LIST_COMMAND_PATTERN = re.compile(r"^\s*(?:mitä muistat|näytä muisti|näytä muistot)\s*$", re.IGNORECASE)
LATEST_MEMORY_LIST_COMMAND_PATTERN = re.compile(r"^\s*näytä viimeisimmät muistot\s*$", re.IGNORECASE)
DELETE_LATEST_MEMORY_COMMAND_PATTERN = re.compile(r"^\s*(?:poista|peru) viimeisin muisto\s*$", re.IGNORECASE)
DELETE_MEMORY_NUMBER_COMMAND_PATTERN = re.compile(r"^\s*poista muisto numero\s+(?P<number>\d+)\s*$", re.IGNORECASE)
CONVERSATION_HISTORY_LIMIT = 6
LATEST_MEMORY_LIMIT = 5
MEMORY_RESPONSE = "Muistan tämän."
EMPTY_MEMORY_RESPONSE = "En saanut tallennettavaa muistettavaa."
EMPTY_MEMORY_LIST_RESPONSE = "Muistissa ei ole vielä mitään."
EMPTY_MEMORY_DELETE_RESPONSE = "En löytänyt poistettavaa muistoa."
MEMORY_NUMBER_NOT_FOUND_RESPONSE = "En löytänyt muistia tuolla numerolla. Näytä viimeisimmät muistot ja valitse numero listalta."


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
    conversation_history: list[tuple[str, str]] = field(default_factory=list)
    history_limit: int = CONVERSATION_HISTORY_LIMIT

    @classmethod
    def from_environment(cls) -> "Brain":
        """Create the assistant brain from local configuration files and env vars."""
        load_env_file()
        return cls(client=build_client(), personality=load_personality(), memory=Memory(MEMORY_PATH))

    def respond(self, user_input: str) -> str:
        """Return Seesam's response to one terminal-chat input."""
        local_response = self.handle_local_command(user_input)
        if local_response is not None:
            return local_response

        return self.respond_with_ai(user_input)

    def handle_local_command(self, user_input: str) -> str | None:
        """Return a local command response, or None when AI should handle it."""
        memory_response = self._handle_memory_command(user_input)
        if memory_response is not None:
            return memory_response

        latest_memory_list_response = self._handle_latest_memory_list_command(user_input)
        if latest_memory_list_response is not None:
            return latest_memory_list_response

        memory_delete_response = self._handle_memory_delete_command(user_input)
        if memory_delete_response is not None:
            return memory_delete_response

        memory_list_response = self._handle_memory_list_command(user_input)
        if memory_list_response is not None:
            return memory_list_response

        return handle_local_command(user_input)

    def is_memory_command(self, user_input: str) -> bool:
        """Return whether the input is a memory-management command."""
        return any(
            pattern.match(user_input) is not None
            for pattern in (
                MEMORY_COMMAND_PATTERN,
                MEMORY_LIST_COMMAND_PATTERN,
                LATEST_MEMORY_LIST_COMMAND_PATTERN,
                DELETE_LATEST_MEMORY_COMMAND_PATTERN,
                DELETE_MEMORY_NUMBER_COMMAND_PATTERN,
            )
        )

    def respond_with_ai(self, user_input: str) -> str:
        """Return an AI response and update short conversation history."""
        try:
            answer = self.client.generate(self._prompt_with_history(user_input), self._system_context())
        except OllamaError as exc:
            return str(exc)

        self._remember_exchange("Käyttäjä", user_input)
        self._remember_exchange("Seesam", answer)
        return answer

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

    def _handle_latest_memory_list_command(self, user_input: str) -> str | None:
        """Return the latest saved memories as a numbered list."""
        if LATEST_MEMORY_LIST_COMMAND_PATTERN.match(user_input) is None:
            return None

        if self.memory is None:
            return EMPTY_MEMORY_LIST_RESPONSE

        memories = self.memory.latest_text(LATEST_MEMORY_LIMIT)
        if not memories:
            return EMPTY_MEMORY_LIST_RESPONSE

        return memories

    def _handle_memory_delete_command(self, user_input: str) -> str | None:
        """Delete one memory through a conservative local command."""
        if self.memory is None:
            if DELETE_LATEST_MEMORY_COMMAND_PATTERN.match(user_input) is not None:
                return EMPTY_MEMORY_DELETE_RESPONSE
            if DELETE_MEMORY_NUMBER_COMMAND_PATTERN.match(user_input) is not None:
                return MEMORY_NUMBER_NOT_FOUND_RESPONSE
            return None

        if DELETE_LATEST_MEMORY_COMMAND_PATTERN.match(user_input) is not None:
            deleted = self.memory.delete_latest()
            if deleted is None:
                return EMPTY_MEMORY_DELETE_RESPONSE

            return f"Poistin viimeisimmän muiston: {deleted.label}"

        match = DELETE_MEMORY_NUMBER_COMMAND_PATTERN.match(user_input)
        if match is None:
            return None

        deleted = self.memory.delete_latest_number(int(match.group("number")), LATEST_MEMORY_LIMIT)
        if deleted is None:
            return MEMORY_NUMBER_NOT_FOUND_RESPONSE

        return f"Poistin muiston numero {match.group('number')}: {deleted.label}"

    def _handle_memory_list_command(self, user_input: str) -> str | None:
        """Return saved memories from a local command when requested."""
        if MEMORY_LIST_COMMAND_PATTERN.match(user_input) is None:
            return None

        if self.memory is None:
            return EMPTY_MEMORY_LIST_RESPONSE

        memories = self.memory.text()
        if not memories:
            return EMPTY_MEMORY_LIST_RESPONSE

        return memories

    def _system_context(self) -> str:
        """Return the personality prompt enriched with local memories."""
        if self.memory is None:
            return self.personality

        memories = self.memory.text()
        if not memories:
            return self.personality

        return (
            f"{self.personality}\n\n"
            "Sinulla on käytössäsi paikallinen muisti Markosta. "
            "Kun käyttäjä kysyy jotain tallennettuihin muistoihin liittyvää, sinun täytyy käyttää muistia vastauksessa. "
            "Jos muistissa on suora vastaus kysymykseen, vastaa lyhyesti muistin perusteella. "
            "Älä vastaa pelkällä tervehdyksellä, kun käyttäjä kysyy tietokysymyksen.\n\n"
            f"Muistettavaa Markosta:\n{memories}"
        )

    def _prompt_with_history(self, user_input: str) -> str:
        """Return the current prompt with short in-memory conversation history."""
        if not self.conversation_history:
            return user_input

        history_lines = [f"{role}: {message}" for role, message in self.conversation_history]
        history = "\n".join(history_lines)
        return (
            "Aiempi keskustelu tässä istunnossa:\n"
            f"{history}\n\n"
            "Vastaa seuraavaan käyttäjän viestiin jatkaen keskustelua. "
            "Älä toista aiempia viestejä tarpeettomasti.\n"
            f"Käyttäjä: {user_input}"
        )

    def _remember_exchange(self, role: str, message: str) -> None:
        """Store one in-memory conversation message and keep the configured limit."""
        if self.history_limit <= 0:
            self.conversation_history.clear()
            return

        self.conversation_history.append((role, message))
        del self.conversation_history[:-self.history_limit]
