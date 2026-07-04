import base64
import hashlib
import time
from pathlib import Path

from audio.audio_manager import AudioResult, SPEAKERS_SLEEPING_MESSAGE


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
        lambda: AudioResult(True, "Steljes-kaiuttimet yhdistetty."),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "transfer_playback",
        lambda device_id, play=False: calls.append(("transfer", device_id, play)),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append(("play", device_id)))

    assert spotify_commands.handle_spotify_command("soita spotify") == "Soitan Spotifystä."
    assert calls == [("transfer", "seesam-id", False), ("play", "seesam-id")]


def test_spotify_play_stops_when_media_output_fails(monkeypatch):
    from spotify import spotify_commands

    calls = []

    monkeypatch.setattr(
        spotify_commands,
        "ensure_default_media_output",
        lambda: AudioResult(False, SPEAKERS_SLEEPING_MESSAGE),
    )
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: calls.append("devices"))
    monkeypatch.setattr(spotify_commands.spotify_client, "play", lambda device_id=None: calls.append("play"))

    assert spotify_commands.handle_spotify_command("musiikki päälle") == "Kaiuttimet eivät vastaa. Herätä ne Bluetooth-tilaan."
    assert calls == []


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
    monkeypatch.setattr(
        commands,
        "ensure_media_output",
        lambda device_id=None: audio_manager.AudioResult(True, "Steljes-kaiuttimet yhdistetty."),
    )

    assert commands.handle_local_command("kaiuttimet päälle") == "Steljes-kaiuttimet yhdistetty."


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

    monkeypatch.setattr(spotify_commands, "ensure_default_media_output", lambda: AudioResult(True, "ok"))
    monkeypatch.setattr(spotify_commands.spotify_client, "get_available_devices", lambda: [{"id": "seesam-id", "name": "Seesam"}])
    monkeypatch.setattr(
        spotify_commands.spotify_client,
        "set_volume",
        lambda percent, device_id=None: calls.append((percent, device_id)),
    )

    assert spotify_commands.handle_spotify_command("spotify volume 80") == "Musiikin äänenvoimakkuus 80 prosenttia."
    assert spotify_commands.handle_spotify_command("musiikki ääni 90") == "Musiikin äänenvoimakkuus 90 prosenttia."
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

    for command in [
        "laita spotify päälle",
        "spotify päälle",
        "soita spotify",
        "toista spotify",
        "musiikki päälle",
        "soita musiikkia",
        "jatka musiikkia",
        "jatka spotify",
        "jatka",
        "toista",
    ]:
        assert spotify_commands.handle_spotify_command(command) == "Soitan Spotifystä."

    assert len(calls) == 20


def test_spotify_pause_next_previous_and_status_intents(monkeypatch):
    from spotify import spotify_commands

    calls = []

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

    assert spotify_commands.handle_spotify_command("spotify ääni 80") == "Musiikin äänenvoimakkuus 80 prosenttia."
    assert spotify_commands.handle_spotify_command("musiikki hiljemmalle") == "Musiikin äänenvoimakkuus 50 prosenttia."
    assert spotify_commands.handle_spotify_command("musiikki kovemmalle") == "Musiikin äänenvoimakkuus 90 prosenttia."
    assert calls == [(80, "seesam-id"), (50, "seesam-id"), (90, "seesam-id")]


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
