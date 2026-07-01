"""Server hardware and OS specification helpers."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any


GB = 1024**3


def collect_system_specs() -> dict[str, Any]:
    """Collect read-only server hardware and OS information."""
    specs: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os_name": read_os_name(),
        "kernel": platform.release(),
        "cpu_model": read_cpu_model(),
        "cpu_cores_physical": read_cpu_cores_physical(),
        "cpu_threads": read_cpu_threads(),
        "ram_total_gb": round_gb(read_ram_total_bytes()),
        "disk_total_gb": round_gb(read_disk_total_bytes()),
        "disk_free_gb": round_gb(read_disk_free_bytes()),
        "local_ip": read_local_ip(),
    }

    gpu_name = read_gpu_name()
    if gpu_name:
        specs["gpu_name"] = gpu_name

    return specs


def round_gb(value: int) -> float:
    return round(value / GB, 2)


def read_os_name() -> str:
    try:
        freedesktop = platform.freedesktop_os_release()
    except OSError:
        return platform.platform()

    return freedesktop.get("PRETTY_NAME") or freedesktop.get("NAME") or platform.platform()


def read_cpu_model() -> str:
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", maxsplit=1)[1].strip()
            if line.startswith("Hardware"):
                return line.split(":", maxsplit=1)[1].strip()

    processor = platform.processor()
    return processor or "unknown"


def read_cpu_cores_physical() -> int:
    try:
        import psutil
    except ImportError:
        return os.cpu_count() or 0

    return psutil.cpu_count(logical=False) or os.cpu_count() or 0


def read_cpu_threads() -> int:
    try:
        import psutil
    except ImportError:
        return os.cpu_count() or 0

    return psutil.cpu_count(logical=True) or os.cpu_count() or 0


def read_ram_total_bytes() -> int:
    try:
        import psutil
    except ImportError:
        return read_memory_total_bytes_from_proc()

    return int(psutil.virtual_memory().total)


def read_memory_total_bytes_from_proc() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", maxsplit=1)
        if key == "MemTotal":
            return int(value.strip().split()[0]) * 1024
    return 0


def read_disk_usage() -> Any:
    try:
        import psutil
    except ImportError:
        return shutil.disk_usage("/")

    return psutil.disk_usage("/")


def read_disk_total_bytes() -> int:
    return int(read_disk_usage().total)


def read_disk_free_bytes() -> int:
    return int(read_disk_usage().free)


def read_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "unknown"


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
