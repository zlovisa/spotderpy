"""YouTube search (via yt-dlp, no API key) and best-match ranking."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from .spotify import Track

SEARCH_RESULTS = 8

# Words that usually mean "not the original recording", unless the Spotify title says so too.
PENALTY_WORDS = {
    "live": 25,
    "cover": 30,
    "remix": 25,
    "karaoke": 40,
    "instrumental": 30,
    "acoustic": 15,
    "slowed": 35,
    "sped up": 35,
    "reverb": 20,
    "nightcore": 40,
    "8d": 35,
    "bass boosted": 30,
    "reaction": 40,
    "tutorial": 40,
    "lesson": 30,
    "mashup": 30,
    "parody": 30,
    "1 hour": 35,
    "10 hours": 35,
    "extended": 10,
    "alternate": 25,
    "alternative version": 25,
    "demo": 20,
    "lyrics": 12,
    "lyric": 12,
}


@dataclass
class Candidate:
    id: str
    title: str
    channel: str
    duration_s: float | None
    position: int
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def core_title(title: str) -> str:
    """'Song (feat. X) - Remastered 2011' -> 'song'."""
    title = re.split(r"\s[-–—]\s", title)[0]
    title = re.sub(r"[(\[].*?[)\]]", "", title)
    return normalize(title)


# Spotify title words that mean "a specific version": the video should say so too.
# Maps the word as it appears on Spotify -> the word to look for on YouTube.
VERSION_WORDS = {
    "instrumental": "instrumental",
    "inst": "instrumental",
    "live": "live",
    "remix": "remix",
    "acoustic": "acoustic",
    "unplugged": "unplugged",
    "demo": "demo",
    "slowed": "slowed",
    "sped up": "sped up",
    "a cappella": "a cappella",
    "acapella": "acapella",
}


def required_versions(track: Track) -> list[str]:
    title = normalize(track.title)
    found = [yt for word, yt in VERSION_WORDS.items() if _has_word(title, word)]
    return list(dict.fromkeys(found))


def search_query(track: Track) -> str:
    extra = " ".join(required_versions(track))
    return f"{track.artist} {core_title(track.title) or track.title} {extra}".strip()


def search_url(track: Track) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(search_query(track))


def search(track: Track, n: int = SEARCH_RESULTS) -> list[Candidate]:
    import yt_dlp  # slow-ish import; keep it out of module load

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{search_query(track)}", download=False)
    candidates = []
    for i, e in enumerate(info.get("entries") or []):
        if not e or not e.get("id"):
            continue
        candidates.append(
            Candidate(
                id=e["id"],
                title=e.get("title") or "",
                channel=e.get("channel") or e.get("uploader") or "",
                duration_s=e.get("duration"),
                position=i,
            )
        )
    return candidates


def _has_word(haystack: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


def score(track: Track, c: Candidate, prefer: str = "video") -> Candidate:
    """prefer: "video" favors official music videos, "audio" favors the album version."""
    s = 0.0
    reasons: list[str] = []

    def add(points: float, why: str) -> None:
        nonlocal s
        s += points
        reasons.append(f"{points:+g} {why}")

    artist = normalize(track.artist)
    artist_compact = artist.replace(" ", "")
    channel = normalize(c.channel)
    channel_compact = channel.replace(" ", "")
    vtitle = normalize(c.title)
    official_channel = bool(artist_compact and artist_compact in channel_compact) or "vevo" in channel_compact
    official_video = _has_word(vtitle, "official video") or _has_word(vtitle, "official music video")

    # Duration is the strongest signal that this is the same recording.
    if track.duration_s and c.duration_s:
        diff = abs(track.duration_s - c.duration_s)
        if diff <= 3:
            add(40, "duration match")
        elif diff <= 10:
            add(20, "duration close")
        elif official_channel and official_video and c.duration_s > track.duration_s and diff <= 90:
            add(15, "music video (intro/outro)")
        elif diff > 30:
            add(-30 - min(diff / 10, 30), f"duration off by {diff:.0f}s")

    if channel == f"{artist} topic":
        add(25, "artist Topic channel")
    elif artist_compact and artist_compact in channel_compact:
        add(20, "artist's channel")
    elif "vevo" in channel_compact:
        add(15, "VEVO channel")

    want = core_title(track.title)
    if want and _has_word(vtitle, want):
        add(20, "title match")
    else:
        add(-20, "title mismatch")
    if artist and (_has_word(vtitle, artist) or "topic" in channel):
        add(5, "artist in title")
    if official_video:
        add(15 if official_channel else 8, "official video")
    elif _has_word(vtitle, "official audio"):
        add(6, "official audio")

    if prefer == "video" and official_video and official_channel:
        add(20, "music video (preferred)")
    elif prefer == "audio":
        if channel.endswith(" topic") or _has_word(vtitle, "official audio") or _has_word(vtitle, "audio"):
            add(25, "audio version (preferred)")
        if official_video or _has_word(vtitle, "music video"):
            add(-20, "music video (audio preferred)")

    for version in required_versions(track):
        if _has_word(vtitle, version):
            add(20, f'is the "{version}" version')
        else:
            add(-30, f'missing "{version}"')

    spotify_title = normalize(track.title)
    for word, penalty in PENALTY_WORDS.items():
        if _has_word(vtitle, word) and not _has_word(spotify_title, word):
            add(-penalty, f'"{word}"')

    # Tie-breaker: trust YouTube's ordering a little.
    s -= c.position
    c.score = s
    c.reasons = reasons
    return c


def rank(track: Track, candidates: list[Candidate], prefer: str = "video") -> list[Candidate]:
    return sorted((score(track, c, prefer) for c in candidates), key=lambda c: c.score, reverse=True)


def find_best(track: Track, prefer: str = "video") -> tuple[Candidate | None, list[Candidate]]:
    ranked = rank(track, search(track), prefer)
    return (ranked[0] if ranked else None), ranked


PLAY_ALL_CHUNK = 50  # YouTube's anonymous watch_videos playlists top out around here


def play_all_urls(video_ids: list[str], chunk: int = PLAY_ALL_CHUNK) -> list[str]:
    """Anonymous YouTube playlist links (no account needed), one per `chunk` videos."""
    return [
        "https://www.youtube.com/watch_videos?video_ids=" + ",".join(video_ids[i : i + chunk])
        for i in range(0, len(video_ids), chunk)
    ]
