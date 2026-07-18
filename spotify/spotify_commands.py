"""Command-level Spotify controls for Seesam."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
import time
import urllib.request
from typing import Any

from audio.audio_manager import SPEAKERS_SLEEPING_MESSAGE, ensure_default_media_output
from core.command_matcher import (
    AUTO_MATCH_THRESHOLD,
    CONFIRM_MATCH_THRESHOLD,
    CommandDefinition,
    is_confirmation_no,
    is_confirmation_yes,
    match_command,
)
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
    "laitas spotify paalle",
    "spotify paalle",
    "avaa spotify",
    "soita spotify",
    "toista spotify",
    "kaynnista spotify",
    "kaynnista musiikki",
    "laita musiikki paalle",
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
SHUTDOWN_COMMANDS = {
    "sammuta spotify",
    "sammuta musiikki",
    "sulje spotify",
    "musiikki pois",
    "spotify pois",
}
NEXT_COMMANDS = {"seuraava", "seuraava biisi", "seuraava kappale", "skippaa"}
PREVIOUS_COMMANDS = {"edellinen", "edellinen biisi", "edellinen kappale"}
STATUS_COMMANDS = {
    "spotify",
    "onko spotify paalla",
    "mika spotify tila",
    "mika on spotifyn tila",
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
    "mita spotify soi",
}
VOLUME_UP_COMMANDS = {"musiikki kovemmalle"}
VOLUME_DOWN_COMMANDS = {"musiikki hiljemmalle"}
DEFAULT_VOLUME_UP = 90
DEFAULT_VOLUME_DOWN = 50
VOLUME_STEP = 10
VOLUME_DOWN_WORDS = {"iljenpa", "hiljenpa", "hiljenpaa", "hiljempaan", "hiljemppoa", "hiljempaa", "hiljemmalle", "hiljasemmalle", "pienemmalle", "pienemmaksi", "pienenna", "pienen"}
VOLUME_UP_WORDS = {"kovempaa", "kovemmalle", "isommalle", "lisaa", "nosta"}
VOLUME_CONTEXT_WORDS = {"musiikki", "spotify", "volume", "volumea", "voluma", "volumaa", "voluumi", "voluumia", "volyymi", "volyymia", "aani", "aanta"}
VOLUME_COMMAND_WORDS = {"laita", "laitan", "laitas", "pista", "pistapa", "aseta", "pienenna", "pienen", "lisaa", "nosta"}
VOLUME_CONFIRMATION_YES = {"kylla", "joo", "juu", "ok", "okei", "ylla"}
VOLUME_CONFIRMATION_NO = {"ei", "ala", "peruuta", "unohda"}
SPOTIFY_NEAR_MATCH_THRESHOLD = CONFIRM_MATCH_THRESHOLD
SPOTIFY_AUTO_MATCH_THRESHOLD = AUTO_MATCH_THRESHOLD
SPOTIFY_SEARCH_AUTO_MATCH_THRESHOLD = 0.96
SPOTIFY_SEARCH_CONFIRM_MATCH_THRESHOLD = 0.72
SPOTIFY_SEARCH_CONFIRMATION_TIMEOUT_SECONDS = 30.0
SPOTIFY_SEARCH_CONFIRMATION_YES = {"kylla", "joo", "juu", "jep", "oikein", "sita", "soita", "soita vaan", "kylla soita", "juuri se"}
SPOTIFY_SEARCH_CONFIRMATION_NO = {"ei", "en", "ei sita", "vaarin", "vaara", "peruuta", "unohda"}
UNCERTAIN_VOLUME_START_WORDS = {"laita", "pista"}
_pending_volume_adjustment: int | None = None
_pending_spotify_confirmation: str | None = None


@dataclass(frozen=True)
class PendingSpotifySearchResult:
    name: str
    uri: str
    query: str
    score: float
    created_at: float
    artist_name: str | None = None
    track_name: str | None = None
    confirmation_type: str = "search"
    requested_artist: str | None = None
    requested_track: str | None = None


@dataclass(frozen=True)
class SpotifySearchRequest:
    query: str
    types: str
    artist_hint: str | None = None
    track_hint: str | None = None


_pending_spotify_search_result: PendingSpotifySearchResult | None = None
SPOTIFY_WORD_ALIASES = {
    "soitan": "soita",
    "suitan": "soita",
    "suita": "soita",
    "suoita": "soita",
    "hiljempaan": "hiljempaa",
    "hiljemppoa": "hiljempaa",
    "potify": "spotify",
    "potifyy": "spotify",
    "potifi": "spotify",
    "potifaisa": "spotify",
    "potifaissa": "spotify",
    "potifissa": "spotify",
    "spotifaissa": "spotify",
    "spotifyissa": "spotify",
    "spotifyssa": "spotify",
    "spotifysta": "spotify",
    "spotivy": "spotify",
    "spotivyn": "spotifyn",
    "spotifai": "spotify",
    "spotifi": "spotify",
    "spotfy": "spotify",
    "spottify": "spotify",
    "samuutas": "sammuta",
    "voluma": "volume",
    "volumaa": "volumea",
    "voluumi": "volume",
    "voluumia": "volumea",
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
GENERIC_SPOTIFY_NAME_WORDS = {"radio", "mix", "live", "playlist"}
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
    global _pending_spotify_confirmation, _pending_spotify_search_result, _pending_volume_adjustment

    normalized = _normalize(text)
    words = normalized.split()

    if _pending_spotify_search_result is not None:
        if time.monotonic() - _pending_spotify_search_result.created_at > SPOTIFY_SEARCH_CONFIRMATION_TIMEOUT_SECONDS:
            _pending_spotify_search_result = None
        elif normalized in SPOTIFY_SEARCH_CONFIRMATION_YES:
            result = _pending_spotify_search_result
            _pending_spotify_search_result = None
            return _play_search_result_response(result, confirmed=True)
        elif normalized in SPOTIFY_SEARCH_CONFIRMATION_NO:
            _pending_spotify_search_result = None
            return "Selvä, en soita sitä."
        else:
            _pending_spotify_search_result = None

    if _pending_volume_adjustment is not None and normalized in VOLUME_CONFIRMATION_YES:
        adjustment = _pending_volume_adjustment
        _pending_volume_adjustment = None
        return _volume_adjustment_response(adjustment)
    if _pending_volume_adjustment is not None and normalized in VOLUME_CONFIRMATION_NO:
        _pending_volume_adjustment = None
        return "Selvä, en tehnyt muutoksia."

    if _pending_spotify_confirmation is not None and is_confirmation_yes(normalized):
        command_kind = _pending_spotify_confirmation
        _pending_spotify_confirmation = None
        return _spotify_command_response(command_kind)
    if _pending_spotify_confirmation is not None and is_confirmation_no(normalized):
        _pending_spotify_confirmation = None
        return "Selvä, en tehnyt muutoksia."
    if normalized in VOLUME_CONFIRMATION_YES:
        return None

    volume = _volume_percent_from_words(words)
    if volume is not None:
        return _volume_response(volume)

    if normalized in VOLUME_UP_COMMANDS:
        return _volume_response(DEFAULT_VOLUME_UP)
    if normalized in VOLUME_DOWN_COMMANDS:
        return _volume_response(DEFAULT_VOLUME_DOWN)

    adjustment = _volume_adjustment_from_words(words)
    if adjustment is not None:
        return _volume_adjustment_response(adjustment)

    if _looks_like_ambiguous_volume_request(words):
        return "Tarkoititko säätää äänenvoimakkuutta?"

    if normalized in STATUS_COMMANDS:
        return _currently_playing_response()
    if normalized in PLAY_COMMANDS:
        return _spotify_command_response("play")
    if normalized in SHUTDOWN_COMMANDS:
        return _spotify_command_response("shutdown")
    if normalized in PAUSE_COMMANDS:
        return _spotify_command_response("pause")
    if normalized in NEXT_COMMANDS:
        return _run_spotify_action(spotify_client.next_track, "Seuraava kappale.", ensure_output=False)
    if normalized in PREVIOUS_COMMANDS:
        return _run_spotify_action(spotify_client.previous_track, "Edellinen kappale.", ensure_output=False)
    uncertain_adjustment = _uncertain_volume_adjustment_from_words(words)
    if uncertain_adjustment is not None:
        _pending_volume_adjustment = uncertain_adjustment
        direction = "kovemmalle" if uncertain_adjustment > 0 else "hiljemmalle"
        return f"Tarkoititko laittaa musiikkia {direction}?"

    near_spotify_command = _near_spotify_command(normalized)
    if near_spotify_command is not None:
        score, command_kind = near_spotify_command
        if score >= SPOTIFY_AUTO_MATCH_THRESHOLD:
            return _spotify_command_response(command_kind)
        _pending_spotify_confirmation = command_kind
        return _spotify_confirmation_question(command_kind)

    search_request = _search_play_request(words, text)
    if search_request is not None:
        return _search_play_response(search_request)
    return None


def _spotify_command_response(command_kind: str) -> str:
    if command_kind == "play":
        return _play_response()
    if command_kind == "shutdown":
        return _shutdown_response()
    if command_kind == "pause":
        return _run_spotify_action(spotify_client.pause, "Tauko.", ensure_output=False)
    if command_kind == "status":
        return _currently_playing_response()
    return None


def _play_response() -> str:
    return _run_spotify_action(_transfer_and_play, "Soitan Spotifystä.", ensure_output=True, power_on_speakers=True)


def _search_play_response(request: SpotifySearchRequest) -> str:
    query = request.query
    types = request.types
    global _pending_spotify_confirmation, _pending_spotify_search_result, _pending_volume_adjustment

    _pending_spotify_confirmation = None
    _pending_spotify_search_result = None
    _pending_volume_adjustment = None
    try:
        result = spotify_client.search(query, types=types, limit=5)
    except (SpotifyClientError, SpotifyAuthError) as error:
        return str(error)
    suggestion = _best_search_result(result, request)
    # A two-word request may be either a multi-word artist name or an
    # unmarked artist + track request. Prefer a real artist result, and only
    # fall back to track field matching when the artist search found none.
    if suggestion is None and request.types == "artist":
        track_request = SpotifySearchRequest(
            query=request.query,
            types="track",
            artist_hint=request.artist_hint,
            track_hint=request.track_hint,
        )
        try:
            track_result = spotify_client.search(query, types="track", limit=5)
        except (SpotifyClientError, SpotifyAuthError) as error:
            return str(error)
        suggestion = _best_search_result(track_result, track_request)
    if suggestion is None or suggestion.score < SPOTIFY_SEARCH_CONFIRM_MATCH_THRESHOLD:
        for fallback_query in _fallback_track_queries(request):
            try:
                fallback_result = spotify_client.search(fallback_query, types="track", limit=5)
            except (SpotifyClientError, SpotifyAuthError) as error:
                return str(error)
            fallback_suggestion = _best_search_result(fallback_result, request)
            if fallback_suggestion is not None and fallback_suggestion.score >= SPOTIFY_SEARCH_CONFIRM_MATCH_THRESHOLD:
                suggestion = fallback_suggestion
                break
    if suggestion is None or suggestion.score < SPOTIFY_SEARCH_CONFIRM_MATCH_THRESHOLD:
        return f"En löytänyt Spotifystä riittävän tarkkaa osumaa haulle {query}."
    if suggestion.score >= SPOTIFY_SEARCH_AUTO_MATCH_THRESHOLD:
        return _play_search_result_response(suggestion)

    _pending_spotify_confirmation = None
    _pending_volume_adjustment = None
    _pending_spotify_search_result = suggestion
    if suggestion.confirmation_type == "alternative_artist_track":
        return (
            f"En löytänyt artistilta {suggestion.requested_artist} kappaletta {suggestion.requested_track}. "
            f"Löysin sen artistilta {suggestion.artist_name}. Soitanko sen?"
        )
    if suggestion.artist_name and suggestion.track_name:
        return f"Tarkoititko {_finnish_genitive_name(suggestion.artist_name)} kappaletta {suggestion.track_name}?"
    if suggestion.uri.startswith("spotify:artist:"):
        return f"Tarkoititko artistia {suggestion.name}?"
    return f"Tarkoititko {suggestion.name}?"


def _play_search_result_response(result: PendingSpotifySearchResult, confirmed: bool = False) -> str:
    if result.confirmation_type == "alternative_artist_track" and result.artist_name and result.track_name:
        success_message = f"Soitan kappaleen {result.track_name}, esittäjänä {result.artist_name}."
    elif result.artist_name and result.track_name:
        success_message = f"Soitan {_finnish_genitive_name(result.artist_name)} kappaleen {result.track_name}."
    else:
        success_message = (
            f"Soitan artistia {result.name}."
            if confirmed and result.uri.startswith("spotify:artist:")
            else f"Soitan Spotifystä: {result.name}."
        )
    return _run_spotify_action(
        lambda: _play_search_result(result.uri),
        success_message,
        ensure_output=True,
        power_on_speakers=True,
    )


def _finnish_genitive_name(name: str) -> str:
    if name.casefold().endswith("nen"):
        return f"{name[:-3]}sen"
    return f"{name}in" if name.casefold().endswith("s") else f"{name}n"


def _finnish_artist_partitive(name: str) -> str:
    return f"{name}iä" if name.casefold().endswith("s") else f"{name}a"


def _play_search_result(uri: str) -> None:
    device_id = _get_seesam_device_id()
    spotify_client.transfer_playback(device_id, play=False)
    spotify_client.play_uri(uri, device_id=device_id)


def _near_spotify_command(normalized: str) -> tuple[float, str] | None:
    definitions = [
        CommandDefinition("play", "soita spotify", _spotify_confirmation_question("play"), aliases=tuple(PLAY_COMMANDS)),
        CommandDefinition("pause", "pysayta spotify", _spotify_confirmation_question("pause"), aliases=tuple(PAUSE_COMMANDS)),
        CommandDefinition("shutdown", "sammuta spotify", _spotify_confirmation_question("shutdown"), aliases=tuple(SHUTDOWN_COMMANDS)),
        CommandDefinition("status", "spotify status", _spotify_confirmation_question("status"), aliases=tuple(STATUS_COMMANDS)),
    ]
    match = match_command(
        normalized,
        definitions,
        auto_threshold=SPOTIFY_AUTO_MATCH_THRESHOLD,
        confirm_threshold=SPOTIFY_NEAR_MATCH_THRESHOLD,
    )
    if match is None:
        return None
    return match.confidence, match.definition.intent_id


def _spotify_confirmation_question(command_kind: str) -> str:
    if command_kind == "shutdown":
        return "Tarkoititko sammuttaa Spotifyn?"
    if command_kind == "pause":
        return "Tarkoititko pysäyttää Spotifyn?"
    if command_kind == "status":
        return "Tarkoititko kysyä Spotifyn tilaa?"
    return "Tarkoititko käynnistää Spotifyn?"


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


def ensure_speakers_powered_off() -> None:
    """Best-effort Hub shutdown for powered speakers."""
    url = f"{SEESAM_HUB_BASE_URL.rstrip('/')}/speakers/power-off"
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SPEAKER_POWER_ON_TIMEOUT_SECONDS):
            pass
    except Exception:
        return


def _shutdown_response() -> str:
    return _run_spotify_action(_pause_and_power_off, "Sammutin Spotifyn.", ensure_output=False)


def _pause_and_power_off() -> None:
    try:
        spotify_client.pause()
    except SpotifyNoActiveDeviceError:
        pass
    try:
        ensure_speakers_powered_off()
    except Exception:
        return


def _volume_response(percent: int) -> str:
    volume = max(0, min(100, percent))
    return _run_spotify_action(
        lambda: _set_seesam_volume(volume),
        f"Volume {volume}",
    )


def _volume_percent_from_words(words: list[str]) -> int | None:
    if len(words) == 3 and words[0] == "musiikki" and words[1].isdigit() and words[2] == "prosenttia":
        return int(words[1])
    volume_words = {"volume", "volumea", "volyymi", "volyymia", "aani", "aanta"}
    for index, word in enumerate(words[:-1]):
        if word in volume_words and words[index + 1].isdigit():
            return int(words[index + 1])
    return None


def _looks_like_ambiguous_volume_request(words: list[str]) -> bool:
    word_set = set(words)
    return (
        bool(word_set & VOLUME_COMMAND_WORDS)
        and bool(word_set & {"hieman", "hiukan", "vahan"})
        and "paa" in word_set
    )


def _volume_adjustment_from_words(words: list[str]) -> int | None:
    word_set = set(words)
    has_down_word = bool(word_set & VOLUME_DOWN_WORDS)
    has_up_word = bool(word_set & VOLUME_UP_WORDS)
    if not has_down_word and not has_up_word:
        return None

    has_context = bool(word_set & VOLUME_CONTEXT_WORDS) or bool(word_set & VOLUME_COMMAND_WORDS) or bool(word_set & {"vahan", "hieman", "hiukan", "viela"}) or (len(words) == 1 and words[0] in {"hiljempaa", "kovempaa"})
    if not has_context:
        return None
    if has_down_word:
        return -VOLUME_STEP
    return VOLUME_STEP


def _uncertain_volume_adjustment_from_words(words: list[str]) -> int | None:
    if not words or _volume_adjustment_from_words(words) is not None:
        return None
    if _looks_like_uncertain_down_phrase(words):
        return -VOLUME_STEP


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


def _looks_like_uncertain_down_phrase(words: list[str]) -> bool:
    if not words or not _looks_like_uncertain_volume_start(words[0]):
        return False
    filler_match = any(SequenceMatcher(None, word, "vahan").ratio() >= 0.6 for word in words[1:])
    down_match = any(SequenceMatcher(None, word, "hiljempaa").ratio() >= 0.55 for word in words[1:])
    return filler_match and down_match


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


def _search_play_request(words: list[str], original_text: str = "") -> SpotifySearchRequest | None:
    if _looks_like_home_control(words):
        return None

    had_spotify_context = False
    if len(words) >= 2 and words[0] in {"soita", "soitas", "laita", "laitan", "laitas"}:
        query_words = words[1:]
    elif len(words) >= 3 and words[0] in {"hae", "etsi"} and words[1] == "spotify":
        query_words = words[2:]
        had_spotify_context = True
    else:
        return None

    while query_words and query_words[0] == "spotify":
        had_spotify_context = True
        query_words = query_words[1:]

    artist_hint: str | None = None
    track_hint: str | None = None
    had_track_marker = bool(set(query_words) & {"kappale", "biisi"})
    had_artist_marker = "artisti" in query_words
    had_playlist_marker = bool(set(query_words) & {"soittolista", "playlist"})
    had_album_marker = "albumi" in query_words
    comma_parts = re.split(r"[,;]", original_text, maxsplit=1)
    if len(comma_parts) == 2:
        left_words = _normalize(comma_parts[0]).split()
        right_words = _normalize(comma_parts[1]).split()
        left_words = [word for word in left_words if word not in {"soita", "soitas", "spotify"}]
        right_words = [word for word in right_words if word not in {"kappale", "biisi", "artistilta"}]
        artist_hint = " ".join(left_words).strip() or None
        track_hint = " ".join(right_words).strip() or None

    if not artist_hint and not track_hint:
        possessive_index = next((index for index, word in enumerate(query_words[:-1]) if word.endswith("sen")), None)
        if possessive_index is not None and possessive_index + 1 < len(query_words):
            artist_hint = " ".join(query_words[:possessive_index + 1])
            track_hint = " ".join(query_words[possessive_index + 1:])

    if query_words and query_words[0] in {"kappale", "biisi"} and "artistilta" in query_words:
        artist_index = query_words.index("artistilta")
        track_hint = " ".join(query_words[1:artist_index]).strip() or None
        artist_hint = " ".join(query_words[artist_index + 1:]).strip() or None
    query_words = [word for word in query_words if word not in {"kappale", "biisi", "artisti", "artistilta", "soittolista", "playlist", "albumi"}]

    radio_words = {"radio", "radiota", "radioon", "radioo"}
    if query_words and query_words[-1] in radio_words and not had_playlist_marker and not had_album_marker:
        query_words = query_words[:-1]
    query_words = [word for word in query_words if word not in {"jotain", "soimaan"}]
    query = " ".join(query_words).strip()
    if not query or query == "spotify":
        return None

    looks_compound = bool(artist_hint and track_hint) or "artistilta" in words
    looks_compound = looks_compound or (len(query_words) >= 3 and any(word.endswith("sen") for word in query_words[:-1]))
    looks_compound = looks_compound or (had_spotify_context and len(query_words) >= 3)
    looks_compound = looks_compound or len(query_words) >= 4
    if looks_compound or had_track_marker:
        types = "track"
    elif had_playlist_marker:
        types = "playlist"
    elif had_album_marker:
        types = "album"
    elif any(word in GENRE_WORDS for word in query_words):
        types = "playlist,track"
    elif had_artist_marker or len(query_words) == 2:
        types = "artist"
    else:
        types = "track,artist,playlist"
    return SpotifySearchRequest(query=query, types=types, artist_hint=artist_hint, track_hint=track_hint)


def _fallback_track_queries(request: SpotifySearchRequest) -> list[str]:
    candidates: list[str] = []
    if request.track_hint:
        candidates.append(request.track_hint)
    else:
        words = request.query.split()
        for split_index in (2, 3):
            if split_index < len(words) - 1:
                candidates.append(" ".join(words[split_index:]))
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate != request.query and candidate not in unique:
            unique.append(candidate)
    return unique[:2]


def _looks_like_home_control(words: list[str]) -> bool:
    for word in words:
        if word in HOME_CONTROL_WORDS:
            return True
        if word.endswith("n") and word[:-1] in HOME_CONTROL_WORDS:
            return True
    return False


def _best_search_result(result: dict[str, Any], request: SpotifySearchRequest) -> PendingSpotifySearchResult | None:
    types = request.types
    query = request.query
    best_result: PendingSpotifySearchResult | None = None
    best_alternative: PendingSpotifySearchResult | None = None
    unnamed_uri: str | None = None
    saw_named_result = False
    for item_type in types.split(","):
        bucket = result.get(f"{item_type}s")
        if not isinstance(bucket, dict):
            continue
        items = bucket.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "").strip()
            if not uri:
                continue
            names = _spotify_result_names(item)
            if not names:
                unnamed_uri = unnamed_uri or uri
                continue
            saw_named_result = True
            if item_type == "track":
                field_match = _track_field_match(request, item)
                if field_match is not None:
                    artist_name, track_name, score = field_match
                    candidate = PendingSpotifySearchResult(
                        name=track_name, uri=uri, query=query, score=score,
                        created_at=time.monotonic(), artist_name=artist_name, track_name=track_name,
                    )
                    if best_result is None or candidate.score > best_result.score:
                        best_result = candidate
                    continue
                alternative = _alternative_artist_track_match(request, item)
                if alternative is not None:
                    requested_artist, requested_track, artist_name, track_name, score = alternative
                    candidate = PendingSpotifySearchResult(
                        name=track_name, uri=uri, query=query, score=score,
                        created_at=time.monotonic(), artist_name=artist_name, track_name=track_name,
                        confirmation_type="alternative_artist_track",
                        requested_artist=_nominative_artist_hint(requested_artist),
                        requested_track=track_name,
                    )
                    if best_alternative is None or candidate.score > best_alternative.score:
                        best_alternative = candidate
                    continue
            name, score = max(
                ((name, _spotify_name_match_score(query, name)) for name in names),
                key=lambda candidate: candidate[1],
            )
            if best_result is None or score > best_result.score:
                best_result = PendingSpotifySearchResult(name=name, uri=uri, query=query, score=score, created_at=time.monotonic())
    if best_result is not None and best_result.score >= SPOTIFY_SEARCH_CONFIRM_MATCH_THRESHOLD:
        return best_result
    if best_alternative is not None:
        return best_alternative
    if best_result is not None:
        return best_result
    if not saw_named_result and unnamed_uri is not None:
        return PendingSpotifySearchResult(name=query, uri=unnamed_uri, query=query, score=1.0, created_at=time.monotonic())
    return None


def _track_field_match(request: SpotifySearchRequest, item: dict[str, Any]) -> tuple[str, str, float] | None:
    track_name = str(item.get("name") or "").strip()
    artists = item.get("artists")
    artist_names = [
        str(artist.get("name") or "").strip()
        for artist in artists
        if isinstance(artist, dict) and artist.get("name")
    ] if isinstance(artists, list) else []
    if not track_name or not artist_names:
        return None

    hint_pairs: list[tuple[str, str]] = []
    if request.artist_hint and request.track_hint:
        hint_pairs.append((request.artist_hint, request.track_hint))
    words = request.query.split()
    hint_pairs.extend((" ".join(words[:index]), " ".join(words[index:])) for index in range(1, len(words)))

    best: tuple[str, str, float] | None = None
    for artist_hint, track_hint in hint_pairs:
        for artist_name in artist_names:
            artist_score = _spotify_name_match_score(artist_hint, artist_name)
            track_score = _spotify_name_match_score(track_hint, track_name)
            if artist_score < 0.65 or track_score < 0.65:
                continue
            whole_score = _spotify_name_match_score(request.query, f"{artist_name} {track_name}")
            score = 0.45 * artist_score + 0.45 * track_score + 0.10 * whole_score
            if artist_score < 0.99 or track_score < 0.99:
                score = min(score, 0.95)
            if best is None or score > best[2]:
                best = (artist_name, track_name, score)
    return best


def _alternative_artist_track_match(
    request: SpotifySearchRequest,
    item: dict[str, Any],
) -> tuple[str, str, str, str, float] | None:
    track_name = str(item.get("name") or "").strip()
    artists = item.get("artists")
    artist_names = [
        str(artist.get("name") or "").strip()
        for artist in artists
        if isinstance(artist, dict) and artist.get("name")
    ] if isinstance(artists, list) else []
    if not track_name or not artist_names:
        return None

    hint_pairs: list[tuple[str, str]] = []
    if request.artist_hint and request.track_hint:
        hint_pairs.append((request.artist_hint, request.track_hint))
    words = request.query.split()
    hint_pairs.extend((" ".join(words[:index]), " ".join(words[index:])) for index in range(1, len(words)))

    best: tuple[str, str, str, str, float] | None = None
    for requested_artist, requested_track in hint_pairs:
        track_score = _spotify_name_match_score(requested_track, track_name)
        if track_score < 0.88:
            continue
        for artist_name in artist_names:
            artist_score = _spotify_name_match_score(requested_artist, artist_name)
            if artist_score >= 0.65:
                continue
            candidate = (requested_artist, requested_track, artist_name, track_name, min(track_score, 0.95))
            if best is None or candidate[4] > best[4]:
                best = candidate
    return best


def _nominative_artist_hint(value: str) -> str:
    words = value.split()
    if words and words[-1].casefold() == "pojan":
        words[-1] = "poika"
    elif words and words[-1].casefold().endswith("sen") and len(words[-1]) > 5:
        words[-1] = f"{words[-1][:-3]}nen"
    return " ".join(words).title()


def _spotify_result_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    name = str(item.get("name") or "").strip()
    if name:
        names.append(name)
    artists = item.get("artists")
    if isinstance(artists, list):
        names.extend(str(artist.get("name") or "").strip() for artist in artists if isinstance(artist, dict))
    for field in ("album", "show"):
        value = item.get(field)
        if isinstance(value, dict):
            names.append(str(value.get("name") or "").strip())
    return [name for name in names if name]


def _spotify_name_forms(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z]+", " ", value.casefold().translate(str.maketrans({"ä": "a", "ö": "o", "å": "a"})))
    normalized = " ".join(normalized.split())
    forms = {normalized}
    words = normalized.split()
    if words:
        last = words[-1]
        if last == "pojan":
            forms.add(" ".join([*words[:-1], "poika"]))
        if last.endswith("rran") and len(last) > 5:
            forms.add(" ".join([*words[:-1], f"{last[:-4]}rta"]))
        if last.endswith("n") and not last.endswith("nen") and len(last) > 4:
            forms.add(" ".join([*words[:-1], last[:-1]]))
        if last.endswith("sen") and len(last) > 5:
            forms.add(" ".join([*words[:-1], f"{last[:-3]}nen"]))
        if last.endswith("kaan") and len(last) > 5:
            forms.add(" ".join([*words[:-1], last[:-2]]))
        if last.endswith("radioon"):
            forms.add(" ".join([*words[:-1], last[:-2]]))
        for suffix in ("tta", "ta", "ia"):
            if len(last) > len(suffix) + 2 and last.endswith(suffix):
                forms.add(" ".join([*words[:-1], last[:-len(suffix)]]))
    return {form for form in forms if form}


def _spotify_name_match_score(query: str, candidate: str) -> float:
    query_forms = _spotify_name_forms(query)
    candidate_forms = _spotify_name_forms(candidate)
    if query_forms & candidate_forms:
        exact_words = set(next(iter(query_forms & candidate_forms)).split())
        return 1.0 if exact_words - GENERIC_SPOTIFY_NAME_WORDS else 0.0
    best = 0.0
    for query_form in query_forms:
        for candidate_form in candidate_forms:
            best = max(best, SequenceMatcher(None, query_form, candidate_form).ratio())
            best = max(best, SequenceMatcher(None, query_form.replace(" ", ""), candidate_form.replace(" ", "")).ratio())
            query_words = set(query_form.split()) - GENERIC_SPOTIFY_NAME_WORDS
            candidate_words = set(candidate_form.split()) - GENERIC_SPOTIFY_NAME_WORDS
            query_important = "".join(word for word in query_form.split() if word not in GENERIC_SPOTIFY_NAME_WORDS)
            candidate_important = "".join(word for word in candidate_form.split() if word not in GENERIC_SPOTIFY_NAME_WORDS)
            if query_important and candidate_important:
                best = max(best, SequenceMatcher(None, query_important, candidate_important).ratio())
            if query_words and query_words <= candidate_words:
                best = max(best, 0.9)
    return best


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
    source_words = text.split()
    combined_words: list[str] = []
    index = 0
    while index < len(source_words):
        if source_words[index:index + 2] == ["poti", "vai"]:
            combined_words.append("spotify")
            index += 2
            continue
        combined_words.append(source_words[index])
        index += 1
    words = [SPOTIFY_WORD_ALIASES.get(word, word) for word in combined_words]
    return " ".join(words)
