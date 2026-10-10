"""Check GitHub Releases for a newer version."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from .config import GITHUB_REPO, VERSION

TIMEOUT = 8


@dataclass
class Release:
    version: str
    url: str  # release page
    notes: str
    installer_url: str | None


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_release() -> Release | None:
    resp = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"Spotderpy/{VERSION}"},
        timeout=TIMEOUT,
    )
    if resp.status_code == 404:  # no releases yet
        return None
    resp.raise_for_status()
    data = resp.json()
    installer = next(
        (a["browser_download_url"] for a in data.get("assets", []) if a.get("name", "").lower().endswith("setup.exe")),
        None,
    )
    return Release(
        version=(data.get("tag_name") or "").lstrip("v"),
        url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
        notes=(data.get("body") or "").strip(),
        installer_url=installer,
    )


def check() -> Release | None:
    """The latest release if it's newer than this build, else None."""
    release = latest_release()
    if release and release.version and is_newer(release.version):
        return release
    return None
