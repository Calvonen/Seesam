from urllib.error import URLError

import pytest

from core import energyzen
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


def test_energyzen_fetches_latest_supabase_row_with_auth_headers(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeHttpResponse(
            b'[{"top_temp":58.2,"bottom_temp":43.1,"showers":3.7,"heating":true,"created_at":"2026-07-02T10:00:00Z"}]'
        )

    monkeypatch.setattr(energyzen, "urlopen", fake_urlopen)

    reading = energyzen.get_latest_reading()

    assert reading == energyzen.TankReading(
        top_temp=58.2,
        bottom_temp=43.1,
        showers=3.7,
        heating=True,
        created_at="2026-07-02T10:00:00Z",
    )
    request, timeout = calls[0]
    assert request.full_url == energyzen.LATEST_READING_URL
    assert request.headers["Apikey"] == "test-key"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert timeout == 5


def test_energyzen_calculates_showers_from_energyzen_app_settings():
    assert energyzen.calculate_showers(61.0, 61.0) == pytest.approx(8.0)
    assert energyzen.calculate_showers(10.0, 10.0) == pytest.approx(0.0)
    assert energyzen.calculate_showers(56.9, 27.7) == pytest.approx(5.0666666667)


def test_energyzen_clamps_calculated_showers_to_tank_range():
    assert energyzen.calculate_showers(80.0, 80.0) == pytest.approx(8.0)
    assert energyzen.calculate_showers(5.0, 5.0) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "nollaan"),
        (1, "yhteen"),
        (2, "kahteen"),
        (5.06, "viiteen"),
        (5.6, "kuuteen"),
        (8, "kahdeksaan"),
        (11.4, "11"),
    ],
)
def test_format_showers_uses_finnish_illative(value, expected):
    assert energyzen._format_showers(value) == expected


def test_energyzen_format_uses_calculated_showers_and_rounds_values():
    reading = energyzen.TankReading(top_temp=56.9, bottom_temp=27.7, showers=2.2, heating=False)

    assert (
        energyzen.format_reading(reading)
        == "Varaajan yläosa on 57 astetta, alaosa 28 astetta. Lämmitys on pois päältä ja lämmintä vettä riittää arviolta viiteen suihkuun."
    )


def test_energyzen_accepts_rows_without_legacy_showers_field(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(b'[{"top_temp":61,"bottom_temp":61,"heating":false}]')

    monkeypatch.setattr(energyzen, "urlopen", fake_urlopen)

    reading = energyzen.get_latest_reading()

    assert reading.showers is None
    assert reading.estimated_showers == pytest.approx(8.0)


def test_energyzen_requires_supabase_key(monkeypatch):
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    with pytest.raises(energyzen.EnergyZenError):
        energyzen.get_latest_reading()


def test_energyzen_raises_clear_error_when_supabase_unreachable(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    def fake_urlopen(request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(energyzen, "urlopen", fake_urlopen)

    with pytest.raises(energyzen.EnergyZenError):
        energyzen.get_latest_reading()


@pytest.mark.parametrize(
    "phrase",
    [
        "paljonko varaajan lämpö on",
        "mikä on lämminvesivaraajan tila",
        "näytä varaajan lämpötilat",
        "paljonko suihkuja on jäljellä",
        "mikä on varraajan lämpötila",
        "paljonko varaajassa on lämmintä",
        "paljonko varaa jossa on lämmintä",
    ],
)
def test_brain_handles_energyzen_questions_without_ollama(monkeypatch, phrase):
    monkeypatch.setattr(
        energyzen,
        "get_latest_reading",
        lambda: energyzen.TankReading(top_temp=58.2, bottom_temp=43.1, showers=0.1, heating=True),
    )
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus")

    assert brain.local_command_name(phrase) == "energyzen"
    assert (
        brain.respond(phrase)
        == "Varaajan yläosa on 58 astetta, alaosa 43 astetta. Lämmitys on päällä ja lämmintä vettä riittää arviolta kuuteen suihkuun."
    )
    assert client.calls == []


def test_brain_returns_energyzen_error_without_ollama(monkeypatch):
    def fail_reading():
        raise energyzen.EnergyZenError("no data")

    monkeypatch.setattr(energyzen, "get_latest_reading", fail_reading)
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus")

    assert brain.respond("paljonko varaajan lämpö on") == "En saanut haettua varaajan tietoja."
    assert client.calls == []
