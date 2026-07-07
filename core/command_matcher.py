"""Shared fuzzy matching helpers for local Seesam commands."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable, Iterable

AUTO_MATCH_THRESHOLD = 0.93
CONFIRM_MATCH_THRESHOLD = 0.80
CONFIRMATION_YES = {"kylla", "joo", "juu", "jes", "kylla vain", "ylla"}
CONFIRMATION_NO = {"ei", "ala", "peru", "peruuta", "en"}


def normalize_command_text(text: str) -> str:
    """Normalize Finnish command text for stable fuzzy comparisons."""
    lowered = text.casefold().strip()
    lowered = lowered.translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"}))
    lowered = re.sub(r"[^0-9a-z]+", " ", lowered)
    return " ".join(lowered.split())


@dataclass(frozen=True)
class CommandDefinition:
    intent_id: str
    canonical_phrase: str
    confirmation_question: str
    handler: Callable[[], str | None] | None = None
    aliases: tuple[str, ...] = ()

    @property
    def phrases(self) -> tuple[str, ...]:
        return (self.canonical_phrase, *self.aliases)


@dataclass(frozen=True)
class CommandMatch:
    definition: CommandDefinition
    confidence: float
    needs_confirmation: bool


def match_command(
    text: str,
    definitions: Iterable[CommandDefinition],
    *,
    auto_threshold: float = AUTO_MATCH_THRESHOLD,
    confirm_threshold: float = CONFIRM_MATCH_THRESHOLD,
) -> CommandMatch | None:
    """Return the best fuzzy command match, or None below the confirmation threshold."""
    normalized = normalize_command_text(text)
    best: tuple[float, CommandDefinition] | None = None
    for definition in definitions:
        for phrase in definition.phrases:
            candidate = normalize_command_text(phrase)
            if not candidate:
                continue
            score = difflib.SequenceMatcher(None, normalized, candidate).ratio()
            if best is None or score > best[0]:
                best = (score, definition)

    if best is None or best[0] < confirm_threshold:
        return None
    return CommandMatch(
        definition=best[1],
        confidence=best[0],
        needs_confirmation=best[0] < auto_threshold,
    )


def is_confirmation_yes(text: str) -> bool:
    return normalize_command_text(text) in CONFIRMATION_YES


def is_confirmation_no(text: str) -> bool:
    return normalize_command_text(text) in CONFIRMATION_NO
