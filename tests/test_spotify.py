import base64
import hashlib
import time
from pathlib import Path

import pytest

from audio.audio_manager import AudioResult, SPEAKERS_SLEEPING_MESSAGE


@pytest.fixture(autouse=True)
def reset_spotify_volume_pending(monkeypatch, request):
    from spotify import spotify_commands

    spotify_commands._pending_volume_adjustment = None
    spotify_commands._pending_spotify_confirmation = None
    spotify_commands._pending_spotify_search_result = None
    if request.node.name not in {
        "test_ensure_speakers_powered_on_posts_to_hub_before_delay",
        "test_ensure_speakers_powered_on_failure_does_not_sleep_or_raise",
        "test_spotify_play_continues_when_speaker_power_on_fails",
    }:
        monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_on", lambda: None)
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: None)
    yield
    spotify_commands._pending_volume_adjustment = None
    spotify_commands._pending_spotify_confirmation = None
    spotify_commands._pending_spotify_search_result = None


def test_pkce_code_challenge_matches_s256():
    from spotify.spotify_auth import generate_code_challenge

    verifier = "a" * 64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")

    assert generate_code_challenge(verifier) == expected


def test_spotify_config_loads_local_client_id_without_secret(tmp_path):
    from spotify.spotify_auth import load_config

    config_path = tmp_path / "spotify_config.local.json"
    config_path.write_text(
        '{"client_id":"local-client","redirect_uri":"http://127.0.0.1:8888/callback","token_path":"data/token.json"}',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.client_id == "local-client"
    assert config.redirect_uri == "http://127.0.0.1:8888/callback"
    assert config.token_path.name == "token.json"


def test_save_token_writes_required_token_fields(tmp_path):
    from spotify.spotify_auth import save_token

    token_path = tmp_path / "spotify_token.local.json"
    stored = save_token(
        {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
        token_path,
    )

    assert token_path.exists()
    assert stored["access_token"] == "access"
    assert stored["refresh_token"] == "refresh"
    assert stored["expires_at"] > int(time.time())


def test_spotify_play_transfers_to_seesam_before_api_play(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands,
        "ensure_default_media_output",
        lambda: calls.append("media_output") or AudioResult(True, "Steljes-kaiuttimet yhdistetty."),
    )
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_on", lambda: calls.append("speaker_power_on"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    assert spotify_commands.handle_spotify_command("soita spotify") == "Soitan Spotifystä."
    assert calls == ["speaker_power_on", "media_output", ("transfer", "seesam-id", False), ("play", "seesam-id")]


def test_ensure_speakers_powered_on_posts_to_hub_before_delay(monkeypatch):
    from spotify import spotify_commands

    calls = []

    class FakeResponse:
        def __enter__(self):
            calls.append("response_enter")
            return self

        def __exit__(self, exc_type, exc, traceback):
            calls.append("response_exit")

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method(), request.data, timeout))
        return FakeResponse()

    monkeypatch.setattr(spotify_commands.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(spotify_commands.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    spotify_commands.ensure_speakers_powered_on()

    assert calls == [
        ("http://192.168.68.74:8000/speakers/power-on", "POST", b"", 5),
        "response_enter",
        "response_exit",
        ("sleep", 10),
    ]


def test_ensure_speakers_powered_on_failure_does_not_sleep_or_raise(monkeypatch):
    from spotify import spotify_commands

    calls = []

    def fail_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method(), timeout))
        raise OSError("hub unavailable")

    monkeypatch.setattr(spotify_commands.urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(spotify_commands.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    spotify_commands.ensure_speakers_powered_on()

    assert calls == [("http://192.168.68.74:8000/speakers/power-on", "POST", 5)]


def test_spotify_play_continues_when_speaker_power_on_fails(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.urllib.request, "urlopen", lambda request, timeout: (_ for _ in ()).throw(OSError("hub unavailable")))
    monkeypatch.setattr(spotify_commands.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: calls.append(("transfer", device_id, play)))
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    assert spotify_commands.handle_spotify_command("soita spotify") == "Soitan Spotifystä."
    assert calls == [("transfer", "seesam-id", False), ("play", "seesam-id")]


def test_spotify_play_stops_when_media_output_fails(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_on", lambda: calls.append("speaker_power_on"))
    monkeypatch.setattr(
        spotify_commands,
        "ensure_default_media_output",
        lambda: calls.append("media_output") or AudioResult(False, SPEAKERS_SLEEPING_MESSAGE),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: calls.append("devices"))
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append("play"))

    assert spotify_commands.handle_spotify_command("musiikki päälle") == "Kaiuttimet eivät vastaa. Herätä ne Bluetooth-tilaan."
    assert calls == ["speaker_power_on", "media_output"]


def test_spotify_currently_playing_response(monkeypatch):
    from spotify import spotify_commands

    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_currently_playing",
        lambda: {"item": {"name": "Kappale", "artists": [{"name": "Artisti"}]}},
    )

    assert spotify_commands.handle_spotify_command("mikä biisi soi") == "Nyt soi Artisti – Kappale."


def test_spotify_command_maps_no_active_device(monkeypatch):
    from spotify import spotify_commands
    from spotify.spotify_client import SpotifyNoActiveDeviceError

    def fail():
        raise SpotifyNoActiveDeviceError("no device")

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: fail())

    assert (
        spotify_commands.handle_spotify_command("jatka")
        == "Spotify-laitetta ei löytynyt. Avaa Spotify kerran puhelimesta tai koneelta."
    )


def test_core_routes_spotify_commands_without_ollama(monkeypatch):
    from core import commands

    monkeypatch.setattr(commands, "handle_spotify_command", lambda text: "Soitan Spotifystä." if text == "soita spotify" else None)

    assert commands.handle_local_command("soita spotify") == "Soitan Spotifystä."


def test_core_keeps_audio_output_commands(monkeypatch):
    from audio import audio_manager
    from core import commands

    monkeypatch.setattr(commands, "handle_spotify_command", lambda text: None)
    monkeypatch.setattr(commands, "ensure_speakers_powered_on", lambda: None)
    monkeypatch.setattr(
        commands,
        "ensure_media_output",
        lambda device_id=None: audio_manager.AudioResult(True, "Steljes-kaiuttimet yhdistetty."),
    )

    assert commands.handle_local_command("kaiuttimet päälle") == "Kaiuttimet kytketty."


def test_spotify_play_does_not_require_seesam_to_be_active(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_available_devices",
        lambda: [{"id": "seesam-id", "name": "Seesam", "is_active": False}],
    )
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    assert spotify_commands.handle_spotify_command("musiikki päälle") == "Soitan Spotifystä."
    assert calls == [("transfer", "seesam-id", False), ("play", "seesam-id")]


def test_spotify_volume_command_targets_seesam_device(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands,
        "ensure_speakers_powered_on",
        lambda: (_ for _ in ()).throw(AssertionError("volume command must not power on speakers")),
    )
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )

    assert spotify_commands.handle_spotify_command("spotify volume 80") == "Volume 80"
    assert spotify_commands.handle_spotify_command("musiikki ääni 90") == "Volume 90"
    assert calls == [(80, "seesam-id"), (90, "seesam-id")]


def test_spotify_play_intents_do_not_fall_through_to_fact_response(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    commands = [
        "käynnistä spotify",
        "kaynnista spotify",
        "avaa spotify",
        "spotify päälle",
        "spotify paalle",
        "laita spotify päälle",
        "laita spotify paalle",
        "laitas spotify päälle",
        "laitas spotify paalle",
        "Laitas poti vai päälle.",
        "Käynnistä spotifai.",
        "toista spotify",
        "soita spotify",
        "käynnistä musiikki",
        "kaynnista musiikki",
        "laita musiikki päälle",
        "laita musiikki paalle",
        "musiikki päälle",
        "musiikki paalle",
        "soita musiikkia",
        "jatka musiikkia",
        "jatka spotify",
        "jatka",
        "toista",
    ]

    for command in commands:
        assert spotify_commands.handle_spotify_command(command) == "Soitan Spotifystä."

    assert len(calls) == len(commands) * 2


def test_spotify_start_aliases_work_like_play_commands(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: (_ for _ in ()).throw(AssertionError("play command must not power off speakers")))
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: calls.append(("transfer", device_id, play)))
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    assert spotify_commands.handle_spotify_command("käynnistä spotify") == "Soitan Spotifystä."
    assert spotify_commands.handle_spotify_command("käynnistä musiikki") == "Soitan Spotifystä."
    assert calls == [
        ("transfer", "seesam-id", False),
        ("play", "seesam-id"),
        ("transfer", "seesam-id", False),
        ("play", "seesam-id"),
    ]


def test_spotify_shutdown_high_confidence_typos_do_not_fall_through(monkeypatch):
    from core import commands
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    for command in ["sammuta potify", "samuta spotify", "sammuta spotivy", "Samuutas potifyy.", "samuutas spotify", "sammuta potifyy"]:
        assert commands.handle_local_command(command) == "Sammutin Spotifyn."

    assert calls == ["pause", "speaker_power_off"] * 6


def test_spotify_shutdown_medium_confidence_typo_asks_confirmation(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    assert spotify_commands.handle_spotify_command("samut potify") == "Tarkoititko sammuttaa Spotifyn?"
    assert calls == []


def test_pending_spotify_confirmation_yes_executes_shutdown(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    assert spotify_commands.handle_spotify_command("samut potify") == "Tarkoititko sammuttaa Spotifyn?"
    assert spotify_commands.handle_spotify_command("kyllä") == "Sammutin Spotifyn."
    assert calls == ["pause", "speaker_power_off"]


def test_pending_spotify_confirmation_no_cancels_shutdown(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    assert spotify_commands.handle_spotify_command("samut potify") == "Tarkoititko sammuttaa Spotifyn?"
    assert spotify_commands.handle_spotify_command("ei") == "Selvä, en tehnyt muutoksia."
    assert calls == []


def test_spotify_shutdown_commands_pause_then_power_off(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands,
        "ensure_speakers_powered_on",
        lambda: (_ for _ in ()).throw(AssertionError("shutdown command must not power on speakers")),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    for command in ["sammuta spotify", "sammuta musiikki", "sulje spotify", "musiikki pois", "spotify pois"]:
        assert spotify_commands.handle_spotify_command(command) == "Sammutin Spotifyn."

    assert calls == ["pause", "speaker_power_off"] * 5


def test_spotify_shutdown_continues_when_pause_has_no_active_device(monkeypatch):
    from spotify import spotify_commands
    from spotify.spotify_client import SpotifyNoActiveDeviceError

    calls = []

    def fail_pause():
        calls.append("pause")
        raise SpotifyNoActiveDeviceError("no active device")

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", fail_pause)
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    assert spotify_commands.handle_spotify_command("sammuta spotify") == "Sammutin Spotifyn."
    assert calls == ["pause", "speaker_power_off"]


def test_spotify_shutdown_continues_when_speaker_power_off_fails(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(
        spotify_commands,
        "ensure_speakers_powered_off",
        lambda: calls.append("speaker_power_off") or (_ for _ in ()).throw(OSError("hub unavailable")),
    )

    assert spotify_commands.handle_spotify_command("sammuta spotify") == "Sammutin Spotifyn."
    assert calls == ["pause", "speaker_power_off"]


def test_spotify_pause_next_previous_and_status_intents(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands,
        "ensure_speakers_powered_on",
        lambda: (_ for _ in ()).throw(AssertionError("non-play command must not power on speakers")),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands.spotify_client, "next_track", lambda: calls.append("next"))
    monkeypatch.setattr(spotify_commands.spotify_client, "previous_track", lambda: calls.append("previous"))
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_currently_playing",
        lambda: {"item": {"name": "Kappale", "artists": [{"name": "Artist"}]}},
    )

    for command in ["tauko", "paussi", "pysäytä musiikki", "pysäytä spotify", "spotify tauko", "musiikki tauko"]:
        assert spotify_commands.handle_spotify_command(command) == "Tauko."
    for command in ["seuraava", "seuraava biisi", "seuraava kappale"]:
        assert spotify_commands.handle_spotify_command(command) == "Seuraava kappale."
    for command in ["edellinen", "edellinen biisi", "edellinen kappale"]:
        assert spotify_commands.handle_spotify_command(command) == "Edellinen kappale."
    for command in [
        "mitä soi",
        "mikä soi",
        "mikä kappale",
        "mikä kappale tämä on",
        "kuka soi",
        "mikä biisi",
        "mikä biisi tämä on",
        "spotify status",
        "mitä spotifyssä soi",
    ]:
        assert spotify_commands.handle_spotify_command(command) == "Nyt soi Artist – Kappale."

    assert calls == ["pause"] * 6 + ["next"] * 3 + ["previous"] * 3




def test_spotify_status_typos_do_not_fall_through_to_ai(monkeypatch):
    from core import commands
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_currently_playing",
        lambda: calls.append("currently_playing") or {"item": {"name": "Kappale", "artists": [{"name": "Artist"}]}},
    )

    assert commands.handle_local_command("onko potify päällä") == "Nyt soi Artist – Kappale."
    assert commands.handle_local_command("mikä on spotivyn tila") == "Nyt soi Artist – Kappale."
    assert calls == ["currently_playing", "currently_playing"]


def test_spotify_status_medium_confidence_typo_can_be_confirmed(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_currently_playing",
        lambda: calls.append("currently_playing") or {"item": {"name": "Kappale", "artists": [{"name": "Artist"}]}},
    )

    assert spotify_commands.handle_spotify_command("spotfy sta") == "Tarkoititko kysyä Spotifyn tilaa?"
    assert calls == []
    assert spotify_commands.handle_spotify_command("juu") == "Nyt soi Artist – Kappale."
    assert calls == ["currently_playing"]


def test_spotify_word_aliases_match_command_intents(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))
    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "get_currently_playing",
        lambda: {"item": {"name": "Kappale", "artists": [{"name": "Artist"}]}},
    )

    for command in ["laita potifi päälle", "laita spotivy päälle", "soita spotifai"]:
        assert spotify_commands.handle_spotify_command(command) == "Soitan Spotifystä."

    assert spotify_commands.handle_spotify_command("pysäytä potifi") == "Tauko."
    assert spotify_commands.handle_spotify_command("potifi tauko") == "Tauko."
    assert spotify_commands.handle_spotify_command("mitä potifissa soi") == "Nyt soi Artist – Kappale."
    assert calls == [
        ("transfer", "seesam-id", False),
        ("play", "seesam-id"),
        ("transfer", "seesam-id", False),
        ("play", "seesam-id"),
        ("transfer", "seesam-id", False),
        ("play", "seesam-id"),
        "pause",
        "pause",
    ]


def test_spotify_search_play_commands(monkeypatch):
    from spotify import spotify_commands

    calls = []
    search_results = {
        ("dark technoa", "playlist,track"): {"playlists": {"items": [{"uri": "spotify:playlist:dark"}]}},
        ("the fine print", "track"): {"tracks": {"items": [{"uri": "spotify:track:fine"}]}},
        ("mirrors", "track"): {"tracks": {"items": [{"uri": "spotify:track:mirrors"}]}},
        ("tool", "artist"): {"artists": {"items": [{"uri": "spotify:artist:tool"}]}},
        ("jukka poika", "artist"): {"artists": {"items": [{"uri": "spotify:artist:jukka"}]}},
        ("suomirock", "playlist,track"): {"playlists": {"items": [{"uri": "spotify:playlist:suomirock"}]}},
        ("rauhallista ambienttia", "playlist,track"): {"tracks": {"items": [{"uri": "spotify:track:ambient"}]}},
        ("jazzia", "playlist,track"): {"playlists": {"items": [{"uri": "spotify:playlist:jazz"}]}},
        ("soulia", "playlist,track"): {"playlists": {"items": [{"uri": "spotify:playlist:soul"}]}},
        ("jukka poika", "track,artist,playlist"): {"tracks": {"items": [{"uri": "spotify:track:jukka"}]}},
        ("silkkii", "track"): {"tracks": {"items": [{"uri": "spotify:track:silkkii"}]}},
    }

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "search",
        lambda query, types="track,artist,playlist", limit=5: calls.append(("search", query, types, limit)) or search_results[(query, types)],
    )
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "play_uri",
        lambda uri, device_id=None: calls.append(("play_uri", uri, device_id)),
    )

    cases = [
        ("soita dark technoa", "dark technoa", "playlist,track", "spotify:playlist:dark"),
        ("soita kappale the fine print", "the fine print", "track", "spotify:track:fine"),
        ("soita biisi mirrors", "mirrors", "track", "spotify:track:mirrors"),
        ("soita artisti tool", "tool", "artist", "spotify:artist:tool"),
        ("hae spotify suomirock", "suomirock", "playlist,track", "spotify:playlist:suomirock"),
        ("laita rauhallista ambienttia", "rauhallista ambienttia", "playlist,track", "spotify:track:ambient"),
        ("soita jotain jazzia", "jazzia", "playlist,track", "spotify:playlist:jazz"),
        ("laita jazzia soimaan", "jazzia", "playlist,track", "spotify:playlist:jazz"),
        ("soita soulia", "soulia", "playlist,track", "spotify:playlist:soul"),
        ("soita jukka poika", "jukka poika", "artist", "spotify:artist:jukka"),
        ("soita artisti jukka poika", "jukka poika", "artist", "spotify:artist:jukka"),
        ("soita kappale silkkii", "silkkii", "track", "spotify:track:silkkii"),
    ]

    for command, query, _types, _uri in cases:
        assert spotify_commands.handle_spotify_command(command) == f"Soitan Spotifystä: {query}."

    expected_calls = []
    for _command, query, types, uri in cases:
        expected_calls.extend([
            ("search", query, types, 5),
            ("transfer", "seesam-id", False),
            ("play_uri", uri, "seesam-id"),
        ])
    assert calls == expected_calls


def test_plain_artist_search_prefers_artist_result_type(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {
        "tracks": {"items": [{"name": "Benny Song", "uri": "spotify:track:first", "artists": [{"name": "Benny Rivers"}]}]},
        "artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]},
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: calls.append(("search", query, types)) or result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: calls.append(("transfer", device_id, play)))
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(("play_uri", uri, device_id)))

    for command in ("Soita Benny Rivers", "Soita artisti Benny Rivers", "Laita Benny Rivers soimaan"):
        calls.clear()
        assert spotify_commands.handle_spotify_command(command) == "Soitan Spotifystä: Benny Rivers."
        assert calls == [("search", "benny rivers", "artist"), ("transfer", "seesam-id", False), ("play_uri", "spotify:artist:benny", "seesam-id")]


def test_explicit_playlist_and_album_select_requested_result_type(monkeypatch):
    from spotify import spotify_commands

    calls = []
    results = {
        ("evening radio", "playlist"): {"playlists": {"items": [{"name": "Evening Radio", "uri": "spotify:playlist:evening"}]}},
        ("northern lights", "album"): {"albums": {"items": [{"name": "Northern Lights", "uri": "spotify:album:northern"}]}},
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: calls.append((query, types)) or results[(query, types)])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("soita soittolista Evening Radio") == "Soitan Spotifystä: Evening Radio."
    assert spotify_commands.handle_spotify_command("soita albumi Northern Lights") == "Soitan Spotifystä: Northern Lights."
    assert calls == [("evening radio", "playlist"), "spotify:playlist:evening", ("northern lights", "album"), "spotify:album:northern"]


def test_uncertain_artist_confirmation_plays_artist_context(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("soita artisti Benny Revers") == "Tarkoititko artistia Benny Rivers?"
    assert spotify_commands.handle_spotify_command("kyllä") == "Soitan artistia Benny Rivers."
    assert calls == ["spotify:artist:benny"]


def test_spotify_search_play_ignores_home_control_commands(monkeypatch):
    from spotify import spotify_commands

    def fail_search(*args, **kwargs):
        raise AssertionError("home control command should not reach Spotify search")

    monkeypatch.setattr(spotify_commands.spotify_client, "search", fail_search)

    assert spotify_commands.handle_spotify_command("laita grillikatoksen valot päälle") is None
    assert spotify_commands.handle_spotify_command("laita olohuoneen valot päälle") is None


def test_spotify_search_play_uses_spotify_word_alias(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "search",
        lambda query, types="track,artist,playlist", limit=5: calls.append((query, types, limit))
        or {"playlists": {"items": [{"uri": "spotify:playlist:suomirock"}]}},
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: None)

    assert spotify_commands.handle_spotify_command("hae spotivy suomirock") == "Soitan Spotifystä: suomirock."
    assert calls == [("suomirock", "playlist,track", 5)]


def test_spotify_context_is_removed_and_best_named_result_is_selected(monkeypatch):
    from spotify import spotify_commands

    calls = []
    results = {
        "benny rivers": {
            "artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]}
        },
        "benny reverse": {
            "artists": {"items": [{"name": "Benny Reverse", "uri": "spotify:artist:reverse"}]}
        },
        "happoradiota": {
            "artists": {"items": [{"name": "Happoradio", "uri": "spotify:artist:happoradio"}]}
        },
    }

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: calls.append(("search", query)) or results[query])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: calls.append(("transfer", device_id)))
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(("play_uri", uri)))

    assert spotify_commands.handle_spotify_command("Soita Spotifyissa, Benny Rivers Radio.") == "Soitan Spotifystä: Benny Rivers."
    assert spotify_commands.handle_spotify_command("Soitas potifaisa Benny Reverse Radio.") == "Soitan Spotifystä: Benny Reverse."
    assert spotify_commands.handle_spotify_command("soita happoradiota") == "Soitan Spotifystä: Happoradio."
    assert ("play_uri", "spotify:playlist:wrong") not in calls
    assert ("play_uri", "spotify:artist:benny") in calls
    assert ("play_uri", "spotify:artist:reverse") in calls
    assert ("play_uri", "spotify:artist:happoradio") in calls


def test_spotify_speech_variants_accept_matching_playlist(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {
        "artists": {
            "items": [
                {"name": "Benny Rivers", "uri": "spotify:artist:benny-rivers"}
            ]
        }
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: calls.append(("search", query)) or result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(("play_uri", uri)))

    commands = [
        ("Soitas potifaissa Beniriverse Radio.", "beniriverse"),
        ("Soita spotifaissa Benny Revers Radio.", "benny revers"),
        ("Soitas potifaissa. Benny Rivers Radio.", "benny rivers"),
        ("Soita Spotifyissa Benny Rivers Radio.", "benny rivers"),
    ]
    for index, (command, query) in enumerate(commands):
        response = spotify_commands.handle_spotify_command(command)
        if index < 2:
            assert response == "Tarkoititko artistia Benny Rivers?"
            assert spotify_commands.handle_spotify_command("kyllä") == "Soitan artistia Benny Rivers."
        else:
            assert response == "Soitan Spotifystä: Benny Rivers."

    assert [(kind, value) for kind, value in calls if kind == "search"] == [("search", query) for _, query in commands]
    assert calls.count(("play_uri", "spotify:artist:benny-rivers")) == len(commands)

    calls_before = list(calls)
    assert spotify_commands.handle_spotify_command("Täältä benirivärs-radioon.") is None
    assert calls == calls_before


def test_spotify_name_matching_tolerates_speech_errors_without_radio_false_positive():
    from spotify import spotify_commands

    for query in [
        "Benny Rivers Radio",
        "Benny River Radio",
        "Benny Revers Radio",
        "Beniriverse Radio",
        "benirivärs-radioon",
    ]:
        assert spotify_commands._spotify_name_match_score(query, "Benny Rivers Radio") >= 0.78

    assert spotify_commands._spotify_name_match_score("Benny Rivers Radio", "Happoradio") < 0.78
    assert spotify_commands._spotify_name_match_score("Benny Rivers Radio", "Radio Hits") < 0.78


def test_pending_spotify_search_result_can_be_rejected(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]}}
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda *args, **kwargs: calls.append("play"))

    assert spotify_commands.handle_spotify_command("Soita Spotifyissa Benny Revers Radio") == "Tarkoititko artistia Benny Rivers?"
    assert spotify_commands.handle_spotify_command("ei") == "Selvä, en soita sitä."
    assert calls == []
    assert spotify_commands._pending_spotify_search_result is None


def test_pending_spotify_search_result_expires(monkeypatch):
    from spotify import spotify_commands

    calls = []
    spotify_commands._pending_spotify_search_result = spotify_commands.PendingSpotifySearchResult(
        name="Benny Rivers Radio",
        uri="spotify:playlist:benny",
        query="benny revers radio",
        score=0.9,
        created_at=0.0,
    )
    monkeypatch.setattr(spotify_commands.time, "monotonic", lambda: spotify_commands.SPOTIFY_SEARCH_CONFIRMATION_TIMEOUT_SECONDS + 1)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda *args, **kwargs: calls.append("play"))

    assert spotify_commands.handle_spotify_command("kyllä") is None
    assert calls == []
    assert spotify_commands._pending_spotify_search_result is None


def test_new_spotify_search_replaces_pending_search_result(monkeypatch):
    from spotify import spotify_commands

    calls = []
    results = {
        "benny revers": {"artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]}},
        "johnny revers": {"artists": {"items": [{"name": "Johnny Rivers", "uri": "spotify:artist:johnny"}]}},
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: results[query])
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("soita spotifyissa benny revers radio") == "Tarkoititko artistia Benny Rivers?"
    assert spotify_commands.handle_spotify_command("soita spotifyissa johnny revers radio") == "Tarkoititko artistia Johnny Rivers?"
    assert spotify_commands.handle_spotify_command("juu") == "Soitan artistia Johnny Rivers."
    assert calls == ["spotify:artist:johnny"]


def test_spotify_artist_search_without_radio_stays_normal_search(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"artists": {"items": [{"name": "Benny Rivers", "uri": "spotify:artist:benny"}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("soita Benny Rivers") == "Soitan Spotifystä: Benny Rivers."
    assert calls == ["spotify:artist:benny"]


def test_playlist_with_radio_in_its_name_uses_normal_playlist_playback(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {
        "playlists": {
            "items": [{"name": "Benny Rivers Radio", "uri": "spotify:playlist:benny-radio"}]
        }
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("soita soittolista Benny Rivers Radio") == "Soitan Spotifystä: Benny Rivers Radio."
    assert calls == ["spotify:playlist:benny-radio"]


def test_spotify_search_rejects_unrelated_radio_result(monkeypatch):
    from spotify import spotify_commands

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "search",
        lambda query, types="track,artist,playlist", limit=5: {
            "playlists": {"items": [{"name": "Happoradio", "uri": "spotify:playlist:wrong"}]}
        },
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("wrong result must not play")))

    assert (
        spotify_commands.handle_spotify_command("Soita Spotifyissa Benny Rivers Radio")
        == "En löytänyt Spotifystä riittävän tarkkaa osumaa haulle benny rivers."
    )


def test_spotify_artist_and_track_structures_match_track_fields(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {
        "tracks": {
            "items": [{
                "name": "Neljän ruuhka",
                "uri": "spotify:track:neljan-ruuhka",
                "artists": [{"name": "Arto Tamminen"}],
            }]
        }
    }
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: calls.append(("search", query, types)) or result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(("play", uri)))

    commands = [
        "Soita Arto Tamminen, neljän ruuhka.",
        "Soita Arto Tammisen neljän ruuhkaan.",
        "Soita spotifaissa Arto Tammisen neljän ruuhkaan.",
        "Soita artistilta Arto Tamminen neljän ruuhka.",
        "Soita kappale neljän ruuhka artistilta Arto Tamminen.",
    ]
    for command in commands:
        assert spotify_commands.handle_spotify_command(command) == "Soitan Arto Tammisen kappaleen Neljän ruuhka."

    assert calls.count(("play", "spotify:track:neljan-ruuhka")) == len(commands)
    assert all(call[2] == "track" for call in calls if call[0] == "search")


def test_spotify_artist_and_track_field_mismatch_is_rejected(monkeypatch):
    from spotify import spotify_commands

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    results = [
        {"name": "Täysin toinen kappale", "uri": "spotify:track:wrong-track", "artists": [{"name": "Arto Tamminen"}]},
    ]
    for item in results:
        monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5, item=item: {"tracks": {"items": [item]}})
        assert spotify_commands.handle_spotify_command("Soita Arto Tamminen, neljän ruuhka") == "En löytänyt Spotifystä riittävän tarkkaa osumaa haulle arto tamminen neljan ruuhka."


def test_spotify_safe_finnish_name_inflections_match_for_scoring():
    from spotify import spotify_commands

    for spoken, result_name in [
        ("Raappanan", "Raappana"),
        ("Alatalon", "Alatalo"),
        ("Tammisen", "Tamminen"),
        ("Jukka-pojan", "Jukka Poika"),
        ("Maapallon", "Maapallo"),
        ("Ruuhkaan", "Ruuhka"),
        ("Virtasen", "Virtanen"),
    ]:
        assert spotify_commands._spotify_name_match_score(spoken, result_name) >= 0.96


def test_spotify_raappana_maapallo_inflections_and_wrong_artists(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"tracks": {"items": [{"name": "Maapallo", "uri": "spotify:track:maapallo", "artists": [{"name": "Raappana"}]}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    for command in [
        "Soita Raappana Maapallo",
        "Soita Raappanan Maapallo",
        "Soita Raappanan Maapallon",
    ]:
        assert spotify_commands.handle_spotify_command(command) == "Soitan Raappanan kappaleen Maapallo."

    assert spotify_commands.handle_spotify_command("Soitan maapallo") == "Soitan Spotifystä: Maapallo."
    assert calls == ["spotify:track:maapallo"] * 4

    for command, requested_artist in [
        ("Soitan Jukka-pojan maapallo", "Jukka Poika"),
        ("Soita jukka-poika maapallo", "Jukka Poika"),
        ("Soita metallika maapallo", "Metallika"),
    ]:
        assert spotify_commands.handle_spotify_command(command) == (
            f"En löytänyt artistilta {requested_artist} kappaletta Maapallo. "
            "Löysin sen artistilta Raappana. Soitanko sen?"
        )
        assert spotify_commands.handle_spotify_command("ei") == "Selvä, en soita sitä."

    assert calls == ["spotify:track:maapallo"] * 4


def test_spotify_heavily_distorted_artist_and_track_variants_ask_confirmation(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"tracks": {"items": [{"name": "Hopeinen kuu", "uri": "spotify:track:hopeinen", "artists": [{"name": "Mikko Alatalo"}]}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    commands = [
        "Suoita Mikko-Ala-Talon hopeinen kuuluu",
        "Suoita Mikko Alatalo, hopeinen kuuluu",
        "Soita Mikko Alatalon hopeinin kuulu",
        "Soitan Mikko ala täällä hopeinen kuulu",
    ]
    for command in commands[:-1]:
        assert spotify_commands.handle_spotify_command(command) == "Tarkoititko Mikko Alatalon kappaletta Hopeinen kuu?"
        assert spotify_commands.handle_spotify_command("ei") == "Selvä, en soita sitä."
    assert spotify_commands.handle_spotify_command(commands[-1]) == "Tarkoititko Mikko Alatalon kappaletta Hopeinen kuu?"
    assert spotify_commands.handle_spotify_command("juuri se") == "Soitan Mikko Alatalon kappaleen Hopeinen kuu."
    assert calls == ["spotify:track:hopeinen"]


def test_spotify_alternative_artist_track_can_be_confirmed_or_rejected(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"tracks": {"items": [{"name": "Hopeinen kuu", "uri": "spotify:track:hopeinen", "artists": [{"name": "Olavi Virta"}]}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    proposal = (
        "En löytänyt artistilta Arto Tamminen kappaletta Hopeinen kuu. "
        "Löysin sen artistilta Olavi Virta. Soitanko sen?"
    )
    assert spotify_commands.handle_spotify_command("Soita Arto Tamminen, Hopeinen kuu") == proposal
    assert spotify_commands._pending_spotify_search_result.confirmation_type == "alternative_artist_track"
    assert spotify_commands.handle_spotify_command("kyllä soita") == "Soitan kappaleen Hopeinen kuu, esittäjänä Olavi Virta."
    assert calls == ["spotify:track:hopeinen"]
    assert spotify_commands._pending_spotify_search_result is None

    assert spotify_commands.handle_spotify_command("Soita Arto Tamminen, Hopeinen kuu") == proposal
    assert spotify_commands.handle_spotify_command("ei sitä") == "Selvä, en soita sitä."
    assert calls == ["spotify:track:hopeinen"]
    assert spotify_commands._pending_spotify_search_result is None


def test_spotify_alternative_artist_track_uses_single_track_fallback_search(monkeypatch):
    from spotify import spotify_commands

    calls = []
    alternative = {"tracks": {"items": [{"name": "Hopeinen kuu", "uri": "spotify:track:hopeinen", "artists": [{"name": "Olavi Virta"}]}]}}

    def fake_search(query, types="track,artist,playlist", limit=5):
        calls.append((query, types, limit))
        return alternative if query == "hopeinen kuu" and types == "track" else {}

    monkeypatch.setattr(spotify_commands.spotify_client, "search", fake_search)

    assert (
        spotify_commands.handle_spotify_command("Soita Arto Tammisen Hopeinen kuu")
        == "En löytänyt artistilta Arto Tamminen kappaletta Hopeinen kuu. Löysin sen artistilta Olavi Virta. Soitanko sen?"
    )
    assert calls == [
        ("arto tammisen hopeinen kuu", "track", 5),
        ("hopeinen kuu", "track", 5),
    ]


def test_spotify_alternative_artist_track_allows_close_track_name(monkeypatch):
    from spotify import spotify_commands

    result = {"tracks": {"items": [{"name": "Hopeinen kuu", "uri": "spotify:track:hopeinen", "artists": [{"name": "Olavi Virta"}]}]}}
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)

    assert (
        spotify_commands.handle_spotify_command("Soita Arto Tamminen, Hopeinen ku")
        == "En löytänyt artistilta Arto Tamminen kappaletta Hopeinen kuu. Löysin sen artistilta Olavi Virta. Soitanko sen?"
    )


def test_spotify_artist_or_track_speech_error_asks_confirmation(monkeypatch):
    from spotify import spotify_commands

    calls = []
    result = {"tracks": {"items": [{"name": "Neljän ruuhka", "uri": "spotify:track:neljan", "artists": [{"name": "Arto Tamminen"}]}]}}
    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: result)
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append(uri))

    assert spotify_commands.handle_spotify_command("Soita Arto Tammine, neljän ruuhka") == "Tarkoititko Arto Tammisen kappaletta Neljän ruuhka?"
    assert spotify_commands.handle_spotify_command("kyllä") == "Soitan Arto Tammisen kappaleen Neljän ruuhka."
    assert spotify_commands.handle_spotify_command("Soita Arto Tamminen, neljän ruuka") == "Tarkoititko Arto Tammisen kappaletta Neljän ruuhka?"
    assert spotify_commands.handle_spotify_command("juu") == "Soitan Arto Tammisen kappaleen Neljän ruuhka."
    assert calls == ["spotify:track:neljan", "spotify:track:neljan"]


def test_spotify_search_play_reports_missing_result(monkeypatch):
    from spotify import spotify_commands

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: {})

    assert (
        spotify_commands.handle_spotify_command("soita dark technoa")
        == "En löytänyt Spotifystä riittävän tarkkaa osumaa haulle dark technoa."
    )


def test_spotify_uncertain_volume_adjustment_confirmation(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "get_current_playback", lambda: {"device": {"volume_percent": 60}})
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )

    assert spotify_commands.handle_spotify_command("paita kovempaa") == "Tarkoititko laittaa musiikkia kovemmalle?"
    assert spotify_commands.handle_spotify_command("kyllä") == "Volume 70"
    assert spotify_commands.handle_spotify_command("paita hiljempaa") == "Tarkoititko laittaa musiikkia hiljemmalle?"
    assert spotify_commands.handle_spotify_command("yllä") == "Volume 50"
    assert calls == [(70, "seesam-id"), (50, "seesam-id")]


def test_spotify_uncertain_volume_adjustment_can_be_cancelled(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "set_volume", lambda percent, device_id=None: calls.append(percent))

    assert spotify_commands.handle_spotify_command("paita kovempaa") == "Tarkoititko laittaa musiikkia kovemmalle?"
    assert spotify_commands.handle_spotify_command("ei") == "Selvä, en tehnyt muutoksia."
    assert calls == []


def test_spotify_yes_without_pending_does_not_start_playback(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append("play"))
    monkeypatch.setattr(spotify_commands.spotify_client, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_off", lambda: calls.append("speaker_power_off"))

    assert spotify_commands.handle_spotify_command("kyllä") is None
    assert calls == []


def test_spotify_volume_regressions_after_confirmation_guard(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "get_current_playback", lambda: {"device": {"volume_percent": 60}})
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: calls.append(("transfer", device_id, play)))
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))
    monkeypatch.setattr(spotify_commands.spotify_client, "set_volume", lambda percent, device_id=None: calls.append(("volume", percent, device_id)))

    assert spotify_commands.handle_spotify_command("laita spotify päälle") == "Soitan Spotifystä."
    assert spotify_commands.handle_spotify_command("laita vähän hiljempaa") == "Volume 50"
    assert calls == [("transfer", "seesam-id", False), ("play", "seesam-id"), ("volume", 50, "seesam-id")]


def test_spotify_volume_phrase_variants(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )

    assert spotify_commands.handle_spotify_command("spotify ääni 80") == "Volume 80"
    assert spotify_commands.handle_spotify_command("musiikki hiljemmalle") == "Volume 50"
    assert spotify_commands.handle_spotify_command("musiikki kovemmalle") == "Volume 90"
    assert calls == [(80, "seesam-id"), (50, "seesam-id"), (90, "seesam-id")]


def test_spotify_volume_speech_adjustments_use_current_volume(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(spotify_commands.spotify_client, "get_current_playback", lambda: {"device": {"volume_percent": 60}})
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("volume command must not search")),
    )

    for command in [
        "laita vähän iljenpä",
        "laita vähän hiljenpää",
        "laita vähän hiljempaa",
        "Laita hiukan hiljempaa.",
        "Laita hieman hiljempaa.",
        "Laita vähän hiljempaan.",
        "Laita vähän hiljemppoa.",
        "Pistä voluma vähän hiljemppoa.",
        "pienennä volumea",
        "pienen volumea",
        "pistä musiikkia hiljemmalle",
        "laita vielä hiljempaa",
        "vielä hiljempaa",
        "hiljempaa",
    ]:
        assert spotify_commands.handle_spotify_command(command) == "Volume 50"

    for command in ["lisää volumea", "laita kovemmalle", "pistä musiikkia kovemmalle", "laita vähän kovempaa", "laita vielä kovempaa", "vielä kovempaa", "kovempaa"]:
        assert spotify_commands.handle_spotify_command(command) == "Volume 70"

    assert spotify_commands.handle_spotify_command("Laita hieman paa.") == "Tarkoititko säätää äänenvoimakkuutta?"
    assert spotify_commands.handle_spotify_command("Laita vähinkö vähämpää.") == "Tarkoititko laittaa musiikkia hiljemmalle?"

    assert calls == [(50, "seesam-id")] * 14 + [(70, "seesam-id")] * 7


def test_spotify_unclear_volume_word_does_not_skip_track(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands.spotify_client, "next_track", lambda: calls.append("next"))
    monkeypatch.setattr(spotify_commands.spotify_client, "previous_track", lambda: calls.append("previous"))

    assert spotify_commands.handle_spotify_command("iljenpä") is None
    assert spotify_commands.handle_spotify_command("seuraava") == "Seuraava kappale."
    assert spotify_commands.handle_spotify_command("edellinen") == "Edellinen kappale."
    assert calls == ["next", "previous"]


def test_spotify_volume_percent_speech_variants(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )

    assert spotify_commands.handle_spotify_command("volume 30") == "Volume 30"
    assert spotify_commands.handle_spotify_command("ääni 40") == "Volume 40"
    assert spotify_commands.handle_spotify_command("musiikki 50 prosenttia") == "Volume 50"
    assert spotify_commands.handle_spotify_command("Laitan volume 50.") == "Volume 50"

    assert calls == [(30, "seesam-id"), (40, "seesam-id"), (50, "seesam-id"), (50, "seesam-id")]


def test_spotify_search_still_handles_genre_after_volume_phrases(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands, "ensure_speakers_powered_on", lambda: calls.append("speaker_power_on"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "search",
        lambda query, types="track,artist,playlist", limit=5: calls.append((query, types, limit))
        or {"playlists": {"items": [{"uri": "spotify:playlist:jazz"}]}},
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "transfer_playback", lambda device_id, play=False: None)
    monkeypatch.setattr(spotify_commands.spotify_client, "play_uri", lambda uri, device_id=None: calls.append((uri, device_id)))

    assert spotify_commands.handle_spotify_command("soita jazzia") == "Soitan Spotifystä: jazzia."
    assert calls == [("jazzia", "playlist,track", 5), "speaker_power_on", ("spotify:playlist:jazz", "seesam-id")]


def test_spotify_client_search_and_play_uri_use_web_api(monkeypatch):
    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient
    from spotify import spotify_client

    calls = []

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(SpotifyClient, "_request", lambda self, method, path, query=None, body=None, retry_auth=True: calls.append((method, path, query, body)))

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))
    client.search("dark technoa", types="playlist,track", limit=5)
    client.play_uri("spotify:track:fine", device_id="seesam-id")
    client.play_uri("spotify:playlist:dark", device_id="seesam-id")

    assert calls == [
        ("GET", "/search", {"q": "dark technoa", "type": "playlist,track", "limit": "5"}, None),
        ("PUT", "/me/player/play", {"device_id": "seesam-id"}, {"uris": ["spotify:track:fine"]}),
        ("PUT", "/me/player/play", {"device_id": "seesam-id"}, {"context_uri": "spotify:playlist:dark"}),
    ]


def test_spotify_client_transfer_playback_uses_player_endpoint(monkeypatch):
    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient
    from spotify import spotify_client

    calls = []

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(SpotifyClient, "_request", lambda self, method, path, query=None, body=None, retry_auth=True: calls.append((method, path, query, body)))

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))
    client.transfer_playback("seesam-id", play=False)
    client.set_volume(80, device_id="seesam-id")

    assert calls == [
        ("PUT", "/me/player", None, {"device_ids": ["seesam-id"], "play": False}),
        ("PUT", "/me/player/volume", {"volume_percent": "80", "device_id": "seesam-id"}, None),
    ]


def test_spotify_client_returns_none_for_204(monkeypatch):
    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient
    from spotify import spotify_client

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b""

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(spotify_client.urllib.request, "urlopen", lambda request, timeout=15: FakeResponse())

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))

    assert client.get_current_playback() is None


def test_spotify_client_returns_none_for_whitespace_response(monkeypatch):
    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient
    from spotify import spotify_client

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"  "

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(spotify_client.urllib.request, "urlopen", lambda request, timeout=15: FakeResponse())

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))

    assert client.get_current_playback() is None


def test_spotify_client_ignores_non_json_write_response(monkeypatch):
    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient
    from spotify import spotify_client

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"ok ok"

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(spotify_client.urllib.request, "urlopen", lambda request, timeout=15: FakeResponse())

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))

    assert client.play("seesam-id") is None


def test_spotify_client_reports_status_and_body_for_invalid_get_json(monkeypatch):
    import pytest

    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient, SpotifyClientError
    from spotify import spotify_client

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"not json"

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(spotify_client.urllib.request, "urlopen", lambda request, timeout=15: FakeResponse())

    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))

    with pytest.raises(SpotifyClientError) as error:
        client.get_current_playback()

    assert "Spotify API error 200: invalid JSON response" in str(error.value)
    assert "response=not json" in str(error.value)
    assert "access" not in str(error.value)


def test_spotify_client_maps_no_active_device_reason_before_premium(monkeypatch):
    import io
    from urllib.error import HTTPError

    import pytest

    from spotify.spotify_auth import SpotifyAuthConfig
    from spotify.spotify_client import SpotifyClient, SpotifyNoActiveDeviceError
    from spotify import spotify_client

    def fail(request, timeout=15):
        payload = b'{"error":{"status":403,"reason":"NO_ACTIVE_DEVICE","message":"No active device"}}'
        raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(payload))

    monkeypatch.setattr(spotify_client, "get_valid_token", lambda config: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(spotify_client.urllib.request, "urlopen", fail)
    client = SpotifyClient(SpotifyAuthConfig(client_id="client", token_path=Path("token.json")))

    with pytest.raises(SpotifyNoActiveDeviceError):
        client.play()
