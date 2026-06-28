"""Minimal HTTP service for the Seesam core container."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DATA_DIR = os.environ.get("SEESAM_DATA_DIR", "/data")


def health_payload() -> dict[str, Any]:
    """Return the health response payload for the service."""
    return {"service": "seesam-core", "status": "ok", "data_dir": DATA_DIR}


class SeesamRequestHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the Seesam core service."""

    server_version = "SeesamCore/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        """Serve the root and health-check endpoints."""
        if self.path in ("/", "/health"):
            self._send_json(health_payload())
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep container logs quiet unless explicitly enabled."""
        if os.environ.get("SEESAM_DEBUG_LOGS") == "1":
            super().log_message(format, *args)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Start the Seesam core HTTP server."""
    server = ThreadingHTTPServer((host, port), SeesamRequestHandler)
    print(f"Seesam core listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run(port=int(os.environ.get("PORT", DEFAULT_PORT)))
