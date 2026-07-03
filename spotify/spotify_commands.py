"""Command-level Spotify controls for Seesam."""

from __future__ import annotations

import re
from typing import Any

from audio.audio_manager import SPEAKERS_SLEEPING_MESSAGE, ensure_default_media_output
from spotify import spotify_client
from spotify.spotify_auth import SpotifyAuthError
from spotify.spotify_client import (
    NO_ACTIVE_DEVICE_MESSAGE,
    PREMIUM_REQUIRED_MESSAGE,
    SpotifyClientError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
)

MEDIA_OUTPUT_FAILURE_MESSAGE = "Kaiuttimet eivät vastaa. Herätä ne Bluetooth-tilaan."
SEESAM_DEVICE_NAME = "Seesam"
PLAY_COMMANDS = {
    "laita spotify paalle",
    "spotify paalle",
    "soita spotify",
    "toista spotify",
    "musiikki paalle",
    "soita musiikkia",
    "jatka musiikkia",
    "jatka spotify",
    "jatka",
    "toista",
}
PAUSE_COMMANDS = {
    "tauko",
    "paussi",
    "pysayta musiikki",
    "pysayta spotify",
    "spotify tauko",
    "musiikki tauko",
}
NEXT_COMMANDS = {"seuraava", "seuraava biisi", "seuraava kappale"}
PREVIOUS_COMMANDS = {"edellinen", "edellinen biisi", "edellinen kappale"}
STATUS_COMMANDS = {
    "spotify",
    "mita soi",
    "mika soi",
    "mika kappale",
    "mika kappale tama on",
    "kuka soi",
    "mika biisi",
    "mika biisi soi",
    "mika biisi tama on",
    "mika kappale soi",
    "spotify status",
    "mita spotifyssa soi",
}
VOLUME_UP_COMMANDS = {"musiikki kovemmalle"}
VOLUME_DOWN_COMMANDS = {"musiikki hiljemmalle"}
DEFAULT_VOLUME_UP = 90
DEFAULT_VOLUME_DOWN = 50


def handle_spotify_command(text: str) -> str | None:
    """Return a short local response for Spotify commands, or None if not matched."""
    normalized = _normalize(text)
    words = normalized.split()

    if normalized in STATUS_COMMANDS:
        return _currently_playing_response()
    if normalized in PLAY_COMMANDS:
        return _play_response()
    if normalized in PAUSE_COMMANDS:
        return _run_spotify_action(spotify_client.pause, "Tauko.", ensure_output=False)
    if normalized in NEXT_COMMANDS:
        return _run_spotify_action(spotify_client.next_track, "Seuraava kappale.", ensure_output=False)
    if normalized in PREVIOUS_COMMANDS:
        return _run_spotify_action(spotify_client.previous_track, "Edellinen kappale.", ensure_output=False)
    if normalized in VOLUME_UP_COMMANDS:
        return _volume_response(DEFAULT_VOLUME_UP)
    if normalized in VOLUME_DOWN_COMMANDS:
        return _volume_response(DEFAULT_VOLUME_DOWN)

    volume = _volume_percent_from_words(words)
    if volume is not None:
        return _volume_response(volume)
    return None


def _play_response() -> str:
    return _run_spotify_action(_transfer_and_play, "Soitan Spotifystä.", ensure_output=True)


def _volume_response(percent: int) -> str:
    volume = max(0, min(100, percent))
    return _run_spotify_action(
        lambda: _set_seesam_volume(volume),
        f"Musiikin äänenvoimakkuus {volume} prosenttia.",
    )


def _volume_percent_from_words(words: list[str]) -> int | None:
    if len(words) == 2 and words[0] in {"aani", "volyymi"} and words[1].isdigit():
        return int(words[1])
    if len(words) == 3 and words[0] == "spotify" and words[1] in {"volume", "volyymi", "aani"} and words[2].isdigit():
        return int(words[2])
    if len(words) == 3 and words[0] == "musiikki" and words[1] in {"aani", "volyymi"} and words[2].isdigit():
        return int(words[2])
    return None


def _currently_playing_response() -> str:
    try:
        data = spotify_client.get_currently_playing()
    except SpotifyNoActiveDeviceError:
        return NO_ACTIVE_DEVICE_MESSAGE
    except SpotifyPremiumRequiredError:
        return PREMIUM_REQUIRED_MESSAGE
    except (SpotifyClientError, SpotifyAuthError) as error:
        return str(error)

    item = (data or {}).get("item")
    if not isinstance(item, dict):
        return "Spotifyssä ei soi nyt mitään."
    artist = _artist_names(item)
    title = str(item.get("name") or "tuntematon kappale")
    return f"Nyt soi {artist} – {title}."


def _transfer_and_play() -> None:
    device_id = _get_seesam_device_id()
    spotify_client.transfer_playback(device_id, play=False)
    spotify_client.play(device_id)


def _set_seesam_volume(percent: int) -> None:
    device_id = _get_seesam_device_id()
    spotify_client.set_volume(percent, device_id=device_id)


def _get_seesam_device_id() -> str:
    for device in spotify_client.get_available_devices():
        if str(device.get("name") or "").casefold() == SEESAM_DEVICE_NAME.casefold():
            device_id = str(device.get("id") or "").strip()
            if device_id:
                return device_id
    raise SpotifyNoActiveDeviceError(NO_ACTIVE_DEVICE_MESSAGE)


def _run_spotify_action(action, success_message: str, ensure_output: bool = True) -> str:
    if ensure_output:
        audio_result = ensure_default_media_output()
        if not audio_result.success:
            if audio_result.message == SPEAKERS_SLEEPING_MESSAGE:
                return MEDIA_OUTPUT_FAILURE_MESSAGE
            return audio_result.message
    try:
        action()
    except SpotifyNoActiveDeviceError:
        return NO_ACTIVE_DEVICE_MESSAGE
    except SpotifyPremiumRequiredError:
        return PREMIUM_REQUIRED_MESSAGE
    except (SpotifyClientError, SpotifyAuthError) as error:
        return str(error)
    return success_message


def _artist_names(item: dict[str, Any]) -> str:
    artists = item.get("artists")
    if not isinstance(artists, list) or not artists:
        return "tuntematon artisti"
    names = [str(artist.get("name")) for artist in artists if isinstance(artist, dict) and artist.get("name")]
    return ", ".join(names) if names else "tuntematon artisti"


def _normalize(text: str) -> str:
    lowered = text.casefold().strip()
    lowered = lowered.translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"}))
    lowered = re.sub(r"[^0-9a-z]+", " ", lowered)
    return " ".join(lowered.split())
