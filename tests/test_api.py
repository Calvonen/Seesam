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


class FakeStatusCollector:
    def collect(self):
        return {
            "hostname": "seesam",
            "uptime": 12.34,
            "cpu_percent": 4.5,
            "memory_used_gb": 1.25,
            "memory_total_gb": 8.0,
            "disk_used_gb": 16.5,
            "disk_total_gb": 64.0,
            "local_ip": "192.168.1.10",
            "services": {
                "ssh": "active",
                "fail2ban": "inactive",
                "ollama": "active",
            },
            "gpu_name": "NVIDIA Test GPU",
        }


def test_health_returns_ok():
    client = TestClient(create_app(brain=FakeBrain()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_returns_server_status():
    client = TestClient(
        create_app(brain=FakeBrain(), status_collector=FakeStatusCollector())
    )

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "hostname": "seesam",
        "uptime": 12.34,
        "cpu_percent": 4.5,
        "memory_used_gb": 1.25,
        "memory_total_gb": 8.0,
        "disk_used_gb": 16.5,
        "disk_total_gb": 64.0,
        "local_ip": "192.168.1.10",
        "services": {
            "ssh": "active",
            "fail2ban": "inactive",
            "ollama": "active",
        },
        "gpu_name": "NVIDIA Test GPU",
    }


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
