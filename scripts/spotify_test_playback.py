#!/usr/bin/env python3
"""Safely test Seesam media output and Spotify play/pause control."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import time

from audio.audio_manager import ensure_default_media_output
from spotify.spotify_client import NO_ACTIVE_DEVICE_MESSAGE, SpotifyClient, SpotifyClientError


if __name__ == "__main__":
    audio = ensure_default_media_output()
    if not audio.success:
        print(audio.message)
        raise SystemExit(1)

    client = SpotifyClient()
    devices = client.get_available_devices()
    print("Spotify devices:")
    for device in devices:
        active = " active" if device.get("is_active") else ""
        print(f"- {device.get('name')} ({device.get('type')}){active}")

    seesam = next((device for device in devices if str(device.get("name") or "").casefold() == "seesam"), None)
    if seesam is None or not seesam.get("id"):
        print(NO_ACTIVE_DEVICE_MESSAGE)
        raise SystemExit(1)

    device_id = str(seesam["id"])
    try:
        client.transfer_playback(device_id, play=False)
        client.play(device_id)
        time.sleep(1)
        client.pause()
        time.sleep(1)
        client.play(device_id)
        print("Spotify transfer/play/pause/play test OK.")
    except SpotifyClientError as error:
        print(str(error))
        raise SystemExit(1)
