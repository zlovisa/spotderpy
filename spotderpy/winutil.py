"""Small Windows integrations via ctypes/winreg (no pywin32 dependency)."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from .config import APP_ID, APP_NAME

IS_WINDOWS = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_NAME = "SpotderpyMutex"  # also referenced by the installer (AppMutex)
SHOW_EVENT_NAME = "SpotderpyShowWindow"
BACKGROUND_ARG = "--background"

log = logging.getLogger("spotderpy")
_handles: list[int] = []  # keep kernel handles alive for the life of the process


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ---- single instance ---------------------------------------------------------

def acquire_single_instance() -> bool:
    """True if we're the first instance. Otherwise, asks the running one to show its window."""
    if not IS_WINDOWS:
        return True
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        k32.OpenEventW.restype = ctypes.c_void_p
        event = k32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)  # EVENT_MODIFY_STATE
        if event:
            k32.SetEvent(ctypes.c_void_p(event))
            k32.CloseHandle(ctypes.c_void_p(event))
        return False
    _handles.append(handle)
    return True


def listen_for_show_requests(callback: Callable[[], None]) -> None:
    """Calls `callback` (from a background thread) whenever a second launch asks us to show up."""
    if not IS_WINDOWS:
        return
    k32 = ctypes.windll.kernel32
    k32.CreateEventW.restype = ctypes.c_void_p
    event = k32.CreateEventW(None, False, False, SHOW_EVENT_NAME)  # auto-reset
    if not event:
        return
    _handles.append(event)

    def wait() -> None:
        while True:
            if k32.WaitForSingleObject(ctypes.c_void_p(event), 0xFFFFFFFF) == 0:
                try:
                    callback()
                except Exception:
                    log.exception("show callback failed")

    threading.Thread(target=wait, name="show-listener", daemon=True).start()


# ---- shell / desktop ---------------------------------------------------------

def set_app_user_model_id() -> None:
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def enable_dpi_awareness() -> None:
    if IS_WINDOWS:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def clipboard_sequence() -> int | None:
    """Windows bumps this on every copy, even when the copied text is identical."""
    if not IS_WINDOWS:
        return None
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def system_uses_dark_theme() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def set_dark_title_bar(hwnd: int, dark: bool) -> None:
    if not IS_WINDOWS:
        return
    try:
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        subprocess.Popen(["explorer", str(path)])


# ---- start at login ----------------------------------------------------------

def launch_command() -> str:
    """Command line that starts this app in the background (used for the login entry)."""
    if is_frozen():
        return f'"{sys.executable}" {BACKGROUND_ARG}'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" -m spotderpy {BACKGROUND_ARG}'


def get_start_at_login() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_start_at_login(enabled: bool) -> None:
    if not IS_WINDOWS:
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
