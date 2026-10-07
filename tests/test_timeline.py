"""Timeline API on a synthetic draft (no CapCut) plus a read/round-trip check on a real draft when one exists."""
import json

import pytest

from ccmod_sdk.timeline import Timeline, TimelineError


def _draft(tmp_path):
    seg = lambda i, s, d: {"id": i, "material_id": "m" + i, "speed": 1.0, "source_timerange": {"start": 0, "duration": d},
                           "target_timerange": {"start": s, "duration": d}, "common_keyframes": []}
    data = {"duration": 10_000_000, "tracks": [{"type": "video", "name": "", "segments": [seg("A", 0, 4_000_000), seg("B", 4_000_000, 6_000_000)]},
                                              {"type": "audio", "segments": [seg("C", 0, 10_000_000)]}]}
    p = tmp_path / "draft_content.json"
    p.write_text(json.dumps(data))
    return p


def test_read_clips_and_tracks(tmp_path):
    tl = Timeline.open(_draft(tmp_path))
    assert [t["type"] for t in tl.tracks()] == ["video", "audio"]
    assert [(c.id, c.start, c.duration) for c in tl.clips("video")] == [("A", 0.0, 4.0), ("B", 4.0, 6.0)]
    assert tl.duration == 10.0


def test_keyframes_add_replace_sort_clear(tmp_path):
    tl = Timeline.open(_draft(tmp_path))
    tl.add_keyframe("A", "alpha", 2.0, 1.0)
    tl.add_keyframe("A", "alpha", 0.0, 0.0)
    tl.add_keyframe("A", "alpha", 2.0, 0.5)                      # same time: replaced
    kf = tl.keyframes("A")["alpha"]
    assert [(k["time"], k["value"]) for k in kf] == [(0.0, 0.0), (2.0, 0.5)]
    with pytest.raises(TimelineError):
        tl.add_keyframe("A", "alpha", 9.0, 1.0)                  # outside the clip
    with pytest.raises(TimelineError):
        tl.add_keyframe("A", "nonsense", 1.0, 1.0)
    assert tl.clear_keyframes("A", "alpha") == 1 and tl.keyframes("A") == {}


def test_split_trim_move_remove(tmp_path):
    tl = Timeline.open(_draft(tmp_path))
    tl.add_keyframe("A", "scale", 1.0, 1.0)
    tl.add_keyframe("A", "scale", 3.0, 2.0)
    a, b = tl.split("A", 2.0)
    assert a == "A" and b != "A"
    cs = {c.id: c for c in tl.clips("video")}
    assert (cs["A"].start, cs["A"].duration) == (0.0, 2.0) and (cs[b].start, cs[b].duration) == (2.0, 2.0)
    assert [k["time"] for k in tl.keyframes("A")["scale"]] == [1.0]
    assert [k["time"] for k in tl.keyframes(b)["scale"]] == [1.0]          # the 3 s key is 1 s into the right half
    right = tl._find(b)[1]
    assert right["source_timerange"] == {"start": 2_000_000, "duration": 2_000_000}
    with pytest.raises(TimelineError):
        tl.split("A", 5.0)
    tl.trim("B", start=5.0, end=9.0)
    sb = tl._find("B")[1]
    assert sb["target_timerange"] == {"start": 5_000_000, "duration": 4_000_000} and sb["source_timerange"]["start"] == 1_000_000
    with pytest.raises(TimelineError):
        tl.move("B", 3.0)                                                  # overlaps the right half of A
    tl.move("B", 6.0)
    assert tl._find("B")[1]["target_timerange"]["start"] == 6_000_000
    tl.remove(b)
    assert [c.id for c in tl.clips("video")] == ["A", "B"]


def test_save_backs_up_once_and_is_atomic(tmp_path):
    p = _draft(tmp_path)
    original = p.read_text()
    tl = Timeline.open(p)
    tl.remove("C")
    assert tl.dirty
    tl.save()
    assert (tmp_path / "draft_content.json.ccmod-backup").read_text() == original
    tl.remove("B")
    tl.save()
    assert (tmp_path / "draft_content.json.ccmod-backup").read_text() == original   # the first backup is kept
    assert [c.id for c in Timeline.open(p).clips()] == ["A"]
    assert not list(tmp_path.glob("*.tmp"))


def test_rejects_non_drafts(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")
    with pytest.raises(TimelineError):
        Timeline.open(f)
    with pytest.raises(FileNotFoundError):
        Timeline.open(tmp_path / "nope.json")


def test_real_draft_roundtrip(tmp_path):
    import draftguard
    try:
        src = draftguard.drafts_root() / "0216" / "draft_content.json"
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pytest.skip("no real draft available")
    tl = Timeline(data, tmp_path / "copy.json")
    assert tl.clips()
    tl.save(backup=False)
    assert json.loads((tmp_path / "copy.json").read_text(encoding="utf-8")) == data
