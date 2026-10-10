"""Persistent list of past lookups (songs and playlists)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import HISTORY_FILE

MAX_ENTRIES = 200
log = logging.getLogger("spotderpy")


@dataclass
class Entry:
    when: float
    kind: str  # "track", "playlist", "album", "tracks"
    label: str  # "Artist - Title" or playlist name
    detail: str  # matched video title, or "13 of 13 songs"
    url: str  # YouTube URL, or file:// URL of the results page
    spotify_url: str = ""


class History:
    def __init__(self, path: Path = HISTORY_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.entries: list[Entry] = self._load()

    def _load(self) -> list[Entry]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [Entry(**e) for e in raw][:MAX_ENTRIES]
        except FileNotFoundError:
            return []
        except Exception:
            log.exception("history file unreadable; starting fresh")
            return []

    def add(self, kind: str, label: str, detail: str, url: str, spotify_url: str = "") -> Entry:
        entry = Entry(time.time(), kind, label, detail, url, spotify_url)
        with self._lock:
            self.entries.insert(0, entry)
            del self.entries[MAX_ENTRIES:]
            self._save()
        return entry

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()
            self._save()

    def snapshot(self) -> list[Entry]:
        with self._lock:
            return list(self.entries)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(e) for e in self.entries], indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("couldn't save history")
