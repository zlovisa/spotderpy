from spotderpy.spotify import Track
from spotderpy.youtube import Candidate, core_title, rank


def cands(*rows):
    return [Candidate(id=f"v{i}", title=t, channel=ch, duration_s=d, position=i) for i, (t, ch, d) in enumerate(rows)]


def test_core_title():
    assert core_title("Don't Stop Me Now - Remastered 2011") == "don t stop me now"
    assert core_title("Stay (with Justin Bieber)") == "stay"
    assert core_title("Señorita") == "senorita"


def test_official_beats_cover_ranked_first():
    track = Track("x", "Never Gonna Give You Up", ["Rick Astley"], 213.6)
    ranked = rank(
        track,
        cands(
            ("Never Gonna Give You Up (cover)", "Some Guy", 215),
            ("Rick Astley - Never Gonna Give You Up (Official Video)", "Rick Astley", 214),
        ),
    )
    assert ranked[0].id == "v1"


def test_topic_channel_beats_random_upload():
    track = Track("x", "Bohemian Rhapsody - Remastered 2011", ["Queen"], 354)
    ranked = rank(
        track,
        cands(
            ("Queen - Bohemian Rhapsody", "music4ever", 360),
            ("Bohemian Rhapsody (Remastered 2011)", "Queen - Topic", 355),
        ),
    )
    assert ranked[0].id == "v1"


def test_duration_mismatch_penalized():
    track = Track("x", "Song", ["Artist"], 200)
    ranked = rank(
        track,
        cands(
            ("Artist - Song (Official Video)", "Artist", 420),  # long music video edit
            ("Artist - Song (Official Audio)", "Artist", 201),
        ),
    )
    assert ranked[0].id == "v1"


def test_live_not_penalized_when_spotify_track_is_live():
    track = Track("x", "Song - Live at Wembley", ["Artist"], 300)
    ranked = rank(
        track,
        cands(
            ("Artist - Song (Studio Version)", "Artist", 240),
            ("Artist - Song (Live at Wembley)", "Artist", 301),
        ),
    )
    assert ranked[0].id == "v1"
    assert not any(r.startswith("-") and '"live"' in r for r in ranked[0].reasons)


def test_slowed_and_nightcore_lose():
    track = Track("x", "Song", ["Artist"], 180)
    ranked = rank(
        track,
        cands(
            ("Artist - Song (slowed + reverb)", "edits", 180),
            ("Nightcore - Song", "nc", 180),
            ("Artist - Song", "ArtistVEVO", 181),
        ),
    )
    assert ranked[0].id == "v2"


def test_official_music_video_with_intro_beats_lyric_video():
    track = Track("x", "Shape of You", ["Ed Sheeran"], 233.7)
    ranked = rank(
        track,
        cands(
            ("Ed Sheeran - Shape Of You [Official Lyric Video]", "Ed Sheeran", 234),
            ("Ed Sheeran - Shape of You (Official Music Video)", "Ed Sheeran", 263),
        ),
    )
    assert ranked[0].id == "v1"


def test_alternate_version_penalized():
    track = Track("x", "Mr. Brightside", ["The Killers"], 222)
    ranked = rank(
        track,
        cands(
            ("The Killers - Mr. Brightside (Alternate Version) (Official Music Video)", "TheKillersMusic", 224),
            ("The Killers - Mr. Brightside (Official Music Video)", "TheKillersMusic", 228),
        ),
    )
    assert ranked[0].id == "v1"


def test_instrumental_track_prefers_instrumental_video():
    track = Track("x", "This Is How We Do It - Instrumental", ["Montell Jordan"], 225)
    ranked = rank(
        track,
        cands(
            ("Montell Jordan - This Is How We Do It (Official Music Video)", "Montell Jordan", 250),
            ("This Is How We Do It (Instrumental)", "Montell Jordan - Topic", 225),
        ),
    )
    assert ranked[0].id == "v1"


def test_inst_abbreviation_and_query():
    from spotderpy.youtube import required_versions, search_query

    track = Track("x", "Ma Boy 2 (inst.)", ["SISTAR19"], 200)
    assert required_versions(track) == ["instrumental"]
    assert search_query(track) == "SISTAR19 ma boy 2 instrumental"
    assert required_versions(Track("x", "Never Gonna Give You Up", ["Rick Astley"])) == []


def test_audio_preference_picks_topic_upload():
    track = Track("x", "Shape of You", ["Ed Sheeran"], 233.7)
    rows = (
        ("Ed Sheeran - Shape of You (Official Music Video)", "Ed Sheeran", 263),
        ("Shape of You", "Ed Sheeran - Topic", 234),
    )
    assert rank(track, cands(*rows))[0].id == "v0"
    assert rank(track, cands(*rows), prefer="audio")[0].id == "v1"
