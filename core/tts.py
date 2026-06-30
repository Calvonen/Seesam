"""Text-to-speech integration for Seesam."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import load_env_file

DEFAULT_TTS_ENGINE = "piper"
DEFAULT_TTS_MODEL = ""
DEFAULT_TTS_PIPER_BIN = "piper"


class TTSError(Exception):
    """HTTP-safe text-to-speech error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_tts_enabled() -> bool:
    """Return whether text-to-speech should be used for responses."""
    load_env_file()
    return os.environ.get("TTS_ENABLED", "false").strip().casefold() == "true"


def synthesize_wav(text: str) -> bytes:
    """Generate WAV audio bytes with Piper without playing audio."""
    text = text.strip()
    if not text:
        raise TTSError(400, "Text must not be empty.")

    if not is_tts_enabled():
        raise TTSError(
            503,
            "TTS is disabled. Set TTS_ENABLED=true to enable speech synthesis.",
        )

    engine = os.environ.get("TTS_ENGINE", DEFAULT_TTS_ENGINE).strip().casefold()
    if engine != "piper":
        raise TTSError(503, "Only Piper text-to-speech is supported.")

    model = os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL).strip()
    piper_bin = os.environ.get("TTS_PIPER_BIN", DEFAULT_TTS_PIPER_BIN).strip()
    if not model:
        raise TTSError(
            503,
            "Piper model is not configured. Set TTS_MODEL to a local .onnx model file.",
        )
    if not Path(model).is_file():
        raise TTSError(
            503,
            f"Piper model missing. TTS_MODEL points to '{model}', but that file does not exist.",
        )
    if not piper_bin:
        raise TTSError(
            503,
            "Piper binary is not configured. Set TTS_PIPER_BIN to 'piper' or an executable path.",
        )
    piper_path = Path(piper_bin)
    if piper_path.is_absolute() or piper_path.parent != Path("."):
        if not piper_path.is_file():
            raise TTSError(
                503,
                f"Piper binary not found. TTS_PIPER_BIN points to '{piper_bin}', but that file does not exist.",
            )
        piper_command = piper_bin
    else:
        piper_command = shutil.which(piper_bin)
        if piper_command is None:
            raise TTSError(
                503,
                f"Piper binary not found. Could not find '{piper_bin}' on PATH.",
            )

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = Path(wav_file.name)

        try:
            subprocess.run(
                [piper_command, "--model", model, "--output_file", str(wav_path)],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return wav_path.read_bytes()
        finally:
            wav_path.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise TTSError(
            500,
            f"Piper synthesis failed while generating WAV audio: {error}",
        ) from error


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
