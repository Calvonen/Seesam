"""Text-to-speech integration for Seesam."""

from __future__ import annotations

import os
import re
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


def normalize_for_speech(text: str) -> str:
    """Return text normalized for Finnish text-to-speech only."""
    spoken = text.strip()
    if not spoken:
        return ""

    spoken = spoken.replace("Intel(R)", "Intel").replace("Core(TM)", "Core")
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*GiB\s*/\s*(\d+(?:\.\d+)?)\s*GiB",
        r"\1 gigaa \2 gigasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*GB\s*/\s*(\d+(?:\.\d+)?)\s*GB",
        r"\1 gigaa \2 gigasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*MiB\s*/\s*(\d+(?:\.\d+)?)\s*MiB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*MB\s*/\s*(\d+(?:\.\d+)?)\s*MB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*MiB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*MB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(r"\s*\(([^()]*)\)", r". \1", spoken)

    replacements = [
        (r"\bVRAM\b", "näyttömuisti"),
        (r"\bRAM\b(?!-muisti)", "ram-muisti"),
        (r"\bGPU\b", "näyttis"),
        (r"\bCPU\b", "prosessori"),
        (r"\bIP\b", "ii pee"),
        (r"(?<=\d)\s*kWh\b", " kilowattituntia"),
        (r"(?<=\d)\s*Wh\b", " wattituntia"),
        (r"(?<=\d)\s*GHz\b", " gigahertsiä"),
        (r"(?<=\d)\s*MHz\b", " megahertsiä"),
        (r"(?<=\d)\s*GiB\b", " gigaa"),
        (r"(?<=\d)\s*GB\b", " gigaa"),
        (r"(?<=\d)\s*MiB\b", " megaa"),
        (r"(?<=\d)\s*MB\b", " megaa"),
        (r"(?<=\d)\s*kW\b", " kilowattia"),
        (r"(?<=\d)\s*mA\b", " milliampeeria"),
        (r"(?<=\d)\s*RPM\b", " kierrosta minuutissa"),
        (r"(?<=\d)\s*W\b", " wattia"),
        (r"(?<=\d)\s*V\b", " volttia"),
        (r"(?<=\d)\s*A\b", " ampeeria"),
        (r"(?<=\d)\s*°C\b", " astetta"),
        (r"(?<=\d)\s*°", " astetta"),
        (r"(?<=\d)\s*%", " prosenttia"),
    ]
    for pattern, replacement in replacements:
        spoken = re.sub(pattern, replacement, spoken)

    spoken = re.sub(
        r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b",
        r"\1 piste \2 piste \3 piste \4",
        spoken,
    )
    spoken = re.sub(r"(?<=\d)\.(?=\d)", ",", spoken)
    spoken = re.sub(r"\s*/\s*", " ", spoken)
    spoken = re.sub(r"\s+", " ", spoken)
    spoken = re.sub(r"\s+([.,:;!?])", r"\1", spoken)
    spoken = re.sub(r"\.\s*\.", ".", spoken)
    return spoken.strip()


def is_tts_enabled() -> bool:
    """Return whether text-to-speech should be used for responses."""
    load_env_file()
    return os.environ.get("TTS_ENABLED", "false").strip().casefold() == "true"


def synthesize_wav(text: str) -> bytes:
    """Generate WAV audio bytes with Piper without playing audio."""
    text = text.strip()
    if not text:
        raise TTSError(400, "Text must not be empty.")

    text = normalize_for_speech(text)

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
    text = text.strip()
    if not is_tts_enabled() or not text:
        return

    text = normalize_for_speech(text)

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
