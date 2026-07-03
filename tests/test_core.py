import re
from pathlib import Path

from core.brain import (
    ASSISTANT_IDENTITY_PATH,
    EPISODE_LOG_PATH,
    LEGACY_MARKO_MEMORY_PATH,
    LEGACY_MEMORY_DIR,
    Brain,
    CONVERSATION_HISTORY_LIMIT,
    MEMORY_PATH,
    USER_PROFILE_PATH,
    initialize_local_memory_files,
    load_personality,
)
from core.commands import handle_local_command
from core.memory import AssistantIdentityMemory, EpisodeLog, Memory, UserProfileMemory
from core.system_status import SystemStatus, format_duration


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt):
        self.calls.append((prompt, system_prompt))
        return f"Vastaus {len(self.calls)}"


class FakeSystemStatus:
    def __init__(self):
        self.answers = {
            "paljonko kello on": "Kello on 12:00:00.",
            "miten kone voi": "Kone voi hyvin.",
            "näytä serverin speksit": "Hostname: seesam",
            "onko ollama käynnissä": "Ollama on käynnissä.",
        }

    def answer(self, message):
        return self.answers.get(message)


def test_wake_command_returns_local_response_without_ollama():
    client = FakeOllamaClient()
    brain = Brain(client=client, personality="persoonallisuus")

    answer = brain.respond("Hei seesam aukene nyt")

    assert answer == "Kuuntelen."
    assert client.calls == []


def test_system_status_commands_are_handled_without_ollama():
    client = FakeOllamaClient()
    brain = Brain(
        client=client,
        personality="vastaa suomeksi",
        system_status=FakeSystemStatus(),
    )

    assert brain.respond("paljonko kello on") == "Kello on 12:00:00."
    assert brain.respond("miten kone voi") == "Kone voi hyvin."
    assert brain.respond("näytä serverin speksit") == "Hostname: seesam"
    assert brain.respond("onko ollama käynnissä") == "Ollama on käynnissä."
    assert client.calls == []


def test_format_duration_returns_compact_finnish_uptime():
    assert format_duration(65) == "1 min"
    assert format_duration(3660) == "1 h 1 min"
    assert format_duration(90000) == "1 pv 1 h"


def test_system_status_keyword_matcher_recognizes_natural_time_phrases():
    status = SystemStatus(started_at=0)

    for phrase in [
        "mitä kello on",
        "paljonko kello",
        "paljonko on kello",
        "kellonaika",
        "mikä aika nyt on",
    ]:
        assert status.match_kind(phrase) == "time"
        assert status.debug_match_name(phrase) == "time"


def test_system_status_keyword_matcher_recognizes_machine_parts_without_memory_confusion():
    status = SystemStatus(started_at=0)

    assert status.match_kind("mikä cpu koneessa") == "cpu"
    assert status.match_kind("mikä prosessori koneessa") == "cpu"
    assert status.match_kind("mikä suoritin koneessa") == "cpu"
    assert status.match_kind("mikä gpu koneessa") == "gpu"
    assert status.match_kind("mikä näytönohjain koneessa") == "gpu"
    assert status.match_kind("mikä grafiikkakortti koneessa") == "gpu"
    assert status.match_kind("mikä näyttis koneessa") == "gpu"
    assert status.match_kind("entä ram") == "ram"
    assert status.match_kind("ram") == "ram"
    assert status.match_kind("paljonko keskusmuisti koneessa") == "ram"
    assert status.match_kind("mitä muistat") is None
    assert status.match_kind("näytä muisti") is None


def test_natural_system_status_phrases_are_handled_without_ollama(monkeypatch):
    def fake_collect(self):
        return {
            "hostname": "seesam",
            "uptime": "1 h",
            "cpu_percent": 12.5,
            "cpu_model": "AMD Test",
            "cpu_cores_physical": 8,
            "cpu_threads": 16,
            "ram_used_gb": 4.0,
            "ram_total_gb": 32.0,
            "ram_free_gb": 28.0,
            "ram_percent": 12.5,
            "disk_used_gb": 10.0,
            "disk_total_gb": 100.0,
            "disk_free_gb": 90.0,
            "disk_percent": 10.0,
            "ollama_status": "active",
            "temperatures_c": {},
            "gpu": {
                "name": "NVIDIA Test GPU",
                "memory_used_mb": 100,
                "memory_total_mb": 1000,
                "temperature_c": 40,
                "utilization_percent": 5,
            },
        }

    monkeypatch.setattr(SystemStatus, "collect", fake_collect)
    client = FakeOllamaClient()
    brain = Brain(
        client=client,
        personality="vastaa suomeksi",
        system_status=SystemStatus(started_at=0),
    )

    assert brain.respond("mitä kello on").startswith("Kello on ")
    assert brain.respond("mikä cpu koneessa") == "Prosessori on AMD Test. Kuorma on 12,5 prosenttia."
    assert brain.respond("mikä gpu koneessa") == "Näyttis on Test GPU, lämpötila 40 astetta ja kuorma 5 prosenttia."
    assert brain.respond("entä ram") == "Muistia on 32 gigaa, josta käytössä 12,5 prosenttia."
    assert brain.respond("ram") == "Muistia on 32 gigaa, josta käytössä 12,5 prosenttia."
    assert client.calls == []


def test_system_status_speech_answers_are_natural_and_details_stay_raw(monkeypatch):
    def fake_collect(self):
        return {
            "hostname": "seesam",
            "uptime": "1 h",
            "cpu_percent": 0.8,
            "cpu_model": "11th Gen Intel(R) Core(TM) i5-11400F @ 2.60GHz",
            "cpu_cores_physical": 6,
            "cpu_threads": 12,
            "ram_used_gb": 4.37,
            "ram_total_gb": 31.23,
            "ram_free_gb": 26.86,
            "ram_percent": 14.0,
            "disk_used_gb": 69.37,
            "disk_total_gb": 575.67,
            "disk_free_gb": 506.3,
            "disk_percent": 7.0,
            "ollama_status": "active",
            "temperatures_c": {},
            "os_name": "Ubuntu Test",
            "kernel": "6.8.0-test",
            "local_ip": "192.168.1.10",
            "gpu": {
                "name": "NVIDIA GeForce RTX 2080 Ti",
                "memory_used_mb": 6983,
                "memory_total_mb": 11264,
                "temperature_c": 32,
                "utilization_percent": 0,
            },
        }

    monkeypatch.setattr(SystemStatus, "collect", fake_collect)
    client = FakeOllamaClient()
    brain = Brain(
        client=client,
        personality="vastaa suomeksi",
        system_status=SystemStatus(started_at=0),
    )

    assert brain.respond("näyttis") == "Näyttis on RTX 2080 Tee ii, lämpötila 32 astetta ja kuorma 0 prosenttia."
    assert brain.system_status.lastSystemInfoTopic == "gpu"
    assert brain.respond("tarkemmin") == "GPU: NVIDIA GeForce RTX 2080 Ti. VRAM: 6983 / 11264 MiB. Lämpötila: 32 °C. Kuorma: 0 %."

    assert brain.respond("mikä prosessori") == "Prosessori on Intel i5-11400F. Kuorma on 0,8 prosenttia."
    assert brain.system_status.lastSystemInfoTopic == "cpu"
    assert brain.respond("kerro tarkemmin") == "CPU: 11th Gen Intel(R) Core(TM) i5-11400F @ 2.60GHz. Ytimet/säikeet: 6 / 12. Kuorma: 0.8 %."

    assert brain.respond("muisti") == "Muistia on 32 gigaa, josta käytössä 14 prosenttia."
    assert brain.system_status.lastSystemInfoTopic == "ram"
    assert brain.respond("näytä tarkat tiedot") == "RAM-muistia on vapaana 26.86 GiB / 31.23 GiB (14.0 % käytössä)."

    assert brain.respond("levy tila") == "Levytilaa on 576 gigaa, josta vapaana 506 gigaa."

    details = brain.respond("tarkat tiedot")
    assert details == "Levytilaa on vapaana 506.3 GiB / 575.67 GiB (7.0 % käytössä)."
    assert brain.system_status.lastSystemInfoTopic == "disk"

    all_details = brain.respond("kaikki tarkat tiedot")
    assert "CPU: 11th Gen Intel(R) Core(TM) i5-11400F @ 2.60GHz. Ytimet/säikeet: 6 / 12. Kuorma: 0.8 %." in all_details
    assert "GPU: NVIDIA GeForce RTX 2080 Ti. VRAM: 6983 / 11264 MiB. Lämpötila: 32 °C. Kuorma: 0 %." in all_details
    assert "RAM-muistia on vapaana 26.86 GiB / 31.23 GiB (14.0 % käytössä)." in all_details
    assert "Levytilaa on vapaana 506.3 GiB / 575.67 GiB (7.0 % käytössä)." in all_details
    assert brain.system_status.lastSystemInfoTopic == "all"

    assert (
        brain.respond("koneen tila")
        == "Kone on kunnossa. Prosessorin kuorma on 0,8 prosenttia, näyttis käy 32 asteessa, muistia on käytössä 14 prosenttia ja levytilaa on vapaana 506 gigaa."
    )
    assert brain.respond("tarkemmin") == all_details
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
    memory_path = tmp_path / "memory" / "memories.local.txt"
    memory_path.parent.mkdir()
    memory_path.write_text("ensimmäinen\n\n   \ntoinen  \n", encoding="utf-8")
    memory = Memory(memory_path)

    assert memory.load() == ["ensimmäinen", "toinen"]

    assert memory.append("  kolmas muisto  ") is True
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]

    assert memory.append("   ") is False
    assert memory.load() == ["ensimmäinen", "toinen", "kolmas muisto"]


def test_memory_append_creates_missing_file_and_parent_directory(tmp_path):
    memory_path = tmp_path / "missing" / "memory" / "memories.local.txt"
    memory = Memory(memory_path)

    assert memory_path.exists() is False

    assert memory.append("uusi muisto") is True

    saved_line = memory_path.read_text(encoding="utf-8")
    assert re.match(
        r"^M000001 \| \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} \| source=voice \| uusi muisto\n$",
        saved_line,
    )
    assert memory.load() == ["uusi muisto"]


def test_assistant_identity_creates_default_local_yaml_file(tmp_path):
    memory_path = tmp_path / "memory" / "seesam.local.yaml"
    memory = AssistantIdentityMemory(memory_path)

    assert memory_path.exists() is False

    assert memory.load() == {
        "name": "Seesam",
        "aliases": ["Sam", "CSAM"],
        "role": "paikallinen ääniavustaja",
        "language": "fi",
        "server": "Seesam-palvelin",
        "backend": "Ollama",
    }
    saved_identity = memory_path.read_text(encoding="utf-8")
    assert "name: Seesam" in saved_identity
    assert "aliases:" in saved_identity
    assert "  - Sam" in saved_identity
    assert "  - CSAM" in saved_identity


def test_system_context_includes_separated_identity_and_user_profile(tmp_path):
    client = FakeOllamaClient()
    assistant_path = tmp_path / "memory" / "seesam.local.yaml"
    user_path = tmp_path / "memory" / "marko.local.yaml"
    assistant_path.parent.mkdir()
    assistant_path.write_text(
        "name: Seesam\nrole: paikallinen ääniavustaja\nlanguage: fi\nserver: testipalvelin\nbackend: Ollama\n",
        encoding="utf-8",
    )
    user_path.write_text(
        "name: Marko\nlanguage: fi\nresponse_style: lyhyt\nimportant_preferences:\n  - pitää selkeydestä\ndeep_memory:\n  []\n",
        encoding="utf-8",
    )
    brain = Brain(
        client=client,
        personality="vastaa suomeksi",
        assistant_identity=AssistantIdentityMemory(assistant_path),
        user_profile=UserProfileMemory(user_path),
    )

    system_context = brain._system_context()

    assert system_context.startswith("vastaa suomeksi")
    assert "Sinun oma nimesi on Seesam" in system_context
    assert "Nimen aliakset ovat: Sam, CSAM" in system_context
    assert "Palvelinkone on testipalvelin" in system_context
    assert "Käyttäjän nimi: Marko" in system_context
    assert "Älä ota omaa nimeäsi käyttäjän muistista" in system_context


def test_assistant_identity_questions_use_local_yaml_without_ollama_or_user_memory(tmp_path, capsys):
    client = FakeOllamaClient()
    assistant_path = tmp_path / "memory" / "seesam.local.yaml"
    user_path = tmp_path / "memory" / "marko.local.yaml"
    assistant_path.parent.mkdir()
    assistant_path.write_text(
        "name: Seesam\naliases:\n  - Sam\n  - CSAM\nrole: paikallinen ääniavustaja\nlanguage: fi\nserver: testipalvelin\nbackend: Ollama\n",
        encoding="utf-8",
    )
    user_path.write_text(
        "name: Marko\nlanguage: fi\nresponse_style: lyhyt\nimportant_preferences:\n  []\ndeep_memory:\n  []\n",
        encoding="utf-8",
    )
    brain = Brain(
        client=client,
        personality="vastaa suomeksi",
        assistant_identity=AssistantIdentityMemory(assistant_path),
        user_profile=UserProfileMemory(user_path),
    )

    answers = [
        brain.respond("kuka olet"),
        brain.respond("kuka sinä olet"),
        brain.respond("mikä sinun nimesi on"),
        brain.respond("kuka on Seesam"),
        brain.respond("kuka on Sam"),
        brain.respond("kuka on CSAM"),
    ]

    assert answers == ["Olen Seesam, paikallinen ääniavustaja."] * 6
    assert client.calls == []
    assert "[IDENTITY] using memory/seesam.local.yaml" in capsys.readouterr().out
    assert "Sam" not in UserProfileMemory(user_path).text()
    assert "CSAM" not in UserProfileMemory(user_path).text()


def _patch_memory_paths(monkeypatch, memory_dir):
    from core import brain as brain_module

    monkeypatch.setattr(brain_module, "ASSISTANT_IDENTITY_PATH", memory_dir / "seesam.local.yaml")
    monkeypatch.setattr(brain_module, "USER_PROFILE_PATH", memory_dir / "marko.local.yaml")
    monkeypatch.setattr(brain_module, "MEMORY_PATH", memory_dir / "memories.local.txt")
    monkeypatch.setattr(brain_module, "EPISODE_LOG_PATH", memory_dir / "episodes.local.log")
    monkeypatch.setattr(brain_module, "LEGACY_MARKO_MEMORY_PATH", memory_dir / "marko.local.txt")
    monkeypatch.setattr(brain_module, "LEGACY_MEMORY_DIR", memory_dir / "legacy")


def test_initialize_local_memory_files_archives_legacy_marko_txt_after_migration(monkeypatch, tmp_path):
    memory_dir = tmp_path / "memory"
    _patch_memory_paths(monkeypatch, memory_dir)
    legacy_path = memory_dir / "marko.local.txt"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        "M000001 | 2026-01-01T12:00:00 | source=voice | vanha tavallinen muisto\n"
        "käyttäjä pitää lyhyistä vastauksista\n"
        "Minun nimeni on Seesam\n",
        encoding="utf-8",
    )

    initialize_local_memory_files()

    archived_path = memory_dir / "legacy" / "marko.local.txt"
    assert legacy_path.exists() is False
    assert archived_path.read_text(encoding="utf-8").startswith("M000001")
    assert "vanha tavallinen muisto" in (memory_dir / "memories.local.txt").read_text(encoding="utf-8")
    assert "käyttäjä pitää lyhyistä vastauksista" in UserProfileMemory(memory_dir / "marko.local.yaml").text()

    initialize_local_memory_files()

    saved_lines = (memory_dir / "memories.local.txt").read_text(encoding="utf-8").splitlines()
    assert saved_lines == ["M000001 | 2026-01-01T12:00:00 | source=voice | vanha tavallinen muisto"]


def test_initialize_local_memory_files_ignores_archived_legacy_marko_txt(monkeypatch, tmp_path):
    memory_dir = tmp_path / "memory"
    _patch_memory_paths(monkeypatch, memory_dir)
    archived_path = memory_dir / "legacy" / "marko.local.txt"
    archived_path.parent.mkdir(parents=True)
    archived_path.write_text("M000001 | 2026-01-01T12:00:00 | source=voice | arkistoitu muisto\n", encoding="utf-8")

    initialize_local_memory_files()

    assert (memory_dir / "memories.local.txt").read_text(encoding="utf-8") == ""
    assert "arkistoitu muisto" not in UserProfileMemory(memory_dir / "marko.local.yaml").text()

def test_default_memory_path_uses_untracked_local_file():
    assert MEMORY_PATH.name == "memories.local.txt"
    assert MEMORY_PATH.parent.name == "memory"


def test_default_assistant_identity_path_uses_untracked_local_yaml_file():
    assert ASSISTANT_IDENTITY_PATH.name == "seesam.local.yaml"
    assert ASSISTANT_IDENTITY_PATH.parent.name == "memory"


def test_default_user_profile_path_uses_untracked_local_yaml_file():
    assert USER_PROFILE_PATH.name == "marko.local.yaml"
    assert USER_PROFILE_PATH.parent.name == "memory"


def test_default_episode_log_path_uses_untracked_local_log_file():
    assert EPISODE_LOG_PATH.name == "episodes.local.log"
    assert EPISODE_LOG_PATH.parent.name == "memory"


def test_default_legacy_marko_path_is_not_runtime_memory():
    assert LEGACY_MARKO_MEMORY_PATH.name == "marko.local.txt"
    assert LEGACY_MEMORY_DIR.name == "legacy"


def test_memory_command_saves_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert memory.entries()[0].id == "M000001"
    assert client.calls == []


def test_memory_command_accepts_no_space_after_colon_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:Marko pitää teestä")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää teestä"]
    assert client.calls == []


def test_memory_command_accepts_tama_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tama : Marko pitää pullasta")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää pullasta"]
    assert client.calls == []


def test_memory_command_accepts_tama_umlaut_typo_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tamä:Marko pitää korvapuusteista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää korvapuusteista"]
    assert client.calls == []


def test_memory_command_is_case_insensitive_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("MUISTA TÄMÄ: Marko pitää kahvista")

    assert answer == "Muistan tämän."
    assert memory.load() == ["Marko pitää kahvista"]
    assert client.calls == []


def test_empty_memory_command_returns_finnish_error_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("muista tämä:   ")

    assert answer == "En saanut tallennettavaa muistettavaa."
    assert memory.load() == []
    assert client.calls == []



def test_memory_list_command_returns_saved_memories_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("Marko pitää kahvista")
    memory.append("Markon koira on Tessu")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mitä muistat")

    assert answer == "- Marko pitää kahvista\n- Markon koira on Tessu"
    assert client.calls == []


def test_memory_list_command_combines_deep_profile_and_ordinary_memories(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("Marko pitää kahvista")
    user_profile_path = tmp_path / "marko.local.yaml"
    user_profile = UserProfileMemory(user_profile_path)
    user_profile.append_deep_memory("käyttäjä haluaa lyhyitä vastauksia")
    brain = Brain(
        client=client,
        personality="persoonallisuus",
        memory=memory,
        user_profile=user_profile,
    )

    answer = brain.respond("mitä muistat")

    assert "Käyttäjän syvä muisti:" in answer
    assert "käyttäjä haluaa lyhyitä vastauksia" in answer
    assert "Tavalliset muistot:" in answer
    assert "- Marko pitää kahvista" in answer
    assert client.calls == []


def test_deep_memory_command_saves_to_user_profile_without_ollama(tmp_path):
    client = FakeOllamaClient()
    user_profile = UserProfileMemory(tmp_path / "marko.local.yaml")
    brain = Brain(client=client, personality="persoonallisuus", user_profile=user_profile)

    answer = brain.respond("tallenna syvään muistiin: käyttäjä haluaa lyhyitä vastauksia")

    assert answer == "Tallensin tämän syvään muistiin."
    assert "käyttäjä haluaa lyhyitä vastauksia" in user_profile.text()
    assert client.calls == []


def test_memory_list_command_accepts_show_memory_phrase_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("Marko pitää teestä")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("näytä muisti")

    assert answer == "- Marko pitää teestä"
    assert client.calls == []


def test_memory_list_command_accepts_show_memories_phrase_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("Marko pitää teestä")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("näytä muistot")

    assert answer == "- Marko pitää teestä"
    assert client.calls == []


def test_memory_list_command_returns_empty_message_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mitä muistat")

    assert answer == "Muistissa ei ole vielä mitään."
    assert client.calls == []


def test_latest_memory_list_command_returns_five_latest_numbered_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    for index in range(1, 7):
        memory.append(f"muisto {index}")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("näytä viimeisimmät muistot")

    assert answer.splitlines() == [
        "1. M000006: muisto 6",
        "2. M000005: muisto 5",
        "3. M000004: muisto 4",
        "4. M000003: muisto 3",
        "5. M000002: muisto 2",
    ]
    assert client.calls == []


def test_latest_memory_command_returns_latest_ordinary_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("ensimmäinen")
    memory.append("uusin")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mikä on viimeisin muistosi")

    assert answer == "M000002: uusin"
    assert client.calls == []


def test_latest_saved_memory_command_returns_latest_ordinary_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("uusin")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("mikä on viimeisin tallennettu muistosi")

    assert answer == "M000001: uusin"
    assert client.calls == []


def test_delete_latest_memory_command_removes_latest_and_reports_it_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("ensimmäinen")
    memory.append("toinen")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("poista viimeisin muisto")

    assert answer == "Poistin viimeisimmän muiston: M000002: toinen"
    assert memory.load() == ["ensimmäinen"]
    assert client.calls == []


def test_undo_latest_memory_command_is_same_safe_delete_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("väärin kuultu")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("peru viimeisin muisto")

    assert answer == "Poistin viimeisimmän muiston: M000001: väärin kuultu"
    assert memory.load() == []
    assert client.calls == []


def test_forget_latest_memory_command_is_same_safe_delete_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("väärin kuultu")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("unohda viimeisin muisto")

    assert answer == "Poistin viimeisimmän muiston: M000001: väärin kuultu"
    assert memory.load() == []
    assert client.calls == []


def test_delete_latest_memory_yours_command_is_same_safe_delete_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("väärin kuultu")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("poista viimeisin muistosi")

    assert answer == "Poistin viimeisimmän muiston: M000001: väärin kuultu"
    assert memory.load() == []
    assert client.calls == []


def test_delete_latest_memory_command_handles_empty_memory_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("poista viimeisin muisto")

    assert answer == "En löytänyt poistettavaa muistoa."
    assert memory.load() == []
    assert client.calls == []


def test_delete_memory_by_latest_list_number_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    for text in ["vanhin", "keskimmäinen", "uusin"]:
        memory.append(text)
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("poista muisto numero 2")

    assert answer == "Poistin muiston numero 2: M000002: keskimmäinen"
    assert memory.load() == ["vanhin", "uusin"]
    assert client.calls == []


def test_delete_memory_by_latest_list_number_reports_missing_number_without_ollama(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("ainoa")
    brain = Brain(client=client, personality="persoonallisuus", memory=memory)

    answer = brain.respond("poista muisto numero 2")

    assert answer == "En löytänyt muistia tuolla numerolla. Näytä viimeisimmät muistot ja valitse numero listalta."
    assert memory.load() == ["ainoa"]
    assert client.calls == []


def test_non_local_input_includes_memory_context(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
    memory.append("Marko pitää kahvista")
    brain = Brain(client=client, personality="vastaa suomeksi", memory=memory)

    answer = brain.respond("moro")

    assert answer == "Vastaus 1"
    assert client.calls == [("moro", brain._system_context())]
    system_context = client.calls[0][1]
    assert system_context.startswith("vastaa suomeksi")
    assert "Tavalliset muista tämä -muistot" in system_context
    assert "Älä vastaa pelkällä tervehdyksellä" in system_context
    assert "- Marko pitää kahvista" in system_context


def test_system_context_omits_memory_instructions_when_memory_is_empty(tmp_path):
    client = FakeOllamaClient()
    memory = Memory(tmp_path / "memories.local.txt")
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


def test_system_status_collect_returns_requested_fields(monkeypatch, tmp_path):
    from core import system_status

    monkeypatch.setattr(system_status.socket, "gethostname", lambda: "seesam")
    monkeypatch.setattr(system_status.platform, "release", lambda: "6.8.0-test")
    monkeypatch.setattr(system_status, "read_os_name", lambda: "Ubuntu Test")
    monkeypatch.setattr(system_status, "read_cpu_model", lambda: "AMD Test")
    monkeypatch.setattr(system_status, "read_local_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(system_status, "read_temperatures", lambda: {"CPU": 45.5})
    monkeypatch.setattr(system_status, "read_gpu_info", lambda: {"name": "NVIDIA Test GPU"})
    monkeypatch.setattr(system_status, "read_service_status", lambda name: "active")
    monkeypatch.setattr(system_status, "read_memory_file_status", lambda: {"memories.local.txt": "ok"})

    status = SystemStatus(started_at=0, version="test-version")
    data = status.collect()

    assert data["hostname"] == "seesam"
    assert data["os_name"] == "Ubuntu Test"
    assert data["kernel"] == "6.8.0-test"
    assert data["cpu_model"] == "AMD Test"
    assert data["ram_total_gb"] >= 0
    assert data["disk_free_gb"] >= 0
    assert data["temperatures_c"] == {"CPU": 45.5}
    assert data["gpu"] == {"name": "NVIDIA Test GPU"}
    assert data["ollama_status"] == "active"
    assert data["version"] == "test-version"


def test_collect_system_specs_returns_expected_fields_without_gpu(monkeypatch):
    from core import specs

    monkeypatch.setattr(specs.socket, "gethostname", lambda: "seesam")
    monkeypatch.setattr(specs.platform, "release", lambda: "6.8.0-test")
    monkeypatch.setattr(specs, "read_os_name", lambda: "Ubuntu 24.04 LTS")
    monkeypatch.setattr(specs, "read_cpu_model", lambda: "AMD Ryzen Test")
    monkeypatch.setattr(specs, "read_cpu_cores_physical", lambda: 8)
    monkeypatch.setattr(specs, "read_cpu_threads", lambda: 16)
    monkeypatch.setattr(specs, "read_ram_total_bytes", lambda: 32 * specs.GB)
    monkeypatch.setattr(specs, "read_disk_total_bytes", lambda: 512 * specs.GB)
    monkeypatch.setattr(specs, "read_disk_free_bytes", lambda: 128 * specs.GB)
    monkeypatch.setattr(specs, "read_local_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(specs, "read_gpu_name", lambda: None)

    assert specs.collect_system_specs() == {
        "hostname": "seesam",
        "os_name": "Ubuntu 24.04 LTS",
        "kernel": "6.8.0-test",
        "cpu_model": "AMD Ryzen Test",
        "cpu_cores_physical": 8,
        "cpu_threads": 16,
        "ram_total_gb": 32.0,
        "disk_total_gb": 512.0,
        "disk_free_gb": 128.0,
        "local_ip": "192.168.1.10",
    }


def test_collect_system_specs_includes_gpu_when_available(monkeypatch):
    from core import specs

    monkeypatch.setattr(specs.socket, "gethostname", lambda: "seesam")
    monkeypatch.setattr(specs.platform, "release", lambda: "6.8.0-test")
    monkeypatch.setattr(specs, "read_os_name", lambda: "Ubuntu 24.04 LTS")
    monkeypatch.setattr(specs, "read_cpu_model", lambda: "AMD Ryzen Test")
    monkeypatch.setattr(specs, "read_cpu_cores_physical", lambda: 8)
    monkeypatch.setattr(specs, "read_cpu_threads", lambda: 16)
    monkeypatch.setattr(specs, "read_ram_total_bytes", lambda: 32 * specs.GB)
    monkeypatch.setattr(specs, "read_disk_total_bytes", lambda: 512 * specs.GB)
    monkeypatch.setattr(specs, "read_disk_free_bytes", lambda: 128 * specs.GB)
    monkeypatch.setattr(specs, "read_local_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(specs, "read_gpu_name", lambda: "NVIDIA Test GPU")

    assert specs.collect_system_specs()["gpu_name"] == "NVIDIA Test GPU"


def test_read_gpu_name_returns_none_when_nvidia_smi_missing(monkeypatch):
    from core import specs

    def fail_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(specs.subprocess, "run", fail_run)

    assert specs.read_gpu_name() is None


def test_transcribe_audio_uses_faster_whisper_with_finnish_default(monkeypatch):
    from core import stt

    calls = []
    loader_calls = []

    class Segment:
        def __init__(self, text):
            self.text = text

    class FakeModel:
        def transcribe(self, audio_path, language):
            calls.append((audio_path, language))
            return [Segment(" moro"), Segment(" Marko ")], object()

    monkeypatch.setattr(stt, "load_env_file", lambda: None)
    monkeypatch.setenv("STT_ENABLED", "true")
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    monkeypatch.setenv("STT_MODEL", "small")
    monkeypatch.delenv("STT_LANGUAGE", raising=False)
    monkeypatch.delenv("STT_DEVICE", raising=False)
    monkeypatch.delenv("STT_COMPUTE_TYPE", raising=False)

    def fake_load_model(model_name, device, compute_type):
        loader_calls.append((model_name, device, compute_type))
        return FakeModel()

    monkeypatch.setattr(stt, "_load_faster_whisper_model", fake_load_model)

    text = stt.transcribe_audio(b"audio bytes", "voice.wav")

    assert text == "moro Marko"
    assert len(calls) == 1
    assert calls[0][0].endswith(".wav")
    assert calls[0][1] == "fi"
    assert loader_calls == [("small", "cpu", "int8")]


def test_transcribe_audio_returns_clear_error_when_disabled(monkeypatch):
    from core import stt

    monkeypatch.setattr(stt, "load_env_file", lambda: None)
    monkeypatch.setenv("STT_ENABLED", "false")

    try:
        stt.transcribe_audio(b"audio bytes", "voice.wav")
    except stt.STTError as error:
        assert error.status_code == 503
        assert "STT is disabled" in error.detail
    else:
        raise AssertionError("Expected STTError")


def test_transcribe_audio_returns_clear_error_when_model_not_configured(monkeypatch):
    from core import stt

    monkeypatch.setattr(stt, "load_env_file", lambda: None)
    monkeypatch.setenv("STT_ENABLED", "true")
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    monkeypatch.setenv("STT_MODEL", "")

    try:
        stt.transcribe_audio(b"audio bytes", "voice.wav")
    except stt.STTError as error:
        assert error.status_code == 503
        assert "Whisper model is not configured" in error.detail
    else:
        raise AssertionError("Expected STTError")


def test_transcribe_audio_allows_cuda_float16_configuration(monkeypatch):
    from core import stt

    loader_calls = []

    class FakeModel:
        def transcribe(self, audio_path, language):
            return [], object()

    def fake_load_model(model_name, device, compute_type):
        loader_calls.append((model_name, device, compute_type))
        return FakeModel()

    monkeypatch.setattr(stt, "load_env_file", lambda: None)
    monkeypatch.setenv("STT_ENABLED", "true")
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    monkeypatch.setenv("STT_MODEL", "small")
    monkeypatch.setenv("STT_DEVICE", "cuda")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float16")
    monkeypatch.setattr(stt, "_load_faster_whisper_model", fake_load_model)

    assert stt.transcribe_audio(b"audio bytes", "voice.wav") == ""
    assert loader_calls == [("small", "cuda", "float16")]


def test_transcribe_audio_returns_clear_error_when_model_missing(monkeypatch):
    from core import stt

    monkeypatch.setattr(stt, "load_env_file", lambda: None)
    monkeypatch.setenv("STT_ENABLED", "true")
    monkeypatch.setenv("STT_ENGINE", "faster-whisper")
    monkeypatch.setenv("STT_MODEL", "missing-model")

    def fail_load(model_name, device, compute_type):
        raise stt.STTError(
            503,
            f"Whisper model missing or unavailable. STT_MODEL is set to '{model_name}'.",
        )

    monkeypatch.setattr(stt, "_load_faster_whisper_model", fail_load)

    try:
        stt.transcribe_audio(b"audio bytes", "voice.wav")
    except stt.STTError as error:
        assert error.status_code == 503
        assert "Whisper model missing or unavailable" in error.detail
        assert "missing-model" in error.detail
    else:
        raise AssertionError("Expected STTError")


def test_normalize_for_speech_converts_technical_units_and_marks():
    from core import tts

    assert tts.normalize_for_speech("0.8 %") == "0,8 prosenttia"
    assert tts.normalize_for_speech("31 °C") == "31 astetta"
    assert tts.normalize_for_speech("506.3 GiB") == "506,3 gigaa"
    assert (
        tts.normalize_for_speech("RAM-muistia on vapaana 27.12 GiB / 31.23 GiB (13.1 % käytössä).")
        == "RAM-muistia on vapaana 27,12 gigaa 31,23 gigasta. 13,1 prosenttia käytössä."
    )
    assert (
        tts.normalize_for_speech("GPU: NVIDIA GeForce RTX 2080 Ti. VRAM: 150 / 11264 MiB. Lämpötila: 31 °C. Kuorma: 0 %.")
        == "näyttis: NVIDIA GeForce RTX 2080 Ti. näyttömuisti: 150 megaa 11264 megasta. Lämpötila: 31 astetta. Kuorma: 0 prosenttia."
    )
    assert (
        tts.normalize_for_speech("CPU: 11th Gen Intel(R) Core(TM) i5-11400F @ 2.60GHz. IP 1.2.3.4")
        == "prosessori: 11th Gen Intel Core i5-11400F @ 2,60 gigahertsiä. ii pee 1 piste 2 piste 3 piste 4"
    )
    assert (
        tts.normalize_for_speech("230 V, 10 A, 500 mA, 2 kW, 3 Wh, 4 kWh, 1200 RPM")
        == "230 volttia, 10 ampeeria, 500 milliampeeria, 2 kilowattia, 3 wattituntia, 4 kilowattituntia, 1200 kierrosta minuutissa"
    )


def test_tts_disabled_does_not_call_subprocess(monkeypatch):
    from core import tts

    calls = []
    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    monkeypatch.setenv("TTS_ENABLED", "false")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", "/tmp/voice.onnx")
    monkeypatch.setenv("TTS_PIPER_BIN", "piper")
    monkeypatch.setattr(tts.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert tts.is_tts_enabled() is False
    tts.speak("Hei")

    assert calls == []


def test_tts_enabled_calls_piper_and_aplay_with_mocked_subprocess(monkeypatch, tmp_path):
    from core import tts

    calls = []
    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    piper_bin = tmp_path / "piper"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))
    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    tts.speak("Hei Marko")

    assert len(calls) == 2
    assert calls[0][0][:4] == [
        str(piper_bin),
        "--model",
        str(model),
        "--output_file",
    ]
    assert calls[0][1]["input"] == "Hei Marko"
    assert calls[0][1]["text"] is True
    assert calls[0][1]["check"] is True
    assert calls[1][0][0] == "aplay"
    assert calls[1][1]["check"] is True


def test_tts_speak_normalizes_text_before_piper(monkeypatch, tmp_path):
    from core import tts

    calls = []
    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    piper_bin = tmp_path / "piper"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))
    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    tts.speak("GPU: NVIDIA Test. Kuorma: 0.8 %. Lämpötila: 31 °C.")

    assert calls[0][1]["input"] == "näyttis: NVIDIA Test. Kuorma: 0,8 prosenttia. Lämpötila: 31 astetta."


def test_piper_failure_does_not_crash_app(monkeypatch):
    from core import tts

    monkeypatch.setattr(tts, "load_env_file", lambda: None)

    def fail_run(command, **kwargs):
        raise tts.subprocess.CalledProcessError(returncode=1, cmd=command)

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", "/tmp/voice.onnx")
    monkeypatch.setenv("TTS_PIPER_BIN", "piper")
    monkeypatch.setattr(tts.subprocess, "run", fail_run)

    tts.speak("Hei Marko")


def test_synthesize_wav_calls_piper_without_aplay(monkeypatch, tmp_path):
    from core import tts

    calls = []
    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    piper_bin = tmp_path / "piper"
    model.write_text("model", encoding="utf-8")
    piper_bin.write_text("#!/bin/sh", encoding="utf-8")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"RIFF wav bytes")

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))
    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    audio = tts.synthesize_wav(" Hei Marko ")

    assert audio == b"RIFF wav bytes"
    assert len(calls) == 1
    assert calls[0][0][:4] == [str(piper_bin), "--model", str(model), "--output_file"]
    assert calls[0][1]["input"] == "Hei Marko"
    assert calls[0][1]["text"] is True
    assert calls[0][1]["check"] is True


def test_synthesize_wav_normalizes_text_before_piper(monkeypatch, tmp_path):
    from core import tts

    calls = []
    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    piper_bin = tmp_path / "piper"
    model.write_text("model", encoding="utf-8")
    piper_bin.write_text("#!/bin/sh", encoding="utf-8")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"RIFF wav bytes")

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))
    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    audio = tts.synthesize_wav("RAM: 27.12 GiB / 31.23 GiB (13.1 % käytössä).")

    assert audio == b"RIFF wav bytes"
    assert calls[0][1]["input"] == "ram-muisti: 27,12 gigaa 31,23 gigasta. 13,1 prosenttia käytössä."


def test_synthesize_wav_returns_clear_error_when_disabled(monkeypatch):
    from core import tts

    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    monkeypatch.setenv("TTS_ENABLED", "false")

    try:
        tts.synthesize_wav("Hei")
    except tts.TTSError as error:
        assert error.status_code == 503
        assert "TTS is disabled" in error.detail
    else:
        raise AssertionError("Expected TTSError")


def test_synthesize_wav_returns_clear_error_when_model_missing(monkeypatch, tmp_path):
    from core import tts

    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    piper_bin = tmp_path / "piper"
    piper_bin.write_text("#!/bin/sh", encoding="utf-8")

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(tmp_path / "missing.onnx"))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))

    try:
        tts.synthesize_wav("Hei")
    except tts.TTSError as error:
        assert error.status_code == 503
        assert "Piper model missing" in error.detail
        assert "missing.onnx" in error.detail
    else:
        raise AssertionError("Expected TTSError")


def test_synthesize_wav_returns_clear_error_when_piper_binary_missing(monkeypatch, tmp_path):
    from core import tts

    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    model.write_text("model", encoding="utf-8")

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", "missing-piper-bin")
    monkeypatch.setattr(tts.shutil, "which", lambda command: None)

    try:
        tts.synthesize_wav("Hei")
    except tts.TTSError as error:
        assert error.status_code == 503
        assert "Piper binary not found" in error.detail
        assert "missing-piper-bin" in error.detail
    else:
        raise AssertionError("Expected TTSError")


def test_synthesize_wav_returns_clear_error_when_synthesis_fails(monkeypatch, tmp_path):
    from core import tts

    monkeypatch.setattr(tts, "load_env_file", lambda: None)
    model = tmp_path / "voice.onnx"
    piper_bin = tmp_path / "piper"
    model.write_text("model", encoding="utf-8")
    piper_bin.write_text("#!/bin/sh", encoding="utf-8")

    def fail_run(command, **kwargs):
        raise tts.subprocess.CalledProcessError(returncode=1, cmd=command)

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_MODEL", str(model))
    monkeypatch.setenv("TTS_PIPER_BIN", str(piper_bin))
    monkeypatch.setattr(tts.subprocess, "run", fail_run)

    try:
        tts.synthesize_wav("Hei")
    except tts.TTSError as error:
        assert error.status_code == 500
        assert "Piper synthesis failed" in error.detail
    else:
        raise AssertionError("Expected TTSError")
