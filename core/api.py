"""HTTP API for the Seesam assistant."""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from core.brain import Brain
from core.status import StatusCollector
from core import stt, tts


class ChatRequest(BaseModel):
    """Incoming chat request payload."""

    message: str


class ChatResponse(BaseModel):
    """Outgoing chat response payload."""

    answer: str


class SpeakRequest(BaseModel):
    """Incoming speech synthesis request payload."""

    text: str


class TranscribeResponse(BaseModel):
    """Outgoing transcription response payload."""

    text: str


def create_app(
    brain: Brain | None = None,
    status_collector: StatusCollector | None = None,
) -> FastAPI:
    """Create the FastAPI app, optionally using an injected Brain for tests."""
    app = FastAPI(title="Seesam HTTP API")
    app.state.brain = brain
    app.state.status_collector = status_collector or StatusCollector.started_now()

    def get_brain() -> Brain:
        if app.state.brain is None:
            app.state.brain = Brain.from_environment()
        return app.state.brain

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return API health status."""
        return {"status": "ok"}

    @app.get("/status")
    def status() -> dict[str, object]:
        """Return server-only runtime status."""
        return app.state.status_collector.collect()

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Return Seesam's answer for one chat message."""
        answer = get_brain().respond(request.message)
        return ChatResponse(answer=answer)

    @app.post("/speak")
    def speak(request: SpeakRequest) -> Response:
        """Return synthesized speech as WAV audio."""
        try:
            audio = tts.synthesize_wav(request.text)
        except tts.TTSError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        return Response(content=audio, media_type="audio/wav")

    @app.post("/transcribe", response_model=TranscribeResponse)
    async def transcribe(file: UploadFile = File(...)) -> TranscribeResponse:
        """Return transcription text for an uploaded audio file."""
        try:
            text = stt.transcribe_audio(await file.read(), file.filename)
        except stt.STTError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        finally:
            await file.close()

        return TranscribeResponse(text=text)

    return app


app = create_app()
