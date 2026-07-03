"""Spotify Authorization Code with PKCE helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).with_name("spotify_config.local.json")
EXAMPLE_CONFIG_PATH = Path(__file__).with_name("spotify_config.example.json")
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "data" / "spotify_token.local.json"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-private",
    "playlist-read-private",
    "playlist-read-collaborative",
]


@dataclass(frozen=True)
class SpotifyAuthConfig:
    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    token_path: Path = DEFAULT_TOKEN_PATH


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify authentication cannot continue."""


def load_config(path: Path = CONFIG_PATH) -> SpotifyAuthConfig:
    """Load local Spotify auth config without requiring secrets in the environment."""
    if not path.exists():
        raise SpotifyAuthError(
            f"Spotify config missing: {path}. Copy {EXAMPLE_CONFIG_PATH} and set client_id."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpotifyAuthError(f"Spotify config could not be loaded: {error}") from error

    client_id = str(data.get("client_id") or "").strip()
    if not client_id or client_id == "YOUR_SPOTIFY_CLIENT_ID":
        raise SpotifyAuthError("Spotify client_id puuttuu paikallisesta konfigista.")

    redirect_uri = str(data.get("redirect_uri") or DEFAULT_REDIRECT_URI).strip()
    token_path = _resolve_project_path(data.get("token_path") or DEFAULT_TOKEN_PATH)
    return SpotifyAuthConfig(client_id=client_id, redirect_uri=redirect_uri, token_path=token_path)


def generate_code_verifier(length: int = 64) -> str:
    """Generate a PKCE code verifier."""
    if length < 43 or length > 128:
        raise ValueError("PKCE code verifier length must be between 43 and 128 characters.")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_code_challenge(code_verifier: str) -> str:
    """Return the S256 PKCE challenge for a verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_login_url(config: SpotifyAuthConfig, code_verifier: str, state: str | None = None) -> str:
    """Build a Spotify authorization URL for Authorization Code with PKCE."""
    query = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": generate_code_challenge(code_verifier),
        "state": state or secrets.token_urlsafe(16),
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(query)


def print_login_url(open_browser: bool = False, config_path: Path = CONFIG_PATH) -> tuple[SpotifyAuthConfig, str, str]:
    """Print the login URL and return config, verifier and state for manual flows."""
    config = load_config(config_path)
    code_verifier = generate_code_verifier()
    state = secrets.token_urlsafe(16)
    login_url = build_login_url(config, code_verifier, state)
    print(login_url)
    if open_browser:
        webbrowser.open(login_url)
    return config, code_verifier, state


def login_with_local_callback(open_browser: bool = False, config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Run a localhost callback server, complete PKCE auth, and store tokens."""
    config = load_config(config_path)
    code_verifier = generate_code_verifier()
    state = secrets.token_urlsafe(16)
    login_url = build_login_url(config, code_verifier, state)
    print("Avaa tämä Spotify-kirjautumisosoite:")
    print(login_url)
    if open_browser:
        webbrowser.open(login_url)

    code = wait_for_callback(config.redirect_uri, state)
    token = exchange_code_for_token(config, code, code_verifier)
    save_token(token, config.token_path)
    print(f"Spotify-token tallennettu: {config.token_path}")
    return token


def wait_for_callback(redirect_uri: str, expected_state: str) -> str:
    """Wait for one Spotify redirect on the redirect URI host and port."""
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8888
    callback_path = parsed.path or "/callback"
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            request_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(request_url.query)
            if request_url.path != callback_path:
                self._respond(404, "Not found")
                return
            if params.get("state", [""])[0] != expected_state:
                result["error"] = "Spotify state mismatch."
                self._respond(400, "Spotify state mismatch. You can close this window.")
                return
            if "error" in params:
                result["error"] = params["error"][0]
                self._respond(400, "Spotify login failed. You can close this window.")
                return
            result["code"] = params.get("code", [""])[0]
            self._respond(200, "Spotify login OK. You can close this window.")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _respond(self, status: int, message: str) -> None:
            body = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with HTTPServer((host, port), CallbackHandler) as server:
        while "code" not in result and "error" not in result:
            server.handle_request()

    if "error" in result:
        raise SpotifyAuthError(result["error"])
    return result["code"]


def exchange_code_for_token(config: SpotifyAuthConfig, code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange an auth code for access and refresh tokens."""
    form = {
        "client_id": config.client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "code_verifier": code_verifier,
    }
    return _token_request(form)


def refresh_access_token(config: SpotifyAuthConfig, refresh_token: str) -> dict[str, Any]:
    """Refresh an access token using the stored refresh token."""
    form = {
        "client_id": config.client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    token = _token_request(form)
    if "refresh_token" not in token:
        token["refresh_token"] = refresh_token
    save_token(token, config.token_path)
    return token


def load_token(path: Path = DEFAULT_TOKEN_PATH) -> dict[str, Any]:
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpotifyAuthError(f"Spotify-token puuttuu tai on rikki: {error}") from error
    for key in ("access_token", "refresh_token", "expires_at"):
        if key not in token:
            raise SpotifyAuthError(f"Spotify-tokenista puuttuu {key}.")
    return token


def save_token(token: dict[str, Any], path: Path = DEFAULT_TOKEN_PATH) -> dict[str, Any]:
    """Persist token data with an absolute expiry timestamp."""
    stored = _with_expiry(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stored


def get_valid_token(config: SpotifyAuthConfig | None = None) -> dict[str, Any]:
    """Load a token and refresh it automatically when it has expired."""
    auth_config = config or load_config()
    token = load_token(auth_config.token_path)
    if int(token.get("expires_at", 0)) <= int(time.time()) + 30:
        token = refresh_access_token(auth_config, str(token["refresh_token"]))
    return token


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SpotifyAuthError(f"Spotify token request failed {error.code}: {detail}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise SpotifyAuthError(f"Spotify token request failed: {error}") from error
    return _with_expiry(payload)


def _with_expiry(token: dict[str, Any]) -> dict[str, Any]:
    stored = dict(token)
    if "expires_at" not in stored:
        stored["expires_at"] = int(time.time()) + int(stored.get("expires_in", 3600)) - 30
    return stored


def _resolve_project_path(value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


if __name__ == "__main__":
    login_with_local_callback(open_browser=False)
