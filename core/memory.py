"""Simple file-based memory storage for Seesam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

MEMORY_ID_PATTERN = re.compile(r"^M(?P<number>\d{6})$")
MEMORY_LINE_PATTERN = re.compile(
    r"^(?P<id>M\d{6})\s*\|\s*(?P<created_at>[^|]+)\s*\|\s*source=(?P<source>[^|]+)\s*\|\s*(?P<text>.*)$"
)
DEFAULT_ASSISTANT_IDENTITY = {
    "name": "Seesam",
    "aliases": ["Sam", "CSAM"],
    "role": "paikallinen ääniavustaja",
    "language": "fi",
    "server": "Seesam-palvelin",
    "backend": "Ollama",
}
DEFAULT_USER_PROFILE = {
    "name": "Marko",
    "language": "fi",
    "response_style": "lyhyt ja käytännöllinen",
    "important_preferences": ["haluaa vastaukset suomeksi"],
    "deep_memory": [],
}


def _yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    if any(char in value for char in [":", "#", "[", "]", "{", "}"]):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def dump_simple_yaml(data: dict[str, object]) -> str:
    """Return a small hand-editable YAML document for string and list values."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            if value:
                lines.extend(f"  - {_yaml_scalar(str(item))}" for item in value)
            else:
                lines.append("  []")
            continue

        lines.append(f"{key}: {_yaml_scalar(str(value))}")

    return "\n".join(lines) + "\n"


def _parse_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def load_simple_yaml(path: Path, defaults: dict[str, object]) -> dict[str, object]:
    """Load the limited YAML shape used by Seesam's local memory files."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_simple_yaml(defaults), encoding="utf-8")
        return dict(defaults)

    data: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("  - ") and current_list_key is not None:
            value = _parse_yaml_scalar(line[4:])
            current_value = data.setdefault(current_list_key, [])
            if isinstance(current_value, list):
                current_value.append(value)
            continue

        if line.startswith("  []") and current_list_key is not None:
            data[current_list_key] = []
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
            continue

        data[key] = _parse_yaml_scalar(value)
        current_list_key = None

    merged = dict(defaults)
    for key, default_value in defaults.items():
        value = data.get(key)
        if isinstance(default_value, list):
            if isinstance(value, list):
                merged[key] = [str(item).strip() for item in value if str(item).strip()]
            continue
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()

    return merged


@dataclass(frozen=True)
class MemoryEntry:
    """One memory line, including legacy lines that do not have metadata."""

    text: str
    line_index: int
    id: str | None = None
    created_at: str | None = None
    source: str | None = None

    @property
    def label(self) -> str:
        """Return a compact human-readable label for command responses."""
        if self.id is None:
            return self.text

        return f"{self.id}: {self.text}"


@dataclass(frozen=True)
class Memory:
    """Load and append ordinary local memories from a text file."""

    path: Path

    def entries(self) -> list[MemoryEntry]:
        """Return non-empty memory entries from the memory file."""
        if not self.path.exists():
            return []

        entries: list[MemoryEntry] = []
        for line_index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            cleaned = line.strip()
            if not cleaned:
                continue

            match = MEMORY_LINE_PATTERN.match(cleaned)
            if match is not None:
                entries.append(
                    MemoryEntry(
                        id=match.group("id"),
                        created_at=match.group("created_at").strip(),
                        source=match.group("source").strip(),
                        text=match.group("text").strip(),
                        line_index=line_index,
                    )
                )
                continue

            entries.append(MemoryEntry(text=cleaned, line_index=line_index))

        return entries

    def load(self) -> list[str]:
        """Return non-empty memory texts from the memory file."""
        return [entry.text for entry in self.entries()]

    def text(self) -> str:
        """Return memories formatted for model context."""
        entries = self.entries()
        if not entries:
            return ""

        return "\n".join(f"- {entry.text}" for entry in entries)

    def latest(self, limit: int = 5) -> list[MemoryEntry]:
        """Return the latest memories, newest first."""
        if limit <= 0:
            return []

        return list(reversed(self.entries()))[:limit]

    def append(self, memory: str, source: str = "voice") -> bool:
        """Append a memory line and return whether anything was saved."""
        cleaned = memory.strip()
        if not cleaned:
            return False

        memory_id = self._next_id()
        created_at = datetime.now().replace(microsecond=0).isoformat()
        cleaned_source = source.strip() or "voice"

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as memory_file:
            memory_file.write(f"{memory_id} | {created_at} | source={cleaned_source} | {cleaned}\n")

        return True

    def delete_latest(self) -> MemoryEntry | None:
        """Delete the latest saved memory and return it."""
        entries = self.entries()
        if not entries:
            return None

        latest_entry = entries[-1]
        self._delete_line(latest_entry.line_index)
        return latest_entry

    def delete_latest_number(self, number: int, limit: int = 5) -> MemoryEntry | None:
        """Delete a memory by its one-based number in the latest memories list."""
        if number < 1:
            return None

        latest_entries = self.latest(limit)
        if number > len(latest_entries):
            return None

        entry = latest_entries[number - 1]
        self._delete_line(entry.line_index)
        return entry

    def latest_entry_text(self) -> str:
        """Return the latest saved memory as a one-line label."""
        latest_entries = self.latest(1)
        if not latest_entries:
            return ""

        return latest_entries[0].label

    def latest_text(self, limit: int = 5) -> str:
        """Return the latest memories as a numbered list."""
        latest_entries = self.latest(limit)
        if not latest_entries:
            return ""

        return "\n".join(
            f"{index}. {entry.label}" for index, entry in enumerate(latest_entries, start=1)
        )

    def _next_id(self) -> str:
        """Return the next stable memory id."""
        max_id = 0
        for entry in self.entries():
            if entry.id is None:
                continue

            match = MEMORY_ID_PATTERN.match(entry.id)
            if match is not None:
                max_id = max(max_id, int(match.group("number")))

        return f"M{max_id + 1:06d}"

    def _delete_line(self, line_index: int) -> None:
        """Delete one physical line from the memory file."""
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if line_index < 0 or line_index >= len(lines):
            return

        del lines[line_index]
        content = "\n".join(lines)
        if content:
            content += "\n"

        self.path.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class AssistantIdentityMemory:
    """Load Seesam's local identity from a YAML file."""

    path: Path

    def load(self) -> dict[str, object]:
        """Return assistant identity values, creating the local file when missing."""
        return load_simple_yaml(self.path, DEFAULT_ASSISTANT_IDENTITY)

    def names(self) -> list[str]:
        """Return the canonical assistant name and configured aliases."""
        identity = self.load()
        names = [str(identity["name"]).strip()]
        aliases = identity.get("aliases", [])
        if isinstance(aliases, list):
            names.extend(str(alias).strip() for alias in aliases)

        seen: set[str] = set()
        unique_names: list[str] = []
        for name in names:
            normalized = name.casefold()
            if not name or normalized in seen:
                continue
            seen.add(normalized)
            unique_names.append(name)

        return unique_names

    def matches_name(self, value: str) -> bool:
        """Return whether a spoken/written name points to this assistant."""
        normalized_value = value.strip().casefold()
        return any(name.casefold() == normalized_value for name in self.names())

    def identity_response(self) -> str:
        """Return the local first-person identity answer."""
        identity = self.load()
        name = str(identity["name"])
        role = str(identity["role"])
        return f"Olen {name}, {role}."

    def context_text(self) -> str:
        """Return assistant identity rules for the model system prompt."""
        identity = self.load()
        name = str(identity["name"])
        aliases = ", ".join(self.names()[1:])
        role = str(identity["role"])
        language = str(identity["language"])
        server = str(identity["server"])
        backend = str(identity["backend"])
        alias_line = f"- Nimen aliakset ovat: {aliases}.\n" if aliases else ""

        return (
            "Seesamin paikallinen identiteetti:\n"
            f"- Sinun oma nimesi on {name}.\n"
            f"{alias_line}"
            f"- Roolisi on {role}.\n"
            f"- Käyttökieli on {language}.\n"
            f"- Palvelinkone on {server}.\n"
            f"- Backend on {backend}.\n"
            "- Älä ota omaa nimeäsi käyttäjän muistista."
        )


@dataclass(frozen=True)
class UserProfileMemory:
    """Load Marko's local profile and deep memory from a YAML file."""

    path: Path

    def load(self) -> dict[str, object]:
        """Return user profile values, creating the local file when missing."""
        return load_simple_yaml(self.path, DEFAULT_USER_PROFILE)

    def append_deep_memory(self, memory: str) -> bool:
        """Append a deep memory line under the user's profile."""
        cleaned = memory.strip()
        if not cleaned:
            return False

        profile = self.load()
        deep_memory = profile.get("deep_memory", [])
        if not isinstance(deep_memory, list):
            deep_memory = []
        if cleaned in deep_memory:
            return True
        deep_memory.append(cleaned)
        profile["deep_memory"] = deep_memory
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(dump_simple_yaml(profile), encoding="utf-8")
        return True

    def text(self) -> str:
        """Return profile and deep memory formatted for local responses and context."""
        profile = self.load()
        lines = [
            f"- Käyttäjän nimi: {profile['name']}",
            f"- Käyttäjän kieli: {profile['language']}",
            f"- Vastaustyyli: {profile['response_style']}",
        ]
        preferences = profile.get("important_preferences", [])
        if isinstance(preferences, list) and preferences:
            lines.append("- Tärkeät pysyvät mieltymykset:")
            lines.extend(f"  - {preference}" for preference in preferences)

        deep_memory = profile.get("deep_memory", [])
        if isinstance(deep_memory, list) and deep_memory:
            lines.append("- Syvä muisti:")
            lines.extend(f"  - {memory}" for memory in deep_memory)

        return "\n".join(lines)


@dataclass(frozen=True)
class EpisodeLog:
    """Append timestamped local memory events to a log file."""

    path: Path

    def append(self, event: str, text: str) -> None:
        cleaned = text.strip().replace("\n", " ")
        created_at = datetime.now().replace(microsecond=0).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{created_at} | {event} | {cleaned}\n")
