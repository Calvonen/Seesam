"""Local Shelly Gen2 RPC client and device configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_CHANNEL = 0
DEFAULT_TIMEOUT_SECONDS = 3


class ShellyError(RuntimeError):
    """Raised when a Shelly device cannot be reached or parsed."""


@dataclass(frozen=True)
class ShellyDevice:
    """One configured local Shelly device."""

    name: str
    type: str
    ip: str
    channel: int = DEFAULT_CHANNEL
    aliases: tuple[str, ...] = ()


def switch_on(ip: str, channel: int = DEFAULT_CHANNEL) -> dict[str, Any]:
    """Turn on one Shelly switch channel through the Gen2 RPC API."""
    return _rpc(ip, "Switch.Set", {"id": channel, "on": "true"})


def switch_off(ip: str, channel: int = DEFAULT_CHANNEL) -> dict[str, Any]:
    """Turn off one Shelly switch channel through the Gen2 RPC API."""
    return _rpc(ip, "Switch.Set", {"id": channel, "on": "false"})


def get_status(ip: str, channel: int = DEFAULT_CHANNEL) -> dict[str, Any]:
    """Return one Shelly switch channel status through the Gen2 RPC API."""
    return _rpc(ip, "Switch.GetStatus", {"id": channel})


def load_devices(path: Path) -> dict[str, ShellyDevice]:
    """Load the limited devices.local.yaml shape used by Seesam."""
    if not path.exists():
        return {}

    devices: dict[str, dict[str, Any]] = {}
    in_devices = False
    current_name: str | None = None
    current_list_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            in_devices = line == "devices:"
            current_name = None
            continue

        if not in_devices:
            continue

        if indent == 2 and line.endswith(":"):
            current_name = line[:-1].strip()
            devices[current_name] = {}
            current_list_key = None
            continue

        if indent == 4 and current_name is not None and ":" in line:
            key, value = line.split(":", 1)
            current_list_key = None
            if not value.strip():
                current_list_key = key.strip()
                devices[current_name][current_list_key] = []
                continue
            devices[current_name][key.strip()] = _parse_scalar(value)
            continue

        if (
            indent == 6
            and current_name is not None
            and current_list_key is not None
            and line.startswith("- ")
        ):
            items = devices[current_name].setdefault(current_list_key, [])
            if isinstance(items, list):
                items.append(_parse_scalar(line[2:]))

    loaded: dict[str, ShellyDevice] = {}
    for name, values in devices.items():
        ip = values.get("ip", "").strip()
        device_type = values.get("type", "").strip()
        if not ip or not device_type:
            continue

        loaded[name] = ShellyDevice(
            name=name,
            type=device_type,
            ip=ip,
            channel=_parse_channel(values.get("channel")),
            aliases=_parse_aliases(values.get("aliases")),
        )

    return loaded


def _rpc(ip: str, method: str, params: dict[str, object]) -> dict[str, Any]:
    query = urlencode(params)
    url = f"http://{ip}/rpc/{method}?{query}"

    try:
        with urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ShellyError("Shelly device is unreachable.") from exc

    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise ShellyError("Shelly response was not valid JSON.") from exc

    if not isinstance(data, dict):
        raise ShellyError("Shelly response was not a JSON object.")

    return data


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def _parse_channel(value: str | None) -> int:
    if value is None:
        return DEFAULT_CHANNEL

    try:
        return int(value.strip())
    except ValueError:
        return DEFAULT_CHANNEL


def _parse_aliases(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    aliases = []
    for item in value:
        alias = str(item).strip()
        if alias:
            aliases.append(alias)
    return tuple(aliases)
