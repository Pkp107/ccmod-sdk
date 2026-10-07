"""CapCut themes: recolor and restyle CapCut's own UI, live and reversible.

A theme is a folder `themes/<id>/` with `theme.json`:

    {
      "id": "midnight", "name": "Midnight", "author": "CCMOD", "version": "1.0.0", "description": "...",
      "colors": { "#262626": "#1b2538", ... },        # exact colour -> colour, for every Rectangle/Text/border in the editor
      "rules":  [ { "match": {"type": "QQuickRectangle", "radiusMin": 3}, "set": {"radius": 2} } ],   # restyle / hide / move / resize
      "qml":    [ { "file": "badge.qml", "parent": "materialPanelParent" } ]                          # extra components to inject
    }

`match` keys: type (QML type name prefix), objectName ("exact" or "prefix*"), color (current colour), radiusMin.
`set` keys: any writable property path, e.g. "radius", "visible", "opacity", "x", "width", "font.pixelSize", "anchors.margins".

How it works: ONE QML engine (theme_engine.qml) is injected into the editor. It walks the live item tree and puts a QML `Binding`
(RestoreBindingOrValue) on every matching property, so reverting a theme restores CapCut's own values. It rescans every 2 s so panels
opened later are themed too. Nothing here touches account, Pro, watermark or licensing.

    ThemeEngine(backend).apply("midnight")     # needs CapCut running (an editor open)
    ThemeEngine(backend).revert()
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
THEMES_DIR = ROOT / "themes"
ENGINE_QML = Path(__file__).resolve().parent / "theme_engine.qml"
_QML_TEXT = ENGINE_QML.read_text(encoding="utf-8")
ENGINE_NAME = "ccmodThemeEngine_" + hashlib.sha1(_QML_TEXT.encode()).hexdigest()[:8]    # a changed engine gets a new name, so a stale one is never reused
ENGINE_PARENT = "materialPanelParent"
_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")


SELECTED_FILE = ROOT / "plugin-state" / "theme.json"


def saved() -> str:
    """The theme id the user chose (applied again whenever an editor opens), or ''."""
    try:
        return str(json.loads(SELECTED_FILE.read_text(encoding="utf-8")).get("id", ""))
    except (OSError, ValueError):
        return ""


def save(theme_id: str) -> None:
    SELECTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SELECTED_FILE.write_text(json.dumps({"id": theme_id}), encoding="utf-8")


class ThemeError(ValueError):
    pass


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or not _ID.match(str(data.get("id", ""))):
        raise ThemeError("theme.json needs an 'id' (lowercase letters, digits, - _ .)")
    if not data.get("name"):
        raise ThemeError("theme.json needs a 'name'")
    colors = data.get("colors", {})
    if not isinstance(colors, dict) or any(not _COLOR.match(str(k)) or not _COLOR.match(str(v)) for k, v in colors.items()):
        raise ThemeError("'colors' must map #rrggbb (or #aarrggbb) to #rrggbb (or #aarrggbb)")
    rules = data.get("rules", [])
    if not isinstance(rules, list) or any(not isinstance(r, dict) or not isinstance(r.get("set"), dict) for r in rules):
        raise ThemeError("every rule needs a 'set' object")
    return data


def discover(themes_dir: Path | None = None) -> list[dict]:
    """All valid themes (invalid ones are skipped); each dict has an extra 'path' key."""
    out = []
    d = themes_dir or THEMES_DIR
    if not d.is_dir():
        return out
    for p in sorted(x for x in d.iterdir() if x.is_dir() and (x / "theme.json").exists()):
        try:
            t = validate(json.loads((p / "theme.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        out.append({**t, "path": str(p)})
    return out


def find(theme_id: str, themes_dir: Path | None = None) -> dict | None:
    return next((t for t in discover(themes_dir) if t["id"] == theme_id), None)


def encode(theme: dict, active: bool = True) -> str:
    """The percent-encoded JSON the QML engine reads from its `cfg` property."""
    cfg = {"id": theme.get("id", ""), "active": active, "colors": theme.get("colors", {}), "rules": theme.get("rules", [])}
    return quote(json.dumps(cfg, separators=(",", ":")), safe="")


class ThemeEngine:
    def __init__(self, backend):
        self.b = backend

    def _present(self) -> bool:
        v = str(self.b.get_prop(ENGINE_NAME, "report") or "")
        return v != "" and "not found" not in v.lower() and "error: " not in v[:7]

    def ensure(self) -> bool:
        if self._present():
            return True
        f = Path(tempfile.mkdtemp(prefix="ccmod_theme_")) / "theme_engine.qml"
        f.write_text(_QML_TEXT.replace('objectName: "ccmodThemeEngine2"', f'objectName: "{ENGINE_NAME}"'), encoding="utf-8")
        self.b.inject_qml(ENGINE_PARENT, str(f))
        time.sleep(0.4)
        return self._present()

    def apply(self, theme: dict | str) -> str:
        """Apply a theme (dict or id) to the live editor; returns the engine's report text."""
        if isinstance(theme, str):
            found = find(theme)
            if found is None:
                raise ThemeError(f"no theme {theme!r}")
            theme = found
        if not self.ensure():
            raise RuntimeError("could not inject the theme engine (is an editor open?)")
        self.b.set_prop(ENGINE_NAME, "cfg", encode(theme))
        for q in theme.get("qml", []):
            self._inject_extra(theme, q)
        time.sleep(0.6)
        return self.report()

    def _inject_extra(self, theme: dict, q: dict) -> None:
        f = Path(theme["path"]) / q["file"]
        if f.is_file():
            self.b.inject_qml(q.get("parent", ENGINE_PARENT), str(f))

    def revert(self) -> str:
        if not self._present():
            return "no theme active"
        self.b.set_prop(ENGINE_NAME, "cfg", encode({"id": ""}, active=False))
        time.sleep(0.3)
        return self.report()

    def inspect(self, type: str = "", objectName: str = "", limit: int = 40) -> dict:
        """List live UI items (type | objectName | x,y wxh | visible | colour | radius) for theme authors."""
        if not self.ensure():
            raise RuntimeError("could not inject the theme engine (is an editor open?)")
        q = {k: v for k, v in (("type", type), ("objectName", objectName), ("limit", limit)) if v}
        self.b.set_prop(ENGINE_NAME, "query", quote(json.dumps(q) + " " * (int(time.time() * 1000) % 7), safe=""))
        time.sleep(0.5)
        raw = str(self.b.get_prop(ENGINE_NAME, "queryResult") or "")
        try:
            return json.loads(raw)
        except ValueError:
            return {"error": raw}

    def report(self) -> str:
        return str(self.b.get_prop(ENGINE_NAME, "report") or "")
