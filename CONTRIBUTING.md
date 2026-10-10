# Developing Spotderpy

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Run the app from source with `.venv\Scripts\pythonw -m spotderpy` (add `--background` to start in the tray only).

The command-line tool is handy for checking how a match was made:

```powershell
.venv\Scripts\spotderpy -n -v "https://open.spotify.com/track/..."   # every candidate with its score breakdown
.venv\Scripts\spotderpy -n "https://open.spotify.com/playlist/..." -o out.csv
.venv\Scripts\spotderpy -c                                           # whatever is on the clipboard
```

## Layout

| Path | What |
|---|---|
| `spotderpy/spotify.py` | Link parsing; song/playlist/album info from Spotify's public embed pages |
| `spotderpy/youtube.py` | YouTube search (yt-dlp) and the match scoring |
| `spotderpy/batch.py` | Playlist/album matching and the HTML/CSV/TXT results |
| `spotderpy/app.py` | Controller: clipboard watcher, lookups, updates, logging |
| `spotderpy/ui.py` | Main window (tkinter + Sun Valley theme) |
| `spotderpy/tray.py` | Tray icon and menu (pystray) |
| `spotderpy/winutil.py` | Windows bits: single instance, start at sign-in, dark title bar, clipboard sequence |
| `spotderpy/config.py` | App constants, file locations, settings |
| `packaging/` | PyInstaller spec, Inno Setup script, `build.ps1` |
| `scripts/` | Icon generator, third-party license collector |

Scoring changes should come with a test in `tests/test_ranking.py`, ideally built from a real wrong-match report.

## Building

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) for the installer, or pass `-SkipInstaller`. The output goes to `dist\release\`:
- `Spotderpy-<version>-Setup.exe` (per-user installer, no admin)
- `Spotderpy-<version>-portable.zip`

## Releasing

1. Bump `__version__` in `spotderpy/__init__.py` and add a section to `CHANGELOG.md`.
2. Commit, then tag and push:
   ```powershell
   git tag v1.0.1
   git push origin main v1.0.1
   ```
3. The **Release** workflow builds both files and publishes the GitHub Release, using the changelog section as the notes. Installed copies will see the update within a day.

Ship a release whenever YouTube breaks search. The build always pulls the newest yt-dlp.

### Code signing (recommended once you have users)

Unsigned builds trigger a SmartScreen warning. Options: [SignPath](https://signpath.org/) (free for open source), Azure Trusted Signing, or a standard code-signing certificate. Sign `dist\Spotderpy\Spotderpy.exe` before running Inno Setup, and sign the installer afterwards.
