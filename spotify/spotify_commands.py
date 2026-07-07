"""Command-level Spotify controls for Seesam."""

from __future__ import annotations

import re
import time
import urllib.request
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
SEESAM_HUB_BASE_URL = "http://192.168.68.74:8000"
SPEAKER_POWER_ON_DELAY_SECONDS = 10
SPEAKER_POWER_ON_TIMEOUT_SECONDS = 5
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
NEXT_COMMANDS = {"seuraava", "seuraava biisi", "seuraava kappale", "skippaa"}
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
VOLUME_STEP = 10
VOLUME_DOWN_WORDS = {"iljenpa", "hiljenpa", "hiljenpaa", "hiljempaa", "hiljemmalle", "hiljasemmalle", "pienemmalle", "pienemmaksi", "pienenna", "pienen"}
VOLUME_UP_WORDS = {"kovempaa", "kovemmalle", "isommalle", "lisaa"}
VOLUME_CONTEXT_WORDS = {"musiikki", "spotify", "volume", "volumea", "volyymi", "volyymia", "aani", "aanta"}
VOLUME_COMMAND_WORDS = {"laita", "pista", "pienenna", "pienen", "lisaa"}
VOLUME_CONFIRMATION_YES = {"kylla", "joo", "juu", "ok", "okei", "ylla"}
VOLUME_CONFIRMATION_NO = {"ei", "ala", "peruuta", "unohda"}
UNCERTAIN_VOLUME_START_WORDS = {"laita", "pista"}
_pending_volume_adjustment: int | None = None
SPOTIFY_WORD_ALIASES = {
    "potifi": "spotify",
    "potifissa": "spotifyssa",
    "spotivy": "spotify",
    "spotifai": "spotify",
    "spotifi": "spotify",
    "spotfy": "spotify",
    "spottify": "spotify",
}
HOME_CONTROL_WORDS = {
    "valo",
    "valot",
    "lamppu",
    "lamput",
    "pistorasia",
    "grillikatos",
    "grillikatoksen",
    "olohuone",
    "keittio",
    "katos",
}
GENRE_WORDS = {
    "ambient",
    "ambienttia",
    "blues",
    "country",
    "disco",
    "elektro",
    "funk",
    "jazz",
    "jazzia",
    "metalli",
    "poppia",
    "pop",
    "punk",
    "rap",
    "reggae",
    "rock",
    "rockia",
    "soul",
    "soulia",
    "suomirock",
    "techno",
    "technoa",
}


def handle_spotify_command(text: str) -> str | None:
    """Return a short local response for Spotify commands, or None if not matched."""
    global _pending_volume_adjustment

    normalized = _normalize(text)
    words = normalized.split()

    if _pending_volume_adjustment is not None and normalized in VOLUME_CONFIRMATION_YES:
        adjustment = _pending_volume_adjustment
        _pending_volume_adjustment = None
        return _volume_adjustment_response(adjustment)
    if _pending_volume_adjustment is not None and normalized in VOLUME_CONFIRMATION_NO:
        _pending_volume_adjustment = None
        return "Selvä, en tehnyt muutoksia."
    if normalized in VOLUME_CONFIRMATION_YES:
        return None

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

    adjustment = _volume_adjustment_from_words(words)
    if adjustment is not None:
        return _volume_adjustment_response(adjustment)

    uncertain_adjustment = _uncertain_volume_adjustment_from_words(words)
    if uncertain_adjustment is not None:
        _pending_volume_adjustment = uncertain_adjustment
        direction = "kovemmalle" if uncertain_adjustment > 0 else "hiljemmalle"
        return f"Tarkoititko laittaa musiikkia {direction}?"

    search_request = _search_play_request(words)
    if search_request is not None:
        query, types = search_request
        return _search_play_response(query, types)
    return None


def _play_response() -> str:
    return _run_spotify_action(_transfer_and_play, "Soitan Spotifystä.", ensure_output=True, power_on_speakers=True)


def _search_play_response(query: str, types: str) -> str:
    return _run_spotify_action(
        lambda: _search_and_play(query, types),
        f"Soitan Spotifystä: {query}.",
        ensure_output=True,
        power_on_speakers=True,
    )


def ensure_speakers_powered_on() -> None:
    """Best-effort Hub wakeup for powered speaker playback."""
    url = f"{SEESAM_HUB_BASE_URL.rstrip('/')}/speakers/power-on"
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SPEAKER_POWER_ON_TIMEOUT_SECONDS):
            pass
    except Exception:
        return
    time.sleep(SPEAKER_POWER_ON_DELAY_SECONDS)


def _search_and_play(query: str, types: str) -> None:
    result = spotify_client.search(query, types=types, limit=5)
    uri = _first_search_uri(result, types)
    if not uri:
        raise SpotifyClientError(f"Spotify-hakutulosta ei löytynyt haulle {query}.")
    device_id = _get_seesam_device_id()
    spotify_client.transfer_playback(device_id, play=False)
    spotify_client.play_uri(uri, device_id=device_id)


def _volume_response(percent: int) -> str:
    volume = max(0, min(100, percent))
    return _run_spotify_action(
        lambda: _set_seesam_volume(volume),
        f"Volume {volume}",
    )


def _volume_percent_from_words(words: list[str]) -> int | None:
    if len(words) == 2 and words[0] in {"aani", "volyymi", "volume"} and words[1].isdigit():
        return int(words[1])
    if len(words) == 3 and words[0] == "spotify" and words[1] in {"volume", "volyymi", "aani"} and words[2].isdigit():
        return int(words[2])
    if len(words) == 3 and words[0] == "musiikki" and words[1].isdigit() and words[2] == "prosenttia":
        return int(words[1])
    if len(words) == 3 and words[0] == "musiikki" and words[1] in {"aani", "volyymi", "volume"} and words[2].isdigit():
        return int(words[2])
    return None


def _volume_adjustment_from_words(words: list[str]) -> int | None:
    word_set = set(words)
    has_down_word = bool(word_set & VOLUME_DOWN_WORDS)
    has_up_word = bool(word_set & VOLUME_UP_WORDS)
    if not has_down_word and not has_up_word:
        return None

    has_context = bool(word_set & VOLUME_CONTEXT_WORDS) or bool(word_set & VOLUME_COMMAND_WORDS) or "vahan" in word_set
    if not has_context:
        return None
    if has_down_word:
        return -VOLUME_STEP
    return VOLUME_STEP


def _uncertain_volume_adjustment_from_words(words: list[str]) -> int | None:
    if not words or _volume_adjustment_from_words(words) is not None:
        return None

    word_set = set(words)
    has_down_word = bool(word_set & VOLUME_DOWN_WORDS)
    has_up_word = bool(word_set & VOLUME_UP_WORDS)
    if not has_down_word and not has_up_word:
        return None
    if not _looks_like_uncertain_volume_start(words[0]):
        return None
    if has_down_word:
        return -VOLUME_STEP
    return VOLUME_STEP


def _looks_like_uncertain_volume_start(word: str) -> bool:
    if word in UNCERTAIN_VOLUME_START_WORDS:
        return True
    return any(_edit_distance_at_most_one(word, expected) for expected in UNCERTAIN_VOLUME_START_WORDS)


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    for index in range(len(longer)):
        if shorter == longer[:index] + longer[index + 1 :]:
            return True
    return False


def _volume_adjustment_response(adjustment: int) -> str:
    current_volume = _current_volume_percent()
    if current_volume is None:
        volume = DEFAULT_VOLUME_UP if adjustment > 0 else DEFAULT_VOLUME_DOWN
    else:
        volume = current_volume + adjustment
    return _volume_response(volume)


def _current_volume_percent() -> int | None:
    try:
        playback = spotify_client.get_current_playback()
    except (SpotifyClientError, SpotifyAuthError):
        return None
    device = (playback or {}).get("device")
    if not isinstance(device, dict):
        return None
    volume = device.get("volume_percent")
    if isinstance(volume, int):
        return volume
    return None


def _search_play_request(words: list[str]) -> tuple[str, str] | None:
    if _looks_like_home_control(words):
        return None

    if len(words) >= 2 and words[0] in {"soita", "laita"}:
        query_words = words[1:]
    elif len(words) >= 3 and words[0] in {"hae", "etsi"} and words[1] == "spotify":
        query_words = words[2:]
    else:
        return None

    types = "track,artist,playlist"
    if "kappale" in query_words or "biisi" in query_words:
        types = "track"
        query_words = [word for word in query_words if word not in {"kappale", "biisi"}]
    elif "artisti" in query_words:
        types = "artist"
        query_words = [word for word in query_words if word != "artisti"]
    elif any(word in GENRE_WORDS for word in query_words):
        types = "playlist,track"

    query_words = [word for word in query_words if word not in {"jotain", "soimaan"}]
    query = " ".join(query_words).strip()
    if not query or query == "spotify":
        return None
    return query, types


def _looks_like_home_control(words: list[str]) -> bool:
    for word in words:
        if word in HOME_CONTROL_WORDS:
            return True
        if word.endswith("n") and word[:-1] in HOME_CONTROL_WORDS:
            return True
    return False


def _first_search_uri(result: dict[str, Any], types: str) -> str | None:
    for item_type in types.split(","):
        bucket = result.get(f"{item_type}s")
        if not isinstance(bucket, dict):
            continue
        items = bucket.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                uri = str(item.get("uri") or "").strip()
                if uri:
                    return uri
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


def _run_spotify_action(
    action,
    success_message: str,
    ensure_output: bool = True,
    power_on_speakers: bool = False,
) -> str:
    if power_on_speakers:
        ensure_speakers_powered_on()

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
    normalized = " ".join(lowered.split())
    return _normalize_spotify_words(normalized)


def _normalize_spotify_words(text: str) -> str:
    words = [SPOTIFY_WORD_ALIASES.get(word, word) for word in text.split()]
    return " ".join(words)
