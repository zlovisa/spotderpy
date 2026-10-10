"""Write spotderpy/assets/THIRD_PARTY_NOTICES.txt from the installed runtime dependencies.

Run from the build environment (packaging/build.ps1 does this) so the notices match what gets bundled.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "spotderpy" / "assets" / "THIRD_PARTY_NOTICES.txt"

# Runtime dependencies that end up inside the app (direct + transitive).
PACKAGES = [
    "yt-dlp", "requests", "urllib3", "idna", "charset-normalizer", "certifi",
    "pyperclip", "pystray", "six", "pillow", "sv-ttk",
]
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")

EXTRA = """\
================================================================================
Python {py}
https://www.python.org/  License: Python Software Foundation License Version 2
Full text: https://docs.python.org/3/license.html

================================================================================
Tcl/Tk
https://www.tcl-lang.org/  License: Tcl/Tk license (BSD-style)
Full text: https://www.tcl-lang.org/software/tcltk/license.html
"""


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    texts = []
    for f in dist.files or []:
        name = Path(str(f)).name.upper()
        if name.startswith(LICENSE_NAMES) and ".dist-info" in str(f):
            try:
                texts.append((Path(str(f)).name, Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
    return texts


def main() -> int:
    parts = [
        "Spotderpy includes the following open-source software.\n"
        "Each component is used under the license reproduced or referenced below.\n"
        "pystray is licensed under the GNU LGPL v3: it is shipped as an unmodified, separate\n"
        "Python package inside the app folder (_internal), and you may replace it with your own build.\n"
    ]
    missing = []
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        meta = dist.metadata
        lic = meta.get("License-Expression") or meta.get("License") or ""
        if len(lic) > 80 or not lic.strip():
            classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License")]
            lic = ", ".join(classifiers) or "see below"
        home = meta.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or []), ""
        )
        parts.append("=" * 80)
        parts.append(f"{meta['Name']} {dist.version}\n{home}  License: {lic}")
        for fname, text in license_texts(dist):
            parts.append(f"--- {fname} ---\n{text.strip()}\n")
    parts.append(EXTRA.format(py=sys.version.split()[0]))
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    if missing:
        print("not installed (skipped):", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
