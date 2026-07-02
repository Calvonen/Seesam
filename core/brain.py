"""Request routing for the Seesam terminal assistant."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.commands import handle_local_command
from core.config import PROJECT_ROOT, load_env_file
from core.memory import AssistantIdentityMemory, EpisodeLog, Memory, UserProfileMemory
from core.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, OllamaError
from core.system_status import SystemStatus

PERSONALITY_PATH = PROJECT_ROOT / "personality" / "seesam.txt"
MEMORY_DIR = PROJECT_ROOT / "memory"
ASSISTANT_IDENTITY_PATH = MEMORY_DIR / "seesam.local.yaml"
USER_PROFILE_PATH = MEMORY_DIR / "marko.local.yaml"
MEMORY_PATH = MEMORY_DIR / "memories.local.txt"
EPISODE_LOG_PATH = MEMORY_DIR / "episodes.local.log"
LEGACY_MARKO_MEMORY_PATH = MEMORY_DIR / "marko.local.txt"
LEGACY_MEMORY_DIR = MEMORY_DIR / "legacy"
MEMORY_COMMAND_PATTERN = re.compile(r"^\s*muista\s+(?:tämä|tama|tamä)\s*:\s*(.*)$", re.IGNORECASE)
DEEP_MEMORY_COMMAND_PATTERN = re.compile(r"^\s*tallenna syvään muistiin\s*:\s*(.*)$", re.IGNORECASE)
MEMORY_LIST_COMMAND_PATTERN = re.compile(r"^\s*(?:mitä muistat|näytä muisti|näytä muistot)\s*$", re.IGNORECASE)
SELF_IDENTITY_QUESTION_PATTERN = re.compile(
    r"^\s*(?:kuka\s+(?:(?:sinä|sina|sä|sa)\s+)?olet|mikä\s+sinun\s+nimesi\s+on)\s*[?.!]?\s*$",
    re.IGNORECASE,
)
ASSISTANT_NAME_QUESTION_PATTERN = re.compile(r"^\s*kuka\s+on\s+(?P<name>.+?)\s*[?.!]?\s*$", re.IGNORECASE)
LATEST_MEMORY_LIST_COMMAND_PATTERN = re.compile(r"^\s*näytä viimeisimmät muistot\s*$", re.IGNORECASE)
LATEST_MEMORY_COMMAND_PATTERN = re.compile(
    r"^\s*mikä on viimeisin (?:muistosi|tallennettu muistosi)\s*$", re.IGNORECASE
)
DELETE_LATEST_MEMORY_COMMAND_PATTERN = re.compile(
    r"^\s*(?:poista viimeisin muistosi|poista viimeisin muisto|peru viimeisin muisto|unohda viimeisin muisto)\s*$",
    re.IGNORECASE,
)
DELETE_MEMORY_NUMBER_COMMAND_PATTERN = re.compile(r"^\s*poista muisto numero\s+(?P<number>\d+)\s*$", re.IGNORECASE)
CONVERSATION_HISTORY_LIMIT = 6
LATEST_MEMORY_LIMIT = 5
MEMORY_RESPONSE = "Muistan tämän."
DEEP_MEMORY_RESPONSE = "Tallensin tämän syvään muistiin."
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


def initialize_local_memory_files() -> None:
    """Create current memory files and migrate legacy marko.local.txt content if needed."""
    assistant_identity = AssistantIdentityMemory(ASSISTANT_IDENTITY_PATH)
    user_profile = UserProfileMemory(USER_PROFILE_PATH)
    assistant_identity.load()
    user_profile.load()
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.touch(exist_ok=True)
    EPISODE_LOG_PATH.touch(exist_ok=True)

    if not LEGACY_MARKO_MEMORY_PATH.exists():
        return

    legacy_lines = [
        line.strip()
        for line in LEGACY_MARKO_MEMORY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not legacy_lines:
        _archive_legacy_marko_memory()
        return

    existing_memory_lines = set(MEMORY_PATH.read_text(encoding="utf-8").splitlines()) if MEMORY_PATH.exists() else set()
    profile_lines: list[str] = []
    assistant_lines: list[str] = []
    migrated = False
    for line in legacy_lines:
        if re.match(r"^M\d{6}\s*\|", line):
            if line not in existing_memory_lines:
                with MEMORY_PATH.open("a", encoding="utf-8") as memory_file:
                    memory_file.write(f"{line}\n")
                existing_memory_lines.add(line)
                migrated = True
            continue

        lowered = line.lower()
        if lowered.startswith("minun nimeni on seesam") or lowered.startswith("seesam-palvelimessa"):
            assistant_lines.append(line)
            migrated = True
            continue

        profile_lines.append(line)
        migrated = True

    for line in profile_lines:
        user_profile.append_deep_memory(line)

    if assistant_lines:
        log = EpisodeLog(EPISODE_LOG_PATH)
        for line in assistant_lines:
            log.append("legacy_assistant_memory_migrated", line)

    if migrated:
        EpisodeLog(EPISODE_LOG_PATH).append("legacy_marko_local_txt_migrated", str(LEGACY_MARKO_MEMORY_PATH))
        _archive_legacy_marko_memory()


def _archive_legacy_marko_memory() -> Path:
    """Move migrated legacy memory out of the runtime memory directory."""
    LEGACY_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    destination = LEGACY_MEMORY_DIR / LEGACY_MARKO_MEMORY_PATH.name
    if destination.exists():
        counter = 1
        while True:
            candidate = LEGACY_MEMORY_DIR / f"{LEGACY_MARKO_MEMORY_PATH.stem}.{counter}{LEGACY_MARKO_MEMORY_PATH.suffix}"
            if not candidate.exists():
                destination = candidate
                break
            counter += 1

    LEGACY_MARKO_MEMORY_PATH.rename(destination)
    return destination


@dataclass
class Brain:
    """Route terminal-chat input to local commands or the Ollama model."""

    client: OllamaClient
    personality: str
    memory: Memory | None = None
    assistant_identity: AssistantIdentityMemory | None = None
    user_profile: UserProfileMemory | None = None
    episode_log: EpisodeLog | None = None
    system_status: SystemStatus | None = None
    conversation_history: list[tuple[str, str]] = field(default_factory=list)
    history_limit: int = CONVERSATION_HISTORY_LIMIT

    @classmethod
    def from_environment(cls) -> "Brain":
        """Create the assistant brain from local configuration files and env vars."""
        load_env_file()
        initialize_local_memory_files()
        return cls(
            client=build_client(),
            personality=load_personality(),
            memory=Memory(MEMORY_PATH),
            assistant_identity=AssistantIdentityMemory(ASSISTANT_IDENTITY_PATH),
            user_profile=UserProfileMemory(USER_PROFILE_PATH),
            episode_log=EpisodeLog(EPISODE_LOG_PATH),
            system_status=SystemStatus.started_now(),
        )

    def respond(self, user_input: str) -> str:
        """Return Seesam's response to one terminal-chat input."""
        local_response = self.handle_local_command(user_input)
        if local_response is not None:
            return local_response

        return self.respond_with_ai(user_input)

    def handle_local_command(self, user_input: str) -> str | None:
        """Return a local command response, or None when AI should handle it."""
        self._log_event("user_message", user_input)

        system_status_response = self._handle_system_status_command(user_input)
        if system_status_response is not None:
            return system_status_response

        assistant_identity_response = self._handle_assistant_identity_question(user_input)
        if assistant_identity_response is not None:
            return assistant_identity_response

        memory_response = self._handle_memory_command(user_input)
        if memory_response is not None:
            return memory_response

        deep_memory_response = self._handle_deep_memory_command(user_input)
        if deep_memory_response is not None:
            return deep_memory_response

        latest_memory_response = self._handle_latest_memory_command(user_input)
        if latest_memory_response is not None:
            return latest_memory_response

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
                DEEP_MEMORY_COMMAND_PATTERN,
                MEMORY_LIST_COMMAND_PATTERN,
                LATEST_MEMORY_LIST_COMMAND_PATTERN,
                LATEST_MEMORY_COMMAND_PATTERN,
                DELETE_LATEST_MEMORY_COMMAND_PATTERN,
                DELETE_MEMORY_NUMBER_COMMAND_PATTERN,
            )
        )

    def local_command_name(self, user_input: str) -> str | None:
        """Return a debug-friendly local command name without executing it."""
        if self.system_status is not None:
            if hasattr(self.system_status, "command_name"):
                if self.system_status.command_name(user_input) is not None:
                    return "system_status"
            elif self.system_status.answer(user_input) is not None:
                return "system_status"
        if self._matches_assistant_identity_question(user_input):
            return "assistant_identity"
        if MEMORY_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_save"
        if DEEP_MEMORY_COMMAND_PATTERN.match(user_input) is not None:
            return "deep_memory_save"
        if LATEST_MEMORY_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_latest"
        if LATEST_MEMORY_LIST_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_latest_list"
        if DELETE_LATEST_MEMORY_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_delete_latest"
        if DELETE_MEMORY_NUMBER_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_delete_number"
        if MEMORY_LIST_COMMAND_PATTERN.match(user_input) is not None:
            return "memory_list"
        if handle_local_command(user_input) is not None:
            return "local_command"
        return None

    def is_system_status_command(self, user_input: str) -> bool:
        """Return whether the input is a local system-status command."""
        return self.local_command_name(user_input) == "system_status"

    def system_status_match_name(self, user_input: str) -> str:
        """Return status debug match category for API logging."""
        if self.system_status is None:
            return "none"
        if hasattr(self.system_status, "debug_match_name"):
            return self.system_status.debug_match_name(user_input)
        if self._handle_system_status_command(user_input) is not None:
            return "system_status"
        return "none"

    def _handle_system_status_command(self, user_input: str) -> str | None:
        """Return local system status answers without calling Ollama."""
        if self.system_status is None:
            return None

        return self.system_status.answer(user_input)

    def respond_with_ai(self, user_input: str) -> str:
        """Return an AI response and update short conversation history."""
        try:
            answer = self.client.generate(self._prompt_with_history(user_input), self._system_context())
        except OllamaError as exc:
            return str(exc)

        self._remember_exchange("Käyttäjä", user_input)
        self._remember_exchange("Seesam", answer)
        return answer

    def _handle_assistant_identity_question(self, user_input: str) -> str | None:
        """Return Seesam identity answers from local identity memory only."""
        if not self._matches_assistant_identity_question(user_input):
            return None

        print("[IDENTITY] using memory/seesam.local.yaml")
        return self.assistant_identity.identity_response() if self.assistant_identity is not None else None

    def _matches_assistant_identity_question(self, user_input: str) -> bool:
        """Return whether input should use only Seesam local identity memory."""
        if self.assistant_identity is None:
            return False

        if SELF_IDENTITY_QUESTION_PATTERN.match(user_input) is not None:
            return True

        match = ASSISTANT_NAME_QUESTION_PATTERN.match(user_input)
        if match is None:
            return False

        name = match.group("name").strip().strip("?.!")
        return self.assistant_identity.matches_name(name)

    def _handle_memory_command(self, user_input: str) -> str | None:
        """Save ordinary memory from a local command when requested."""
        match = MEMORY_COMMAND_PATTERN.match(user_input)
        if match is None:
            return None

        memory_text = match.group(1).strip()
        if not memory_text:
            return EMPTY_MEMORY_RESPONSE

        if self.memory is not None:
            self.memory.append(memory_text)
        self._log_event("memory_saved", memory_text)

        return MEMORY_RESPONSE

    def _handle_deep_memory_command(self, user_input: str) -> str | None:
        """Save deep user memory from a local command when requested."""
        match = DEEP_MEMORY_COMMAND_PATTERN.match(user_input)
        if match is None:
            return None

        memory_text = match.group(1).strip()
        if not memory_text:
            return EMPTY_MEMORY_RESPONSE

        if self.user_profile is not None:
            self.user_profile.append_deep_memory(memory_text)
        self._log_event("deep_memory_saved", memory_text)

        return DEEP_MEMORY_RESPONSE

    def _handle_latest_memory_command(self, user_input: str) -> str | None:
        """Return the latest saved ordinary memory."""
        if LATEST_MEMORY_COMMAND_PATTERN.match(user_input) is None:
            return None

        if self.memory is None:
            return EMPTY_MEMORY_LIST_RESPONSE

        latest = self.memory.latest_entry_text()
        if not latest:
            return EMPTY_MEMORY_LIST_RESPONSE

        return latest

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
        """Delete one ordinary memory through a conservative local command."""
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

            self._log_event("memory_deleted", deleted.label)
            return f"Poistin viimeisimmän muiston: {deleted.label}"

        match = DELETE_MEMORY_NUMBER_COMMAND_PATTERN.match(user_input)
        if match is None:
            return None

        deleted = self.memory.delete_latest_number(int(match.group("number")), LATEST_MEMORY_LIMIT)
        if deleted is None:
            return MEMORY_NUMBER_NOT_FOUND_RESPONSE

        self._log_event("memory_deleted", deleted.label)
        return f"Poistin muiston numero {match.group('number')}: {deleted.label}"

    def _handle_memory_list_command(self, user_input: str) -> str | None:
        """Return deep user memory and ordinary memories from local files."""
        if MEMORY_LIST_COMMAND_PATTERN.match(user_input) is None:
            return None

        parts: list[str] = []
        if self.user_profile is not None:
            user_profile = self.user_profile.text()
            if user_profile:
                parts.append(f"Käyttäjän syvä muisti:\n{user_profile}")

        if self.memory is not None:
            memories = self.memory.text()
            if memories:
                if self.user_profile is None:
                    parts.append(memories)
                else:
                    parts.append(f"Tavalliset muistot:\n{memories}")

        if not parts:
            return EMPTY_MEMORY_LIST_RESPONSE

        return "\n\n".join(parts)

    def _system_context(self) -> str:
        """Return the personality prompt enriched with separated local memories."""
        context_parts = [self.personality]

        if self.assistant_identity is not None:
            context_parts.append(self.assistant_identity.context_text())

        if self.user_profile is not None:
            context_parts.append(
                "Käyttäjän tiedot tulevat vain Markon paikallisesta profiilimuistista:\n"
                f"{self.user_profile.text()}"
            )

        if self.memory is not None:
            memories = self.memory.text()
            if memories:
                context_parts.append(
                    "Tavalliset muista tämä -muistot:\n"
                    f"{memories}\n\n"
                    "Käytä näitä, kun käyttäjä kysyy tallennettuihin muistoihin liittyvää. "
                    "Älä vastaa pelkällä tervehdyksellä, kun käyttäjä kysyy tietokysymyksen."
                )

        return "\n\n".join(context_parts)

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

    def _log_event(self, event: str, text: str) -> None:
        """Write a best-effort local episode log entry."""
        if self.episode_log is None:
            return

        self.episode_log.append(event, text)
