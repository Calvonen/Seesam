#!/usr/bin/env python3
"""Start Spotify PKCE login and store a local token."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spotify.spotify_auth import login_with_local_callback


if __name__ == "__main__":
    login_with_local_callback(open_browser=False)
