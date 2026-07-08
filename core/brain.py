"""Request routing for the Seesam terminal assistant."""

from __future__ import annotations

import difflib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from core import energyzen, shelly
from core.commands import handle_local_command
from core.command_matcher import CommandDefinition, is_confirmation_no, is_confirmation_yes, match_command
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
DEVICES_PATH = MEMORY_DIR / "devices.local.yaml"
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
SHELLY_CONNECTION_ERROR_RESPONSE = "En saanut yhteyttä Shelly-laitteeseen."
SHELLY_NEAR_MATCH_THRESHOLD = 0.80
SHELLY_AUTO_MATCH_THRESHOLD = 0.93
SHELLY_AMBIGUITY_MARGIN = 0.02
SHELLY_CONFIRMATION_TTL_SECONDS = 30.0
SHELLY_CONFIRMATION_YES = {"kylla", "joo", "juu", "tee niin", "kylla vaan", "ok"}
SHELLY_CONFIRMATION_NO = {"ei", "ala", "peruuta", "unohda"}
ENERGYZEN_CONNECTION_ERROR_RESPONSE = "En saanut haettua varaajan tietoja."
GRILLIKATOS_LIGHTS_ON_RESPONSE = "Grillikatoksen valot sytytetty."
GRILLIKATOS_LIGHTS_OFF_RESPONSE = "Grillikatoksen valot sammutettu."
ENERGYZEN_TANK_WORDS = (
    "varaaja",
    "varaajan",
    "varaajassa",
    "varraaja",
    "varraajan",
    "varaaj",
    "raaja",
    "vesivaraaja",
    "lamminvesivaraaja",
    "lammin vesi",
    "varaja",
    "varaj",
)
ENERGYZEN_STATUS_WORDS = {"tila", "lampotila", "lampo", "paljonko", "kuinka", "riittaako", "vesi", "vetta"}
ENERGYZEN_TANK_PHRASE_PATTERNS = (
    re.compile(r"\bvaraa?\s+jossa\b"),
)
ENERGYZEN_HEAT_WORDS = ("lampo", "lamminta", "suihku","lämmin",)
ENERGYZEN_SHOWER_PHRASES = ("lammita suihku", "suihkuja")
WAKE_WORD_VARIANTS = {"seesam", "seesami", "sesam", "seisem", "seisemmin", "seism", "seisma"}


def load_personality(path: Path = PERSONALITY_PATH) -> str:
    """Load Seesam's Finnish personality prompt."""
    return path.read_text(encoding="utf-8").strip()


def _normalize_command_text(text: str) -> str:
    """Normalize Finnish voice command text for conservative local matching."""
    lowered = text.lower().strip()
    lowered = lowered.translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"}))
    lowered = re.sub(r"[?.!,]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return _normalize_voice_command_errors(lowered)


def is_wake_word_only(text: str) -> bool:
    """Return whether input is only Seesam's wake word or a common STT variant."""
    normalized = _normalize_command_text(text)
    words = normalized.split()
    if words and words[0] == "hei":
        words = words[1:]
    return len(words) == 1 and words[0] in WAKE_WORD_VARIANTS


def _strip_wake_word_prefix(text: str) -> str:
    """Remove a leading wake word while preserving the command after it."""
    stripped = text.strip()
    normalized = _normalize_command_text(stripped)
    if normalized.startswith("seesam aukene") or normalized.startswith("hei seesam aukene"):
        return stripped
    wake_pattern = "|".join(sorted(WAKE_WORD_VARIANTS, key=len, reverse=True))
    return re.sub(rf"(?i)^\s*(?:hei\s+)?(?:{wake_pattern})(?=$|[\s?.!,])[\s?.!,]*", "", stripped).strip() or stripped


def _normalize_voice_command_errors(text: str) -> str:
    text = text.replace("lamminta vetta", "lammin vesi")
    words = text.split()
    if not words:
        return text
    if words[0] in {"aita", "vaita", "laitan"}:
        words[0] = "laita"
    words = [
        "valot"
        if word == "malot"
        else "valo"
        if word == "malo"
        else "lampotila"
        if word in {"lampotilon", "lempatila", "lapotila"}
        else word
        for word in words
    ]
    return " ".join(words)


def _shelly_device_aliases(device: shelly.ShellyDevice) -> tuple[str, ...]:
    aliases = [device.name, *device.aliases]
    normalized_aliases = []
    seen = set()
    for alias in aliases:
        normalized = _normalize_command_text(alias)
        if normalized and normalized not in seen:
            seen.add(normalized)
            normalized_aliases.append(normalized)
    return tuple(normalized_aliases)


def _shelly_alias_command_phrases(alias: str) -> dict[str, tuple[str, ...]]:
    status_alias = alias.removesuffix(" valot") + " valojen" if alias.endswith(" valot") else alias
    return {
        "on": (
            f"sytyta {alias}",
            f"laita {alias} paalle",
            f"{alias} valot paalle",
            f"{alias} paalle",
            f"paalle {alias}",
        ),
        "off": (
            f"sammuta {alias}",
            f"laita {alias} pois",
            f"{alias} valot pois",
            f"{alias} pois paalta",
            f"{alias} pois",
        ),
        "status": (
            f"mika on {alias} tila",
            f"mika on {status_alias} tila",
            f"ovatko {alias} paalla",
        ),
    }


def _shelly_alias_command_kind(command: str, alias: str) -> str | None:
    for kind, phrases in _shelly_alias_command_phrases(alias).items():
        if command in phrases:
            return kind
    return None


def _is_safe_light_device(device: shelly.ShellyDevice) -> bool:
    if device.type.strip().casefold() == "light":
        return True
    words = " ".join(_normalize_command_text(alias) for alias in (device.name, *device.aliases))
    return any(word in words.split() for word in {"valo", "valot", "lamppu", "lamput"})


def _shelly_confirmation_question(command_kind: str, device: shelly.ShellyDevice) -> str:
    device_name = _normalize_command_text(device.aliases[0] if device.aliases else device.name)
    if command_kind == "on":
        return f"Tarkoititko sytyttää {device_name}?"
    if command_kind == "off":
        return f"Tarkoititko sammuttaa {device_name}?"
    return f"Tarkoititko {device_name}?"

@dataclass
class PendingShellyConfirmation:
    action: str
    device: shelly.ShellyDevice
    created_at: float


@dataclass
class PendingLocalCommandConfirmation:
    definition: CommandDefinition
    created_at: float


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
    devices_path: Path = DEVICES_PATH
    conversation_history: list[tuple[str, str]] = field(default_factory=list)
    history_limit: int = CONVERSATION_HISTORY_LIMIT
    pending_shelly_confirmation: PendingShellyConfirmation | None = None
    pending_local_command_confirmation: PendingLocalCommandConfirmation | None = None

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
        if is_wake_word_only(user_input):
            return "Kerro."
        command_input = _strip_wake_word_prefix(user_input)

        pending_handled, pending_response = self._handle_pending_shelly_confirmation(command_input)
        if pending_handled:
            return pending_response

        pending_handled, pending_response = self._handle_pending_local_command_confirmation(command_input)
        if pending_handled:
            return pending_response

        system_status_response = self._handle_system_status_command(command_input)
        if system_status_response is not None:
            return system_status_response

        energyzen_response = self._handle_energyzen_command(command_input)
        if energyzen_response is not None:
            return energyzen_response

        shelly_response = self._handle_shelly_command(command_input)
        if shelly_response is not None:
            return shelly_response

        assistant_identity_response = self._handle_assistant_identity_question(command_input)
        if assistant_identity_response is not None:
            return assistant_identity_response

        local_response = handle_local_command(command_input)
        if local_response is not None:
            return local_response

        memory_response = self._handle_memory_command(command_input)
        if memory_response is not None:
            return memory_response

        deep_memory_response = self._handle_deep_memory_command(command_input)
        if deep_memory_response is not None:
            return deep_memory_response

        latest_memory_response = self._handle_latest_memory_command(command_input)
        if latest_memory_response is not None:
            return latest_memory_response

        latest_memory_list_response = self._handle_latest_memory_list_command(command_input)
        if latest_memory_list_response is not None:
            return latest_memory_list_response

        memory_delete_response = self._handle_memory_delete_command(command_input)
        if memory_delete_response is not None:
            return memory_delete_response

        memory_list_response = self._handle_memory_list_command(command_input)
        if memory_list_response is not None:
            return memory_list_response

        near_local_response = self._handle_near_local_command(command_input)
        if near_local_response is not None:
            return near_local_response

        return None

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
        if self._shelly_command_kind(user_input) is not None:
            return "shelly"
        if self._matches_energyzen_command(user_input):
            return "energyzen"
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

    def local_route_name(self, user_input: str) -> str:
        """Return API debug route for local tools using only the latest input."""
        command_name = self.local_command_name(user_input)

        if command_name == "energyzen":
            return "energyzen"
        if command_name == "shelly":
            return "shelly"
        if command_name == "system_status":
            return "system"
        if command_name in {
            "memory_save",
            "deep_memory_save",
            "memory_latest",
            "memory_latest_list",
            "memory_delete_latest",
            "memory_delete_number",
            "memory_list",
        }:
            return "memory"

        return "none"

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

    def _handle_pending_local_command_confirmation(self, user_input: str) -> tuple[bool, str | None]:
        pending = self.pending_local_command_confirmation
        if pending is None:
            return False, None

        age_seconds = time.monotonic() - pending.created_at
        if age_seconds > SHELLY_CONFIRMATION_TTL_SECONDS:
            self.pending_local_command_confirmation = None
            if is_confirmation_yes(user_input) or is_confirmation_no(user_input):
                return True, "Varmistus vanheni, en tehnyt muutoksia."
            return False, None

        if is_confirmation_yes(user_input):
            self.pending_local_command_confirmation = None
            return True, pending.definition.handler() if pending.definition.handler is not None else None
        if is_confirmation_no(user_input):
            self.pending_local_command_confirmation = None
            return True, "Selvä, en tehnyt muutoksia."

        self.pending_local_command_confirmation = None
        return False, None


    def _handle_near_local_command(self, user_input: str) -> str | None:
        match = match_command(user_input, self._local_command_definitions())
        if match is None:
            return None
        if match.needs_confirmation:
            self.pending_local_command_confirmation = PendingLocalCommandConfirmation(match.definition, time.monotonic())
            return match.definition.confirmation_question
        return match.definition.handler() if match.definition.handler is not None else None


    def _local_command_definitions(self) -> tuple[CommandDefinition, ...]:
        return (
            CommandDefinition(
                "system_status",
                "koneen tila",
                "Tarkoititko näyttää koneen tilan?",
                handler=lambda: self._handle_system_status_command("koneen tila"),
                aliases=(
                    "koneen tiedot",
                    "tietokoneen tila",
                    "jarjestelman tila",
                    "järjestelmän tila",
                    "mika on koneen tila",
                    "mikä on koneen tila",
                    "nayta koneen tiedot",
                    "näytä koneen tiedot",
                ),
            ),
            CommandDefinition(
                "energyzen",
                "paljonko varaajan lampo on",
                "Tarkoititko kysyä varaajan lämpötilaa?",
                handler=lambda: self._handle_energyzen_command("paljonko varaajan lämpö on"),
                aliases=(
                    "varaajan lampotila",
                    "varaajan lämpötila",
                    "varaajan lampo",
                    "varaajan lämpö",
                    "mika varaajan lampo",
                    "mikä varaajan lämpö",
                    "mika varaajan lampotila",
                    "mikä varaajan lämpötila",
                    "mika on varaajan lampotila",
                    "mikä on varaajan lämpötila",
                    "paljonko lamminta vetta",
                    "paljonko lämmintä vettä",
                    "riittaako lammin vesi",
                    "riittääkö lämmin vesi",
                    "lamminvesivaraajan tila",
                    "lämminvesivaraajan tila",
                    "varaajan tila",
                    "mika on lamminvesivaraajan tila",
                    "mikä on lämminvesivaraajan tila",
                    "nayta varaajan lampotilat",
                    "näytä varaajan lämpötilat",
                    "paljonko suihkuja on jaljella",
                    "paljonko suihkuja on jäljellä",
                    "paljonko varaajassa on lamminta",
                    "paljonko varaajassa on lämmintä",
                ),
            ),
        )


    def _handle_pending_shelly_confirmation(self, user_input: str) -> tuple[bool, str | None]:
        pending = self.pending_shelly_confirmation
        if pending is None:
            return False, None

        normalized = _normalize_command_text(user_input)
        age_seconds = time.monotonic() - pending.created_at
        if age_seconds > SHELLY_CONFIRMATION_TTL_SECONDS:
            self.pending_shelly_confirmation = None
            if normalized in SHELLY_CONFIRMATION_YES or normalized in SHELLY_CONFIRMATION_NO:
                return True, "Varmistus vanheni, en tehnyt muutoksia."
            return False, None

        if normalized in SHELLY_CONFIRMATION_YES:
            self.pending_shelly_confirmation = None
            return True, self._execute_shelly_action(pending.action, pending.device)
        if normalized in SHELLY_CONFIRMATION_NO:
            self.pending_shelly_confirmation = None
            return True, "Selvä, en tehnyt muutoksia."

        self.pending_shelly_confirmation = None
        return False, None


    def _handle_system_status_command(self, user_input: str) -> str | None:
        """Return local system status answers without calling Ollama."""
        if self.system_status is None:
            return None

        return self.system_status.answer(user_input)

    def _handle_energyzen_command(self, user_input: str) -> str | None:
        """Return EnergyZen tank readings without calling Ollama."""
        if not self._matches_energyzen_command(user_input):
            return None

        try:
            return energyzen.format_reading(energyzen.get_latest_reading())
        except energyzen.EnergyZenError:
            return ENERGYZEN_CONNECTION_ERROR_RESPONSE

    def _matches_energyzen_command(self, user_input: str) -> bool:
        normalized = _normalize_command_text(user_input)
        words = set(normalized.split())
        if "energyzen" in normalized or "lamminvesivaraaja" in normalized:
            return True

        has_tank_word = (
            any(word in words for word in ENERGYZEN_TANK_WORDS)
            or any(word.startswith("varaaja") for word in words)
            or "lammin vesi" in normalized
            or any(pattern.search(normalized) is not None for pattern in ENERGYZEN_TANK_PHRASE_PATTERNS)
        )
        has_status_word = bool(words & ENERGYZEN_STATUS_WORDS)
        has_heat_word = any(word in normalized for word in ENERGYZEN_HEAT_WORDS)
        has_shower_phrase = any(phrase in normalized for phrase in ENERGYZEN_SHOWER_PHRASES)

        return (has_tank_word and (has_status_word or has_heat_word)) or has_shower_phrase

    def _handle_shelly_command(self, user_input: str) -> str | None:
        """Handle configured Shelly device commands without calling Ollama."""
        command = self._match_shelly_command(user_input)
        if command is None:
            near_command = self._near_shelly_command(user_input)
            if near_command is None:
                return None
            score, command_kind, device, is_unique_device = near_command
            can_run_automatically = (
                score >= SHELLY_AUTO_MATCH_THRESHOLD
                and is_unique_device
                and command_kind in {"on", "off", "status"}
                and _is_safe_light_device(device)
            )
            if not can_run_automatically:
                self.pending_shelly_confirmation = PendingShellyConfirmation(command_kind, device, time.monotonic())
                return _shelly_confirmation_question(command_kind, device)
        else:
            command_kind, device = command

        return self._execute_shelly_action(command_kind, device)

    def _execute_shelly_action(self, command_kind: str, device: shelly.ShellyDevice) -> str:
        try:
            if command_kind == "on":
                shelly.switch_on(device.ip, device.channel)
                return GRILLIKATOS_LIGHTS_ON_RESPONSE
            if command_kind == "off":
                shelly.switch_off(device.ip, device.channel)
                return GRILLIKATOS_LIGHTS_OFF_RESPONSE

            status = shelly.get_status(device.ip, device.channel)
        except shelly.ShellyError:
            return SHELLY_CONNECTION_ERROR_RESPONSE

        if not isinstance(status.get("output"), bool):
            return SHELLY_CONNECTION_ERROR_RESPONSE

        state = "päällä" if status["output"] else "pois päältä"
        return f"Grillikatoksen valot ovat {state}."

    def _shelly_command_kind(self, user_input: str) -> str | None:
        """Return Shelly command kind for configured device aliases."""
        command = self._match_shelly_command(user_input)
        if command is None:
            return None
        return command[0]

    def _match_shelly_command(self, user_input: str) -> tuple[str, shelly.ShellyDevice] | None:
        normalized = _normalize_command_text(user_input)
        for device in shelly.load_devices(self.devices_path).values():
            for alias in _shelly_device_aliases(device):
                match = _shelly_alias_command_kind(normalized, alias)
                if match is not None:
                    return match, device
        return None

    def _near_shelly_command(self, user_input: str) -> tuple[float, str, shelly.ShellyDevice, bool] | None:
        normalized = _normalize_command_text(user_input)
        best: tuple[float, str, shelly.ShellyDevice] | None = None
        device_scores: dict[shelly.ShellyDevice, float] = {}
        for device in shelly.load_devices(self.devices_path).values():
            for alias in _shelly_device_aliases(device):
                for kind, phrases in _shelly_alias_command_phrases(alias).items():
                    for phrase in phrases:
                        score = difflib.SequenceMatcher(None, normalized, phrase).ratio()
                        if score > device_scores.get(device, 0.0):
                            device_scores[device] = score
                        if best is None or score > best[0]:
                            best = (score, kind, device)
        if best is None or best[0] < SHELLY_NEAR_MATCH_THRESHOLD:
            return None
        is_unique_device = all(
            device == best[2] or score < best[0] - SHELLY_AMBIGUITY_MARGIN
            for device, score in device_scores.items()
        )
        return best[0], best[1], best[2], is_unique_device

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
