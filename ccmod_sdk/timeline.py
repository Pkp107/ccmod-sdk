"""Timeline API: read and edit a CapCut project's timeline (tracks, clips, keyframes) as data.

A project draft is JSON (draft_content.json). This module gives it a small, stable Python API with safe saving:

    tl = Timeline.open("0216")             # project folder name, or a path to a draft_content.json
    for c in tl.clips():                   # every segment on every track
        print(c.id, c.track_type, c.start, c.duration)
    tl.add_keyframe(clip.id, "alpha", 0.0, 0.0)
    tl.add_keyframe(clip.id, "alpha", 1.5, 1.0)
    tl.split(clip.id, 2.0)                 # cut at 2 s on the timeline
    tl.save()                              # snapshot first (draftguard), then atomic write

Times in this API are **seconds** (floats); the draft stores microseconds and this class converts. CapCut must have the project
closed (or reopen it) to see the edit: this edits the file, not the live editor. Nothing here touches accounts, licensing,
Pro flags or the watermark; those fields are never read or written.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

US = 1_000_000

# the keyframe property names CapCut uses, by friendly name
PROPERTIES = {
    "alpha": "KFTypeAlpha", "opacity": "KFTypeAlpha", "scale": "KFTypeScaleX", "scale_x": "KFTypeScaleX", "scale_y": "KFTypeScaleY",
    "rotation": "KFTypeRotation", "x": "KFTypePositionX", "y": "KFTypePositionY", "volume": "KFTypeVolume",
}
CURVES = ("Line", "Bezier")


class TimelineError(ValueError):
    pass


@dataclass
class Clip:
    id: str
    track_index: int
    track_type: str
    start: float
    duration: float
    material_id: str
    speed: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def _us(seconds: float) -> int:
    return int(round(float(seconds) * US))


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


class Timeline:
    def __init__(self, data: dict, path: Path | None = None):
        if not isinstance(data, dict) or "tracks" not in data:
            raise TimelineError("not a CapCut draft (no 'tracks')")
        self.data = data
        self.path = path
        self.dirty = False

    # ---- open / save ----
    @classmethod
    def open(cls, project_or_path: str | Path) -> "Timeline":
        p = Path(str(project_or_path))
        if not p.suffix:                                     # a project name
            import draftguard
            p = draftguard.drafts_root() / str(project_or_path) / "draft_content.json"
        elif p.is_dir():
            p = p / "draft_content.json"
        if not p.is_file():
            raise FileNotFoundError(p)
        return cls(json.loads(p.read_text(encoding="utf-8")), p)

    def save(self, path: str | Path | None = None, backup: bool = True) -> Path:
        """Write the draft atomically. Keeps one `.ccmod-backup` copy of the original next to it the first time."""
        out = Path(path) if path else self.path
        if out is None:
            raise TimelineError("no path to save to")
        if backup and out.exists():
            bak = out.with_name(out.name + ".ccmod-backup")
            if not bak.exists():
                bak.write_bytes(out.read_bytes())
        fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, out)
        self.dirty = False
        return out

    # ---- reading ----
    @property
    def duration(self) -> float:
        end = max((c.end for c in self.clips()), default=0.0)
        return max(end, float(self.data.get("duration", 0)) / US)

    def tracks(self) -> list[dict]:
        return [{"index": i, "type": t.get("type", ""), "name": t.get("name", ""), "clips": len(t.get("segments", []))}
                for i, t in enumerate(self.data["tracks"])]

    def clips(self, track_type: str | None = None) -> list[Clip]:
        out = []
        for i, t in enumerate(self.data["tracks"]):
            if track_type and t.get("type") != track_type:
                continue
            for s in t.get("segments", []):
                tr = s.get("target_timerange") or {}
                out.append(Clip(s.get("id", ""), i, t.get("type", ""), tr.get("start", 0) / US, tr.get("duration", 0) / US,
                                s.get("material_id", ""), float(s.get("speed", 1.0) or 1.0)))
        return sorted(out, key=lambda c: (c.start, c.track_index))

    def _find(self, clip_id: str) -> tuple[dict, dict]:
        for t in self.data["tracks"]:
            for s in t.get("segments", []):
                if s.get("id") == clip_id:
                    return t, s
        raise TimelineError(f"no clip with id {clip_id!r}")

    def keyframes(self, clip_id: str) -> dict[str, list[dict]]:
        """{property: [{time, value, curve}]} for a clip, times in seconds from the clip's start."""
        _, s = self._find(clip_id)
        rev = {v: k for k, v in PROPERTIES.items() if k not in ("opacity", "scale_x")}
        out: dict[str, list[dict]] = {}
        for kf in s.get("common_keyframes", []):
            name = rev.get(kf.get("property_type"), kf.get("property_type"))
            out[name] = [{"time": e.get("time_offset", 0) / US, "value": (e.get("values") or [0])[0], "curve": e.get("curveType", "Line")}
                         for e in kf.get("keyframe_list", [])]
        return out

    # ---- editing ----
    def add_keyframe(self, clip_id: str, prop: str, time: float, value: float, curve: str = "Line") -> None:
        """Add (or replace the one at the same time) a keyframe. `time` is seconds from the clip's start."""
        if prop not in PROPERTIES and not prop.startswith("KFType"):
            raise TimelineError(f"unknown property {prop!r}; use one of {sorted(PROPERTIES)} or a raw KFType name")
        if curve not in CURVES:
            raise TimelineError(f"curve must be one of {CURVES}")
        _, s = self._find(clip_id)
        if time < 0 or time > float(s["target_timerange"]["duration"]) / US + 1e-9:
            raise TimelineError("keyframe time is outside the clip")
        ptype = PROPERTIES.get(prop, prop)
        lst = s.setdefault("common_keyframes", [])
        entry = next((k for k in lst if k.get("property_type") == ptype), None)
        if entry is None:
            entry = {"id": _new_id(), "material_id": "", "property_type": ptype, "keyframe_list": []}
            lst.append(entry)
        off = _us(time)
        entry["keyframe_list"] = [k for k in entry["keyframe_list"] if k.get("time_offset") != off]
        entry["keyframe_list"].append({"id": _new_id(), "curveType": curve, "time_offset": off,
                                       "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
                                       "values": [float(value)], "string_value": "", "graphID": ""})
        entry["keyframe_list"].sort(key=lambda k: k["time_offset"])
        self.dirty = True

    def clear_keyframes(self, clip_id: str, prop: str | None = None) -> int:
        _, s = self._find(clip_id)
        lst = s.get("common_keyframes", [])
        keep = [k for k in lst if prop is not None and k.get("property_type") != PROPERTIES.get(prop, prop)]
        n = len(lst) - len(keep)
        s["common_keyframes"] = keep
        self.dirty = bool(n) or self.dirty
        return n

    def move(self, clip_id: str, start: float) -> None:
        """Move a clip to a new start time (seconds). Refuses overlaps on the same track."""
        t, s = self._find(clip_id)
        dur = s["target_timerange"]["duration"]
        new = _us(start)
        if new < 0:
            raise TimelineError("start must be >= 0")
        for o in t["segments"]:
            if o is s:
                continue
            ot = o["target_timerange"]
            if new < ot["start"] + ot["duration"] and ot["start"] < new + dur:
                raise TimelineError("would overlap another clip on this track")
        s["target_timerange"]["start"] = new
        self.dirty = True

    def trim(self, clip_id: str, start: float | None = None, end: float | None = None) -> None:
        """Trim a clip's head/tail. `start`/`end` are timeline seconds inside the clip."""
        _, s = self._find(clip_id)
        tr, sr = s["target_timerange"], s.get("source_timerange") or {"start": 0, "duration": s["target_timerange"]["duration"]}
        speed = float(s.get("speed", 1.0) or 1.0)
        a, b = tr["start"], tr["start"] + tr["duration"]
        na = _us(start) if start is not None else a
        nb = _us(end) if end is not None else b
        if not (a <= na < nb <= b):
            raise TimelineError("trim must stay inside the clip and leave some length")
        sr["start"] = int(sr["start"] + (na - a) * speed)
        sr["duration"] = int((nb - na) * speed)
        tr["start"], tr["duration"] = na, nb - na
        s["source_timerange"] = sr
        self._shift_keyframes(s, -(na - a), nb - na)
        self.dirty = True

    def split(self, clip_id: str, at: float) -> tuple[str, str]:
        """Cut a clip in two at timeline second `at`. Returns the two clip ids (the first keeps the original id)."""
        t, s = self._find(clip_id)
        tr = s["target_timerange"]
        cut = _us(at)
        if not (tr["start"] < cut < tr["start"] + tr["duration"]):
            raise TimelineError("split point must be inside the clip")
        right = copy.deepcopy(s)
        right["id"] = _new_id()
        d1 = cut - tr["start"]
        speed = float(s.get("speed", 1.0) or 1.0)
        sr = s.get("source_timerange") or {"start": 0, "duration": tr["duration"]}
        right["target_timerange"] = {"start": cut, "duration": tr["duration"] - d1}
        right["source_timerange"] = {"start": int(sr["start"] + d1 * speed), "duration": int(sr["duration"] - d1 * speed)}
        s["source_timerange"] = {"start": sr["start"], "duration": int(d1 * speed)}
        s["target_timerange"] = {"start": tr["start"], "duration": d1}
        self._shift_keyframes(right, -d1, right["target_timerange"]["duration"])
        self._shift_keyframes(s, 0, d1)
        t["segments"].insert(t["segments"].index(s) + 1, right)
        self.dirty = True
        return s["id"], right["id"]

    def remove(self, clip_id: str) -> None:
        t, s = self._find(clip_id)
        t["segments"].remove(s)
        self.dirty = True

    @staticmethod
    def _shift_keyframes(seg: dict, delta_us: int, new_len_us: int) -> None:
        for kf in seg.get("common_keyframes", []):
            kf["keyframe_list"] = [dict(k, time_offset=k["time_offset"] + delta_us) for k in kf.get("keyframe_list", [])
                                   if 0 <= k["time_offset"] + delta_us <= new_len_us]
