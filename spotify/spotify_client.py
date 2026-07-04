"""Small Spotify Web API client for Seesam media playback."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from spotify.spotify_auth import SpotifyAuthConfig, get_valid_token, load_config, refresh_access_token

API_BASE = "https://api.spotify.com/v1"
NO_ACTIVE_DEVICE_MESSAGE = "Spotify-laitetta ei löytynyt. Avaa Spotify kerran puhelimesta tai koneelta."
PREMIUM_REQUIRED_MESSAGE = "Spotify-toiston ohjaus vaatii Premiumin."


class SpotifyClientError(RuntimeError):
    """Base error raised for Spotify Web API failures."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class SpotifyNoActiveDeviceError(SpotifyClientError):
    """Raised when Spotify has no active playback device."""


class SpotifyPremiumRequiredError(SpotifyClientError):
    """Raised when Spotify refuses playback control for account/scope reasons."""


class SpotifyClient:
    def __init__(self, config: SpotifyAuthConfig | None = None):
        self.config = config or load_config()

    def get_current_playback(self) -> dict[str, Any] | None:
        return self._request("GET", "/me/player")

    def get_currently_playing(self) -> dict[str, Any] | None:
        return self._request("GET", "/me/player/currently-playing")

    def get_available_devices(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/me/player/devices") or {}
        return list(data.get("devices") or [])

    def play(self, device_id: str | None = None) -> None:
        query = {"device_id": device_id} if device_id else None
        self._request("PUT", "/me/player/play", query=query)

    def play_uri(self, uri: str, device_id: str | None = None) -> None:
        query = {"device_id": device_id} if device_id else None
        body = {"uris": [uri]} if uri.startswith("spotify:track:") else {"context_uri": uri}
        self._request("PUT", "/me/player/play", query=query, body=body)

    def transfer_playback(self, device_id: str, play: bool = False) -> None:
        self._request("PUT", "/me/player", body={"device_ids": [device_id], "play": play})

    def pause(self) -> None:
        self._request("PUT", "/me/player/pause")

    def next_track(self) -> None:
        self._request("POST", "/me/player/next")

    def previous_track(self) -> None:
        self._request("POST", "/me/player/previous")

    def set_volume(self, percent: int, device_id: str | None = None) -> None:
        volume = max(0, min(100, int(percent)))
        query = {"volume_percent": str(volume)}
        if device_id:
            query["device_id"] = device_id
        self._request("PUT", "/me/player/volume", query=query)

    def search(self, query: str, types: str = "track,artist,playlist", limit: int = 5) -> dict[str, Any]:
        return self._request(
            "GET",
            "/search",
            query={"q": query, "type": types, "limit": str(limit)},
        ) or {}

    def _request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        token = get_valid_token(self.config)
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status == 204:
                    return None
                raw = response.read().decode("utf-8", errors="replace")
                return _parse_success_body(response.status, raw, method)
        except urllib.error.HTTPError as error:
            if error.code == 401 and retry_auth:
                refresh_access_token(self.config, str(token["refresh_token"]))
                return self._request(method, path, query, body, retry_auth=False)
            payload, response_text = _read_error_payload(error)
            message = _extract_error_message(payload)
            if error.code == 404 or "NO_ACTIVE_DEVICE" in message.upper():
                raise SpotifyNoActiveDeviceError(NO_ACTIVE_DEVICE_MESSAGE, error.code, payload) from error
            if error.code == 403:
                raise SpotifyPremiumRequiredError(PREMIUM_REQUIRED_MESSAGE, error.code, payload) from error
            detail = _format_error_detail(error.code, message, response_text)
            raise SpotifyClientError(detail, error.code, payload) from error
        except OSError as error:
            raise SpotifyClientError(f"Spotify API request failed: {error}") from error


def get_current_playback() -> dict[str, Any] | None:
    return SpotifyClient().get_current_playback()


def get_currently_playing() -> dict[str, Any] | None:
    return SpotifyClient().get_currently_playing()


def get_available_devices() -> list[dict[str, Any]]:
    return SpotifyClient().get_available_devices()


def play(device_id: str | None = None) -> None:
    SpotifyClient().play(device_id)


def play_uri(uri: str, device_id: str | None = None) -> None:
    SpotifyClient().play_uri(uri, device_id)


def transfer_playback(device_id: str, play: bool = False) -> None:
    SpotifyClient().transfer_playback(device_id, play)


def pause() -> None:
    SpotifyClient().pause()


def next_track() -> None:
    SpotifyClient().next_track()


def previous_track() -> None:
    SpotifyClient().previous_track()


def set_volume(percent: int, device_id: str | None = None) -> None:
    SpotifyClient().set_volume(percent, device_id)


def search(query: str, types: str = "track,artist,playlist", limit: int = 5) -> dict[str, Any]:
    return SpotifyClient().search(query, types, limit)


def _parse_success_body(status: int, raw: str, method: str) -> Any:
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        if method in {"PUT", "POST", "DELETE"}:
            return None
        raise SpotifyClientError(
            _format_error_detail(status, "invalid JSON response", raw),
            status,
            {"response_text": _short_text(raw)},
        ) from error


def _read_error_payload(error: urllib.error.HTTPError) -> tuple[Any, str]:
    raw = error.read().decode("utf-8", errors="replace")
    try:
        return (json.loads(raw), raw) if raw.strip() else ({}, raw)
    except json.JSONDecodeError:
        return {"error": {"message": _short_text(raw)}}, raw


def _format_error_detail(status: int, message: str, response_text: str) -> str:
    detail = f"Spotify API error {status}: {message}"
    short = _short_text(response_text)
    if short:
        detail += f". response={short}"
    return detail


def _short_text(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("reason") or error.get("message") or payload)
        if isinstance(error, str):
            return error
    return str(payload)
