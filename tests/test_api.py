import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core import stt, tts
from core.brain import Brain
from core.memory import Memory
from core.api import create_app


class FakeBrain:
    def __init__(self):
        self.messages = []

    def handle_local_command(self, message):
        return None

    def is_memory_command(self, message):
        return False

    def respond_with_ai(self, message):
        self.messages.append(message)
        return f"echo: {message}"

    def respond(self, message):
        local_response = self.handle_local_command(message)
        if local_response is not None:
            return local_response

        return self.respond_with_ai(message)


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


class FakeSystemStatus:
    def health(self):
        return {
            "status": "ok",
            "server_time": "2026-07-02T12:34:56+03:00",
            "uptime": "1 h 2 min",
            "memory_file_status": {"memories.local.txt": "ok"},
            "ollama_status": "active",
            "disk_free_gb": 128.5,
            "ram_free_gb": 12.25,
            "version": "test-version",
        }


def test_health_returns_ok_with_local_system_fields():
    client = TestClient(create_app(brain=FakeBrain(), system_status=FakeSystemStatus()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "server_time": "2026-07-02T12:34:56+03:00",
        "uptime": "1 h 2 min",
        "memory_file_status": {"memories.local.txt": "ok"},
        "ollama_status": "active",
        "disk_free_gb": 128.5,
        "ram_free_gb": 12.25,
        "version": "test-version",
    }


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


def test_system_specs_returns_server_hardware_specs():
    client = TestClient(
        create_app(
            brain=FakeBrain(),
            specs_collector=lambda: {
                "hostname": "seesam",
                "os_name": "Ubuntu 24.04 LTS",
                "kernel": "6.8.0-test",
                "cpu_model": "AMD Ryzen Test",
                "cpu_cores_physical": 8,
                "cpu_threads": 16,
                "ram_total_gb": 31.25,
                "disk_total_gb": 512.0,
                "disk_free_gb": 128.5,
                "gpu_name": "NVIDIA Test GPU",
                "local_ip": "192.168.1.10",
            },
        )
    )

    response = client.get("/system/specs")

    assert response.status_code == 200
    assert response.json() == {
        "hostname": "seesam",
        "os_name": "Ubuntu 24.04 LTS",
        "kernel": "6.8.0-test",
        "cpu_model": "AMD Ryzen Test",
        "cpu_cores_physical": 8,
        "cpu_threads": 16,
        "ram_total_gb": 31.25,
        "disk_total_gb": 512.0,
        "disk_free_gb": 128.5,
        "gpu_name": "NVIDIA Test GPU",
        "local_ip": "192.168.1.10",
    }


def test_speak_returns_wav_audio(monkeypatch):
    client = TestClient(create_app(brain=FakeBrain()))
    monkeypatch.setattr(tts, "synthesize_wav", lambda text: b"RIFF wav bytes")

    response = client.post("/speak", json={"text": "moro"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF wav bytes"


def test_speak_returns_json_error_when_tts_unavailable(monkeypatch):
    client = TestClient(create_app(brain=FakeBrain()))

    def fail_synthesis(text):
        raise tts.TTSError(503, "TTS is disabled. Set TTS_ENABLED=true to enable speech synthesis.")

    monkeypatch.setattr(tts, "synthesize_wav", fail_synthesis)

    response = client.post("/speak", json={"text": "moro"})

    assert response.status_code == 503
    assert response.json() == {"detail": "TTS is disabled. Set TTS_ENABLED=true to enable speech synthesis."}


def test_transcribe_returns_text_for_uploaded_audio(monkeypatch):
    client = TestClient(create_app(brain=FakeBrain()))
    calls = []

    def fake_transcribe(audio, filename):
        calls.append((audio, filename))
        return "moro Marko"

    monkeypatch.setattr(stt, "transcribe_audio", fake_transcribe)

    response = client.post(
        "/transcribe",
        files={"file": ("voice.wav", b"audio bytes", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "moro Marko"}
    assert calls == [(b"audio bytes", "voice.wav")]


def test_transcribe_returns_json_error_when_stt_unavailable(monkeypatch):
    client = TestClient(create_app(brain=FakeBrain()))

    def fail_transcription(audio, filename):
        raise stt.STTError(
            503,
            "STT is disabled. Set STT_ENABLED=true to enable speech transcription.",
        )

    monkeypatch.setattr(stt, "transcribe_audio", fail_transcription)

    response = client.post(
        "/transcribe",
        files={"file": ("voice.wav", b"audio bytes", "audio/wav")},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "STT is disabled. Set STT_ENABLED=true to enable speech transcription.",
    }


def test_chat_uses_injected_brain_and_returns_answer(capsys):
    brain = FakeBrain()
    client = TestClient(create_app(brain=brain))

    response = client.post("/chat", json={"message": "moro"})

    assert response.status_code == 200
    assert response.json() == {"answer": "echo: moro"}
    assert brain.messages == ["moro"]
    output = capsys.readouterr().out
    assert "[API CHAT RAW] moro" in output
    assert "[STATUS MATCH] none" in output
    assert "[LOCAL COMMAND MATCH] none" in output
    assert "API message sent to AI" in output


def test_chat_handles_memory_command_locally_from_memory_file(tmp_path, capsys):
    class FakeOllamaClient:
        def __init__(self):
            self.calls = []

        def generate(self, prompt, system_prompt):
            self.calls.append((prompt, system_prompt))
            return "AI vastaus"

    ollama = FakeOllamaClient()
    memory = Memory(tmp_path / "memory" / "memories.local.txt")
    memory.append("Marko pitää kahvista")
    brain = Brain(client=ollama, personality="persoonallisuus", memory=memory)
    client = TestClient(create_app(brain=brain))

    response = client.post("/chat", json={"message": "mitä muistat"})

    assert response.status_code == 200
    assert response.json() == {"answer": "- Marko pitää kahvista"}
    assert ollama.calls == []
    output = capsys.readouterr().out
    assert "[API CHAT RAW] mitä muistat" in output
    assert "[STATUS MATCH] none" in output
    assert "[LOCAL COMMAND MATCH] memory_list" in output
    assert "API memory command handled locally: mitä muistat" in output


def test_chat_handles_system_status_command_locally(capsys):
    class FakeLocalSystemStatus:
        def command_name(self, message):
            if message == "onko ollama käynnissä":
                return "system_status"
            return None

        def debug_match_name(self, message):
            if message == "onko ollama käynnissä":
                return "ollama"
            return "none"

        def answer(self, message):
            if message == "onko ollama käynnissä":
                return "Ollama on käynnissä."
            return None

    class FakeOllamaClient:
        def __init__(self):
            self.calls = []

        def generate(self, prompt, system_prompt):
            self.calls.append((prompt, system_prompt))
            return "AI vastaus"

    ollama = FakeOllamaClient()
    brain = Brain(
        client=ollama,
        personality="persoonallisuus",
        system_status=FakeLocalSystemStatus(),
    )
    client = TestClient(create_app(brain=brain))

    response = client.post("/chat", json={"message": "onko ollama käynnissä"})

    assert response.status_code == 200
    assert response.json() == {"answer": "Ollama on käynnissä."}
    assert ollama.calls == []
    output = capsys.readouterr().out
    assert "[API CHAT RAW] onko ollama käynnissä" in output
    assert "[STATUS MATCH] ollama" in output
    assert "[LOCAL COMMAND MATCH] system_status" in output
    assert "API system status command handled locally: onko ollama käynnissä" in output


def test_chat_requires_message_field():
    client = TestClient(create_app(brain=FakeBrain()))

    response = client.post("/chat", json={"text": "moro"})

    assert response.status_code == 422
