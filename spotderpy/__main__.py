"""`python -m spotderpy` runs the tray app; `python -m spotderpy <link>` resolves a song, album or playlist."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import batch, spotify, youtube


def _single(track_id: str, args: argparse.Namespace) -> int:
    track = spotify.get_track(track_id)
    dur = f" ({int(track.duration_s // 60)}:{int(track.duration_s % 60):02d})" if track.duration_s else ""
    print(f"Spotify: {track}{dur}")

    best, ranked = youtube.find_best(track)
    if args.verbose:
        for c in ranked:
            print(f"  {c.score:6.1f}  {c.url}  [{c.channel}] {c.title}")
            print(f"          {', '.join(c.reasons)}")
    if best is None:
        print("No YouTube results; try:", youtube.search_url(track))
        return 1
    print(f"YouTube: {best.title} [{best.channel}]")
    print(best.url)
    if not args.no_open:
        webbrowser.open(best.url)
    return 0


def _batch(target: spotify.Target, args: argparse.Namespace) -> int:
    def progress(done: int, total: int, r: batch.Result) -> None:
        song = str(r.track) if r.track else r.source_id
        if r.best:
            mark = " " if r.confident else "?"
            print(f"[{done:>3}/{total}]{mark} {song}  ->  {r.best.url}  ({r.best.title})")
        else:
            print(f"[{done:>3}/{total}]! {song}  ->  not found: {r.error}")

    label = {"playlist": "playlist", "album": "album", "tracks": f"{len(target.ids)} songs"}[target.kind]
    print(f"Matching {label} (this takes ~1s per song, {batch.WORKERS} at a time)...")
    result = batch.run(target, progress)

    print()
    if result.note:
        print("Note:", result.note, "\n")
    flagged = [r for r in result.results if r.best and not r.confident]
    if flagged:
        print(f"{len(flagged)} match(es) marked '?' are worth a quick check.")
    for i, url in enumerate(result.play_all_urls, 1):
        print(f"Play on YouTube (part {i}): {url}" if len(result.play_all_urls) > 1 else f"Play all on YouTube: {url}")

    out = Path(args.output) if args.output else batch.default_report_path(result)
    batch.write(result, out)
    if out.suffix.lower() != ".html" and not args.output_only:
        html_path = batch.write(result, batch.default_report_path(result))
        print(f"Saved {out}\nResults page: {html_path}")
        out = html_path
    else:
        print(f"Saved {out}")
    if not args.no_open and out.suffix.lower() == ".html":
        webbrowser.open(out.resolve().as_uri())
    return 0


def cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="spotderpy",
        description="Find YouTube videos for a Spotify song, album or playlist link.",
    )
    parser.add_argument("link", nargs="?", help="Spotify song/album/playlist link (or spotify: URI)")
    parser.add_argument("-c", "--clipboard", action="store_true",
                        help="read link(s) from the clipboard, e.g. after Ctrl+A, Ctrl+C in a Spotify playlist")
    parser.add_argument("-f", "--file", help="read link(s) from a text file")
    parser.add_argument("-o", "--output", help="for albums/playlists: save results to this .html, .csv or .txt file")
    parser.add_argument("--output-only", action="store_true", help="with -o .csv/.txt, skip the HTML results page")
    parser.add_argument("-n", "--no-open", action="store_true", help="don't open anything in the browser")
    parser.add_argument("-v", "--verbose", action="store_true", help="single songs: show every candidate and its score")
    args = parser.parse_args(argv)

    if args.clipboard:
        import pyperclip

        text = pyperclip.paste()
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.link:
        text = args.link
    else:
        parser.error("give a link, or use --clipboard / --file")

    target = spotify.resolve(text)
    if not target:
        print("No Spotify song, album or playlist link found.", file=sys.stderr)
        return 2
    if target.is_batch:
        return _batch(target, args)
    return _single(target.id, args)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from .winutil import BACKGROUND_ARG

    args = sys.argv[1:]
    # The packaged Spotderpy.exe has no console, so the CLI is only for `python -m spotderpy`.
    if args and args != [BACKGROUND_ARG] and not getattr(sys, "frozen", False):
        sys.exit(cli(args))
    from .app import main as app_main

    app_main(background=BACKGROUND_ARG in args)


if __name__ == "__main__":
    main()
