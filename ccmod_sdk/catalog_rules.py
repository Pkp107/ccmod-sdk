"""Declarative catalog rules - what a plugin (or the user) writes in ccmod-redirects.json to extend the Effects grid.

    {"plugin": "ccmod", "pattern": "*get_panel_info*",
     "proxy": {"categories": [{"category_id": "9990001", "name": "CCMOD", "position": 0}],
               "tiles": {"effect_type": 7, "mode": "append",
                         "items": [{"effect_id": "8849954550253485357", "title": "CCMOD Easedown", "md5": "df34..."}]}}}

    {"plugin": "ccmod", "pattern": "*get_resources_by_category_id*",
     "proxy": {"serve_category": {"category_id": "9990001",
                                  "items": [{"effect_id": "...", "title": "CCMOD Easedown", "md5": "..."}]}}}

`categories` adds a category to the strip. `tiles` appends/replaces tiles in a (scoped by effect_type) response.
`serve_category` answers a request for OUR synthetic category id entirely locally (it has no real server-side list):
the response envelope is cloned from the last real get_resources_by_category_id reply seen (cached in state_dir), so the
shape always matches whatever CapCut version is running. Every other request passes through untouched.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import catalog

ENVELOPE_FILE = "catalog_envelope.json"


def _effect_type(doc) -> str | None:
    for d in catalog._walk(doc):
        if "effect_type" in d:
            return str(d["effect_type"])
    return None


_PIN_LOCK = threading.RLock()        # the redirect server answers requests on several threads; pin assignment is read-modify-write


class CatalogProxy:
    def __init__(self, state_dir: Path, asset_base: str | None = None, assets_dir: Path | None = None):
        self.state_dir = Path(state_dir)
        self.asset_base = asset_base                  # http://127.0.0.1:<port>/asset/  (the redirect server serves assets_dir there)
        self.assets_dir = Path(assets_dir) if assets_dir else None

    def cover_url(self, name: str | None) -> str | None:
        """URL CapCut should load a tile cover from. ?v=<mtime> so an edited image is picked up (CapCut caches covers by URL)."""
        if not name or not self.asset_base:
            return None
        v = ""
        if self.assets_dir and (self.assets_dir / name).is_file():
            v = "?v=%d" % int((self.assets_dir / name).stat().st_mtime)
        return self.asset_base + name + v

    # ---- the borrowed real ids: "this id means OUR package" must hold in every list CapCut sees, or a stock md5 wins at apply ----
    def _idmap_path(self) -> Path:
        return self.state_dir / "real_id_md5.json"

    def _remember_ids(self, rows: list[dict]) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            m = self._load_idmap()
            m.update({str(r["real_id"]): r["md5"] for r in rows if r.get("real_id") and r.get("md5")})
            self._idmap_path().write_text(json.dumps(m, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _pins(self) -> dict:
        try:
            return json.loads((self.state_dir / "pins.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_pins(self, pins: dict) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / "pins.json").write_text(json.dumps(pins, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _load_idmap(self) -> dict:
        try:
            return json.loads(self._idmap_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _override_md5(self, body: bytes) -> bytes:
        """Set common_attr.md5 of every tile whose id is one of our borrowed real ids (any list, any panel)."""
        m = self._load_idmap()
        if not m:
            return body
        try:
            doc = json.loads(body)
        except ValueError:
            return body
        hit = False
        for d in catalog._walk(doc):
            ca = d.get("common_attr") if isinstance(d.get("common_attr"), dict) else None
            if ca and str(ca.get("id")) in m and ca.get("md5") != m[str(ca["id"])]:
                ca["md5"] = m[str(ca["id"])]; hit = True
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode() if hit else body

    def _with_covers(self, items: list[dict]) -> list[dict]:
        return [dict(t, cover=self.cover_url(t["cover"])) if t.get("cover") else t for t in items]

    # ---- envelope cache: the last real per-category reply is the template for synthetic categories ----
    def _remember(self, url: str, resp: bytes) -> None:
        """Cache a real per-category reply as the template for synthetic categories. Only get_resources_by_category_id replies
        qualify: a get_panel_info reply also contains effect_item_lists (nested in category_resources) but has a different
        shape - serving it for a category request leaves the grid on "No content" (found live, 5 Oct)."""
        if "get_resources_by_category_id" not in url:
            return
        try:
            data = json.loads(resp).get("data")
            if isinstance(data, dict) and isinstance(data.get("effect_item_list"), list) and data["effect_item_list"]:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                (self.state_dir / ENVELOPE_FILE).write_bytes(resp)
        except (ValueError, OSError, AttributeError):
            pass

    def envelope(self) -> bytes | None:
        try:
            raw = (self.state_dir / ENVELOPE_FILE).read_bytes()
            data = json.loads(raw).get("data")
            return raw if isinstance(data, dict) and isinstance(data.get("effect_item_list"), list) else None
        except (OSError, ValueError, AttributeError):
            return None

    # ---- the transform for one rule ----
    @staticmethod
    def _serves(spec: dict) -> list[dict]:
        sc = spec.get("serve_category")
        return [] if not sc else (sc if isinstance(sc, list) else [sc])

    def _match(self, spec: dict, request_body: bytes) -> dict | None:
        want = catalog.request_category_id(request_body)
        return next((s for s in self._serves(spec) if want == str(s.get("category_id"))), None)

    def via(self, spec: dict, request_body: bytes):
        """For a serve_category entry with `via_category`: (rewritten request body that names the real category, entry)."""
        sc = self._match(spec, request_body)
        if not sc or not sc.get("via_category"):
            return None
        d = json.loads(request_body)
        d["category_id"] = int(sc["via_category"])
        if sc.get("via_key"):
            d["category_key"] = sc["via_key"]
        return json.dumps(d, separators=(",", ":")).encode(), sc

    def apply_via(self, sc: dict, upstream: bytes) -> bytes:
        if sc.get("mode") == "none":                       # debugging aid: pass the real reply through unchanged
            return upstream
        if sc.get("mode") == "membership":                 # debugging aid: real tiles, plus our category id in their category_ids
            return catalog.add_membership(upstream, sc["category_id"])
        if str(sc.get("mode", "")).startswith("retag_"):   # keep real ids; rewrite title/md5 of the first len(items) tiles
            rep: list = []
            with _PIN_LOCK:
                pins = self._pins()
                out = catalog.retag_tiles(upstream, sc["category_id"], sc["mode"][6:], self._with_covers(sc["items"]),
                                          offset=int(sc.get("offset", 0)), report=rep, only=bool(sc.get("only", True)), pins=pins)
                self._save_pins(pins)
            self._remember_ids(rep)
            try:
                (self.state_dir / f"via_ids_{sc['category_id']}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            except OSError:
                pass
            return out
        if str(sc.get("mode", "")).startswith("bisect_"):  # debugging aid: membership + ONE kind of change to the first tile
            return catalog.bisect_first_tile(upstream, sc["category_id"], sc["mode"][7:], sc["items"][0])
        return catalog.add_tiles(upstream, sc["items"], replace=True, category_id=sc.get("category_id"),
                                 effect_type=int(sc.get("effect_type", 7)), mode=sc.get("mode", "full"))

    def wants_local(self, spec: dict, request_body: bytes) -> bool:
        return self._match(spec, request_body) is not None

    def serve_local(self, spec: dict, request_body: bytes = b"") -> bytes | None:
        sc = self._match(spec, request_body) or (self._serves(spec) or [None])[0]
        if sc is None:
            return None
        env = self.envelope()
        if env is None:                                  # CapCut prefetches every category at launch, before any real reply exists
            from .catalog_skeleton import skeleton_envelope
            env = skeleton_envelope()
        return catalog.add_tiles(env, sc["items"], replace=True, category_id=sc.get("category_id"),
                                 effect_type=int(sc.get("effect_type", 7)), mode=sc.get("mode", "full"))

    def _dump_panel(self, upstream: bytes) -> None:
        """Recon aid: keep the last REAL get_panel_info reply per effect_type (panel_<type>.json) to see how a panel is built."""
        try:
            doc = json.loads(upstream)
            types = {str(c.get("common_attr", {}).get("effect_type")) for e in (doc.get("data", {}).get("category_resources") or {}).values()
                     for c in (e.get("effect_item_list") or [])[:1]}
            self.state_dir.mkdir(parents=True, exist_ok=True)
            for t in types:
                (self.state_dir / f"panel_{t}.json").write_bytes(upstream)
        except (ValueError, OSError, AttributeError):
            pass

    def rewrite(self, spec: dict, url: str, request_body: bytes, upstream: bytes) -> bytes:
        self._remember(url, upstream)
        self._dump_panel(upstream)
        out = upstream
        matched_types: set[int] = set()
        dcs = spec.get("default_category") or []
        if isinstance(dcs, dict):
            dcs = [dcs]
        for dc0 in dcs:                                          # one entry per panel kind (effects = type 7, transitions = 19)
            dc = dict(dc0)
            dc["items"] = self._with_covers(dc.get("items", []))
            out = self._default_category(out, dc)
            if dc.get("_matched"):                               # only the panel that has this default category is renamed
                matched_types.add(int(dc.get("effect_type", 7)))
            if dc.get("_ids"):                                  # which real stock id sits under each of our titles (for local package install)
                self._remember_ids(dc["_ids"])
                fname = "default_category_ids.json" if int(dc.get("effect_type", 7)) == 7 else f"default_category_ids_{int(dc.get('effect_type', 7))}.json"
                try:
                    (self.state_dir / fname).write_text(json.dumps(dc["_ids"], indent=1), encoding="utf-8")
                except OSError:
                    pass
        for c in spec.get("categories", []):                    # extra tabs only on the panel kind they belong to (not body effects, lyrics, ...)
            if not dcs or int(c.get("effect_type", 7)) in matched_types:
                out = catalog.add_category(out, category_id=c["category_id"], name=c["name"], key=c.get("key"),
                                           position=int(c.get("position", 0)))
        for inl in spec.get("inline", []):
            out = self._inline(out, inl)
        out = self._override_md5(out)
        t = spec.get("tiles")
        if t:
            try:
                want = str(t.get("effect_type", "")) or None
                if want is None or _effect_type(json.loads(out)) == want:
                    out = catalog.add_tiles(out, t["items"], replace=t.get("mode") == "replace",
                                        effect_type=int(t["effect_type"]) if t.get("effect_type") else None)
            except ValueError:
                pass
        return out

    @staticmethod
    def _inline(panel: bytes, inl: dict) -> bytes:
        """Put a category's tiles INLINE in a get_panel_info reply (data.category_resources[<id>]), so CapCut needs no
        per-category fetch. Inline entries are not id-checked the way fetched lists are (found live, 5 Oct)."""
        import copy
        doc = json.loads(panel)
        data = doc.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
            return panel
        res = data.setdefault("category_resources", {})
        base = next((v for v in res.values() if isinstance(v, dict) and v.get("effect_item_list")), None)
        if base is None:
            from .catalog_skeleton import skeleton_envelope
            base = json.loads(skeleton_envelope())["data"]
        entry = copy.deepcopy(base)
        tiles = base["effect_item_list"]
        entry["effect_item_list"] = [catalog.make_tile(tiles[0], category_id=inl["category_id"], effect_type=int(inl.get("effect_type", 7)),
                                                       mode=inl.get("mode", "full"), **t) for t in inl["items"]]
        entry["has_more"] = False
        entry["next_offset"] = len(entry["effect_item_list"])
        res[str(inl["category_id"])] = entry
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()

    def _default_category(self, panel: bytes, dc: dict) -> bytes:
        """The first category of a panel is rendered from INLINE data (data.category_resources[<its id>]), which CapCut does not
        id-check. Rename that real default category and replace its inline tiles with ours - the route that worked live in
        August (in-place edit), now through the proxy so the list can be any length."""
        doc = json.loads(panel)
        data = doc.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("category_resources"), dict):
            return panel
        want = int(dc.get("effect_type", 7))
        for key, entry in data["category_resources"].items():
            lst = entry.get("effect_item_list") if isinstance(entry, dict) else None
            if not lst or lst[0].get("common_attr", {}).get("effect_type") != want:
                continue
            dc["_matched"] = True
            with _PIN_LOCK:
                pins = self._pins()
                picks = catalog.pick_tiles(lst, dc["items"], pins)      # one STABLE real tile per item (real lists are re-ranked per request)
                self._save_pins(pins)
            items = dc["items"][:len(picks)]
            dc["_ids"] = [{"title": t.get("title"), "our_id": t.get("effect_id"), "md5": t.get("md5"),
                           "real_id": picks[i].get("common_attr", {}).get("id")} for i, t in enumerate(items)]
            entry["effect_item_list"] = [catalog.make_tile(picks[i], category_id=key, effect_type=want, mode=t.get("mode", dc.get("mode", "full")),
                                                           **{k: v for k, v in t.items() if k != "mode"})
                                         for i, t in enumerate(items)]
            entry["has_more"] = False
            entry["next_offset"] = len(entry["effect_item_list"])
            for c in data.get("categories", []):
                if str(c.get("category_id")) == str(key):
                    c["category_name"] = dc.get("name", "ccmod")
                    if "category_key" in c:
                        c["category_key"] = dc.get("name", "ccmod").lower()
            break
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
