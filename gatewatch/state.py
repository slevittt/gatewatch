"""Small files in state_dir: the current exit and the guard's memory of the last incident."""
import json
import os
import shutil
import time
from typing import Optional

from .config import Config
from .net import Exit


def _atomic_write(path: str, text: str, mode: int = 0o600) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_exit(cfg: Config) -> Optional[Exit]:
    try:
        with open(cfg.exit_file, encoding="utf-8") as f:
            return Exit.parse(json.load(f)["url"])
    except (OSError, ValueError, KeyError):
        return None


def write_exit(cfg: Config, ex: Exit, reason: str = "") -> None:
    if os.path.exists(cfg.exit_file):
        shutil.copy2(cfg.exit_file, cfg.exit_file + ".bak")
    _atomic_write(cfg.exit_file, json.dumps(
        {"url": ex.url, "set_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "reason": reason}, indent=1))


def restore_exit_backup(cfg: Config) -> bool:
    if os.path.exists(cfg.exit_file + ".bak"):
        shutil.copy2(cfg.exit_file + ".bak", cfg.exit_file)
        os.utime(cfg.exit_file)          # new mtime so a running relay reloads it
        return True
    return False


def load_guard_state(cfg: Config) -> dict:
    try:
        with open(cfg.state_path("guard.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"status": "ok"}


def save_guard_state(cfg: Config, st: dict) -> None:
    _atomic_write(cfg.state_path("guard.json"), json.dumps(st, indent=1), 0o644)
