"""App identity, file locations, and persisted user settings."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import __version__

APP_NAME = "Spotderpy"
APP_ID = "Spotderpy.Spotderpy"  # Windows AppUserModelID (taskbar grouping, notifications)
GITHUB_REPO = "zlovisa/spotderpy"
REPO_URL = f"https://github.com/{GITHUB_REPO}"
ISSUES_URL = f"{REPO_URL}/issues/new"
VERSION = __version__

log = logging.getLogger("spotderpy")


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


CONFIG_DIR = _env_dir("APPDATA", Path.home() / ".config") / APP_NAME
DATA_DIR = _env_dir("LOCALAPPDATA", Path.home() / ".local" / "share") / APP_NAME
LOG_DIR = DATA_DIR / "logs"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"


def asset_path(name: str) -> Path:
    """Works from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "spotderpy" / "assets" / name


def default_results_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / APP_NAME


@dataclass
class Settings:
    watch_clipboard: bool = True
    open_mode: str = "open"  # "open": open the best match right away; "choose": show the choices
    prefer: str = "video"  # "video": official music video; "audio": album/audio version
    notifications: bool = True
    results_dir: str = ""  # empty = Documents\Spotderpy
    check_updates: bool = True
    last_update_check: float = 0.0
    skipped_version: str = ""
    welcomed: bool = False
    hide_hint_shown: bool = False

    @property
    def results_path(self) -> Path:
        return Path(self.results_dir) if self.results_dir else default_results_dir()


class SettingsStore:
    """Thread-safe settings with atomic saves."""

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except Exception:
            log.exception("settings file unreadable; using defaults")
            return Settings()
        known = {f.name for f in fields(Settings)}
        try:
            return Settings(**{k: v for k, v in raw.items() if k in known})
        except TypeError:
            return Settings()

    def update(self, **changes) -> Settings:
        with self._lock:
            for key, value in changes.items():
                if not hasattr(self.data, key):
                    raise AttributeError(key)
                setattr(self.data, key, value)
            self._save()
            return self.data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.data), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
