"""Audio output device management for Seesam."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name("audio_devices.json")
SPEAKERS_SLEEPING_MESSAGE = "Steljes-kaiuttimet eivät vastaa. Herätä ne Bluetooth-tilaan."
SINK_NOT_ACTIVATED_MESSAGE = (
    "Bluetooth-yhteys on päällä, mutta äänilaite ei aktivoitunut. "
    "Kokeile käynnistää Seesamin äänipalvelut tai reboot."
)


@dataclass(frozen=True)
class AudioResult:
    """Result from ensuring an audio output device."""

    success: bool
    message: str
    device_id: str | None = None
    sink_id: str | None = None


class AudioManagerError(RuntimeError):
    """Raised when audio device configuration is invalid."""


def load_audio_devices(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load audio output device configuration."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AudioManagerError(f"Audio device configuration could not be loaded: {error}") from error

    if not isinstance(data, dict) or not isinstance(data.get("devices"), dict):
        raise AudioManagerError("Audio device configuration must include a devices object.")
    return data


def find_device_id_for_text(text: str, path: Path = CONFIG_PATH) -> str | None:
    """Return a configured device id when user text mentions a device alias."""
    normalized = text.casefold()
    config = load_audio_devices(path)
    for device_id, device in config["devices"].items():
        aliases = [device.get("name", ""), *device.get("aliases", [])]
        if any(str(alias).casefold() in normalized for alias in aliases if alias):
            return str(device.get("id") or device_id)
    return None


def ensure_default_media_output() -> AudioResult:
    """Ensure the configured default media output is ready."""
    return ensure_media_output(None, CONFIG_PATH)


def ensure_media_output(device_id: str | None = None, path: Path = CONFIG_PATH) -> AudioResult:
    """Ensure the configured media output is connected, selected, and at configured volume."""
    try:
        config = load_audio_devices(path)
    except AudioManagerError as error:
        return AudioResult(False, str(error))

    devices = config["devices"]
    media_output = config.get("media_output")
    selected_id = device_id
    if selected_id is None and isinstance(media_output, dict):
        selected_id = media_output.get("default")
    if not selected_id:
        if len(devices) == 1:
            selected_id = next(iter(devices))
        else:
            return AudioResult(False, "Mediaulostuloa ei ole valittu. Kerro missä musiikki toistetaan.")

    device = devices.get(str(selected_id))
    if not isinstance(device, dict):
        return AudioResult(False, f"Äänilaitetta '{selected_id}' ei löydy asetuksista.")

    if device.get("type") != "bluetooth":
        return AudioResult(False, f"Äänilaitteen '{selected_id}' tyyppiä ei tueta vielä.")

    return _ensure_bluetooth_output(str(selected_id), device)


def _ensure_bluetooth_output(device_id: str, device: dict[str, Any]) -> AudioResult:
    name = str(device.get("name") or device_id)
    mac = str(device.get("mac") or "").strip()
    if not mac:
        return AudioResult(False, f"Bluetooth-laitteelta '{name}' puuttuu MAC-osoite.", device_id)

    volume = _format_volume(device.get("volume", 0.40))

    power_result = _run(["bluetoothctl", "power", "on"])
    if not power_result.success:
        return AudioResult(False, f"Bluetoothin käynnistys epäonnistui: {power_result.message}", device_id)

    info_result = _run(["bluetoothctl", "info", mac])
    connected = info_result.success and "Connected: yes" in info_result.message
    if not connected:
        connect_result = _run(["bluetoothctl", "connect", mac])
        if not connect_result.success:
            if _is_sleeping_speaker_error(connect_result.message):
                return AudioResult(False, SPEAKERS_SLEEPING_MESSAGE, device_id)
            return AudioResult(False, f"Laitteeseen {name} yhdistäminen epäonnistui: {connect_result.message}", device_id)
        connected = True

    time.sleep(3)

    status_result = _run(["wpctl", "status"])
    if not status_result.success:
        return AudioResult(False, f"Äänilaitteiden listaus epäonnistui: {status_result.message}", device_id)

    sink_lines = _sink_lines(status_result.message)
    sink_id = _find_sink_id(status_result.message, name)
    if sink_id is None:
        if connected:
            return AudioResult(False, SINK_NOT_ACTIVATED_MESSAGE, device_id)
        seen = "\n".join(sink_lines) if sink_lines else "ei sink-rivejä"
        return AudioResult(
            False,
            f"Äänilaitetta '{name}' ei löytynyt wpctl status -tulosteen Sinks-osiosta. Sink-rivit:\n{seen}",
            device_id,
        )

    default_result = _run(["wpctl", "set-default", sink_id])
    if not default_result.success:
        return AudioResult(False, f"Oletusulostulon asetus epäonnistui: {default_result.message}", device_id, sink_id)

    volume_result = _run(["wpctl", "set-volume", sink_id, volume])
    if not volume_result.success:
        return AudioResult(False, f"Äänenvoimakkuuden asetus epäonnistui: {volume_result.message}", device_id, sink_id)

    return AudioResult(True, "Steljes-kaiuttimet yhdistetty.", device_id, sink_id)


def _is_sleeping_speaker_error(message: str) -> bool:
    normalized = message.casefold()
    return "br-connection-page-timeout" in normalized or ("device" in normalized and "not available" in normalized)


def _run(command: list[str]) -> AudioResult:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as error:
        return AudioResult(False, str(error))

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        return AudioResult(False, output or f"{command[0]} exited with {result.returncode}")
    return AudioResult(True, output)


def _sink_lines(wpctl_status: str) -> list[str]:
    lines: list[str] = []
    in_sinks = False
    for line in wpctl_status.splitlines():
        stripped = line.strip()
        label = stripped.lstrip("│├└─ ").strip()
        if label == "Sinks:":
            in_sinks = True
            continue
        if in_sinks and label.endswith(":") and not label.startswith(("*", "│", "├", "└")):
            break
        if in_sinks and stripped:
            lines.append(line)
    return lines

def _find_sink_id(wpctl_status: str, device_name: str) -> str | None:
    sink_line_pattern = re.compile(r"^\s*(?:[│├└─]\s*)*(?:\*\s*)?(\d+)\.\s+(.+?)(?:\s+\[|$)")
    for line in _sink_lines(wpctl_status):
        normalized_line = line.replace("│", " ").replace("├", " ").replace("└", " ").replace("─", " ")
        match = sink_line_pattern.match(normalized_line)
        if match is None:
            continue
        sink_id, sink_name = match.groups()
        if sink_name.strip() == device_name:
            return sink_id
    return None

def _format_volume(value: Any) -> str:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = 0.40
    return f"{volume:.2f}"
