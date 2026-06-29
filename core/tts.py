"""Text-to-speech integration for Seesam."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_TTS_ENGINE = "piper"
DEFAULT_TTS_MODEL = "/home/marko/piper-models/fi_FI-harri-medium.onnx"
DEFAULT_TTS_PIPER_BIN = "piper"


def is_tts_enabled() -> bool:
    """Return whether text-to-speech should be used for responses."""
    return os.environ.get("TTS_ENABLED", "false").strip().casefold() == "true"


def speak(text: str) -> None:
    """Speak text aloud with Piper and aplay when TTS is enabled.

    TTS failures are intentionally swallowed so terminal chat keeps working even
    if Piper, the model file, or audio playback is unavailable.
    """
    if not is_tts_enabled() or not text.strip():
        return

    engine = os.environ.get("TTS_ENGINE", DEFAULT_TTS_ENGINE).strip().casefold()
    if engine != "piper":
        return

    model = os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL).strip()
    piper_bin = os.environ.get("TTS_PIPER_BIN", DEFAULT_TTS_PIPER_BIN).strip()
    if not model or not piper_bin:
        return

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = Path(wav_file.name)

        try:
            subprocess.run(
                [piper_bin, "--model", model, "--output_file", str(wav_path)],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["aplay", str(wav_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            wav_path.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError):
        return
