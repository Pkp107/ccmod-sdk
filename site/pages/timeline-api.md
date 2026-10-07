---
title: Timeline API
section: Building
order: 60
---

# Timeline API

Read and edit a project's timeline as data: tracks, clips, keyframes, split, trim, move. It works on the project's draft file (`draft_content.json`), so **close the project in CapCut (or reopen it) to see an edit**. It is not a live edit of the open editor.

```python
tl = self.ctx.draft.timeline("0216")          # needs the `draft` permission; or Timeline.open(path)
for clip in tl.clips("video"):
    print(clip.id, clip.start, clip.duration, clip.speed)

a, b = tl.split(clip.id, 2.0)                 # cut at 2 s on the timeline
tl.trim(b, start=3.0, end=5.0)
tl.move(b, 10.0)                              # refuses to overlap another clip on the track
tl.add_keyframe(a, "alpha", 0.0, 0.0)         # seconds from the clip start
tl.add_keyframe(a, "alpha", 1.0, 1.0)
tl.save()                                     # keeps a .ccmod-backup of the original, then writes atomically
```

All times are **seconds**; the draft stores microseconds and the API converts.

| Call | Returns | Notes |
|---|---|---|
| `Timeline.open(project_or_path)` | `Timeline` | a project folder name, a folder, or a `draft_content.json`. `FileNotFoundError` / `TimelineError` for bad input |
| `tracks()` | `list[dict]` | `{index, type, name, clips}` |
| `clips(track_type=None)` | `list[Clip]` | `id, track_index, track_type, start, duration, end, material_id, speed`, sorted by start |
| `duration` | `float` | end of the last clip |
| `keyframes(clip_id)` | `dict` | `{property: [{time, value, curve}]}` |
| `add_keyframe(clip_id, prop, time, value, curve="Line")` | `None` | replaces a key at the same time; keeps the list sorted. `prop`: `alpha`, `scale`, `scale_x`, `scale_y`, `rotation`, `x`, `y`, `volume`, or a raw `KFType...` name |
| `clear_keyframes(clip_id, prop=None)` | `int` | how many removed |
| `split(clip_id, at)` | `(id, id)` | splits source ranges and keyframes correctly; the first half keeps the id |
| `trim(clip_id, start=None, end=None)` | `None` | timeline seconds inside the clip |
| `move(clip_id, start)` | `None` | raises on overlap |
| `remove(clip_id)` | `None` | |
| `save(path=None, backup=True)` | `Path` | |

## What is verified

Unit tests cover every edit on a synthetic draft, and a real project's draft loads and writes back **identically** (round trip). Opening an edited project in CapCut has not yet been checked on screen, so keep the backup until you've looked. `time_marks` (markers) are not edited yet because their item format hasn't been confirmed.

## Safety

The API only touches the timeline structure. It never reads or writes Pro, account, licensing or watermark fields. `draftguard` (`ctx.draft.save/restore`) still protects a project from format bumps; use it when you open drafts in newer builds.
