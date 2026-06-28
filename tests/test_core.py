from pathlib import Path

from core.commands import handle_local_command
from core.main import load_personality, respond


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt):
        self.calls.append((prompt, system_prompt))
        return "Moro Marko!"


def test_wake_command_returns_local_response_without_ollama():
    client = FakeOllamaClient()

    answer = respond("Hei seesam aukene nyt", client, "persoonallisuus")

    assert answer == "Kuuntelen."
    assert client.calls == []


def test_non_local_input_goes_to_ollama():
    client = FakeOllamaClient()

    answer = respond("moro", client, "vastaa suomeksi")

    assert answer == "Moro Marko!"
    assert client.calls == [("moro", "vastaa suomeksi")]


def test_personality_contains_required_finnish_guidance():
    personality = load_personality(Path("personality/seesam.txt"))

    assert "Vastaa aina suomeksi" in personality
    assert "Käyttäjä on Marko" in personality
    assert "moro" in personality
    assert "lyhyinä" in personality


def test_command_helper_is_case_insensitive():
    assert handle_local_command("SEESAM AUKENE") == "Kuuntelen."
