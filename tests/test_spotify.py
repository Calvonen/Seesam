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

    for command in ["sammuta potify", "samuta spotify", "sammuta spotivy"]:
        assert commands.handle_local_command(command) == "Sammutin Spotifyn."

    assert calls == ["pause", "speaker_power_off"] * 3


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
        ("soita jukka poika", "jukka poika", "track,artist,playlist", "spotify:track:jukka"),
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


def test_spotify_search_play_reports_missing_result(monkeypatch):
    from spotify import spotify_commands

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "search", lambda query, types="track,artist,playlist", limit=5: {})

    assert (
        spotify_commands.handle_spotify_command("soita dark technoa")
        == "Spotify-hakutulosta ei löytynyt haulle dark technoa."
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

    for command in [
        "laita vähän iljenpä",
        "laita vähän hiljenpää",
        "laita vähän hiljempaa",
        "pienennä volumea",
        "pienen volumea",
        "pistä musiikkia hiljemmalle",
    ]:
        assert spotify_commands.handle_spotify_command(command) == "Volume 50"

    for command in ["lisää volumea", "laita kovemmalle", "pistä musiikkia kovemmalle"]:
        assert spotify_commands.handle_spotify_command(command) == "Volume 70"

    assert calls == [(50, "seesam-id")] * 6 + [(70, "seesam-id")] * 3


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

    assert calls == [(30, "seesam-id"), (40, "seesam-id"), (50, "seesam-id")]


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
    assert calls == ["speaker_power_on", ("jazzia", "playlist,track", 5), ("spotify:playlist:jazz", "seesam-id")]


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
