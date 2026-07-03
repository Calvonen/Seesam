"""EnergyZen hot-water tank readings from Supabase."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPABASE_ENDPOINT = "https://amyvzelzbvjvrevikvrp.supabase.co/rest/v1/tank_readings"
LATEST_READING_URL = f"{SUPABASE_ENDPOINT}?select=*&order=created_at.desc&limit=1"
DEFAULT_TIMEOUT_SECONDS = 5
MIN_TANK_TEMPERATURE = 10.0
FULL_TANK_AVERAGE_TEMPERATURE = 61.0
SHOWERS_AT_FULL_TANK = 8.0


class EnergyZenError(RuntimeError):
    """Raised when EnergyZen readings cannot be fetched or parsed."""


@dataclass(frozen=True)
class TankReading:
    """Latest EnergyZen hot-water tank values."""

    top_temp: float
    bottom_temp: float
    heating: bool
    showers: float | None = None
    created_at: str | None = None

    @property
    def estimated_showers(self) -> float:
        """Estimated showers left, calculated with EnergyZen app settings."""
        return calculate_showers(self.top_temp, self.bottom_temp)


def get_latest_reading() -> TankReading:
    """Fetch the newest tank_readings row from Supabase."""
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    if not supabase_key:
        raise EnergyZenError("SUPABASE_KEY is not configured.")

    request = Request(
        LATEST_READING_URL,
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        },
    )

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise EnergyZenError("EnergyZen readings are unreachable.") from exc

    try:
        data = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise EnergyZenError("EnergyZen response was not valid JSON.") from exc

    if not isinstance(data, list) or not data:
        raise EnergyZenError("EnergyZen response did not include readings.")

    first = data[0]
    if not isinstance(first, dict):
        raise EnergyZenError("EnergyZen reading was not an object.")

    return _parse_reading(first)


def format_reading(reading: TankReading) -> str:
    """Return a concise Finnish answer for the latest tank reading."""
    heating_state = "päällä" if reading.heating else "pois päältä"
    return (
        f"Varaajan yläosa on {_format_temperature(reading.top_temp)} astetta, "
        f"alaosa {_format_temperature(reading.bottom_temp)} astetta. "
        f"Lämmitys on {heating_state} ja lämmintä vettä riittää arviolta "
        f"{_format_showers(reading.estimated_showers)} suihkuun."
    )


def calculate_showers(top_temp: float, bottom_temp: float) -> float:
    """Calculate estimated showers left using EnergyZen app settings."""
    average_temp = (top_temp + bottom_temp) / 2
    fill_ratio = (average_temp - MIN_TANK_TEMPERATURE) / (
        FULL_TANK_AVERAGE_TEMPERATURE - MIN_TANK_TEMPERATURE
    )
    clamped_fill_ratio = min(max(fill_ratio, 0.0), 1.0)
    return clamped_fill_ratio * SHOWERS_AT_FULL_TANK


def _parse_reading(data: dict[str, Any]) -> TankReading:
    try:
        return TankReading(
            top_temp=_parse_float(data["top_temp"]),
            bottom_temp=_parse_float(data["bottom_temp"]),
            heating=_parse_bool(data["heating"]),
            showers=_parse_optional_float(data.get("showers")),
            created_at=str(data["created_at"]) if data.get("created_at") is not None else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EnergyZenError("EnergyZen reading was missing required values.") from exc


def _parse_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    return float(value)


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _parse_float(value)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "päällä", "paalla"}:
            return True
        if normalized in {"false", "0", "no", "off", "pois", "pois päältä", "pois paalta"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError("invalid boolean")


def _format_temperature(value: float) -> str:
    return f"{value:.0f}"


def _format_showers(value: float) -> str:
    return f"{value:.0f}"
