"""Catalog rewriting: add categories and tiles to CapCut's effect catalog responses.

CapCut's Effects grid is fed by two JSON responses (see docs/reference/capcut-moddability-model-2026-08-05.md):
  get_panel_info                  -> {"data": {"categories": [...], "effect_item_list": [...]}}  (the strip + first tiles)
  get_resources_by_category_id    -> {"data": {"effect_item_list": [{"common_attr": {...}, ...}, ...]}}  (a category's tiles)
These helpers work on whatever shape arrives: they CLONE an existing category / tile as the template and override only
the fields we know (id, title, md5 ...). Repointing to a pre-installed package id sidesteps the signature gate.

Nothing here talks to CapCut - it is pure JSON in, JSON out, so it is unit-tested without the app.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Iterable

TILE_ID_KEYS = ("id", "effect_id", "third_resource_id_str", "third_resource_id", "resource_id")
TITLE_KEYS = ("title", "name")


def _dump(doc: Any) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()


def _walk(o: Any):
    """Yield every dict in a JSON tree."""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def find_list(doc: Any, key: str) -> list | None:
    """The first list stored under `key` anywhere in the document."""
    for d in _walk(doc):
        if isinstance(d.get(key), list):
            return d[key]
    return None


COVER_KEYS = ("small", "large", "static_img", "medium")


def _set_cover(tile: dict, url: str | None) -> None:
    """Point a tile's thumbnail(s) at `url` (all of cover_url.small/static_img/... that exist)."""
    if not url:
        return
    for d in _walk(tile):
        cu = d.get("cover_url")
        if isinstance(cu, dict):
            for k in COVER_KEYS:
                if k in cu and isinstance(cu[k], str):
                    cu[k] = url


def _set_sdk_extra(tile: dict, sdk_extra) -> None:
    """The sliders CapCut offers for an applied tile come from the tile's sdk_extra (setting.effect_adjust_params).
    dict -> that JSON; "" / "{}" -> that literal string; None -> leave the borrowed tile's value alone."""
    if sdk_extra is None:
        return
    val = sdk_extra if isinstance(sdk_extra, str) else json.dumps(sdk_extra, separators=(",", ":"))
    for d in _walk(tile):
        if isinstance(d.get("sdk_extra"), str):
            d["sdk_extra"] = val


def make_tile(template: dict, *, effect_id: str, title: str, md5: str | None = None, extra: dict | None = None,
              category_id: str | None = None, effect_type: int | None = None, mode: str = "full", cover: str | None = None,
              sdk_extra: dict | None = None) -> dict:
    """Clone a real tile and repoint it at one of our pre-installed donorless packages.

    Modes "title_md5" / "only_*" leave every commercial/licensing field of the borrowed tile exactly as served (CapCut drops tiles whose
    signed business data was edited, and we never touch Pro/licensing data). Only the legacy modes below rewrite flags on a COPY."""
    tile = copy.deepcopy(template)
    if mode == "real":                              # debugging aid: the untouched template tile
        return tile
    _set_cover(tile, cover)
    _set_sdk_extra(tile, sdk_extra)
    if mode in ("only_title", "only_md5", "only_ids", "title_md5"):   # debugging aids: ONE kind of edit on an otherwise real tile
        for d in _walk(tile):
            if mode in ("only_title", "title_md5"):
                for k in TITLE_KEYS:
                    if k in d and isinstance(d[k], str):
                        d[k] = title
            if mode in ("only_md5", "title_md5") and md5 and isinstance(d.get("md5"), str):
                d["md5"] = md5
            if mode == "only_ids":
                for k in TILE_ID_KEYS:
                    if k in d and isinstance(d[k], (str, int)) and str(d[k]).isdigit():
                        d[k] = str(effect_id) if isinstance(d[k], str) else int(effect_id)
        return tile
    for d in _walk(tile):
        for k in TILE_ID_KEYS:
            if k in d and isinstance(d[k], (str, int)) and str(d[k]).isdigit():
                d[k] = str(effect_id) if isinstance(d[k], str) else int(effect_id)
        if mode in ("repoint", "minimal", "oldstyle"):   # debugging aids; "oldstyle" = the August in-place edit: ids + md5 + title only
            if md5 and isinstance(d.get("md5"), str):
                d["md5"] = md5
            if mode == "oldstyle":
                for k in TITLE_KEYS:
                    if k in d and isinstance(d[k], str):
                        d[k] = title
            if mode == "minimal":
                for k in TITLE_KEYS:
                    if k in d and isinstance(d[k], str):
                        d[k] = title
                if category_id is not None and isinstance(d.get("category_ids"), list):
                    d["category_ids"] = [int(category_id)]
            continue
        for k in TITLE_KEYS:
            if k in d and isinstance(d[k], str):
                d[k] = title
        if md5 and isinstance(d.get("md5"), str):
            d["md5"] = md5
        if effect_type is not None and "effect_type" in d and isinstance(d["effect_type"], int):
            d["effect_type"] = effect_type             # the template may come from another panel (found live: a type-26 tile => "No content")
        if "is_business" in d:
            d["is_business"] = False
        if isinstance(d.get("business_scope"), list):
            d["business_scope"] = []
        if isinstance(d.get("business_info"), dict):
            d["business_info"] = {"json_str": json.dumps({"is_vip": False, "is_expired": False, "paid_type": "free"}, separators=(",", ":"))}
        elif isinstance(d.get("business_info"), str):
            d["business_info"] = json.dumps({"is_vip": False, "is_expired": False, "paid_type": "free"}, separators=(",", ":"))
        if isinstance(d.get("extra"), str) and "is_vip" in d["extra"]:
            d["extra"] = json.dumps({"effect_duration": 3000}, separators=(",", ":"))
        if category_id is not None and isinstance(d.get("category_ids"), list):
            d["category_ids"] = [int(category_id)] + [c for c in d["category_ids"] if str(c) != str(category_id)][:0]
    for k, v in (extra or {}).items():
        for d in _walk(tile):
            if k in d:
                d[k] = v
    return tile


def add_tiles(resp: bytes | str, tiles: Iterable[dict], *, replace: bool = False, category_id: str | None = None,
              effect_type: int | None = None, mode: str = "full") -> bytes:
    """Append (or with replace=True, substitute) tiles in a response's effect_item_list. `tiles` are dicts with
    effect_id/title/md5. Unknown shapes are returned unchanged."""
    doc = json.loads(resp)
    lst = find_list(doc, "effect_item_list")
    if not lst:
        return _dump(doc)
    template = lst[0]
    new = [make_tile(template, category_id=category_id, effect_type=effect_type, mode=mode, **t) for t in tiles]
    if replace:
        lst[:] = new
        for d in _walk(doc):                       # one complete page: no "load more"
            if isinstance(d.get("has_more"), bool):
                d["has_more"] = False
            if "next_offset" in d:
                d["next_offset"] = len(new)
    else:
        lst.extend(new)
    return _dump(doc)


def add_category(resp: bytes | str, *, category_id: str, name: str, key: str | None = None, position: int = 0) -> bytes:
    """Insert a category object (cloned from an existing one) into a get_panel_info response's `categories` list."""
    doc = json.loads(resp)
    cats = find_list(doc, "categories")
    if not cats:
        return _dump(doc)
    if any(str(c.get("category_id")) == str(category_id) for c in cats if isinstance(c, dict)):
        return _dump(doc)                                              # idempotent
    c = copy.deepcopy(cats[0])
    for d in _walk(c):
        if "category_id" in d:
            d["category_id"] = str(category_id) if isinstance(d["category_id"], str) else int(category_id)
        if "category_name" in d:
            d["category_name"] = name
        if "category_key" in d:
            d["category_key"] = key or name.lower()
    cats.insert(max(0, min(position, len(cats))), c)
    return _dump(doc)


def request_category_id(request_body: bytes) -> str | None:
    """The category_id a get_resources_by_category_id POST asks for (JSON or form body)."""
    try:
        for x in _walk(json.loads(request_body)):
            if "category_id" in x:
                return str(x["category_id"])
    except (ValueError, TypeError):
        pass
    m = re.search(rb'category_id"?\s*[=:]\s*"?(\d+)', request_body or b"")
    return m.group(1).decode() if m else None


def add_membership(resp: bytes | str, category_id: str) -> bytes:
    """Debugging aid: leave every tile as it is but add `category_id` to each tile's category_ids."""
    doc = json.loads(resp)
    for d in _walk(doc):
        if isinstance(d.get("category_ids"), list) and int(category_id) not in d["category_ids"]:
            d["category_ids"].append(int(category_id))
    return _dump(doc)


def bisect_first_tile(resp: bytes | str, category_id: str, what: str, item: dict) -> bytes:
    """Debugging aid: keep every real tile (with our category id added so the grid shows them) and change ONLY the first tile:
    what = "title" | "ids" | "md5" | "all"  (all = ids + md5 + title)."""
    doc = json.loads(add_membership(resp, category_id))
    lst = find_list(doc, "effect_item_list")
    if not lst:
        return _dump(doc)
    for d in _walk(lst[0]):
        if what in ("title", "all"):
            for k in TITLE_KEYS:
                if k in d and isinstance(d[k], str):
                    d[k] = item["title"]
        if what in ("ids", "all"):
            for k in TILE_ID_KEYS:
                if k in d and isinstance(d[k], (str, int)) and str(d[k]).isdigit():
                    d[k] = str(item["effect_id"]) if isinstance(d[k], str) else int(item["effect_id"])
        if what in ("md5", "all") and isinstance(d.get("md5"), str):
            d["md5"] = item["md5"]
    return _dump(doc)


def _is_paid(tile: dict) -> bool:
    """READ-ONLY: does CapCut mark this stock tile as a subscription effect? (we only use it to choose which tiles to borrow;
    nothing in the tile's business/licensing data is ever changed)."""
    try:
        info = json.loads(tile.get("common_attr", {}).get("business_info", {}).get("json_str") or "{}")
    except (ValueError, AttributeError):
        return False
    return bool(info.get("is_vip")) or info.get("paid_type") not in (None, "", "free")


def pick_tiles(lst: list, items: list[dict], pins: dict) -> list:
    """One real tile per item, STABLE across requests: an item keeps the real id it was pinned to (`pins`: our_id -> real_id,
    updated in place) whenever that tile is in `lst`; new/unmatched items take the next real tile nobody else is pinned to.
    (Real lists are re-ranked per request, so 'the 5th tile' is a different id every time.)
    Free stock tiles are preferred, so our (free) effects do not inherit another effect's Pro badge; if the list has too few
    free tiles the paid ones fill in."""
    by_id = {str(t.get("common_attr", {}).get("id")): t for t in lst}
    mine = {i["effect_id"] for i in items}
    elsewhere = {v for k, v in pins.items() if k not in mine}
    n_free = sum(1 for t in lst if not _is_paid(t) and str(t.get("common_attr", {}).get("id")) not in elsewhere)
    for i in items:                                                    # a pin on a paid tile moves to a free one when enough exist
        rid = pins.get(i["effect_id"])
        if rid in by_id and _is_paid(by_id[rid]) and n_free >= len(items):
            del pins[i["effect_id"]]
    taken = {pins[i["effect_id"]] for i in items if pins.get(i["effect_id"]) in by_id}
    ordered = [t for t in lst if not _is_paid(t)] + [t for t in lst if _is_paid(t)]
    free = (t for t in ordered if str(t.get("common_attr", {}).get("id")) not in taken | elsewhere)
    out = []
    for it in items:
        rid = pins.get(it["effect_id"])
        if rid in by_id:
            out.append(by_id[rid]); continue
        t = next(free, None)
        if t is None:
            break
        pins[it["effect_id"]] = str(t["common_attr"]["id"])
        out.append(t)
    return out


def retag_tiles(resp: bytes | str, category_id: str, what: str, items: list[dict], offset: int = 0, report: list | None = None,
                only: bool = False, pins: dict | None = None) -> bytes:
    """Keep each real tile's id (fetched lists drop tiles whose id changed) and rewrite only presentation fields on
    len(items) tiles starting at `offset`, one item per tile. what = "title" | "md5" | "titlemd5".
    `report` (optional) receives one {title, our_id, md5, real_id} row per retagged tile (to install packages under the real ids)."""
    doc = json.loads(add_membership(resp, category_id))
    lst = find_list(doc, "effect_item_list")
    if not lst:
        return _dump(doc)
    picked = []
    tiles = pick_tiles(lst, items, pins) if pins is not None else lst[offset:]
    for tile, item in zip(tiles, items):
        picked.append(tile)
        _set_cover(tile, item.get("cover"))
        _set_sdk_extra(tile, item.get("sdk_extra"))
        if report is not None:
            report.append({"title": item.get("title"), "our_id": item.get("effect_id"), "md5": item.get("md5"),
                           "real_id": tile.get("common_attr", {}).get("id")})
        for d in _walk(tile):
            if what in ("title", "titlemd5"):
                for k in TITLE_KEYS:
                    if k in d and isinstance(d[k], str):
                        d[k] = item["title"]
            if what in ("md5", "titlemd5") and isinstance(d.get("md5"), str):
                d["md5"] = item["md5"]
    if only and picked:                                        # the category lists ONLY our tiles, not the borrowed real list
        lst[:] = picked
        for d in _walk(doc):
            if isinstance(d.get("has_more"), bool):
                d["has_more"] = False
            if "next_offset" in d:
                d["next_offset"] = len(picked)
    return _dump(doc)
