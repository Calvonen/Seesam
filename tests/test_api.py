import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.api import create_app


class FakeBrain:
    def __init__(self):
        self.messages = []

    def respond(self, message):
        self.messages.append(message)
        return f"echo: {message}"


def test_health_returns_ok():
    client = TestClient(create_app(brain=FakeBrain()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_uses_injected_brain_and_returns_answer():
    brain = FakeBrain()
    client = TestClient(create_app(brain=brain))

    response = client.post("/chat", json={"message": "moro"})

    assert response.status_code == 200
    assert response.json() == {"answer": "echo: moro"}
    assert brain.messages == ["moro"]


def test_chat_requires_message_field():
    client = TestClient(create_app(brain=FakeBrain()))

    response = client.post("/chat", json={"text": "moro"})

    assert response.status_code == 422
