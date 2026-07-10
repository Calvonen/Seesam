"""Manage one push-to-talk recording and its background processing."""
from __future__ import annotations
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Protocol

class BrainLike(Protocol):
    def respond(self, text: str) -> str: ...

class ListenSession:
    def __init__(self, brain_getter: Callable[[], BrainLike], transcribe: Callable[[bytes, str | None], str], speak: Callable[[str], None], popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self._brain_getter, self._transcribe, self._speak, self._popen = brain_getter, transcribe, speak, popen
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._audio_path: Path | None = None
        self._processing = False
        self._last_transcript: str | None = None
        self._last_answer: str | None = None

    def start(self) -> str:
        with self._lock:
            if self._process is not None:
                return "already_listening"
            with tempfile.NamedTemporaryFile(prefix="seesam-listen-", suffix=".wav", delete=False) as file:
                audio_path = Path(file.name)
            try:
                process = self._popen(["arecord", "-D", "hw:0,0", "-f", "S16_LE", "-r", "48000", "-c", "2", str(audio_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                audio_path.unlink(missing_ok=True)
                raise
            self._process, self._audio_path = process, audio_path
            return "listening_started"

    def stop(self) -> str:
        with self._lock:
            if self._process is None or self._audio_path is None:
                return "not_listening"
            process, audio_path = self._process, self._audio_path
            self._process, self._audio_path, self._processing = None, None, True
        threading.Thread(target=self._finish_recording, args=(process, audio_path), name="seesam-listen-processing", daemon=True).start()
        return "listen_stopped_processing"

    def status(self) -> dict[str, object]:
        with self._lock:
            return {"listening": self._process is not None, "processing": self._processing, "last_transcript": self._last_transcript, "last_answer": self._last_answer}

    def _finish_recording(self, process: subprocess.Popen, audio_path: Path) -> None:
        try:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            transcript = self._transcribe(audio_path.read_bytes(), audio_path.name)
            answer = self._brain_getter().respond(transcript)
            with self._lock:
                self._last_transcript, self._last_answer = transcript, answer
            self._speak(answer)
        finally:
            audio_path.unlink(missing_ok=True)
            with self._lock:
                self._processing = False
