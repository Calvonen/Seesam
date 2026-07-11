"""Local command handling for Seesam terminal chat."""

from __future__ import annotations

import re

from audio.audio_manager import ensure_media_output, find_device_id_for_text
from core.command_matcher import CommandDefinition, is_confirmation_no, is_confirmation_yes, match_command
from spotify.spotify_commands import ensure_speakers_powered_on, handle_spotify_command

WAKE_COMMAND = "seesam aukene"
WAKE_RESPONSE = "Kuuntelen."
AUDIO_OUTPUT_COMMAND_PHRASES = {
    "laita kaiuttimet paalle",
    "kaiuttimet paalle",
    "laita kaijuttimet paalle",
    "kaijuttimet paalle",
    "laita kajarit paalle",
    "kajarit paalle",
    "laita amyrit paalle",
    "amyrit paalle",
    "kytke kaiuttimet",
    "yhdista kaiuttimet",
    "yhdista bluetooth kaiuttimet",
    "steljes paalle",
    "media paalle",
}
MEDIA_PLAYBACK_COMMAND_PHRASES = {
    "käynnistä spotify",
    "kaynnista spotify",
    "avaa spotify",
    "spotify päälle",
    "spotify paalle",
    "laita spotify päälle",
    "laita spotify paalle",
    "laitas spotify päälle",
    "laitas spotify paalle",
    "toista spotify",
    "soita spotify",
    "soita musiikkia",
    "käynnistä musiikki",
    "kaynnista musiikki",
    "laita musiikki päälle",
    "laita musiikki paalle",
    "musiikki päälle",
    "musiikki paalle",
}
_pending_local_confirmation: CommandDefinition | None = None


def _normalize_command(text: str) -> str:
    lowered = text.casefold().strip()
    lowered = lowered.translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"}))
    lowered = re.sub(r"[^0-9a-z]+", " ", lowered)
    return " ".join(lowered.split())


def handle_local_command(user_input: str) -> str | None:
    """Return a local response when input matches a built-in command."""
    global _pending_local_confirmation

    normalized = _normalize_command(user_input)
    if _pending_local_confirmation is not None and is_confirmation_yes(normalized):
        pending = _pending_local_confirmation
        _pending_local_confirmation = None
        return pending.handler() if pending.handler is not None else None
    if _pending_local_confirmation is not None and is_confirmation_no(normalized):
        _pending_local_confirmation = None
        return "Selvä, en tehnyt muutoksia."

    if WAKE_COMMAND in user_input.casefold():
        return WAKE_RESPONSE

    normalized_audio_phrases = {_normalize_command(phrase) for phrase in AUDIO_OUTPUT_COMMAND_PHRASES}
    if normalized in normalized_audio_phrases:
        return _ensure_default_audio_output()

    alias_device_id = find_device_id_for_text(user_input)
    if alias_device_id is not None and ("paalle" in normalized.split() or "yhdista" in normalized.split()):
        result = ensure_media_output(alias_device_id)
        return result.message

    spotify_response = handle_spotify_command(user_input)
    if spotify_response is not None:
        return spotify_response

    near_command = match_command(user_input, _local_command_definitions())
    if near_command is not None:
        if near_command.needs_confirmation:
            _pending_local_confirmation = near_command.definition
            return near_command.definition.confirmation_question
        return near_command.definition.handler() if near_command.definition.handler is not None else None

    return None


def _ensure_default_audio_output() -> str:
    ensure_speakers_powered_on()
    result = ensure_media_output("steljes_ns3")
    return "Kaiuttimet kytketty." if result.success else result.message


def _local_command_definitions() -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            "wake",
            WAKE_COMMAND,
            "Tarkoititko avata Seesamin?",
            handler=lambda: WAKE_RESPONSE,
        ),
        CommandDefinition(
            "audio_output",
            "kaiuttimet paalle",
            "Tarkoititko yhdistää kaiuttimet?",
            handler=_ensure_default_audio_output,
            aliases=tuple(AUDIO_OUTPUT_COMMAND_PHRASES),
        ),
    )
