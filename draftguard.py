"""draftguard — protect project drafts from CapCut-version format bumps.

Opening a project in a newer CapCut rewrites its draft (e.g. new_version 175 -> 181) and older builds then say
"update needed". Guard = snapshot before opening, restore after closing (or on demand).

    python draftguard.py save 0216        # snapshot draft_content.json (+ Timelines/*) as .ccguard
    python draftguard.py restore 0216     # put the snapshot back
    python draftguard.py status           # list projects, their format number, snapshots
"""
import json, re, shutil, sys
from pathlib import Path
import ccversion

SUFFIX = ".ccguard"


def drafts_root() -> Path:
    return ccversion.local_root() / "User Data" / "Projects" / "com.lveditor.draft"


def _files(proj: Path):
    f = [proj / "draft_content.json"]
    f += sorted((proj / "Timelines").glob("*/draft_content.json")) if (proj / "Timelines").is_dir() else []
    return [p for p in f if p.exists()]


def format_of(path: Path):
    try:
        m = re.search(r'"new_version"\s*:\s*"([\d.]+)"', path.read_text(encoding="utf-8")[:400000])
        return m.group(1) if m else None
    except OSError:
        return None


def save(name: str) -> int:
    proj = drafts_root() / name
    n = 0
    for f in _files(proj):
        shutil.copy2(f, f.with_name(f.name + SUFFIX)); n += 1
    return n


def restore(name: str) -> int:
    proj = drafts_root() / name
    n = 0
    for f in _files(proj):
        g = f.with_name(f.name + SUFFIX)
        if g.exists():
            shutil.copy2(g, f); n += 1
    return n


def status():
    for proj in sorted(p for p in drafts_root().iterdir() if p.is_dir()):
        fs = _files(proj)
        if not fs: continue
        snap = fs[0].with_name(fs[0].name + SUFFIX)
        print(f"{proj.name:<24} format={format_of(fs[0])}  snapshot={format_of(snap) if snap.exists() else '-'}")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "status"
    if c == "save": print("saved", save(sys.argv[2]), "file(s)")
    elif c == "restore": print("restored", restore(sys.argv[2]), "file(s)")
    else: status()
