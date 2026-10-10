"""System tray icon and menu (pystray runs its own message loop thread on Windows)."""

from __future__ import annotations

import logging
import webbrowser
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageEnhance

from .config import APP_NAME, asset_path

if TYPE_CHECKING:
    from .app import Controller

log = logging.getLogger("spotderpy")


def _opener(url: str):
    # pystray inspects the callback's arity, so no default-arg lambdas here.
    return lambda: webbrowser.open(url)


class Tray:
    def __init__(self, ctl: Controller) -> None:
        self.ctl = ctl
        self._normal = Image.open(asset_path("tray.png")).convert("RGBA")
        gray = ImageEnhance.Color(self._normal).enhance(0.0)
        self._paused = ImageEnhance.Brightness(gray).enhance(0.9)
        self._status = ""
        self.icon = pystray.Icon(APP_NAME, self._normal, APP_NAME, menu=self._menu())

    def _menu(self) -> pystray.Menu:
        ctl = self.ctl
        return pystray.Menu(
            pystray.MenuItem(f"Open {APP_NAME}", lambda: ctl.show_window(), default=True),
            pystray.MenuItem("Look up copied link", lambda: ctl.lookup_clipboard()),
            pystray.MenuItem(
                "Watch clipboard",
                lambda: ctl.set_setting("watch_clipboard", not ctl.settings.data.watch_clipboard),
                checked=lambda _: ctl.settings.data.watch_clipboard,
            ),
            pystray.MenuItem("Recent", pystray.Menu(self._recent_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: f"Update to {ctl.available_update.version}…" if ctl.available_update else "Update",
                lambda: ctl.open_update(),
                visible=lambda _: ctl.available_update is not None,
            ),
            pystray.MenuItem("Quit", lambda: ctl.quit()),
        )

    def _recent_items(self):
        entries = self.ctl.history.snapshot()[:5]
        if not entries:
            yield pystray.MenuItem("Nothing yet", None, enabled=False)
            return
        for e in entries:
            label = e.label if len(e.label) <= 48 else e.label[:47] + "…"
            yield pystray.MenuItem(label, _opener(e.url))

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            log.exception("tray stop failed")

    def set_status(self, status: str = "") -> None:
        """Tooltip text; empty restores the default."""
        self._status = status
        self.refresh()

    def refresh(self) -> None:
        watching = self.ctl.settings.data.watch_clipboard
        try:
            self.icon.icon = self._normal if watching else self._paused
            default = f"{APP_NAME}: watching for Spotify links" if watching else f"{APP_NAME}: paused"
            self.icon.title = (self._status or default)[:127]
            self.icon.update_menu()
        except Exception:
            log.exception("tray refresh failed")

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message[:255], APP_NAME)
        except Exception:
            log.exception("notify failed")
