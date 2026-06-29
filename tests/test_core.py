from pathlib import Path

from core.brain import Brain, CONVERSATION_HISTORY_LIMIT, MEMORY_PATH, load_personality
from core.commands import handle_local_command
from core.memory import Memory


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt):
        self.calls.append((prompt, system_prompt))
        return f"Vastaus {len(self.calls)}"


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

    assert answer == "Vastaus 1"
    assert client.calls == [("moro", "vastaa suomeksi")]


def test_personality_contains_required_finnish_guidance():
    personality = load_personality(Path("personality/seesam.txt"))

    assert "Vastaa aina suomeksi" in personality
    assert "Käytä paikallista muistia" in personality
    assert "Älä vastaa pelkällä tervehdyksellä" in personality
    assert "käytännöllisinä" in personality
    assert "Olet Seesam" not in personality
    assert "Käyttäjä on Marko" not in personality


def test_command_helper_is_case_insensitive():
    assert handle_local_command("SEESAM AUKENE") == "Kuuntelen."


def test_memory_load_ignores_empty_lines_and_append_saves_line(tmp_path):
    memory_path = tmp_path / "memory" / "marko.local.txt"
    memory_path.parent.mkdir()
    memory_path.write_text("ensimmäinen\n\n   \ntoinen  \n", encoding="utf-8")
    memory = Memory(memory_path)

    assert memory.load() == ["ensimmäinen", "toinen"]

    assert memory.append("  kolmas muisto  ") is True
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]

    assert memory.append("   ") is False
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]


def test_memory_append_creates_missing_file_and_parent_directory(tmp_path):
    memory_path = tmp_path / "missing" / "memory" / "marko.local.txt"
    memory = Memory(memory_path)

    assert memory_path.exists() is False

    assert memory.append("uusi muisto") is True

    assert memory_path.read_text(encoding="utf-8") == "uusi muisto\n"
    assert memory.load() == ["uusi muisto"]


def test_default_memory_path_uses_untracked_local_file():
    assert MEMORY_PATH.name == "marko.local.txt"
    assert MEMORY_PATH.parent.name == "memory"


def test_memory_command_saves_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert client.calls == []


def test_memory_command_accepts_no_space_after_colon_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:Marko pitää teestä")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää teestä"]
    assert client.calls == []


def test_memory_command_accepts_tama_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tama : Marko pitää pullasta")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää pullasta"]
    assert client.calls == []


def test_memory_command_accepts_tama_umlaut_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tamä:Marko pitää korvapuusteista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää korvapuusteista"]
    assert client.calls == []


def test_memory_command_is_case_insensitive_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("MUISTA TÄMÄ: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert client.calls == []


def test_empty_memory_command_returns_finnish_error_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:   ")

    assert answer == "En saanut tallennettavaa muistettavaa."
    assert memory.load() == []
    assert client.calls == []



def test_memory_list_command_returns_saved_memories_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    memory.append("Marko pitää kahvista")
    memory.append("Markon koira on Tessu")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mitä muistat")

    assert answer == "- Marko pitää kahvista\n- Markon koira on Tessu"
    assert client.calls == []


def test_memory_list_command_accepts_show_memory_phrase_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    memory.append("Marko pitää teestä")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("näytä muisti")

    assert answer == "- Marko pitää teestä"
    assert client.calls == []


def test_memory_list_command_returns_empty_message_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mitä muistat")

    assert answer == "Muistissa ei ole vielä mitään."
    assert client.calls == []


def test_non_local_input_includes_memory_context(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    memory.append("Marko pitää kahvista")
    brain = Brain(client=client, personality="vastaa suomeksi", memory=memory)

    answer = brain.respond("moro")

    assert answer == "Vastaus 1"
    assert client.calls == [("moro", brain._system_context())]
    system_context = client.calls[0][1]
    assert system_context.startswith("vastaa suomeksi")
    assert "Sinulla on käytössäsi paikallinen muisti Markosta" in system_context
    assert "sinun täytyy käyttää muistia vastauksessa" in system_context
    assert "vastaa lyhyesti muistin perusteella" in system_context
    assert "Älä vastaa pelkällä tervehdyksellä" in system_context
    assert "Muistettavaa Markosta:\n- Marko pitää kahvista" in system_context


def test_system_context_omits_memory_instructions_when_memory_is_empty(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "marko.local.txt")
    brain = Brain(client=client, personality="vastaa suomeksi", memory=memory)

    assert brain._system_context() == "vastaa suomeksi"


def test_conversation_history_is_included_in_prompt_sent_to_ollama():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="vastaa suomeksi")

    first_answer = brain.respond("Kerro yksi vinkki")
    second_answer = brain.respond("Entä toinen?")

    assert first_answer == "Vastaus 1"
    assert second_answer == "Vastaus 2"
    second_prompt = client.calls[1][0]
    assert "Aiempi keskustelu tässä istunnossa:" in second_prompt
    assert "Käyttäjä: Kerro yksi vinkki" in second_prompt
    assert "Seesam: Vastaus 1" in second_prompt
    assert second_prompt.endswith("Käyttäjä: Entä toinen?")


def test_local_commands_do_not_call_ollama_or_update_conversation_history():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="vastaa suomeksi")

    answer = brain.respond("seesam aukene")

    assert answer == "Kuuntelen."
    assert client.calls == []
    assert brain.conversation_history == []


def test_conversation_history_is_limited_to_configured_length():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="vastaa suomeksi", history_limit=CONVERSATION_HISTORY_LIMIT)

    for index in range(5):
        brain.respond(f"viesti {index}")

    assert len(brain.conversation_history) == CONVERSATION_HISTORY_LIMIT
    assert brain.conversation_history == [
        ("Käyttäjä", "viesti 2"),
        ("Seesam", "Vastaus 3"),
        ("Käyttäjä", "viesti 3"),
        ("Seesam", "Vastaus 4"),
        ("Käyttäjä", "viesti 4"),
        ("Seesam", "Vastaus 5"),
    ]

    latest_prompt = client.calls[-1][0]
    assert "Käyttäjä: viesti 0" not in latest_prompt
    assert "Seesam: Vastaus 1" not in latest_prompt
    assert "Käyttäjä: viesti 1" in latest_prompt
    assert "Seesam: Vastaus 2" in latest_prompt
    assert latest_prompt.endswith("Käyttäjä: viesti 4")
