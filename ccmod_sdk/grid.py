"""The CCMOD grid: our effects as tiles in CapCut's REAL Effects panel (proven on-screen, 5 Oct 2026).

How it works:
  * the proxy renames the real default category of the video-effects panel to "CCMOD" and fills its inline tiles with real stock
    tiles whose id is KEPT (a changed id is dropped by CapCut) but whose title / md5 / cover / sliders are ours;
  * an extra category tab carries the overflow the same way (served from a real category's list, only our tiles kept);
  * our package is installed under each borrowed real id (Cache/effect/<real_id>/<md5>/) so a native drag applies OUR effect;
  * which real tile each effect uses is pinned (pins.json) so it is stable although the real lists are re-ranked per request.
Covers are editable files: <rules dir>/ccmod-assets/<key>.png (written once, never overwritten).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import covers

ROOT = Path(__file__).resolve().parent.parent
EFFECT_DIR = Path(os.path.expandvars(r"%LOCALAPPDATA%\CapCut\User Data\Cache\effect"))
EXTRAS_ID = "9990100"             # synthetic category id for the overflow tab (far outside CapCut's real ids)
DEFAULT_PANEL_CATEGORY = "26918"  # the real default category (Trending) of the video-effects panel on 8.9.x
TRANS_EXTRAS_ID = "9990101"
TRANS_PANEL_CATEGORY = "27186"    # ... and of the transitions panel (effect_type 19, category_key hot3)
TRANS_INDEX = ROOT / "scratch" / "_cctrans_index.json"


def slider_cfg(pkg_dir: Path) -> dict | None:
    """The package's own extra.json `setting` -> the tile's sdk_extra, so the applied clip shows OUR slider."""
    try:
        return {"setting": json.loads((pkg_dir / "extra.json").read_text(encoding="utf-8"))["setting"]}
    except (OSError, ValueError, KeyError):
        return None


def grid_items(effect_dir: Path | None = None, index: Path | None = None, assets: Path | None = None) -> list[dict]:
    """Installed donorless effects (package really on disk) as grid items with an editable cover and their own slider config."""
    effect_dir = effect_dir or EFFECT_DIR
    ix = json.loads((index or ROOT / "scratch" / "_ccfx_index.json").read_text(encoding="utf-8"))
    if index is None:
        covers.ensure_covers(assets or covers.ASSETS)
    out = []
    for key, v in ix.items():
        pkg = effect_dir / str(v["id"]) / v["md5"]
        if pkg.is_dir():
            out.append({"effect_id": str(v["id"]), "title": v["label"].removeprefix("CCMOD ").strip() or v["label"], "md5": v["md5"], "cover": f"{key}.png", "sdk_extra": slider_cfg(pkg)})
    return out


def transition_items(effect_dir: Path | None = None, assets: Path | None = None) -> list[dict]:
    """Installed donorless transitions (scratch/_cctrans_index.json) as grid items."""
    if not TRANS_INDEX.exists():
        return []
    covers.ensure_covers(assets or covers.ASSETS, TRANS_INDEX)
    return grid_items(effect_dir, TRANS_INDEX)


def _parts(items: list[dict], name: str, extras_name: str, main_count: int, effect_type: int, panel_cat: str, extras_id: str,
           extras_key: str, via_key: str) -> tuple[dict, list[dict], list[dict]]:
    main, extra = items[:main_count], items[main_count:]
    for it in main:
        it["mode"] = "title_md5"
    dc = {"name": name, "effect_type": effect_type, "mode": "title_md5", "items": main}
    cats = [{"category_id": extras_id, "name": extras_name, "position": 1, "key": extras_key, "effect_type": effect_type}] if extra else []
    serve = [{"category_id": panel_cat, "items": main, "mode": "retag_titlemd5", "effect_type": effect_type,
              "via_category": panel_cat}]                        # CapCut ALSO fetches the default list separately: same retag
    if extra:
        serve.append({"category_id": extras_id, "items": extra, "mode": "retag_titlemd5", "effect_type": effect_type,
                      "via_category": panel_cat, "via_key": via_key})
    return dc, cats, serve


def build_rules(items: list[dict], plugin: str, name: str = "ccmod", extras_name: str = "ccmod extras",
                main_count: int = 8, effect_type: int = 7, transitions: list[dict] | None = None) -> list[dict]:
    """The catalog rules (get_panel_info rewrite, default-list refetch, extras list) for these items; `transitions` adds the
    same CCMOD category to the Transitions panel (effect_type 19)."""
    dc, cats, serve = _parts(items, name, extras_name, main_count, effect_type, DEFAULT_PANEL_CATEGORY, EXTRAS_ID, "ccmod-extras", "hot2")
    panel = {"default_category": dc, "categories": cats}
    if transitions:
        tdc, tcats, tserve = _parts(transitions, name, extras_name, main_count, 19, TRANS_PANEL_CATEGORY, TRANS_EXTRAS_ID,
                                    "ccmod-trans-extras", "hot3")
        panel = {"default_category": [dc, tdc], "categories": cats + tcats}
        serve += tserve
    return [{"plugin": plugin, "pattern": "*get_panel_info*", "proxy": panel},
            {"plugin": plugin, "pattern": "*get_resources_by_category_id*", "proxy": {"serve_category": serve}}]


def install_borrowed(state_dir: Path, effect_dir: Path | None = None) -> list[str]:
    """Copy our packages under the real ids the proxy borrowed (default_category_ids.json + via_ids_*.json). Idempotent: a folder
    is replaced when it holds a different effect; the marker lives BESIDE the md5 folder (a file inside breaks CapCut's check)."""
    effect_dir = effect_dir or EFFECT_DIR
    rows: list[dict] = []
    for f in [*sorted(state_dir.glob("default_category_ids*.json")), *sorted(state_dir.glob("via_ids_*.json"))]:
        try:
            rows += json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    done = []
    for r in rows:
        src, dst = effect_dir / str(r["our_id"]) / r["md5"], effect_dir / str(r["real_id"]) / r["md5"]
        marker = dst.parent / f"ccmod_source_{r['md5']}.txt"
        if not src.is_dir():
            continue
        if dst.exists():
            if marker.exists() and marker.read_text().strip() == str(r["our_id"]):
                continue
            shutil.rmtree(dst)
            for stale in dst.parent.glob("*_tmp"):
                shutil.rmtree(stale, ignore_errors=True)
        shutil.copytree(src, dst)
        marker.write_text(str(r["our_id"]))
        done.append(f"{r['title']} -> {r['real_id']}")
    return done
