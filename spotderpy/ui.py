"""Main window (tkinter + Sun Valley theme): Find, History, Settings, About.

Every method that touches widgets runs on the Tk thread. Other threads go through `call()`.
"""

from __future__ import annotations

import ctypes
import io
import logging
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlencode

import requests
import sv_ttk
from PIL import Image, ImageTk

from . import batch, winutil, youtube
from .config import APP_NAME, ISSUES_URL, LOG_DIR, REPO_URL, VERSION, asset_path
from .spotify import Track

if TYPE_CHECKING:
    from .app import Controller
    from .updates import Release

log = logging.getLogger("spotderpy")


def _fmt_dur(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _fmt_when(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.year == now.year:
        return f"{dt:%b} {dt.day}"
    return f"{dt:%b} {dt.day}, {dt.year}"


class MainWindow:
    def __init__(self, ctl: Controller) -> None:
        self.ctl = ctl
        self.root = tk.Tk(className=APP_NAME)
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self.dark = winutil.system_uses_dark_theme()
        sv_ttk.set_theme("dark" if self.dark else "light")
        self.muted = "#a1a1aa" if self.dark else "#6b6b76"
        self.error_fg = "#f87171" if self.dark else "#dc2626"
        self.f_title = ("Segoe UI Semibold", 16)
        self.f_h2 = ("Segoe UI Semibold", 12)
        self.f_body = ("Segoe UI", 10)
        self.f_small = ("Segoe UI", 9)
        try:
            self.root.iconbitmap(default=str(asset_path("icon.ico")))
        except tk.TclError:
            log.warning("couldn't load window icon")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.bind("<Escape>", lambda _e: self.hide())
        self.root.report_callback_exception = self._on_tk_error

        self.thumb_w, self.thumb_h = self.px(80), self.px(45)
        style = ttk.Style()
        style.configure("Results.Treeview", rowheight=self.thumb_h + self.px(10))
        style.configure("History.Treeview", rowheight=self.px(30))

        self._queue: queue.Queue[tuple[Callable, tuple]] = queue.Queue()
        self._photos: dict[str, ImageTk.PhotoImage] = {}
        self._result_gen = 0
        self._title_bar_done = False
        self.last_song: tuple[Track, list[youtube.Candidate]] | None = None

        self._build()
        w, h = self.px(720), self.px(700)
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(self.px(540), self.px(560))
        self.root.after(50, self._drain)

    # ---- plumbing ----------------------------------------------------------------
    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def call(self, fn: Callable, *args) -> None:
        """Thread-safe: run fn(*args) on the Tk thread."""
        self._queue.put((fn, args))

    def _drain(self) -> None:
        try:
            while True:
                fn, args = self._queue.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log.exception("UI call %s failed", getattr(fn, "__name__", fn))
        except queue.Empty:
            pass
        try:
            self.root.after(50, self._drain)
        except tk.TclError:
            pass  # window destroyed

    def mainloop(self) -> None:
        self.root.mainloop()

    def destroy(self) -> None:
        self.root.destroy()

    def _on_tk_error(self, exc, val, tb) -> None:
        log.error("Tk callback error", exc_info=(exc, val, tb))

    def show(self, first_run: bool = False) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        if not self._title_bar_done and winutil.IS_WINDOWS:
            self.root.update_idletasks()
            winutil.set_dark_title_bar(ctypes.windll.user32.GetParent(self.root.winfo_id()), self.dark)
            self._title_bar_done = True
        if not self.entry_var.get().strip():
            text = self.ctl.read_clipboard()
            if self.ctl.has_spotify_link(text) and len(text) < 500:
                self.entry_var.set(text.strip())
        if first_run:
            self.notebook.select(self.tab_find)
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def hide(self) -> None:
        self.root.withdraw()
        if not self.ctl.settings.data.hide_hint_shown:
            self.ctl.settings.update(hide_hint_shown=True)
            self.ctl.tray.notify(f"{APP_NAME} is still running in the tray and watching for Spotify links.")

    def _bring_front(self) -> None:
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.root.lift()

    # ---- layout --------------------------------------------------------------------
    def _build(self) -> None:
        self.banner = ttk.Frame(self.root, padding=(self.px(16), self.px(10)))
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=self.px(10), pady=self.px(10))
        self.tab_find = self._build_find()
        self.tab_history = self._build_history()
        self.tab_settings = self._build_settings()
        self.tab_about = self._build_about()
        for frame, label in (
            (self.tab_find, "Find"),
            (self.tab_history, "History"),
            (self.tab_settings, "Settings"),
            (self.tab_about, "About"),
        ):
            self.notebook.add(frame, text=f"  {label}  ")

    def _clear(self, frame: tk.Widget) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _muted(self, parent, text: str, **kw) -> ttk.Label:
        return ttk.Label(parent, text=text, foreground=self.muted, font=self.f_small, **kw)

    def _wrap(self, label: ttk.Label) -> None:
        """Re-wrap the label's text whenever its width changes."""
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(200, e.width - 4)))

    # ---- Find tab ---------------------------------------------------------------
    def _build_find(self) -> ttk.Frame:
        f = ttk.Frame(self.notebook, padding=self.px(18))
        ttk.Label(f, text="Find a song on YouTube", font=self.f_title).pack(anchor="w")
        hint = self._muted(f, "Paste a Spotify song, album or playlist link. You can also just copy a link "
                              "anywhere and Spotderpy will pick it up from the clipboard.")
        hint.pack(anchor="w", fill="x", pady=(self.px(2), self.px(12)))
        self._wrap(hint)

        row = ttk.Frame(f)
        row.pack(fill="x")
        self.entry_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.entry_var, font=self.f_body)
        self.entry.pack(side="left", fill="x", expand=True, ipady=self.px(2))
        self.entry.bind("<Return>", lambda _e: self._on_find())
        self.find_btn = ttk.Button(row, text="Find", style="Accent.TButton", command=self._on_find, width=10)
        self.find_btn.pack(side="left", padx=(self.px(8), 0))

        self.result = ttk.Frame(f)
        self.result.pack(fill="both", expand=True, pady=(self.px(16), 0))
        self._show_tips()
        return f

    def _show_tips(self) -> None:
        self._clear(self.result)
        box = ttk.Frame(self.result)
        box.pack(fill="x", pady=(self.px(10), 0))
        ttk.Label(box, text="How it works", font=self.f_h2).pack(anchor="w", pady=(0, self.px(6)))
        tips = [
            ("Songs", "In Spotify, choose Share → Copy Song Link. The YouTube video opens by itself."),
            ("Playlists & albums", "Copy the link and you'll get a page with every song's video and a Play all button."),
            ("Big playlists", "Spotify only shares the first 100 songs of a playlist link. For more, click a song "
                              "in the playlist, press Ctrl+A then Ctrl+C."),
            ("Tray icon", "Spotderpy keeps running in the system tray. Right-click it to pause or quit."),
        ]
        for title, text in tips:
            item = ttk.Frame(box)
            item.pack(fill="x", pady=self.px(4))
            ttk.Label(item, text=title, font=("Segoe UI Semibold", 10)).pack(anchor="w")
            body = self._muted(item, text)
            body.pack(anchor="w", fill="x")
            self._wrap(body)

    def _on_find(self) -> None:
        text = self.entry_var.get().strip()
        if not text:
            self.show_error("Paste a Spotify link first.")
            return
        if not self.ctl.has_spotify_link(text):
            self.show_error("That doesn't look like a Spotify link. Copy one from Spotify using Share → Copy link.")
            return
        self.show_busy("Looking it up…")
        self.ctl.lookup(text, source="window")

    def show_busy(self, message: str, bring_front: bool = False) -> None:
        self._result_gen += 1
        self._clear(self.result)
        if bring_front:
            self._bring_front()
            self.notebook.select(self.tab_find)
        ttk.Label(self.result, text=message, font=self.f_body).pack(anchor="w", pady=(self.px(8), self.px(8)))
        bar = ttk.Progressbar(self.result, mode="indeterminate")
        bar.pack(fill="x")
        bar.start(12)

    def show_error(self, message: str) -> None:
        self._result_gen += 1
        self._clear(self.result)
        msg = ttk.Label(self.result, text=message, foreground=self.error_fg, font=self.f_body)
        msg.pack(anchor="w", fill="x", pady=(self.px(8), 0))
        self._wrap(msg)

    def show_song(self, track: Track, ranked: list[youtube.Candidate]) -> None:
        self._result_gen += 1
        gen = self._result_gen
        self.last_song = (track, ranked)
        self._clear(self.result)
        if not self.root.winfo_viewable():
            self._bring_front()
        self.notebook.select(self.tab_find)

        head = ttk.Frame(self.result)
        head.pack(fill="x")
        ttk.Label(head, text=track.title, font=self.f_h2).pack(anchor="w")
        sub = ", ".join(track.artists) + (f"  ·  {_fmt_dur(track.duration_s)}" if track.duration_s else "")
        self._muted(head, sub).pack(anchor="w")

        if not ranked:
            self.show_error_below(f"No YouTube results for “{track}”.", track)
            return

        tree = ttk.Treeview(self.result, columns=("video", "channel", "length"), show="tree headings",
                            style="Results.Treeview", selectmode="browse", height=5)
        tree.heading("#0", text="")
        tree.heading("video", text="Video", anchor="w")
        tree.heading("channel", text="Channel", anchor="w")
        tree.heading("length", text="Length", anchor="e")
        tree.column("#0", width=self.thumb_w + self.px(24), stretch=False)
        tree.column("video", width=self.px(260), stretch=True)
        tree.column("channel", width=self.px(130), stretch=False)
        tree.column("length", width=self.px(56), stretch=False, anchor="e")
        tree.tag_configure("best", font=("Segoe UI Semibold", 10))
        tree.tag_configure("low", foreground=self.muted)
        by_iid: dict[str, youtube.Candidate] = {}
        for i, c in enumerate(ranked[:8]):
            iid = f"c{i}"
            by_iid[iid] = c
            tags = ("best",) if i == 0 else (("low",) if c.score < batch.LOW_CONFIDENCE else ())
            title = ("★ " if i == 0 else "") + c.title
            tree.insert("", "end", iid=iid, text="", values=(title, c.channel, _fmt_dur(c.duration_s)), tags=tags)
        tree.selection_set("c0")
        tree.pack(fill="both", expand=True, pady=(self.px(10), 0))

        def selected() -> youtube.Candidate:
            sel = tree.selection()
            return by_iid[sel[0]] if sel else ranked[0]

        tree.bind("<Double-1>", lambda _e: webbrowser.open(selected().url))
        tree.bind("<Return>", lambda _e: webbrowser.open(selected().url))

        buttons = ttk.Frame(self.result)
        buttons.pack(fill="x", pady=(self.px(10), 0))
        ttk.Button(buttons, text="▶  Open on YouTube", style="Accent.TButton",
                   command=lambda: webbrowser.open(selected().url)).pack(side="left")
        copy_btn = ttk.Button(buttons, text="Copy link")
        copy_btn.configure(command=lambda: self._copy(selected().url, copy_btn, "Copy link"))
        copy_btn.pack(side="left", padx=(self.px(8), 0))
        ttk.Button(buttons, text="More on YouTube", command=lambda: webbrowser.open(youtube.search_url(track))
                   ).pack(side="left", padx=(self.px(8), 0))
        ttk.Button(buttons, text="Wrong match?", command=self.report_wrong_match).pack(side="right")

        threading.Thread(target=self._load_thumbs, args=(gen, tree, list(by_iid.items())), daemon=True).start()

    def show_error_below(self, message: str, track: Track) -> None:
        ttk.Label(self.result, text=message, foreground=self.error_fg).pack(anchor="w", pady=(self.px(10), 0))
        ttk.Button(self.result, text="Search YouTube", command=lambda: webbrowser.open(youtube.search_url(track))
                   ).pack(anchor="w", pady=(self.px(8), 0))

    def _load_thumbs(self, gen: int, tree: ttk.Treeview, items: list[tuple[str, youtube.Candidate]]) -> None:
        session = requests.Session()
        for iid, c in items:
            if gen != self._result_gen:
                return
            try:
                data = session.get(f"https://i.ytimg.com/vi/{c.id}/mqdefault.jpg", timeout=6).content
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img = img.resize((self.thumb_w, self.thumb_h), Image.LANCZOS)
            except Exception:
                continue
            self.call(self._set_thumb, gen, tree, iid, img)

    def _set_thumb(self, gen: int, tree: ttk.Treeview, iid: str, img: Image.Image) -> None:
        if gen != self._result_gen or not tree.winfo_exists():
            return
        photo = ImageTk.PhotoImage(img)
        self._photos[f"{gen}:{iid}"] = photo
        for key in [k for k in self._photos if not k.startswith(f"{gen}:")]:
            del self._photos[key]
        tree.item(iid, image=photo)

    def _copy(self, text: str, button: ttk.Button | None = None, label: str = "") -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if button is not None:
            button.configure(text="Copied ✓")
            self.root.after(1500, lambda: button.winfo_exists() and button.configure(text=label))

    # batch view
    def start_batch(self, what: str) -> None:
        self._result_gen += 1
        self._clear(self.result)
        self.batch_title = ttk.Label(self.result, text=f"Finding YouTube videos for {what}…", font=self.f_h2)
        self.batch_title.pack(anchor="w")
        self.batch_bar = ttk.Progressbar(self.result, mode="indeterminate")
        self.batch_bar.pack(fill="x", pady=(self.px(10), self.px(4)))
        self.batch_bar.start(12)
        self.batch_count = self._muted(self.result, "Reading the song list from Spotify…")
        self.batch_count.pack(anchor="w")

    def batch_progress(self, done: int, total: int) -> None:
        if not getattr(self, "batch_bar", None) or not self.batch_bar.winfo_exists():
            return
        if str(self.batch_bar.cget("mode")) != "determinate":
            self.batch_bar.stop()
            self.batch_bar.configure(mode="determinate", maximum=total)
        self.batch_bar.configure(value=done)
        self.batch_count.configure(text=f"{done} of {total} songs")

    def batch_done(self, result: batch.BatchResult, path: Path) -> None:
        self._result_gen += 1
        self._clear(self.result)
        matched = len(result.video_ids)
        flagged = sum(1 for r in result.results if r.best and not r.confident)
        ttk.Label(self.result, text=result.name, font=self.f_h2).pack(anchor="w")
        summary = f"Matched {matched} of {len(result.results)} songs"
        if flagged:
            summary += f" · {flagged} worth a quick check"
        self._muted(self.result, summary).pack(anchor="w")
        if result.note:
            note = ttk.Label(self.result, text=result.note, foreground=self.muted, font=self.f_small)
            note.pack(anchor="w", fill="x", pady=(self.px(8), 0))
            self._wrap(note)

        page = path.resolve().as_uri()
        row = ttk.Frame(self.result)
        row.pack(fill="x", pady=(self.px(14), 0))
        ttk.Button(row, text="Open results page", style="Accent.TButton", command=lambda: webbrowser.open(page)
                   ).pack(side="left")
        chunks = result.play_all_urls
        if chunks:
            label = "▶  Play all" if len(chunks) == 1 else f"▶  Play first {youtube.PLAY_ALL_CHUNK}"
            ttk.Button(row, text=label, command=lambda: webbrowser.open(chunks[0])).pack(side="left", padx=(self.px(8), 0))
        links = "\n".join(r.best.url for r in result.results if r.best)
        copy_btn = ttk.Button(row, text="Copy all links")
        copy_btn.configure(command=lambda: self._copy(links, copy_btn, "Copy all links"))
        copy_btn.pack(side="left", padx=(self.px(8), 0))
        ttk.Button(row, text="Open folder", command=lambda: winutil.open_folder(path.parent)).pack(side="right")

    # ---- History tab ---------------------------------------------------------------
    def _build_history(self) -> ttk.Frame:
        f = ttk.Frame(self.notebook, padding=self.px(18))
        ttk.Label(f, text="History", font=self.f_title).pack(anchor="w")
        self._muted(f, "Songs and playlists you've looked up. Double-click to open.").pack(anchor="w", pady=(self.px(2), self.px(10)))
        self.history_tree = ttk.Treeview(f, columns=("when", "item", "match"), show="headings",
                                         style="History.Treeview", selectmode="browse")
        for col, text, width, stretch in (("when", "When", 80, False), ("item", "Spotify", 220, True),
                                          ("match", "YouTube match", 220, True)):
            self.history_tree.heading(col, text=text, anchor="w")
            self.history_tree.column(col, width=self.px(width), stretch=stretch)
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", lambda _e: self._history_open())
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(self.px(10), 0))
        ttk.Button(row, text="Open", style="Accent.TButton", command=self._history_open).pack(side="left")
        self.history_copy = ttk.Button(row, text="Copy link", command=self._history_copy)
        self.history_copy.pack(side="left", padx=(self.px(8), 0))
        ttk.Button(row, text="Open in Spotify", command=self._history_spotify).pack(side="left", padx=(self.px(8), 0))
        ttk.Button(row, text="Clear history", command=self._history_clear).pack(side="right")
        self._history_entries = []
        self.refresh_history()
        return f

    def refresh_history(self) -> None:
        tree = self.history_tree
        tree.delete(*tree.get_children())
        self._history_entries = self.ctl.history.snapshot()
        for i, e in enumerate(self._history_entries):
            label = e.label if e.kind == "track" else f"♫ {e.label}"
            tree.insert("", "end", iid=str(i), values=(_fmt_when(e.when), label, e.detail))

    def _history_selected(self):
        sel = self.history_tree.selection()
        return self._history_entries[int(sel[0])] if sel else None

    def _history_open(self) -> None:
        e = self._history_selected()
        if e:
            webbrowser.open(e.url)

    def _history_copy(self) -> None:
        e = self._history_selected()
        if e:
            self._copy(e.url, self.history_copy, "Copy link")

    def _history_spotify(self) -> None:
        e = self._history_selected()
        if e and e.spotify_url:
            webbrowser.open(e.spotify_url)

    def _history_clear(self) -> None:
        if messagebox.askyesno(APP_NAME, "Clear your lookup history?", parent=self.root):
            self.ctl.history.clear()
            self.refresh_history()
            self.ctl.tray.refresh()

    # ---- Settings tab --------------------------------------------------------------
    def _build_settings(self) -> ttk.Frame:
        f = ttk.Frame(self.notebook, padding=self.px(18))
        s = self.ctl.settings.data
        ttk.Label(f, text="Settings", font=self.f_title).pack(anchor="w", pady=(0, self.px(6)))

        def section(title: str) -> None:
            ttk.Label(f, text=title, font=self.f_h2).pack(anchor="w", pady=(self.px(14), self.px(4)))

        def switch(text: str, var: tk.BooleanVar, command: Callable[[], None]) -> None:
            ttk.Checkbutton(f, text=text, variable=var, style="Switch.TCheckbutton", command=command
                            ).pack(anchor="w", pady=self.px(3))

        section("General")
        self.var_login = tk.BooleanVar(value=winutil.get_start_at_login())
        switch(f"Start {APP_NAME} when I sign in to Windows", self.var_login, self._toggle_login)
        self.var_watch = tk.BooleanVar(value=s.watch_clipboard)
        switch("Watch the clipboard for Spotify links", self.var_watch,
               lambda: self.ctl.set_setting("watch_clipboard", self.var_watch.get()))
        self.var_notify = tk.BooleanVar(value=s.notifications)
        switch("Show notifications", self.var_notify,
               lambda: self.ctl.set_setting("notifications", self.var_notify.get()))

        section("When I copy a song link")
        self.var_mode = tk.StringVar(value=s.open_mode)
        for value, text in (("open", "Open the best match on YouTube right away"),
                            ("choose", "Show me the matches first")):
            ttk.Radiobutton(f, text=text, value=value, variable=self.var_mode,
                            command=lambda: self.ctl.set_setting("open_mode", self.var_mode.get())
                            ).pack(anchor="w", pady=self.px(3))

        section("I prefer")
        self.var_prefer = tk.StringVar(value=s.prefer)
        for value, text in (("video", "The official music video"),
                            ("audio", "The audio-only version (same as on Spotify)")):
            ttk.Radiobutton(f, text=text, value=value, variable=self.var_prefer,
                            command=lambda: self.ctl.set_setting("prefer", self.var_prefer.get())
                            ).pack(anchor="w", pady=self.px(3))

        section("Playlist results")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=self.px(3))
        self.results_dir_label = ttk.Label(row, text=str(s.results_path), font=self.f_small, foreground=self.muted)
        self.results_dir_label.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Change…", command=self._choose_results_dir).pack(side="left", padx=(self.px(8), 0))
        ttk.Button(row, text="Open", command=lambda: winutil.open_folder(self.ctl.settings.data.results_path)
                   ).pack(side="left", padx=(self.px(8), 0))

        section("Updates")
        self.var_updates = tk.BooleanVar(value=s.check_updates)
        switch("Check for updates automatically", self.var_updates,
               lambda: self.ctl.set_setting("check_updates", self.var_updates.get()))
        return f

    def sync_settings(self) -> None:
        s = self.ctl.settings.data
        self.var_watch.set(s.watch_clipboard)
        self.var_notify.set(s.notifications)
        self.var_mode.set(s.open_mode)
        self.var_prefer.set(s.prefer)
        self.var_updates.set(s.check_updates)
        self.var_login.set(winutil.get_start_at_login())

    def _toggle_login(self) -> None:
        try:
            winutil.set_start_at_login(self.var_login.get())
        except OSError as e:
            log.exception("couldn't change start-at-login")
            messagebox.showerror(APP_NAME, f"Couldn't change the startup setting:\n{e}", parent=self.root)
        self.var_login.set(winutil.get_start_at_login())

    def _choose_results_dir(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, initialdir=str(self.ctl.settings.data.results_path),
                                         title="Where should playlist results be saved?")
        if chosen:
            self.ctl.set_setting("results_dir", str(Path(chosen)))
            self.results_dir_label.configure(text=str(Path(chosen)))

    # ---- About tab -------------------------------------------------------------------
    def _build_about(self) -> ttk.Frame:
        f = ttk.Frame(self.notebook, padding=self.px(18))
        top = ttk.Frame(f)
        top.pack(fill="x")
        try:
            logo = Image.open(asset_path("icon.png")).resize((self.px(72), self.px(72)), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(logo)
            ttk.Label(top, image=self._logo).pack(side="left", padx=(0, self.px(14)))
        except Exception:
            log.exception("couldn't load logo")
        text = ttk.Frame(top)
        text.pack(side="left", fill="x", expand=True)
        ttk.Label(text, text=APP_NAME, font=("Segoe UI Semibold", 20)).pack(anchor="w")
        self._muted(text, f"Version {VERSION}").pack(anchor="w")
        ttk.Label(text, text="Copy a Spotify link, get the YouTube video.", font=self.f_body).pack(anchor="w", pady=(self.px(4), 0))

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(self.px(20), 0))
        self.update_btn = ttk.Button(row, text="Check for updates", style="Accent.TButton", command=self._check_updates)
        self.update_btn.pack(side="left")
        self.update_status = self._muted(row, "")
        self.update_status.pack(side="left", padx=(self.px(10), 0))

        links = ttk.Frame(f)
        links.pack(fill="x", pady=(self.px(16), 0))
        for text, cmd in (
            ("Report a wrong match or a bug", self.report_wrong_match),
            ("Project website", lambda: webbrowser.open(REPO_URL)),
            ("Open-source licenses", self._open_licenses),
            ("Open log folder", lambda: winutil.open_folder(LOG_DIR)),
        ):
            ttk.Button(links, text=text, command=cmd).pack(anchor="w", pady=self.px(3))

        disclaimer = self._muted(
            f,
            "Spotderpy reads public song info from Spotify's web pages and searches YouTube. It doesn't need your "
            "accounts, doesn't download any music, and doesn't collect any data. "
            "Not affiliated with, endorsed by, or sponsored by Spotify or YouTube.",
        )
        disclaimer.pack(anchor="w", fill="x", side="bottom")
        self._wrap(disclaimer)
        return f

    def _open_licenses(self) -> None:
        path = asset_path("THIRD_PARTY_NOTICES.txt")
        if path.exists() and winutil.IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(f"{REPO_URL}/blob/main/THIRD_PARTY_NOTICES.txt")

    def report_wrong_match(self) -> None:
        body = ["**What happened?**", "", ""]
        title = "Wrong match"
        if self.last_song:
            track, ranked = self.last_song
            title = f"Wrong match: {track}"
            body = [
                f"**Spotify song:** {track} (https://open.spotify.com/track/{track.id})",
                f"**Spotderpy picked:** {ranked[0].url if ranked else 'nothing'}",
                "**The right video is:** (paste the YouTube link here)",
                "",
            ]
        body.append(f"_Spotderpy {VERSION}_")
        webbrowser.open(f"{ISSUES_URL}?{urlencode({'title': title, 'body': chr(10).join(body)})}")

    # ---- updates ---------------------------------------------------------------------
    def _check_updates(self) -> None:
        self.update_btn.state(["disabled"])
        self.update_status.configure(text="Checking…")
        self.ctl.check_updates_now()

    def update_check_result(self, release: Release | None, error: str | None) -> None:
        self.update_btn.state(["!disabled"])
        if error:
            self.update_status.configure(text=error)
        elif release:
            self.update_status.configure(text=f"Version {release.version} is available.")
        else:
            self.update_status.configure(text="You're up to date.")

    def show_update_banner(self, release: Release) -> None:
        self._clear(self.banner)
        ttk.Label(self.banner, text=f"{APP_NAME} {release.version} is available.", font=("Segoe UI Semibold", 10)
                  ).pack(side="left")
        ttk.Button(self.banner, text="Skip this version", command=self._skip_update).pack(side="right")
        ttk.Button(self.banner, text="Download", style="Accent.TButton", command=self.ctl.open_update
                   ).pack(side="right", padx=(0, self.px(8)))
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", before=self.notebook)

    def _skip_update(self) -> None:
        self.ctl.skip_update()
        self.banner.pack_forget()
