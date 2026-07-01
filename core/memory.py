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
    """Load and append Marko's local memories from a text file."""

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
