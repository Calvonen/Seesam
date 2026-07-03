from urllib.error import URLError

import pytest

from core import shelly
from core.brain import Brain


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt):
        self.calls.append((prompt, system_prompt))
        return "AI vastaus"


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


def write_devices_config(path):
    path.write_text(
        "\n".join(
            [
                "devices:",
                "  grillikatos:",
                "    type: shelly_plus_plug_s",
                "    ip: 192.168.68.58",
                "    channel: 0",
                "    aliases:",
                "      - grillikatoksen valot",
                "      - grilli katoksen valot",
                "      - grilli katos",
                "      - grillikatos",
                "      - krillikatoksen valot",
                "      - krilli katoksen valot",
                "      - krilli katos",
                "      - katoksen valot",
                "      - grillivalot",
                "      - pihavalot",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_shelly_switch_on_uses_gen2_rpc_url(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return FakeHttpResponse(b'{"was_on":false}')

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)

    assert shelly.switch_on("192.168.68.58") == {"was_on": False}
    assert calls == [("http://192.168.68.58/rpc/Switch.Set?id=0&on=true", 3)]


def test_shelly_switch_off_uses_gen2_rpc_url(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return FakeHttpResponse(b'{"was_on":true}')

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)

    assert shelly.switch_off("192.168.68.58") == {"was_on": True}
    assert calls == [("http://192.168.68.58/rpc/Switch.Set?id=0&on=false", 3)]


def test_shelly_get_status_uses_gen2_rpc_url(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return FakeHttpResponse(b'{"id":0,"output":true}')

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)

    assert shelly.get_status("192.168.68.58") == {"id": 0, "output": True}
    assert calls == [("http://192.168.68.58/rpc/Switch.GetStatus?id=0", 3)]


def test_shelly_raises_clear_error_when_device_is_unreachable(monkeypatch):
    def fake_urlopen(url, timeout):
        raise URLError("no route")

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)

    with pytest.raises(shelly.ShellyError):
        shelly.get_status("192.168.68.58")


def test_load_devices_reads_local_yaml_shape(tmp_path):
    path = tmp_path / "devices.local.yaml"
    write_devices_config(path)

    devices = shelly.load_devices(path)

    assert devices["grillikatos"] == shelly.ShellyDevice(
        name="grillikatos",
        type="shelly_plus_plug_s",
        ip="192.168.68.58",
        channel=0,
        aliases=(
            "grillikatoksen valot",
            "grilli katoksen valot",
            "grilli katos",
            "grillikatos",
            "krillikatoksen valot",
            "krilli katoksen valot",
            "krilli katos",
            "katoksen valot",
            "grillivalot",
            "pihavalot",
        ),
    )


@pytest.mark.parametrize(
    ("phrase", "payload", "expected_answer", "expected_url"),
    [
        (
            "sytytä grillikatoksen valot",
            b'{"was_on":false}',
            "Grillikatoksen valot sytytetty.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=true",
        ),
        (
            "laita grillikatoksen valot päälle",
            b'{"was_on":false}',
            "Grillikatoksen valot sytytetty.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=true",
        ),
        (
            "sammuta grillikatoksen valot",
            b'{"was_on":true}',
            "Grillikatoksen valot sammutettu.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=false",
        ),
        (
            "laita grillikatoksen valot pois",
            b'{"was_on":true}',
            "Grillikatoksen valot sammutettu.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=false",
        ),
        (
            "mikä on grillikatoksen valojen tila",
            b'{"id":0,"output":true}',
            "Grillikatoksen valot ovat päällä.",
            "http://192.168.68.58/rpc/Switch.GetStatus?id=0",
        ),
        (
            "ovatko grillikatoksen valot päällä",
            b'{"id":0,"output":true}',
            "Grillikatoksen valot ovat päällä.",
            "http://192.168.68.58/rpc/Switch.GetStatus?id=0",
        ),
        (
            "sytytä krilli katoksen valot",
            b'{"was_on":false}',
            "Grillikatoksen valot sytytetty.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=true",
        ),
        (
            "sammuta grilli katos",
            b'{"was_on":true}',
            "Grillikatoksen valot sammutettu.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=false",
        ),
        (
            "laita katoksen valot päälle",
            b'{"was_on":false}',
            "Grillikatoksen valot sytytetty.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=true",
        ),
        (
            "katoksen valot pois",
            b'{"was_on":true}',
            "Grillikatoksen valot sammutettu.",
            "http://192.168.68.58/rpc/Switch.Set?id=0&on=false",
        ),
    ],
)
def test_brain_handles_grillikatos_shelly_commands_without_ollama(
    monkeypatch,
    tmp_path,
    phrase,
    payload,
    expected_answer,
    expected_url,
):
    path = tmp_path / "devices.local.yaml"
    write_devices_config(path)
    calls = []

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return FakeHttpResponse(payload)

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus", devices_path=path)

    assert brain.local_command_name(phrase) == "shelly"
    assert calls == []

    assert brain.respond(phrase) == expected_answer
    assert calls == [(expected_url, 3)]
    assert client.calls == []


def test_brain_returns_shelly_connection_error_without_ollama(monkeypatch, tmp_path):
    path = tmp_path / "devices.local.yaml"
    write_devices_config(path)

    def fake_urlopen(url, timeout):
        raise URLError("no route")

    monkeypatch.setattr(shelly, "urlopen", fake_urlopen)
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus", devices_path=path)

    assert brain.respond("sytytä grillikatoksen valot") == "En saanut yhteyttä Shelly-laitteeseen."
    assert client.calls == []
