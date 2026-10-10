"""Spotify link parsing and track/playlist metadata lookup (no API credentials needed)."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
# Spotify only renders og: meta tags for link-preview style clients, not browsers.
PREVIEW_USER_AGENT = "Spotderpy/0.1 (link preview)"
TIMEOUT = 10
EMBED_TRACK_LIMIT = 100  # the public embed page lists at most this many tracks

_ID = r"([A-Za-z0-9]{22})"
_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?(track|album|playlist)/" + _ID,
    re.IGNORECASE,
)
_URI_RE = re.compile(r"spotify:(track|album|playlist):" + _ID)
_SHORT_LINK_RE = re.compile(r"https?://spotify\.(?:link|app\.link)/[A-Za-z0-9_\-]+", re.IGNORECASE)


@dataclass
class Track:
    id: str
    title: str
    artists: list[str]
    duration_s: float | None = None

    @property
    def artist(self) -> str:
        return self.artists[0] if self.artists else ""

    def __str__(self) -> str:
        return f"{', '.join(self.artists)} - {self.title}"


@dataclass
class Collection:
    kind: str  # "playlist" or "album"
    id: str
    name: str
    tracks: list[Track]

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.kind}/{self.id}"

    @property
    def maybe_truncated(self) -> bool:
        return len(self.tracks) >= EMBED_TRACK_LIMIT


@dataclass
class Target:
    """What a piece of copied text points at."""

    kind: str  # "track", "playlist", "album", or "tracks" (several track links at once)
    ids: list[str]

    @property
    def id(self) -> str:
        return self.ids[0]

    @property
    def is_batch(self) -> bool:
        return self.kind != "track"


def _get(url: str, user_agent: str = USER_AGENT) -> requests.Response:
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def find_links(text: str) -> list[tuple[str, str]]:
    """All (kind, id) pairs in the text, in order, without duplicates."""
    if not text:
        return []
    matches = sorted(
        [*_URL_RE.finditer(text), *_URI_RE.finditer(text)], key=lambda m: m.start()
    )
    seen: dict[tuple[str, str], None] = {}
    for m in matches:
        seen.setdefault((m.group(1).lower(), m.group(2)), None)
    return list(seen)


def classify(text: str) -> Target | None:
    links = find_links(text)
    if not links:
        return None
    kind, first_id = links[0]
    if kind in ("playlist", "album"):
        return Target(kind, [first_id])
    track_ids = [i for k, i in links if k == "track"]
    if len(track_ids) > 1:
        return Target("tracks", track_ids)
    return Target("track", track_ids)


def find_track_id(text: str) -> str | None:
    """Return the first track ID in a full link or spotify: URI, without hitting the network."""
    return next((i for k, i in find_links(text) if k == "track"), None)


def find_short_link(text: str) -> str | None:
    if not text:
        return None
    m = _SHORT_LINK_RE.search(text)
    return m.group(0) if m else None


def looks_like_spotify(text: str) -> bool:
    return bool(find_links(text) or find_short_link(text))


def resolve(text: str) -> Target | None:
    """Like classify, but also follows spotify.link short links."""
    target = classify(text)
    if target:
        return target
    short = find_short_link(text)
    if not short:
        return None
    resp = _get(short)
    # Short links either redirect over HTTP or serve a page that redirects in JS;
    # either way the real URL appears in the final URL or the body.
    target = classify(resp.url)
    if target:
        return target
    body_links = find_links(resp.text)
    return Target(body_links[0][0], [body_links[0][1]]) if body_links else None


def _next_data_entity(page: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def parse_embed_html(page: str, track_id: str) -> Track | None:
    entity = _next_data_entity(page)
    if not entity:
        return None
    title = entity.get("name") or entity.get("title")
    artists = [a["name"] for a in entity.get("artists") or [] if a.get("name")]
    if not title or not artists:
        return None
    duration_ms = entity.get("duration")
    return Track(
        id=track_id,
        title=title,
        artists=artists,
        duration_s=duration_ms / 1000 if duration_ms else None,
    )


def parse_embed_collection(page: str, kind: str, collection_id: str) -> Collection | None:
    entity = _next_data_entity(page)
    if not entity or "trackList" not in entity:
        return None
    tracks = []
    for item in entity["trackList"] or []:
        title = item.get("title")
        artists = [a.strip() for a in (item.get("subtitle") or "").split(",") if a.strip()]
        if not title or not artists:
            continue  # podcast episodes, local files, etc.
        duration_ms = item.get("duration")
        tracks.append(
            Track(
                id=(item.get("uri") or "").rsplit(":", 1)[-1],
                title=title,
                artists=artists,
                duration_s=duration_ms / 1000 if duration_ms else None,
            )
        )
    name = entity.get("name") or entity.get("title") or f"Spotify {kind}"
    return Collection(kind=kind, id=collection_id, name=name, tracks=tracks)


def _meta(page: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', page
    )
    return html.unescape(m.group(1)) if m else None


def parse_track_page_html(page: str, track_id: str) -> Track | None:
    """Fallback: og tags on open.spotify.com/track/<id> ("Artist · Album · Song · Year")."""
    title = _meta(page, "og:title")
    desc = _meta(page, "og:description")
    if not title or not desc:
        return None
    artist = desc.split(" · ")[0].strip()
    if not artist:
        return None
    duration = _meta(page, "music:duration")
    return Track(
        id=track_id,
        title=title,
        artists=[artist],
        duration_s=float(duration) if duration and duration.isdigit() else None,
    )


def get_track(track_id: str) -> Track:
    track = parse_embed_html(_get(f"https://open.spotify.com/embed/track/{track_id}").text, track_id)
    if track:
        return track
    page = _get(f"https://open.spotify.com/track/{track_id}", PREVIEW_USER_AGENT).text
    track = parse_track_page_html(page, track_id)
    if track:
        return track
    raise LookupError(f"Couldn't read track info for Spotify track {track_id}")


def get_collection(kind: str, collection_id: str) -> Collection:
    page = _get(f"https://open.spotify.com/embed/{kind}/{collection_id}").text
    collection = parse_embed_collection(page, kind, collection_id)
    if collection is None:
        raise LookupError(f"Couldn't read the track list for Spotify {kind} {collection_id}")
    return collection
