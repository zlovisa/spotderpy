import csv

from spotderpy import batch, youtube
from spotderpy.spotify import Track


def make_batch():
    def cand(vid, score):
        c = youtube.Candidate(id=vid, title=f"Video {vid} <b>", channel="Chan", duration_s=200, position=0)
        c.score = score
        return c

    results = [
        batch.Result(0, Track("a", "Song A", ["Artist & Co"], 200), cand("vidA", 90)),
        batch.Result(1, Track("b", "Song B", ["Artist"], 180), cand("vidB", 10)),
        batch.Result(2, Track("c", "Song C", ["Artist"], 180), None, "no YouTube results"),
    ]
    return batch.BatchResult("My <Playlist>", "https://open.spotify.com/playlist/x", results)


def test_play_all_urls_chunked():
    ids = [f"v{i}" for i in range(120)]
    urls = youtube.play_all_urls(ids)
    assert len(urls) == 3
    assert urls[0].startswith("https://www.youtube.com/watch_videos?video_ids=v0,v1,")
    assert urls[2].endswith("v100," + ",".join(f"v{i}" for i in range(101, 120)))


def test_confidence_and_ids():
    b = make_batch()
    assert [r.confident for r in b.results] == [True, False, False]
    assert b.video_ids == ["vidA", "vidB"]


def test_html_escapes_and_lists_everything():
    page = batch.render_html(make_batch())
    assert "My &lt;Playlist&gt;" in page and "<Playlist>" not in page
    assert "Video vidA &lt;b&gt;" in page
    assert "2 of 3 songs matched" in page and "1 flagged" in page
    assert "watch_videos?video_ids=vidA,vidB" in page
    assert "Not found" in page


def test_csv_and_txt(tmp_path):
    b = make_batch()
    rows = list(csv.reader(batch.write(b, tmp_path / "out.csv").open(encoding="utf-8-sig")))
    assert rows[0][:4] == ["#", "artist", "title", "youtube_url"]
    assert rows[1][3] == "https://www.youtube.com/watch?v=vidA"
    assert rows[2][-1] == "yes" and rows[3][3] == ""
    txt = batch.write(b, tmp_path / "out.txt").read_text(encoding="utf-8").split()
    assert txt == ["https://www.youtube.com/watch?v=vidA", "https://www.youtube.com/watch?v=vidB"]
