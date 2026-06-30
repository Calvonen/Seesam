"""Server status collection helpers."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GB = 1024**3
SERVICE_NAMES = ("ssh", "fail2ban", "ollama")


@dataclass(frozen=True)
class StatusCollector:
    """Collect server-only runtime status values."""

    started_at: float

    @classmethod
    def started_now(cls) -> "StatusCollector":
        return cls(started_at=time.monotonic())

    def collect(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "hostname": socket.gethostname(),
            "uptime": round(time.monotonic() - self.started_at, 2),
            "cpu_percent": read_cpu_percent(),
            "memory_used_gb": round_gb(read_memory_used_bytes()),
            "memory_total_gb": round_gb(read_memory_total_bytes()),
            "disk_used_gb": round_gb(read_disk_used_bytes()),
            "disk_total_gb": round_gb(read_disk_total_bytes()),
            "local_ip": read_local_ip(),
            "services": {name: read_service_status(name) for name in SERVICE_NAMES},
        }

        gpu_name = read_gpu_name()
        if gpu_name:
            status["gpu_name"] = gpu_name

        return status


def round_gb(value: int) -> float:
    return round(value / GB, 2)


def read_cpu_percent() -> float:
    first = read_cpu_times()
    time.sleep(0.1)
    second = read_cpu_times()

    idle_delta = second["idle"] - first["idle"]
    total_delta = second["total"] - first["total"]
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 1)


def read_cpu_times() -> dict[str, int]:
    line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    values = [int(value) for value in line.split()[1:]]
    idle = values[3] + values[4]
    return {"idle": idle, "total": sum(values)}


def read_memory_total_bytes() -> int:
    meminfo = read_meminfo()
    return meminfo["MemTotal"] * 1024


def read_memory_used_bytes() -> int:
    meminfo = read_meminfo()
    total = meminfo["MemTotal"]
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    return (total - available) * 1024


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", maxsplit=1)
        values[key] = int(value.strip().split()[0])
    return values


def read_disk_total_bytes() -> int:
    return shutil.disk_usage("/").total


def read_disk_used_bytes() -> int:
    return shutil.disk_usage("/").used


def read_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "unknown"


def read_service_status(service_name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return "unknown"

    status = result.stdout.strip()
    return status or "unknown"


def read_gpu_name() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None

    if result.returncode != 0:
        return None

    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names[0] if names else None
