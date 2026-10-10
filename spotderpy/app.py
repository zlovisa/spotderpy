"""Application controller: clipboard watching, lookups, and wiring between tray, window and storage."""

from __future__ import annotations

import logging
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pyperclip

from . import batch, spotify, updates, winutil, youtube
from .config import APP_NAME, LOG_DIR, VERSION, SettingsStore
from .history import History

POLL_INTERVAL = 0.5
REPEAT_COOLDOWN = 5  # some apps write the clipboard several times per copy; don't open duplicate tabs
MAX_CLIPBOARD = 200_000  # Ctrl+A, Ctrl+C on a big Spotify playlist copies one link per song
UPDATE_CHECK_EVERY = 24 * 3600

log = logging.getLogger("spotderpy")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_DIR / "spotderpy.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def excepthook(exc_type, exc, tb):
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = excepthook
    threading.excepthook = lambda a: log.critical(
        "uncaught exception in %s", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback)
    )


class Controller:
    def __init__(self, start_hidden: bool) -> None:
        from .tray import Tray
        from .ui import MainWindow

        self.start_hidden = start_hidden
        self.settings = SettingsStore()
        self.history = History()
        self.available_update: updates.Release | None = None
        self._stop = threading.Event()
        self._batch_lock = threading.Lock()
        self._last_trigger: dict[str, float] = {}
        self.ui = MainWindow(self)
        self.tray = Tray(self)

    # ---- lifecycle -----------------------------------------------------------
    def run(self) -> None:
        self.tray.start()
        self.tray.refresh()
        threading.Thread(target=self._watch_clipboard, name="clipboard", daemon=True).start()
        winutil.listen_for_show_requests(self.show_window)
        if not self.settings.data.welcomed:
            self.settings.update(welcomed=True)
            self.ui.call(self.ui.show, True)
        elif not self.start_hidden:
            self.ui.call(self.ui.show)
        elif self.settings.data.notifications:
            self.tray.notify("Running in the background. Copy a Spotify link to find it on YouTube.")
        self._maybe_check_updates()
        self.ui.mainloop()
        # window loop ended -> shut down
        self._stop.set()
        self.tray.stop()

    def quit(self) -> None:
        log.info("quit requested")
        self.ui.call(self.ui.destroy)

    def show_window(self) -> None:
        self.ui.call(self.ui.show)

    # ---- settings --------------------------------------------------------------
    def set_setting(self, key: str, value) -> None:
        self.settings.update(**{key: value})
        log.info("setting %s = %r", key, value)
        if key == "watch_clipboard":
            self.tray.refresh()
            self.ui.call(self.ui.sync_settings)

    def notify(self, message: str) -> None:
        if self.settings.data.notifications:
            self.tray.notify(message)

    # ---- clipboard -------------------------------------------------------------
    @staticmethod
    def read_clipboard() -> str | None:
        try:
            return pyperclip.paste()
        except Exception:  # clipboard can be briefly locked by other apps
            return None

    @staticmethod
    def has_spotify_link(text: str | None) -> bool:
        return bool(text) and len(text) <= MAX_CLIPBOARD and spotify.looks_like_spotify(text)

    def _watch_clipboard(self) -> None:
        # Whatever was copied before startup is ignored (use "Look up copied link").
        last_seq = winutil.clipboard_sequence()
        last_text = self.read_clipboard()
        while not self._stop.wait(POLL_INTERVAL):
            seq = winutil.clipboard_sequence()
            if seq is not None:
                if seq == last_seq:
                    continue
                last_seq = seq
                text = self.read_clipboard()
            else:  # no sequence number off Windows: fall back to watching for new text
                text = self.read_clipboard()
                if text == last_text:
                    continue
                last_text = text
            if not self.settings.data.watch_clipboard or not self.has_spotify_link(text):
                continue
            log.info("spotify link copied: %s", text[:120].replace("\n", " "))
            self.lookup(text, source="clipboard")

    def lookup_clipboard(self) -> None:
        text = self.read_clipboard()
        if not self.has_spotify_link(text):
            self.tray.notify("There's no Spotify song, album or playlist link on the clipboard.")
            return
        self.lookup(text, source="manual")

    # ---- lookups ---------------------------------------------------------------
    def lookup(self, text: str, source: str) -> None:
        """source: "clipboard" (automatic), "manual" (tray menu) or "window" (Find tab)."""
        threading.Thread(target=self._lookup, args=(text, source), name="lookup", daemon=True).start()

    def _lookup(self, text: str, source: str) -> None:
        in_window = source == "window"
        try:
            target = spotify.resolve(text)
        except Exception as e:
            log.exception("failed resolving %r", text[:200])
            self._report_error(f"Couldn't read that Spotify link ({e}).", in_window)
            return
        if not target:
            self._report_error("That isn't a Spotify song, album or playlist link.", in_window)
            return

        key = f"{target.kind}:{','.join(target.ids)}"
        now = time.monotonic()
        if source == "clipboard" and now - self._last_trigger.get(key, -REPEAT_COOLDOWN) < REPEAT_COOLDOWN:
            log.info("skipping %s: same link handled %.1fs ago", key, now - self._last_trigger[key])
            return
        self._last_trigger[key] = now

        if target.is_batch:
            self._lookup_batch(target, in_window)
        else:
            self._lookup_track(target.id, in_window)

    def _report_error(self, message: str, in_window: bool) -> None:
        if in_window:
            self.ui.call(self.ui.show_error, message)
        else:
            self.tray.notify(message)

    def _lookup_track(self, track_id: str, in_window: bool) -> None:
        prefer = self.settings.data.prefer
        choose = in_window or self.settings.data.open_mode == "choose"
        if choose:
            self.ui.call(self.ui.show_busy, "Looking up the song…", not in_window)
        track = None
        try:
            track = spotify.get_track(track_id)
            log.info("track %s: %s (%.0fs)", track_id, track, track.duration_s or 0)
            best, ranked = youtube.find_best(track, prefer)
            for c in ranked[:3]:
                log.info("  %6.1f %s | %s | %s", c.score, c.url, c.channel, c.title)
        except Exception as e:
            log.exception("failed handling track %s", track_id)
            if track is None:
                self._report_error(f"Couldn't read that song from Spotify ({e}).", choose)
                return
            best, ranked = None, []

        spotify_url = f"https://open.spotify.com/track/{track_id}"
        if best:
            self.history.add("track", str(track), best.title, best.url, spotify_url)
            self.ui.call(self.ui.refresh_history)
            self.tray.refresh()
        if choose:
            self.ui.call(self.ui.show_song, track, ranked)
            return
        if best:
            webbrowser.open(best.url)
            self.notify(f"▶ {track}\n{best.title}")
        else:
            webbrowser.open(youtube.search_url(track))
            self.notify(f"Couldn't pick a video, so I opened YouTube search instead.\n{track}")

    def _lookup_batch(self, target: spotify.Target, in_window: bool) -> None:
        if not self._batch_lock.acquire(blocking=False):
            self._last_trigger.pop(f"{target.kind}:{','.join(target.ids)}", None)
            self._report_error("Still working on the previous playlist. Try again when it's done.", in_window)
            return
        try:
            what = f"{len(target.ids)} songs" if target.kind == "tracks" else f"that {target.kind}"
            self.ui.call(self.ui.start_batch, what)
            if not in_window:
                self.notify(f"Finding YouTube videos for {what}…\nThe results page opens when it's done.")

            def progress(done: int, total: int, r: batch.Result) -> None:
                self.ui.call(self.ui.batch_progress, done, total)
                if done == 1 or done == total or done % 5 == 0:
                    self.tray.set_status(f"{APP_NAME}: matching {done}/{total}")
                log.info("  [%d/%d] %s -> %s", done, total, r.track, r.best.url if r.best else r.error)

            result = batch.run(target, progress, self.settings.data.prefer)
            path = batch.write(result, batch.default_report_path(result, base=self.settings.data.results_path))
            log.info("batch %s: wrote %s", target.kind, path)
            page = path.resolve().as_uri()
            matched = len(result.video_ids)
            spotify_url = result.source_url
            self.history.add(target.kind, result.name, f"{matched} of {len(result.results)} songs", page, spotify_url)
            self.ui.call(self.ui.batch_done, result, path)
            self.ui.call(self.ui.refresh_history)
            if not in_window:
                webbrowser.open(page)
                source = "" if target.kind == "tracks" else f" from {result.name}"
                self.notify(f"Matched {matched} of {len(result.results)} songs{source}.")
        except Exception as e:
            log.exception("batch failed for %s", target)
            self.ui.call(self.ui.show_error, f"Couldn't process that {target.kind} ({e}).")
            if not in_window:
                self.tray.notify(f"Couldn't process that {target.kind}.\n{e}")
        finally:
            self.tray.set_status("")
            self._batch_lock.release()

    # ---- updates ---------------------------------------------------------------
    def _maybe_check_updates(self) -> None:
        s = self.settings.data
        if s.check_updates and time.time() - s.last_update_check > UPDATE_CHECK_EVERY:
            threading.Thread(target=self._check_updates, args=(False,), name="updates", daemon=True).start()

    def check_updates_now(self) -> None:
        threading.Thread(target=self._check_updates, args=(True,), name="updates", daemon=True).start()

    def _check_updates(self, manual: bool) -> None:
        try:
            release = updates.check()
            self.settings.update(last_update_check=time.time())
        except Exception as e:
            log.warning("update check failed: %s", e)
            if manual:
                self.ui.call(self.ui.update_check_result, None, f"Couldn't check for updates ({e}).")
            return
        log.info("update check: %s", release.version if release else "up to date")
        if release and (manual or release.version != self.settings.data.skipped_version):
            self.available_update = release
            self.tray.refresh()
            self.ui.call(self.ui.show_update_banner, release)
            if not manual:
                self.notify(f"{APP_NAME} {release.version} is available. Open {APP_NAME} to update.")
        if manual:
            self.ui.call(self.ui.update_check_result, release, None)

    def open_update(self) -> None:
        release = self.available_update
        if not release:
            return
        installed = winutil.is_frozen() and "programs" in str(Path(sys.executable).parent).lower()
        webbrowser.open(release.installer_url if installed and release.installer_url else release.url)

    def skip_update(self) -> None:
        if self.available_update:
            self.settings.update(skipped_version=self.available_update.version)
        self.available_update = None
        self.tray.refresh()


def main(background: bool = False) -> None:
    setup_logging()
    if not winutil.acquire_single_instance():
        log.info("already running; asked the other instance to show itself")
        return
    winutil.set_app_user_model_id()
    winutil.enable_dpi_awareness()
    log.info("starting %s %s (background=%s, frozen=%s)", APP_NAME, VERSION, background, winutil.is_frozen())
    Controller(start_hidden=background).run()
    log.info("exited")
