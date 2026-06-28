"""Local command handling for Seesam terminal chat."""

from __future__ import annotations

WAKE_COMMAND = "seesam aukene"
WAKE_RESPONSE = "Kuuntelen."


def handle_local_command(user_input: str) -> str | None:
    """Return a local response when input matches a built-in command."""
    if WAKE_COMMAND in user_input.casefold():
        return WAKE_RESPONSE

    return None
