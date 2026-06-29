"""HTTP API for the Seesam assistant."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from core.brain import Brain


class ChatRequest(BaseModel):
    """Incoming chat request payload."""

    message: str


class ChatResponse(BaseModel):
    """Outgoing chat response payload."""

    answer: str


def create_app(brain: Brain | None = None) -> FastAPI:
    """Create the FastAPI app, optionally using an injected Brain for tests."""
    app = FastAPI(title="Seesam HTTP API")
    app.state.brain = brain

    def get_brain() -> Brain:
        if app.state.brain is None:
            app.state.brain = Brain.from_environment()
        return app.state.brain

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return API health status."""
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Return Seesam's answer for one chat message."""
        answer = get_brain().respond(request.message)
        return ChatResponse(answer=answer)

    return app


app = create_app()
