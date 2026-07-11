"""HTTP API for the Seesam assistant."""

from __future__ import annotations

import ipaddress
import subprocess
import threading

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from core.brain import Brain
from core.listen_session import ListenSession
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


class ListenStartResponse(BaseModel):
    """Outgoing listen start acknowledgement payload."""

    ok: bool
    action: str


class ListenStatusResponse(BaseModel):
    listening: bool
    processing: bool
    last_transcript: str | None
    last_answer: str | None
    audio_ready: bool


class ListenUploadResponse(BaseModel):
    ok: bool
    action: str
    transcript: str
    answer: str
    audio_ready: bool


class ShutdownResponse(BaseModel):
    ok: bool
    action: str


def _poweroff() -> None:
    """Power off the host; kept separate so tests can inject a harmless runner."""
    subprocess.run(["sudo", "/usr/bin/systemctl", "poweroff"], check=False)


def _is_local_or_lan_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def create_app(
    brain: Brain | None = None,
    status_collector: StatusCollector | None = None,
    specs_collector=collect_system_specs,
    system_status: SystemStatus | None = None,
    listen_session: ListenSession | None = None,
    shutdown_runner=_poweroff,
    shutdown_delay_seconds: float = 1.0,
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

    app.state.listen_session = listen_session or ListenSession(get_brain, stt.transcribe_audio, tts.synthesize_wav)

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

    @app.post("/system/shutdown", response_model=ShutdownResponse)
    def system_shutdown(request: Request) -> ShutdownResponse:
        """Schedule host shutdown for callers connected from local/LAN networks."""
        client_host = request.client.host if request.client is not None else ""
        if not _is_local_or_lan_address(client_host):
            raise HTTPException(status_code=403, detail="Shutdown is only available from local/LAN networks.")

        timer = threading.Timer(shutdown_delay_seconds, shutdown_runner)
        timer.daemon = True
        timer.start()
        return ShutdownResponse(ok=True, action="shutdown_scheduled")

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: Request) -> ChatResponse:
        """Return Seesam's answer for one chat message."""
        request_body = await request.json()
        if not isinstance(request_body, dict) or not isinstance(request_body.get("message"), str):
            raise HTTPException(
                status_code=422,
                detail="Field 'message' is required and must be a string.",
            )

        chat_request = ChatRequest(**request_body)
        other_fields = {
            key: value
            for key, value in request_body.items()
            if key not in {"message", "history"}
        }
        brain = get_brain()
        print(f"[API CHAT BODY] {request_body}")
        print(f"[API CHAT MESSAGE] {chat_request.message}")
        print(f"[API CHAT HISTORY] {request_body.get('history')}")
        print(f"[API CHAT OTHER FIELDS] {other_fields}")
        local_route = "none"
        if hasattr(brain, "local_route_name"):
            local_route = brain.local_route_name(chat_request.message)
        print(f"[LOCAL ROUTE] {local_route}")

        local_answer = brain.handle_local_command(chat_request.message)
        if local_answer is not None:
            return ChatResponse(answer=local_answer)

        answer = brain.respond_with_ai(chat_request.message)
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

    @app.post("/listen/start", response_model=ListenStartResponse)
    def listen_start() -> ListenStartResponse:
        """Start push-to-talk recording without blocking the request."""
        return ListenStartResponse(ok=True, action=app.state.listen_session.start())

    @app.post("/listen/stop", response_model=ListenStartResponse)
    def listen_stop() -> ListenStartResponse:
        return ListenStartResponse(ok=True, action=app.state.listen_session.stop())

    @app.post("/listen/upload", response_model=ListenUploadResponse)
    async def listen_upload(file: UploadFile = File(...)) -> ListenUploadResponse:
        try:
            transcript, answer = app.state.listen_session.process_audio(await file.read(), file.filename)
        finally:
            await file.close()
        return ListenUploadResponse(ok=True, action="upload_processed", transcript=transcript, answer=answer, audio_ready=True)

    @app.get("/listen/status", response_model=ListenStatusResponse)
    def listen_status() -> ListenStatusResponse:
        return ListenStatusResponse(**app.state.listen_session.status())

    @app.get("/listen/last-audio")
    def listen_last_audio() -> Response:
        audio = app.state.listen_session.get_last_audio()
        if audio is None:
            raise HTTPException(status_code=404, detail="No listen response audio is available.")
        return Response(content=audio, media_type="audio/wav")

    return app


app = create_app()
