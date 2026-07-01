"""Speech-to-text integration for Seesam."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from core.config import load_env_file

DEFAULT_STT_ENGINE = "faster-whisper"
DEFAULT_STT_MODEL = "small"
DEFAULT_STT_LANGUAGE = "fi"
DEFAULT_STT_DEVICE = "cpu"
DEFAULT_STT_COMPUTE_TYPE = "int8"

_WHISPER_MODEL: Any | None = None
_WHISPER_MODEL_CONFIG: tuple[str, str, str] | None = None


class STTError(Exception):
    """HTTP-safe speech-to-text error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_stt_enabled() -> bool:
    """Return whether speech-to-text should be used."""
    load_env_file()
    return os.environ.get("STT_ENABLED", "false").strip().casefold() == "true"


def _load_faster_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    """Load and cache the configured faster-whisper model."""
    global _WHISPER_MODEL, _WHISPER_MODEL_CONFIG

    model_config = (model_name, device, compute_type)
    if _WHISPER_MODEL is not None and _WHISPER_MODEL_CONFIG == model_config:
        return _WHISPER_MODEL

    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise STTError(
            503,
            "faster-whisper is not installed. Install project requirements to enable STT.",
        ) from error

    try:
        _WHISPER_MODEL = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
        _WHISPER_MODEL_CONFIG = model_config
        return _WHISPER_MODEL
    except Exception as error:
        raise STTError(
            503,
            "Whisper model missing or unavailable. "
            f"STT_MODEL is set to '{model_name}', "
            f"STT_DEVICE is set to '{device}', "
            f"and STT_COMPUTE_TYPE is set to '{compute_type}'.",
        ) from error


def transcribe_audio(audio: bytes, filename: str | None = None) -> str:
    """Transcribe uploaded audio bytes and return plain text."""
    if not audio:
        raise STTError(400, "Audio file must not be empty.")

    if not is_stt_enabled():
        raise STTError(
            503,
            "STT is disabled. Set STT_ENABLED=true to enable speech transcription.",
        )

    engine = os.environ.get("STT_ENGINE", DEFAULT_STT_ENGINE).strip().casefold()
    if engine != "faster-whisper":
        raise STTError(503, "Only faster-whisper speech-to-text is supported.")

    model_name = os.environ.get("STT_MODEL", DEFAULT_STT_MODEL).strip()
    if not model_name:
        raise STTError(
            503,
            "Whisper model is not configured. Set STT_MODEL to a faster-whisper model name or local model path.",
        )

    language = os.environ.get("STT_LANGUAGE", DEFAULT_STT_LANGUAGE).strip() or DEFAULT_STT_LANGUAGE
    device = os.environ.get("STT_DEVICE", DEFAULT_STT_DEVICE).strip() or DEFAULT_STT_DEVICE
    compute_type = (
        os.environ.get("STT_COMPUTE_TYPE", DEFAULT_STT_COMPUTE_TYPE).strip()
        or DEFAULT_STT_COMPUTE_TYPE
    )
    model = _load_faster_whisper_model(model_name, device, compute_type)

    suffix = Path(filename or "").suffix or ".audio"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
            audio_path = Path(audio_file.name)
            audio_file.write(audio)

        try:
            segments, _info = model.transcribe(str(audio_path), language=language)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
            return text.strip()
        finally:
            audio_path.unlink(missing_ok=True)
    except STTError:
        raise
    except Exception as error:
        raise STTError(
            500,
            f"Whisper transcription failed while processing uploaded audio: {error}",
        ) from error
