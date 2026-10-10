import json

import pytest

from spotderpy import spotify

TID = "4PTG3Z6ehGkBFwjybzWkR8"


@pytest.mark.parametrize(
    "text",
    [
        f"https://open.spotify.com/track/{TID}",
        f"https://open.spotify.com/track/{TID}?si=abc123def456",
        f"https://open.spotify.com/intl-de/track/{TID}?si=x",
        f"https://open.spotify.com/intl-pt-br/track/{TID}",
        f"https://open.spotify.com/embed/track/{TID}",
        f"spotify:track:{TID}",
        f"check this out!! https://open.spotify.com/track/{TID}?si=1 so good",
    ],
)
def test_find_track_id(text):
    assert spotify.find_track_id(text) == TID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello world",
        "https://open.spotify.com/album/4PTG3Z6ehGkBFwjybzWkR8",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://open.spotify.com/track/tooShort",
    ],
)
def test_find_track_id_rejects(text):
    assert spotify.find_track_id(text) is None


def test_short_link_detected():
    assert spotify.looks_like_spotify("https://spotify.link/AbCdEf123")
    assert spotify.find_short_link("x https://spotify.app.link/AbC_d-9?e=1") == "https://spotify.app.link/AbC_d-9"


def test_parse_embed_html():
    data = {
        "props": {
            "pageProps": {
                "state": {
                    "data": {
                        "entity": {
                            "type": "track",
                            "name": "Never Gonna Give You Up",
                            "artists": [{"name": "Rick Astley"}],
                            "duration": 213573,
                        }
                    }
                }
            }
        }
    }
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'
    track = spotify.parse_embed_html(page, TID)
    assert track.title == "Never Gonna Give You Up"
    assert track.artists == ["Rick Astley"]
    assert track.duration_s == pytest.approx(213.573)


def test_parse_embed_html_unexpected_shape():
    page = '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
    assert spotify.parse_embed_html(page, TID) is None
    assert spotify.parse_embed_html("<html></html>", TID) is None


def test_parse_track_page_fallback():
    page = (
        '<meta property="og:title" content="Don&#x27;t Stop Me Now - Remastered 2011"/>'
        '<meta property="og:description" content="Queen · Jazz · Song · 1978"/>'
        '<meta name="music:duration" content="209"/>'
    )
    track = spotify.parse_track_page_html(page, TID)
    assert track.title == "Don't Stop Me Now - Remastered 2011"
    assert track.artists == ["Queen"]
    assert track.duration_s == 209


PID = "37i9dQZF1DXcBWIGoYBM5M"
T2 = "0VjIjW4GlUZAMYd2vXMi3b"


@pytest.mark.parametrize(
    "text, kind, ids",
    [
        (f"https://open.spotify.com/playlist/{PID}?si=abc", "playlist", [PID]),
        (f"https://open.spotify.com/intl-fr/album/{TID}", "album", [TID]),
        (f"spotify:playlist:{PID}", "playlist", [PID]),
        (f"https://open.spotify.com/track/{TID}?si=1", "track", [TID]),
        # Ctrl+A, Ctrl+C in a Spotify playlist: one link per line (dupes collapse, order kept)
        (f"https://open.spotify.com/track/{T2}\r\nhttps://open.spotify.com/track/{TID}\r\nhttps://open.spotify.com/track/{T2}",
         "tracks", [T2, TID]),
    ],
)
def test_classify(text, kind, ids):
    target = spotify.classify(text)
    assert (target.kind, target.ids) == (kind, ids)
    assert target.is_batch == (kind != "track")


def test_classify_nothing():
    assert spotify.classify("no links here") is None


def test_parse_embed_collection():
    entity = {
        "type": "playlist",
        "name": "Road Trip",
        "trackList": [
            {"uri": f"spotify:track:{TID}", "title": "Never Gonna Give You Up", "subtitle": "Rick Astley", "duration": 213573},
            {"uri": f"spotify:track:{T2}", "title": "Stay", "subtitle": "The Kid LAROI, Justin Bieber", "duration": 141805},
            {"uri": "spotify:episode:xyz", "title": "Some podcast", "subtitle": "", "duration": 1},
        ],
    }
    page = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}) + "</script>")
    c = spotify.parse_embed_collection(page, "playlist", PID)
    assert c.name == "Road Trip"
    assert [t.id for t in c.tracks] == [TID, T2]
    assert c.tracks[1].artists == ["The Kid LAROI", "Justin Bieber"]
    assert c.tracks[1].artist == "The Kid LAROI"
    assert not c.maybe_truncated
