#!/usr/bin/env python3
"""Test the configured media audio output."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio.audio_manager import ensure_default_media_output


def main() -> int:
    result = ensure_default_media_output()
    print(result.message)
    if result.sink_id:
        print(f"sink_id={result.sink_id}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
