"""Placeholder for future speech-to-text integration."""

from __future__ import annotations


class SpeechRecognizer:
    """Future adapter for local speech recognition engines such as Whisper."""

    def listen(self) -> str:
        """Return recognized speech when speech input support is implemented."""
        raise NotImplementedError("Speech recognition is not implemented yet.")
