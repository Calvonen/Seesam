"""Small Ollama API client used by the Seesam terminal assistant."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_MODEL = "gemma3:1b"
DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaError(RuntimeError):
    """Raised when Ollama cannot produce a response."""


@dataclass(frozen=True)
class OllamaClient:
    """Client for Ollama's local generation API."""

    model: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    timeout: float = 120.0

    def generate(self, prompt: str, system_prompt: str) -> str:
        """Generate a response from Ollama for the terminal chat."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }
        request = Request(
            f"{self.host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OllamaError(f"Ollama palautti virheen {exc.code}.") from exc
        except URLError as exc:
            raise OllamaError("Ollamaan ei saatu yhteyttä. Käynnistä Ollama ja varmista malli.") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollaman vastausta ei voitu lukea.") from exc

        answer = str(data.get("response", "")).strip()
        if not answer:
            raise OllamaError("Ollama ei palauttanut vastausta.")

        return answer
