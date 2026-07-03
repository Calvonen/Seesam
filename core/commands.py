"""Local command handling for Seesam terminal chat."""

from __future__ import annotations

import re

from audio.audio_manager import ensure_media_output, find_device_id_for_text
from spotify.spotify_commands import handle_spotify_command

WAKE_COMMAND = "seesam aukene"
WAKE_RESPONSE = "Kuuntelen."
AUDIO_OUTPUT_COMMAND_PHRASES = {
    "kaiuttimet paalle",
    "kaiuttimet päälle",
    "yhdista kaiuttimet",
    "yhdistä kaiuttimet",
    "steljes paalle",
    "steljes päälle",
    "media paalle",
    "media päälle",
}
MEDIA_PLAYBACK_COMMAND_PHRASES = {
    "soita spotify",
    "soita musiikkia",
    "musiikki paalle",
    "musiikki päälle",
}


def _normalize_command(text: str) -> str:
    lowered = text.casefold().strip()
    lowered = lowered.translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"}))
    lowered = re.sub(r"[^0-9a-z]+", " ", lowered)
    return " ".join(lowered.split())


def handle_local_command(user_input: str) -> str | None:
    """Return a local response when input matches a built-in command."""
    if WAKE_COMMAND in user_input.casefold():
        return WAKE_RESPONSE

    spotify_response = handle_spotify_command(user_input)
    if spotify_response is not None:
        return spotify_response

    normalized = _normalize_command(user_input)
    normalized_audio_phrases = {_normalize_command(phrase) for phrase in AUDIO_OUTPUT_COMMAND_PHRASES}
    if normalized in normalized_audio_phrases:
        result = ensure_media_output("steljes_ns3")
        return result.message

    alias_device_id = find_device_id_for_text(user_input)
    if alias_device_id is not None and ("paalle" in normalized.split() or "yhdista" in normalized.split()):
        result = ensure_media_output(alias_device_id)
        return result.message

    return None
