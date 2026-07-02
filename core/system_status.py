"""Local system status helpers for Seesam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import time
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    psutil = None

from core.config import PROJECT_ROOT

GB = 1024**3
VERSION = "local-file-memory-v1"
TIME_WORDS = {"aika", "kello", "kellonaika"}
DATE_PHRASES = {"mikä päivä tänään on", "mikä päivä tanaan on"}
CPU_WORDS = {"cpu", "prosessori", "suoritin"}
GPU_WORDS = {"gpu", "näytönohjain", "naytonohjain", "grafiikkakortti", "näyttis", "nayttis"}
RAM_WORDS = {"ram", "muisti", "keskusmuisti"}
DISK_WORDS = {"levy", "levytila", "levytilaa", "disk"}
OLLAMA_WORDS = {"ollama"}
MACHINE_CONTEXT_WORDS = {"kone", "koneessa", "serveri", "serverin", "palvelin", "palvelimen"}
GENERAL_STATUS_PHRASES = {
    "miten kone voi",
    "mikä on koneen tila",
    "mika on koneen tila",
    "näytä koneen tiedot",
    "nayta koneen tiedot",
    "näytä serverin speksit",
    "nayta serverin speksit",
}

MEMORY_LOCAL_PATHS = (
    PROJECT_ROOT / "memory" / "seesam.local.yaml",
    PROJECT_ROOT / "memory" / "marko.local.yaml",
    PROJECT_ROOT / "memory" / "memories.local.txt",
    PROJECT_ROOT / "memory" / "episodes.local.log",
)


def normalize_user_text(text: str) -> str:
    """Normalize spoken Finnish command text for keyword matching."""
    lowered = text.lower()
    without_punctuation = re.sub(r"[^0-9a-zåäö]+", " ", lowered)
    return " ".join(without_punctuation.strip().split())


def words_in(text: str) -> set[str]:
    """Return normalized whitespace-separated words."""
    return set(text.split())


def has_any(words: set[str], candidates: set[str]) -> bool:
    return bool(words & candidates)


def has_machine_context(words: set[str]) -> bool:
    return has_any(words, MACHINE_CONTEXT_WORDS)


def is_memory_management_phrase(normalized: str) -> bool:
    """Avoid confusing Seesam's memory commands with RAM questions."""
    return normalized in {
        "mitä muistat",
        "mita muistat",
        "näytä muisti",
        "nayta muisti",
        "näytä muistot",
        "nayta muistot",
        "näytä viimeisimmät muistot",
        "nayta viimeisimmat muistot",
        "mikä on viimeisin muistosi",
        "mika on viimeisin muistosi",
        "mikä on viimeisin tallennettu muistosi",
        "mika on viimeisin tallennettu muistosi",
    } or normalized.startswith("muista ") or normalized.startswith("tallenna syvään muistiin")


def gb(value: int | float) -> float:
    """Return bytes as rounded GiB."""
    return round(float(value) / GB, 2)


def format_duration(seconds: float) -> str:
    """Return a compact Finnish uptime string."""
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} pv")
    if hours:
        parts.append(f"{hours} h")
    if minutes or not parts:
        parts.append(f"{minutes} min")
    return " ".join(parts)


def read_os_name() -> str:
    """Return a human-readable OS name."""
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return platform.platform()
    return release.get("PRETTY_NAME") or release.get("NAME") or platform.platform()


def read_cpu_model() -> str:
    """Return CPU model from procfs when available."""
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name") or line.startswith("Hardware"):
                return line.split(":", maxsplit=1)[1].strip()
    return platform.processor() or "unknown"


def read_local_ip() -> str:
    """Return primary local IP without sending traffic."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "unknown"


def read_gpu_info() -> dict[str, object] | None:
    """Return GPU data from nvidia-smi when available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None

    if result.returncode != 0:
        return None

    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_line:
        return None

    parts = [part.strip() for part in first_line.split(",")]
    info: dict[str, object] = {"name": parts[0]}
    if len(parts) >= 3:
        info["memory_used_mb"] = _parse_int(parts[1])
        info["memory_total_mb"] = _parse_int(parts[2])
    if len(parts) >= 4:
        info["temperature_c"] = _parse_int(parts[3])
    if len(parts) >= 5:
        info["utilization_percent"] = _parse_int(parts[4])
    return info


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def read_temperatures() -> dict[str, float]:
    """Return current sensor temperatures when psutil exposes them."""
    if psutil is None or not hasattr(psutil, "sensors_temperatures"):
        return {}

    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False)
    except (OSError, RuntimeError):
        return {}

    temperatures: dict[str, float] = {}
    for sensor_name, entries in sensors.items():
        for index, entry in enumerate(entries):
            if entry.current is None:
                continue
            label = entry.label or (sensor_name if len(entries) == 1 else f"{sensor_name}_{index + 1}")
            temperatures[label] = round(float(entry.current), 1)
    return temperatures


def read_service_status(service_name: str) -> str:
    """Return systemd service status, or unknown when systemd is unavailable."""
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
    return result.stdout.strip() or "unknown"


def read_memory_file_status() -> dict[str, str]:
    """Return exists/missing status for local memory files."""
    return {path.name: "ok" if path.exists() else "missing" for path in MEMORY_LOCAL_PATHS}


def read_uptime_seconds() -> float:
    """Return OS uptime in seconds."""
    if psutil is not None:
        return time.time() - psutil.boot_time()

    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return 0.0


def read_virtual_memory() -> dict[str, float]:
    """Return memory totals in bytes with a psutil-compatible shape."""
    if psutil is not None:
        memory = psutil.virtual_memory()
        return {
            "total": float(memory.total),
            "available": float(memory.available),
            "used": float(memory.used),
            "percent": round(float(memory.percent), 1),
        }

    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", maxsplit=1)
            values[key] = int(value.strip().split()[0]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return {"total": 0.0, "available": 0.0, "used": 0.0, "percent": 0.0}

    total = float(values.get("MemTotal", 0))
    available = float(values.get("MemAvailable", values.get("MemFree", 0)))
    used = max(0.0, total - available)
    percent = round(used / total * 100, 1) if total else 0.0
    return {"total": total, "available": available, "used": used, "percent": percent}


def read_cpu_percent() -> float:
    """Return current CPU utilization percentage."""
    if psutil is not None:
        return round(float(psutil.cpu_percent(interval=0.1)), 1)

    first = read_proc_cpu_times()
    time.sleep(0.1)
    second = read_proc_cpu_times()
    total_delta = second["total"] - first["total"]
    idle_delta = second["idle"] - first["idle"]
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 1)


def read_proc_cpu_times() -> dict[str, int]:
    try:
        values = [int(value) for value in Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]]
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return {"idle": 0, "total": 0}
    idle = values[3] + values[4]
    return {"idle": idle, "total": sum(values)}


def read_load_average() -> list[float]:
    """Return 1/5/15 minute load averages when available."""
    if psutil is not None and hasattr(psutil, "getloadavg"):
        return list(psutil.getloadavg())
    try:
        return [float(value) for value in Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3]]
    except (FileNotFoundError, OSError, ValueError):
        return []


def read_cpu_count(logical: bool) -> int:
    """Return CPU count with psutil preferred and procfs as fallback."""
    if psutil is not None:
        return psutil.cpu_count(logical=logical) or 0
    if logical:
        return __import__("os").cpu_count() or 0

    try:
        blocks = Path("/proc/cpuinfo").read_text(encoding="utf-8").strip().split("\n\n")
    except (FileNotFoundError, OSError):
        return 0

    cores: set[tuple[str, str]] = set()
    for block in blocks:
        values: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            values[key.strip()] = value.strip()
        physical_id = values.get("physical id", "0")
        core_id = values.get("core id")
        if core_id is not None:
            cores.add((physical_id, core_id))

    return len(cores) if cores else (__import__("os").cpu_count() or 0)


@dataclass(frozen=True)
class SystemStatus:
    """Collect local server status and render Finnish answers."""

    started_at: float
    version: str = VERSION

    @classmethod
    def started_now(cls) -> "SystemStatus":
        return cls(started_at=time.monotonic())

    def collect(self) -> dict[str, Any]:
        """Collect real-time server status values."""
        now = datetime.now().astimezone()
        uptime_seconds = read_uptime_seconds()
        memory = read_virtual_memory()
        disk = shutil.disk_usage("/")
        cpu_percent = read_cpu_percent()
        load_average = read_load_average()
        data: dict[str, Any] = {
            "server_time": now.isoformat(timespec="seconds"),
            "server_date": now.date().isoformat(),
            "uptime_seconds": round(uptime_seconds, 2),
            "uptime": format_duration(uptime_seconds),
            "process_uptime_seconds": round(time.monotonic() - self.started_at, 2),
            "hostname": socket.gethostname(),
            "local_ip": read_local_ip(),
            "os_name": read_os_name(),
            "kernel": platform.release(),
            "cpu_model": read_cpu_model(),
            "cpu_cores_physical": read_cpu_count(logical=False),
            "cpu_threads": read_cpu_count(logical=True),
            "cpu_percent": round(float(cpu_percent), 1),
            "load_average": load_average,
            "ram_total_gb": gb(memory["total"]),
            "ram_used_gb": gb(memory["used"]),
            "ram_free_gb": gb(memory["available"]),
            "ram_percent": memory["percent"],
            "disk_total_gb": gb(disk.total),
            "disk_used_gb": gb(disk.used),
            "disk_free_gb": gb(disk.free),
            "disk_percent": round(disk.used / disk.total * 100, 1) if disk.total else 0.0,
            "temperatures_c": read_temperatures(),
            "memory_file_status": read_memory_file_status(),
            "ollama_status": read_service_status("ollama"),
            "version": self.version,
        }
        gpu_info = read_gpu_info()
        if gpu_info:
            data["gpu"] = gpu_info
        return data

    def health(self) -> dict[str, Any]:
        """Return API health fields requested by the mobile/client app."""
        data = self.collect()
        return {
            "status": "ok",
            "server_time": data["server_time"],
            "uptime": data["uptime"],
            "memory_file_status": data["memory_file_status"],
            "ollama_status": data["ollama_status"],
            "disk_free_gb": data["disk_free_gb"],
            "ram_free_gb": data["ram_free_gb"],
            "version": data["version"],
        }

    def match_kind(self, user_input: str) -> str | None:
        """Return the local status category matched from natural speech."""
        normalized = normalize_user_text(user_input)
        words = words_in(normalized)
        if normalized in DATE_PHRASES:
            return "time"
        if has_any(words, TIME_WORDS):
            return "time"
        if has_any(words, OLLAMA_WORDS):
            return "ollama"
        if has_any(words, GPU_WORDS):
            return "gpu"
        if has_any(words, CPU_WORDS):
            return "cpu"
        if has_any(words, DISK_WORDS):
            return "disk"
        if normalized == "entä ram" or normalized == "enta ram" or normalized == "ram":
            return "ram"
        if (
            has_any(words, RAM_WORDS)
            and not is_memory_management_phrase(normalized)
            and (has_machine_context(words) or "ram" in words or "keskusmuisti" in words)
        ):
            return "ram"
        if normalized in GENERAL_STATUS_PHRASES:
            return "status"
        return None

    def command_name(self, user_input: str) -> str | None:
        """Return debug command name when input is a system-status command."""
        if self.match_kind(user_input) is not None:
            return "system_status"
        return None

    def debug_match_name(self, user_input: str) -> str:
        """Return status debug category for API logging."""
        match_kind = self.match_kind(user_input)
        if match_kind in {"time", "cpu", "gpu", "ram", "disk", "ollama"}:
            return match_kind
        return "none"

    def answer(self, user_input: str) -> str | None:
        """Return a Finnish local answer for supported system-status questions."""
        normalized = normalize_user_text(user_input)
        match_kind = self.match_kind(user_input)
        if match_kind == "time":
            now = datetime.now().astimezone()
            if normalized in DATE_PHRASES:
                return f"Tänään on {now:%d.%m.%Y}."
            return f"Kello on {now:%H:%M:%S}."
        if match_kind == "cpu":
            return format_cpu(self.collect())
        if match_kind == "gpu":
            return format_gpu(self.collect())
        if match_kind == "ram":
            return format_memory(self.collect())
        if match_kind == "disk":
            return format_disk(self.collect())
        if match_kind == "ollama":
            return format_ollama(self.collect())
        if match_kind == "status":
            if normalize_user_text(user_input) in {"näytä koneen tiedot", "nayta koneen tiedot", "näytä serverin speksit", "nayta serverin speksit"}:
                return format_specs(self.collect())
            return format_machine_status(self.collect())
        return None

    def is_system_status_command(self, user_input: str) -> bool:
        """Return whether a prompt should be handled locally as system status."""
        return self.match_kind(user_input) is not None


def format_machine_status(data: dict[str, Any]) -> str:
    """Return a compact machine health summary."""
    lines = [
        f"Kone {data['hostname']} on käynnissä. Uptime: {data['uptime']}.",
        f"CPU-kuorma: {data['cpu_percent']} %.",
        f"RAM: {data['ram_used_gb']} / {data['ram_total_gb']} GiB käytössä, vapaana {data['ram_free_gb']} GiB.",
        f"Levy: {data['disk_used_gb']} / {data['disk_total_gb']} GiB käytössä, vapaana {data['disk_free_gb']} GiB.",
        f"Ollama: {data['ollama_status']}.",
    ]
    temperatures = data.get("temperatures_c") or {}
    if temperatures:
        first_name, first_temp = next(iter(temperatures.items()))
        lines.append(f"Lämpötila: {first_name} {first_temp} °C.")
    return "\n".join(lines)


def format_specs(data: dict[str, Any]) -> str:
    """Return hardware and OS specs."""
    lines = [
        f"Hostname: {data['hostname']}",
        f"Käyttöjärjestelmä: {data['os_name']}",
        f"Kernel: {data['kernel']}",
        f"CPU: {data['cpu_model']}",
        f"CPU-ytimet/säikeet: {data['cpu_cores_physical']} / {data['cpu_threads']}",
        f"RAM yhteensä: {data['ram_total_gb']} GiB",
        f"Levy yhteensä: {data['disk_total_gb']} GiB, vapaana {data['disk_free_gb']} GiB",
        f"IP: {data['local_ip']}",
    ]
    gpu = data.get("gpu")
    if isinstance(gpu, dict):
        gpu_line = f"GPU: {gpu.get('name', 'unknown')}"
        if gpu.get("memory_total_mb") is not None:
            gpu_line += f", VRAM {gpu.get('memory_used_mb')} / {gpu.get('memory_total_mb')} MiB"
        if gpu.get("temperature_c") is not None:
            gpu_line += f", {gpu.get('temperature_c')} °C"
        lines.append(gpu_line)
    return "\n".join(lines)


def format_disk(data: dict[str, Any]) -> str:
    return (
        f"Levytilaa on vapaana {data['disk_free_gb']} GiB / {data['disk_total_gb']} GiB "
        f"({data['disk_percent']} % käytössä)."
    )


def format_memory(data: dict[str, Any]) -> str:
    return (
        f"RAM-muistia on vapaana {data['ram_free_gb']} GiB / {data['ram_total_gb']} GiB "
        f"({data['ram_percent']} % käytössä)."
    )


def format_cpu(data: dict[str, Any]) -> str:
    return (
        f"CPU: {data['cpu_model']}. "
        f"Ytimet/säikeet: {data['cpu_cores_physical']} / {data['cpu_threads']}. "
        f"Kuorma: {data['cpu_percent']} %."
    )


def format_gpu(data: dict[str, Any]) -> str:
    gpu = data.get("gpu")
    if not isinstance(gpu, dict):
        return "GPU-tietoja ei ole saatavilla."

    parts = [f"GPU: {gpu.get('name', 'unknown')}."]
    if gpu.get("memory_total_mb") is not None:
        parts.append(f"VRAM: {gpu.get('memory_used_mb')} / {gpu.get('memory_total_mb')} MiB.")
    if gpu.get("temperature_c") is not None:
        parts.append(f"Lämpötila: {gpu.get('temperature_c')} °C.")
    if gpu.get("utilization_percent") is not None:
        parts.append(f"Kuorma: {gpu.get('utilization_percent')} %.")
    return " ".join(parts)


def format_ollama(data: dict[str, Any]) -> str:
    status = str(data["ollama_status"])
    if status == "active":
        return "Ollama on käynnissä."
    if status == "inactive":
        return "Ollama ei ole käynnissä."
    return f"Ollaman tila on {status}."
