"""Match a whole playlist/album (or a pile of track links) to YouTube and write a results page."""

from __future__ import annotations

import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__, spotify, youtube
from .config import default_results_dir
from .spotify import Track

WORKERS = 4
LOW_CONFIDENCE = 45  # scores below this get flagged for a manual check


@dataclass
class Result:
    position: int
    track: Track | None
    best: youtube.Candidate | None = None
    error: str | None = None
    source_id: str = ""

    @property
    def confident(self) -> bool:
        return self.best is not None and self.best.score >= LOW_CONFIDENCE


@dataclass
class BatchResult:
    name: str
    source_url: str
    results: list[Result]
    note: str | None = None

    @property
    def video_ids(self) -> list[str]:
        return [r.best.id for r in self.results if r.best]

    @property
    def play_all_urls(self) -> list[str]:
        return youtube.play_all_urls(self.video_ids)


Progress = Callable[[int, int, Result], None]


def _match_one(position: int, item: Track | str, prefer: str = "video") -> Result:
    track = item if isinstance(item, Track) else None
    source_id = item.id if isinstance(item, Track) else item
    for attempt in range(2):
        try:
            if track is None:
                track = spotify.get_track(source_id)
            best, _ = youtube.find_best(track, prefer)
            return Result(position, track, best, None if best else "no YouTube results", source_id)
        except Exception as e:  # network hiccups, YouTube throttling
            error = str(e) or type(e).__name__
            time.sleep(1.5)
    return Result(position, track, None, error, source_id)


def match_all(items: list[Track | str], progress: Progress | None = None, prefer: str = "video") -> list[Result]:
    """Items are Tracks (playlist/album) or bare track IDs (pasted links). Order is preserved."""
    results: list[Result | None] = [None] * len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(_match_one, i, item, prefer) for i, item in enumerate(items)]
        for fut in futures:
            r = fut.result()
            results[r.position] = r
            done += 1
            if progress:
                progress(done, len(items), r)
    return [r for r in results if r is not None]


def run(target: spotify.Target, progress: Progress | None = None, prefer: str = "video") -> BatchResult:
    if target.kind in ("playlist", "album"):
        collection = spotify.get_collection(target.kind, target.id)
        note = None
        if collection.kind == "playlist" and collection.maybe_truncated:
            note = (
                f"Spotify's public page only lists the first {spotify.EMBED_TRACK_LIMIT} songs. "
                "For the whole playlist: open it in the Spotify app, click a song, press Ctrl+A then Ctrl+C, "
                "and copy that instead."
            )
        results = match_all(list(collection.tracks), progress, prefer)
        return BatchResult(collection.name, collection.url, results, note)
    results = match_all(list(target.ids), progress, prefer)
    return BatchResult(f"{len(target.ids)} Spotify songs", "", results)


# ---- output -----------------------------------------------------------------

LOGO_SVG = (
    '<svg width="22" height="22" viewBox="0 0 64 64" aria-hidden="true">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#7c3aed"/><stop offset="1" stop-color="#fb7185"/></linearGradient></defs>'
    '<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>'
    '<path d="M16 19v26l21-13z" fill="#fff"/>'
    '<path d="M40 25a10 10 0 0 1 0 14M45 20a17 17 0 0 1 0 24" stroke="#fff" stroke-width="3.4" fill="none" stroke-linecap="round"/>'
    "</svg>"
)

def reports_dir(base: Path | None = None) -> Path:
    d = base or default_results_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_report_path(batch: BatchResult, ext: str = ".html", base: Path | None = None) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", batch.name).strip(" .") or "playlist"
    stamp = datetime.now().strftime("%Y-%m-%d %H%M")
    return reports_dir(base) / f"{safe[:80]} ({stamp}){ext}"


def write(batch: BatchResult, path: Path) -> Path:
    ext = path.suffix.lower()
    if ext == ".csv":
        _write_csv(batch, path)
    elif ext == ".txt":
        path.write_text("\n".join(r.best.url for r in batch.results if r.best) + "\n", encoding="utf-8")
    else:
        path.write_text(render_html(batch), encoding="utf-8")
    return path


def _write_csv(batch: BatchResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads UTF-8
        w = csv.writer(f)
        w.writerow(["#", "artist", "title", "youtube_url", "youtube_title", "channel", "score", "check"])
        for r in batch.results:
            t, b = r.track, r.best
            w.writerow([
                r.position + 1,
                ", ".join(t.artists) if t else "",
                t.title if t else r.source_id,
                b.url if b else "",
                b.title if b else (r.error or ""),
                b.channel if b else "",
                f"{b.score:.0f}" if b else "",
                "" if r.confident else "yes",
            ])


def _fmt_dur(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def render_html(batch: BatchResult) -> str:
    e = html.escape
    matched = sum(1 for r in batch.results if r.best)
    flagged = sum(1 for r in batch.results if r.best and not r.confident)
    rows = []
    for r in batch.results:
        t, b = r.track, r.best
        song = (
            f'<div class="t">{e(t.title)}</div><div class="a">{e(", ".join(t.artists))}'
            f'<span class="d">{_fmt_dur(t.duration_s)}</span></div>'
            if t else f'<div class="t">{e(r.source_id)}</div>'
        )
        search = youtube.search_url(t) if t else ""
        if b:
            flag = "" if r.confident else '<span class="flag">check</span>'
            match = (
                f'<a class="m" href="{e(b.url)}" target="_blank" rel="noopener">'
                f'<img loading="lazy" src="https://i.ytimg.com/vi/{e(b.id)}/mqdefault.jpg" alt="">'
                f'<span><span class="t">{e(b.title)}</span><span class="a">{e(b.channel)}'
                f'<span class="d">{_fmt_dur(b.duration_s)}</span></span></span></a>'
                f'<div class="x">{flag}<a href="{e(search)}" target="_blank" rel="noopener">other results</a></div>'
            )
        else:
            match = (
                f'<div class="err">Not found ({e(r.error or "")})</div>'
                + (f'<a href="{e(search)}" target="_blank" rel="noopener">search YouTube</a>' if t else "")
            )
        cls = "" if r.confident else ' class="low"'
        rows.append(f"<tr{cls}><td class=n>{r.position + 1}</td><td>{song}</td><td>{match}</td></tr>")

    chunks = batch.play_all_urls
    size = youtube.PLAY_ALL_CHUNK
    play_buttons = "".join(
        f'<a class="btn primary" href="{e(u)}" target="_blank" rel="noopener">▶ Play '
        + ("all" if len(chunks) == 1 else f"{i * size + 1}–{min((i + 1) * size, matched)}")
        + " on YouTube</a>"
        for i, u in enumerate(chunks)
    )
    links_json = json.dumps([r.best.url for r in batch.results if r.best])
    source = (
        f' · <a href="{e(batch.source_url)}" target="_blank" rel="noopener">open in Spotify</a>'
        if batch.source_url else ""
    )
    note = f'<p class="note">{e(batch.note)}</p>' if batch.note else ""
    summary = f"{matched} of {len(batch.results)} songs matched"
    if flagged:
        summary += f" · {flagged} flagged to check"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(batch.name)} · Spotderpy</title>
<style>
:root {{ --bg:#f7f7fb; --fg:#18181b; --mut:#6b6b76; --card:#fff; --line:#e6e6ee; --acc:#7c3aed; --acc2:#fb7185; --warn:#fff6db; --warnfg:#8a4b00; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111116; --fg:#f4f4f5; --mut:#a1a1aa; --card:#1b1b22; --line:#2c2c36; --acc:#a78bfa; --acc2:#fb7185; --warn:#33290f; --warnfg:#fcd34d; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:28px; }}
.sub {{ color:var(--mut); margin-bottom:20px; }}
.sub a, td a {{ color:inherit; }}
.bar {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:20px; }}
.btn {{ border:1px solid var(--line); background:var(--card); color:var(--fg); padding:9px 14px; border-radius:8px; font:inherit; cursor:pointer; text-decoration:none; }}
.btn.primary {{ background:linear-gradient(135deg,#7c3aed,#f472b6); border:0; color:#fff; font-weight:600; }}
.brand {{ display:flex; align-items:center; gap:8px; color:var(--mut); font-size:13px; font-weight:600; margin-bottom:18px; text-decoration:none; }}
footer {{ color:var(--mut); font-size:12px; margin-top:28px; text-align:center; }}
footer a {{ color:inherit; }}
.note {{ background:var(--warn); color:var(--warnfg); padding:10px 14px; border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
td {{ padding:10px 12px; border-top:1px solid var(--line); vertical-align:middle; }}
tr:first-child td {{ border-top:0; }}
tr.low {{ background:var(--warn); }}
td.n {{ color:var(--mut); width:1%; text-align:right; }}
td:nth-child(2) {{ width:38%; }}
.t {{ font-weight:600; display:block; }}
.a {{ color:var(--mut); font-size:13px; display:block; }}
.d {{ margin-left:8px; }}
.m {{ display:flex; gap:10px; align-items:center; text-decoration:none; color:inherit; }}
.m img {{ width:96px; aspect-ratio:16/9; object-fit:cover; border-radius:6px; flex:none; background:var(--line); }}
.x {{ font-size:12px; color:var(--mut); margin-top:4px; }}
.flag {{ color:var(--warnfg); font-weight:700; margin-right:8px; }}
.err {{ color:#e11d48; }}
@media (max-width:640px) {{ td:nth-child(2) {{ width:auto; }} .m img {{ width:72px; }} td {{ padding:8px; }} }}
</style></head><body><main>
<div class="brand">{LOGO_SVG}<span>Spotderpy</span></div>
<h1>{e(batch.name)}</h1>
<div class="sub">{summary}{source}</div>
{note}
<div class="bar">{play_buttons}<button class="btn" id="copy">Copy all links</button></div>
<table>{"".join(rows)}</table>
<footer>Made with Spotderpy {__version__} · Matches are automatic. Highlighted rows are worth a quick check. · Not affiliated with Spotify or YouTube.</footer>
</main>
<script>
const links = {links_json};
document.getElementById("copy").onclick = async (ev) => {{
  try {{ await navigator.clipboard.writeText(links.join("\\n")); ev.target.textContent = "Copied " + links.length + " links"; }}
  catch {{ ev.target.textContent = "Copy failed"; }}
}};
</script>
</body></html>
"""
