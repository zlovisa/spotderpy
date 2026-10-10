import json

from spotderpy import updates
from spotderpy.config import Settings, SettingsStore
from spotderpy.history import MAX_ENTRIES, History


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.data == Settings()
    store.update(prefer="audio", open_mode="choose")
    again = SettingsStore(path)
    assert again.data.prefer == "audio" and again.data.open_mode == "choose"


def test_settings_tolerates_junk(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"prefer": "audio", "from_a_future_version": 1}))
    assert SettingsStore(path).data.prefer == "audio"
    path.write_text("{not json")
    assert SettingsStore(path).data == Settings()


def test_history_persists_newest_first_and_caps(tmp_path):
    path = tmp_path / "history.json"
    h = History(path)
    for i in range(MAX_ENTRIES + 5):
        h.add("track", f"Song {i}", "video", f"https://youtu.be/{i}")
    again = History(path)
    assert len(again.entries) == MAX_ENTRIES
    assert again.entries[0].label == f"Song {MAX_ENTRIES + 4}"
    again.clear()
    assert History(path).entries == []


def test_version_compare():
    assert updates.is_newer("1.0.1", "1.0.0")
    assert updates.is_newer("v1.10.0", "1.9.9")
    assert updates.is_newer("2.0", "1.9.9")
    assert not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("0.9.0", "1.0.0")
    assert not updates.is_newer("1.0.0-beta", "1.0.0")
