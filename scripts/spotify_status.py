#!/usr/bin/env python3
"""Print current Spotify playback status."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spotify.spotify_commands import handle_spotify_command


if __name__ == "__main__":
    print(handle_spotify_command("mitä soi"))
