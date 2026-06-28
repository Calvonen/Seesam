"""Simple file-based memory storage for Seesam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Memory:
    """Load and append Marko's local memories from a text file."""

    path: Path

    def load(self) -> list[str]:
        """Return non-empty memory lines from the memory file."""
        if not self.path.exists():
            return []

        return [
            line.strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def text(self) -> str:
        """Return memories formatted for model context."""
        memories = self.load()
        if not memories:
            return ""

        return "\n".join(f"- {memory}" for memory in memories)

    def append(self, memory: str) -> bool:
        """Append a memory line and return whether anything was saved."""
        cleaned = memory.strip()
        if not cleaned:
            return False

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as memory_file:
            memory_file.write(f"{cleaned}\n")

        return True
