# PyInstaller spec for Spotderpy. Build with packaging/build.ps1 (it generates version_info.txt first).
# One-folder build: starts faster than one-file and trips fewer antivirus false positives.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "spotderpy" / "assets"), "spotderpy/assets"), *collect_data_files("sv_ttk")],
    hiddenimports=["pystray._win32"],
    excludes=["pytest", "_pytest", "unittest", "pydoc_data", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Spotderpy",
    icon=str(ROOT / "spotderpy" / "assets" / "icon.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    console=False,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="Spotderpy", upx=False)
