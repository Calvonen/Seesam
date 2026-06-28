from pathlib import Path

from core.brain import Brain, load_personality
from core.commands import handle_local_command
from core.memory import Memory


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt):
        self.calls.append((prompt, system_prompt))
        return "Moro Marko!"


def test_wake_command_returns_local_response_without_ollama():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus")

    answer = brain.respond("Hei seesam aukene nyt")

    assert answer == "Kuuntelen."
    assert client.calls == []


def test_non_local_input_goes_to_ollama():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="vastaa suomeksi")

    answer = brain.respond("moro")

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


def test_memory_load_ignores_empty_lines_and_append_saves_line(tmp_path):
    memory_path = tmp_path / "memory" / "marko.txt"
    memory_path.parent.mkdir()
    memory_path.write_text("ensimmäinen\n\n   \ntoinen  \n", encoding="utf-8")
    memory = Memory(memory_path)

    assert memory.load() == ["ensimmäinen", "toinen"]

    assert memory.append("  kolmas muisto  ") is True
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]

    assert memory.append("   ") is False
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]


def test_memory_command_saves_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert client.calls == []


def test_memory_command_accepts_no_space_after_colon_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:Marko pitää teestä")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää teestä"]
    assert client.calls == []


def test_memory_command_accepts_tama_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tama : Marko pitää pullasta")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää pullasta"]
    assert client.calls == []


def test_memory_command_accepts_tama_umlaut_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tamä:Marko pitää korvapuusteista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää korvapuusteista"]
    assert client.calls == []


def test_memory_command_is_case_insensitive_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("MUISTA TÄMÄ: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert client.calls == []


def test_empty_memory_command_returns_finnish_error_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:   ")

    assert answer == "En saanut tallennettavaa muistettavaa."
    assert memory.load() == []
    assert client.calls == []


def test_non_local_input_includes_memory_context(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.txt")
    memory.append("Marko pitää kahvista")
    brain = Brain(client=client, personality="vastaa suomeksi", memory=memory)

    answer = brain.respond("moro")

    assert answer == "Moro Marko!"
    assert client.calls == [("moro", "vastaa suomeksi\n\nMuistettavaa Markosta:\n- Marko pitää kahvista")]
