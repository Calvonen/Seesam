"""HTTP API for the Seesam assistant."""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from core.brain import Brain
from core.specs import collect_system_specs
from core.status import StatusCollector
from core.system_status import SystemStatus
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
    specs_collector=collect_system_specs,
    system_status: SystemStatus | None = None,
) -> FastAPI:
    """Create the FastAPI app, optionally using an injected Brain for tests."""
    app = FastAPI(title="Seesam HTTP API")
    app.state.brain = brain
    app.state.status_collector = status_collector or StatusCollector.started_now()
    app.state.specs_collector = specs_collector
    app.state.system_status = system_status or SystemStatus.started_now()

    def get_brain() -> Brain:
        if app.state.brain is None:
            app.state.brain = Brain.from_environment()
        return app.state.brain

    @app.get("/health")
    def health() -> dict[str, object]:
        """Return API health and local server status fields."""
        return app.state.system_status.health()

    @app.get("/status")
    def status() -> dict[str, object]:
        """Return server-only runtime status."""
        return app.state.status_collector.collect()

    @app.get("/system/specs")
    def system_specs() -> dict[str, object]:
        """Return server hardware and OS specifications."""
        return app.state.specs_collector()

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Return Seesam's answer for one chat message."""
        brain = get_brain()
        print(f"[API CHAT RAW] {request.message}")
        status_match = "none"
        if hasattr(brain, "system_status_match_name"):
            status_match = brain.system_status_match_name(request.message)
        print(f"[STATUS MATCH] {status_match}")
        command_name = "none"
        if hasattr(brain, "local_command_name"):
            command_name = brain.local_command_name(request.message) or "none"
        print(f"[LOCAL COMMAND MATCH] {command_name}")
        local_answer = brain.handle_local_command(request.message)
        if local_answer is not None:
            if brain.is_memory_command(request.message):
                print(f"API memory command handled locally: {request.message}")
            elif brain.is_system_status_command(request.message):
                print(f"API system status command handled locally: {request.message}")
            return ChatResponse(answer=local_answer)

        print("API message sent to AI")
        answer = brain.respond_with_ai(request.message)
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
