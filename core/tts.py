"""Text-to-speech integration for Seesam."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import load_env_file

DEFAULT_TTS_ENGINE = "piper"
DEFAULT_TTS_MODEL = ""
DEFAULT_TTS_PIPER_BIN = "piper"


class TTSError(Exception):
    """HTTP-safe text-to-speech error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


TEXT_EMOTICON_PATTERN = re.compile(
    r"(?<!\w)(?:[:;=8xX][-oO']?[)(DPp/\\]|[)(][-oO']?[:;=8xX]|<3)(?!\w)"
)
EMOJI_PATTERN = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE0F]+")
TIME_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")

FI_NUMBERS = {
    0: "nolla",
    1: "yksi",
    2: "kaksi",
    3: "kolme",
    4: "neljä",
    5: "viisi",
    6: "kuusi",
    7: "seitsemän",
    8: "kahdeksan",
    9: "yhdeksän",
    10: "kymmenen",
    11: "yksitoista",
    12: "kaksitoista",
    13: "kolmetoista",
    14: "neljätoista",
    15: "viisitoista",
    16: "kuusitoista",
    17: "seitsemäntoista",
    18: "kahdeksantoista",
    19: "yhdeksäntoista",
}

FI_WEEKDAYS = (
    "maanantai",
    "tiistai",
    "keskiviikko",
    "torstai",
    "perjantai",
    "lauantai",
    "sunnuntai",
)

FI_MONTHS_PARTITIVE = (
    "tammikuuta",
    "helmikuuta",
    "maaliskuuta",
    "huhtikuuta",
    "toukokuuta",
    "kesäkuuta",
    "heinäkuuta",
    "elokuuta",
    "syyskuuta",
    "lokakuuta",
    "marraskuuta",
    "joulukuuta",
)

FI_ORDINAL_DAYS = {
    1: "ensimmäinen",
    2: "toinen",
    3: "kolmas",
    4: "neljäs",
    5: "viides",
    6: "kuudes",
    7: "seitsemäs",
    8: "kahdeksas",
    9: "yhdeksäs",
    10: "kymmenes",
    11: "yhdestoista",
    12: "kahdestoista",
    13: "kolmastoista",
    14: "neljästoista",
    15: "viidestoista",
    16: "kuudestoista",
    17: "seitsemästoista",
    18: "kahdeksastoista",
    19: "yhdeksästoista",
    20: "kahdeskymmenes",
    30: "kolmaskymmenes",
}


def sanitize_text_for_tts(text: str) -> str:
    """Remove emoji and text emoticons from text sent to TTS only."""
    cleaned = EMOJI_PATTERN.sub(" ", text)
    cleaned = TEXT_EMOTICON_PATTERN.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_text_for_speech(text: str) -> str:
    """Remove characters that should not be spoken by TTS."""
    return sanitize_text_for_tts(text)


def _fi_weekday_name(weekday: int) -> str:
    """Return Finnish weekday name for date.weekday() values."""
    if 0 <= weekday < len(FI_WEEKDAYS):
        return FI_WEEKDAYS[weekday]
    return str(weekday)


def _fi_month_partitive(month: int) -> str:
    """Return Finnish month name used in spoken dates."""
    if 1 <= month <= len(FI_MONTHS_PARTITIVE):
        return FI_MONTHS_PARTITIVE[month - 1]
    return str(month)


def _fi_ordinal_day(day: int) -> str:
    """Return Finnish ordinal day for spoken dates."""
    if day in FI_ORDINAL_DAYS:
        return FI_ORDINAL_DAYS[day]
    if 21 <= day <= 29:
        return f"{FI_ORDINAL_DAYS[20]} {FI_ORDINAL_DAYS[day - 20]}"
    if day == 31:
        return f"{FI_ORDINAL_DAYS[30]} {FI_ORDINAL_DAYS[1]}"
    return str(day)


def spoken_finnish_date(date_obj) -> str:
    """Return natural Finnish date speech with weekday, day, and month."""
    return f"{_fi_weekday_name(date_obj.weekday())} {_fi_ordinal_day(date_obj.day)} {_fi_month_partitive(date_obj.month)}"


def _fi_number(n: int) -> str:
    """Return a small Finnish cardinal number for spoken time."""
    if n in FI_NUMBERS:
        return FI_NUMBERS[n]
    if 20 <= n <= 59:
        tens = (n // 10) * 10
        ones = n % 10
        tens_word = {
            20: "kaksikymmentä",
            30: "kolmekymmentä",
            40: "neljäkymmentä",
            50: "viisikymmentä",
        }[tens]
        return tens_word if ones == 0 else f"{tens_word} {FI_NUMBERS[ones]}"
    return str(n)


def _spoken_hour(hour: int) -> str:
    return _fi_number(hour % 24)


def _spoken_finnish_time(hour: int, minute: int, precise: bool = False) -> str:
    """Return natural Finnish speech for a clock time without seconds."""
    hour %= 24
    minute = max(0, min(59, minute))
    next_hour = (hour + 1) % 24

    if precise:
        if minute == 0:
            return _spoken_hour(hour)
        return f"{_spoken_hour(hour)} {_fi_number(minute)}"

    if minute == 0:
        return _spoken_hour(hour)
    if 1 <= minute <= 7:
        return f"vähän yli {_spoken_hour(hour)}"
    if 13 <= minute <= 17:
        return f"varttia yli {_spoken_hour(hour)}"
    if 28 <= minute <= 32:
        return f"puoli {_spoken_hour(next_hour)}"
    if 43 <= minute <= 47:
        return f"varttia vaille {_spoken_hour(next_hour)}"
    if 53 <= minute <= 59:
        return f"kohta {_spoken_hour(next_hour)}"
    return f"{_spoken_hour(hour)} {_fi_number(minute)}"


def is_approximate_finnish_time(minute: int) -> bool:
    """Return whether normal Finnish time speech rounds the minute range."""
    return 1 <= minute <= 7 or 13 <= minute <= 17 or 28 <= minute <= 32 or 43 <= minute <= 47 or 53 <= minute <= 59


def normalize_times_for_tts(text: str, precise: bool = False) -> str:
    """Convert digital clock times to Finnish spoken form."""

    def replace_time(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return match.group(0)
        return _spoken_finnish_time(hour, minute, precise=precise)

    return TIME_PATTERN.sub(replace_time, text)


def normalize_for_speech(text: str) -> str:
    """Return text normalized for Finnish text-to-speech only."""
    spoken = sanitize_text_for_tts(text)
    if not spoken:
        return ""

    spoken = normalize_times_for_tts(spoken)
    spoken = spoken.replace("Intel(R)", "Intel").replace("Core(TM)", "Core")
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*GiB\s*/\s*(\d+(?:\.\d+)?)\s*GiB",
        r"\1 gigaa \2 gigasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*GB\s*/\s*(\d+(?:\.\d+)?)\s*GB",
        r"\1 gigaa \2 gigasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*MiB\s*/\s*(\d+(?:\.\d+)?)\s*MiB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*MB\s*/\s*(\d+(?:\.\d+)?)\s*MB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*MiB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*MB",
        r"\1 megaa \2 megasta",
        spoken,
    )
    spoken = re.sub(r"\s*\(([^()]*)\)", r". \1", spoken)

    replacements = [
        (r"\bVRAM\b", "näyttömuisti"),
        (r"\bRAM\b(?!-muisti)", "ram-muisti"),
        (r"\bGPU\b", "näyttis"),
        (r"\bCPU\b", "prosessori"),
        (r"\bIP\b", "ii pee"),
        (r"(?<=\d)\s*kWh\b", " kilowattituntia"),
        (r"(?<=\d)\s*Wh\b", " wattituntia"),
        (r"(?<=\d)\s*GHz\b", " gigahertsiä"),
        (r"(?<=\d)\s*MHz\b", " megahertsiä"),
        (r"(?<=\d)\s*GiB\b", " gigaa"),
        (r"(?<=\d)\s*GB\b", " gigaa"),
        (r"(?<=\d)\s*MiB\b", " megaa"),
        (r"(?<=\d)\s*MB\b", " megaa"),
        (r"(?<=\d)\s*kW\b", " kilowattia"),
        (r"(?<=\d)\s*mA\b", " milliampeeria"),
        (r"(?<=\d)\s*RPM\b", " kierrosta minuutissa"),
        (r"(?<=\d)\s*W\b", " wattia"),
        (r"(?<=\d)\s*V\b", " volttia"),
        (r"(?<=\d)\s*A\b", " ampeeria"),
        (r"(?<=\d)\s*°C\b", " astetta"),
        (r"(?<=\d)\s*°", " astetta"),
        (r"(?<=\d)\s*%", " prosenttia"),
    ]
    for pattern, replacement in replacements:
        spoken = re.sub(pattern, replacement, spoken)

    spoken = re.sub(
        r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b",
        r"\1 piste \2 piste \3 piste \4",
        spoken,
    )
    spoken = re.sub(r"(?<=\d)\.(?=\d)", ",", spoken)
    spoken = re.sub(r"\s*/\s*", " ", spoken)
    spoken = re.sub(r"\s+", " ", spoken)
    spoken = re.sub(r"\s+([.,:;!?])", r"\1", spoken)
    spoken = re.sub(r"\.\s*\.", ".", spoken)
    return spoken.strip()


def is_tts_enabled() -> bool:
    """Return whether text-to-speech should be used for responses."""
    load_env_file()
    return os.environ.get("TTS_ENABLED", "false").strip().casefold() == "true"


def synthesize_wav(text: str) -> bytes:
    """Generate WAV audio bytes with Piper without playing audio."""
    text = text.strip()
    if not text:
        raise TTSError(400, "Text must not be empty.")

    text = normalize_for_speech(text)
    if not text:
        raise TTSError(400, "Text must not be empty.")

    if not is_tts_enabled():
        raise TTSError(
            503,
            "TTS is disabled. Set TTS_ENABLED=true to enable speech synthesis.",
        )

    engine = os.environ.get("TTS_ENGINE", DEFAULT_TTS_ENGINE).strip().casefold()
    if engine != "piper":
        raise TTSError(503, "Only Piper text-to-speech is supported.")

    model = os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL).strip()
    piper_bin = os.environ.get("TTS_PIPER_BIN", DEFAULT_TTS_PIPER_BIN).strip()
    if not model:
        raise TTSError(
            503,
            "Piper model is not configured. Set TTS_MODEL to a local .onnx model file.",
        )
    if not Path(model).is_file():
        raise TTSError(
            503,
            f"Piper model missing. TTS_MODEL points to '{model}', but that file does not exist.",
        )
    if not piper_bin:
        raise TTSError(
            503,
            "Piper binary is not configured. Set TTS_PIPER_BIN to 'piper' or an executable path.",
        )
    piper_path = Path(piper_bin)
    if piper_path.is_absolute() or piper_path.parent != Path("."):
        if not piper_path.is_file():
            raise TTSError(
                503,
                f"Piper binary not found. TTS_PIPER_BIN points to '{piper_bin}', but that file does not exist.",
            )
        piper_command = piper_bin
    else:
        piper_command = shutil.which(piper_bin)
        if piper_command is None:
            raise TTSError(
                503,
                f"Piper binary not found. Could not find '{piper_bin}' on PATH.",
            )

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = Path(wav_file.name)

        try:
            subprocess.run(
                [piper_command, "--model", model, "--output_file", str(wav_path)],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return wav_path.read_bytes()
        finally:
            wav_path.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise TTSError(
            500,
            f"Piper synthesis failed while generating WAV audio: {error}",
        ) from error


def speak(text: str) -> None:
    """Speak text aloud with Piper and aplay when TTS is enabled.

    TTS failures are intentionally swallowed so terminal chat keeps working even
    if Piper, the model file, or audio playback is unavailable.
    """
    text = text.strip()
    if not is_tts_enabled() or not text:
        return

    text = normalize_for_speech(text)
    if not text:
        return

    engine = os.environ.get("TTS_ENGINE", DEFAULT_TTS_ENGINE).strip().casefold()
    if engine != "piper":
        return

    model = os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL).strip()
    piper_bin = os.environ.get("TTS_PIPER_BIN", DEFAULT_TTS_PIPER_BIN).strip()
    if not model or not piper_bin:
        return

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = Path(wav_file.name)

        try:
            subprocess.run(
                [piper_bin, "--model", model, "--output_file", str(wav_path)],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["aplay", str(wav_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            wav_path.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError):
        return
