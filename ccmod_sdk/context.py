"""The Context a plugin receives: a permission-gated API over CCMOD's control surfaces.

    ctx.ui        inject QML (buttons, panels, tabs), read/write UI props, click items          [permission: ui]
    ctx.engine    call CapCut controllers, playhead time, seek, reflect on live objects         [permission: engine]
    ctx.effects   list/install CCMOD effects, drive the selected effect's param live            [permission: effects]
    ctx.draft     snapshot / restore project drafts (format-bump protection)                     [permission: draft]
    ctx.builds    inspect installed CapCut builds                                               [permission: builds]
    ctx.hooks     resolve engine functions by byte signature (survives updates)                 [permission: render]
    ctx.network   register local redirects for CapCut's requests (served from local files)      [permission: network]
    ctx.storage   a private JSON/data folder for the plugin                                     [permission: files]
    ctx.events    subscribe to / emit host events (no permission needed)
    ctx.log       logging (no permission needed)

A namespace the manifest did not ask for raises PermissionError the moment it is touched.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .backend import Backend
from .manifest import Manifest

ROOT = Path(__file__).resolve().parent.parent


class _Namespace:
    """Base for gated namespaces; subclasses define `permission`."""
    permission = ""

    def __init__(self, ctx: "Context"):
        self._ctx = ctx

    def _b(self) -> Backend:
        return self._ctx.backend


class UI(_Namespace):
    permission = "ui"

    def inject_qml(self, parent_selector: str, qml: str) -> str:
        """Inject QML text under the live item matched by `parent_selector` (e.g. a class name)."""
        f = Path(tempfile.mkdtemp(prefix="ccmod_qml_")) / "inject.qml"
        f.write_text(qml, encoding="utf-8")
        return self._b().inject_qml(parent_selector, str(f))

    def inject_qml_file(self, parent_selector: str, path: str | Path) -> str:
        return self._b().inject_qml(parent_selector, str(Path(path)))

    def get_prop(self, selector: str, prop: str) -> str: return self._b().get_prop(selector, prop)
    def set_prop(self, selector: str, prop: str, value) -> str: return self._b().set_prop(selector, prop, str(value))
    def click(self, selector: str) -> str: return self._b().click(selector)

    # ---- buttons that call back into Python ----
    def _exists(self, selector: str, prop: str = "clicks") -> bool:
        v = str(self._b().get_prop(selector, prop) or "")
        return v != "" and "not found" not in v.lower() and "error" not in v.lower()

    def _button_name(self, bid: str) -> str:
        return f"ccmodBtn_{self._ctx.manifest.id.replace('-', '_')}_{bid}"

    def add_button(self, label: str, on_click: Callable[[], None], where: str = "timeline-toolbar", id: str | None = None,
                   icon: str | Path | None = None, x: int | None = None, y: int | None = None, width: int = 110, height: int = 28) -> bool:
        """Add a button to the editor; `on_click()` runs in Python when it is pressed.

        where: "timeline-toolbar" | "panel" | "tab-row" (see BUTTON_PLACES), or any live QQuickItem class / objectName as a selector.
        Idempotent: calling it again for the same id (e.g. on every editor_open) does nothing while the button exists.
        Returns False when the place does not exist yet (e.g. no editor open)."""
        ctx = self._ctx
        bid = id or re.sub(r"\W+", "_", label).strip("_").lower()
        name = self._button_name(bid)
        if self._exists(name):
            ctx._register_button(name, on_click)
            return True
        sel, dx, dy = BUTTON_PLACES.get(where, (where, None, None))
        if where == "tab-row":
            sel = self.find_tab_row()
            width, height = (width if width != 110 else 50), (height if height != 28 else 42)
        if not sel:
            return False
        icon_url = ("file:///" + Path(icon).resolve().as_posix()) if icon else ""
        qml = (_BUTTON_QML.replace("%NAME%", name).replace("%LABEL%", label.replace('"', "'")).replace("%ICON%", icon_url)
               .replace("%W%", str(width)).replace("%H%", str(height)))
        self.inject_qml(sel, qml)
        for k, v in (("x", x if x is not None else dx), ("y", y if y is not None else dy)):
            if v is not None:
                self.set_prop(name, k, v)
        ctx._register_button(name, on_click)
        return True

    def panel(self, panel_id: str, title: str, widgets: list[dict], on_change: Callable[[str, object], None] | None = None,
              x: int = 80, y: int = 80, width: int = 280, parent: str = "MainTimeLineToolBar_QMLTYPE"):
        """A floating, draggable panel of CapCut-styled controls (label, slider, toggle, dropdown, text, button, separator).
        `on_change(widget_id, value)` runs when a control changes. Returns a `Panel` (get/set/show/hide/close); call `.create()`
        again from `on_editor_open` to re-inject it after the editor reopens. See ccmod_sdk.uikit."""
        from .uikit import Panel
        p = Panel(self._ctx, panel_id, title, widgets, on_change, x, y, width, parent)
        p.create()
        return p

    def set_button_label(self, id: str, label: str) -> None:
        self.set_prop(self._button_name(id) + "_label", "text", label)

    def remove_button(self, id: str) -> None:
        name = self._button_name(id)
        self.set_prop(name, "visible", "false")
        self._ctx._buttons.pop(name, None)

    # ---- CapCut themes (see ccmod_sdk/themes.py) ----
    def themes(self) -> list[dict]:
        """Installed CapCut themes: id, name, description, preview colours."""
        from . import themes
        return [{k: t.get(k) for k in ("id", "name", "description", "preview", "author", "version")} for t in themes.discover()]

    def apply_theme(self, theme_id: str) -> str:
        """Recolour / restyle the live editor with a theme from themes/<id>/ (reversible with revert_theme)."""
        from . import themes
        return themes.ThemeEngine(self._b()).apply(theme_id)

    def revert_theme(self) -> str:
        from . import themes
        return themes.ThemeEngine(self._b()).revert()

    def inspect(self, type: str = "", objectName: str = "", limit: int = 40) -> dict:
        """List live UI items matching a QML type prefix / objectName (for theme and plugin authors)."""
        from . import themes
        return themes.ThemeEngine(self._b()).inspect(type, objectName, limit)

    def find_tab_row(self) -> str | None:
        """Address ("0x...") of the editor's toolbar row of tabs (Media/Audio/.../Templates), or None while no editor is open."""
        import re
        best = None
        for line in self._b().positioners(0).splitlines():
            m = re.match(r"\s*(0x[0-9a-fA-F]+)\s+QQuickRow\s+kids=(\d+)\s+scene=\(\d+,\d+\)\s+size=(\d+)x(\d+)\s+vis=1", line)
            if m and int(m.group(4)) in range(38, 48) and int(m.group(3)) >= 400 and int(m.group(2)) >= 8:
                if best is None or int(m.group(2)) > best[1]:
                    best = (m.group(1), int(m.group(2)))
        return best[0] if best else None


_BUTTON_QML = """
import QtQuick 2.15
Rectangle {
    objectName: "%NAME%"
    property int clicks: 0
    width: %W%; height: %H%; radius: 6; z: 9999
    color: ma.containsPress ? "#4A4A4F" : (ma.containsMouse ? "#3A3A3E" : "#2B2B2E")
    border.color: "#4A4A4F"; border.width: 1
    Row { anchors.centerIn: parent; spacing: 6
        Image { visible: "%ICON%" !== ""; source: "%ICON%"; width: 16; height: 16; sourceSize.width: 32; sourceSize.height: 32; smooth: true
                anchors.verticalCenter: parent.verticalCenter }
        Text { objectName: "%NAME%_label"; text: "%LABEL%"; color: "#FFFFFF"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: parent.clicks = parent.clicks + 1 }
}
"""

# Named places a plugin can put a button: (selector the QML is injected under, default x, default y)
BUTTON_PLACES = {
    "timeline-toolbar": ("MainTimeLineToolBar_QMLTYPE", None, None),   # the editor's timeline toolbar
    "panel": ("materialPanelParent", 8, 8),                             # top-left of the left (media/effects) panel area
    "tab-row": (None, None, None),                                      # appended to the editor's top tab row (Media/Effects/...)
}


class Engine(_Namespace):
    permission = "engine"

    def invoke(self, selector: str, method: str, args: str = "") -> str:
        """Call a method/slot on a live CapCut QObject. Arg syntax: 'i:123', 'sl:a|b' (see docs)."""
        return self._b().invoke(selector, method, args)

    def get_prop(self, selector: str, prop: str) -> str: return self._b().get_prop(selector, prop)
    def set_prop(self, selector: str, prop: str, value) -> str: return self._b().set_prop(selector, prop, str(value))
    def list_objects(self, limit: int = 0) -> list[str]:
        """Class names of live custom QObjects, e.g. 'MainTimeLineCursorViewModel'."""
        out = []
        for line in self._b().list_custom(limit).splitlines():
            m = re.match(r"\s*0x[0-9a-fA-F]+\s+x\d+\s+(\S+)", line)
            if m:
                out.append(m.group(1))
        return out

    def describe(self, selector: str, depth: int = 5) -> str: return self._b().dump_meta(selector, depth)

    # -- timeline helpers (proven 4 Oct 2026) --
    def playhead_seconds(self) -> float:
        """Playhead time in seconds = cursor x / pixelSize (pixelSize is px per microsecond)."""
        cx = float(self._b().get_prop("MainTimeLineCursorViewModel", "centerX") or 0)
        px = float(self._b().get_prop("MainTimeLineCanvasViewModel", "pixelSize") or 0)
        return (cx / px) / 1e6 if px > 0 else 0.0

    def seek(self, seconds: float) -> str:
        return self._b().invoke("MainTimeLineCursorViewModel", "clickSeekByTime", f"i:{int(seconds * 1_000_000)}")

    def timeline_duration_seconds(self) -> float:
        return float(self._b().get_prop("MainTimeLineCanvasViewModel", "timelineDuration") or 0) / 1e6


class Effects(_Namespace):
    permission = "effects"

    def _ccfx(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ccfx", ROOT / "scratch" / "ccfx.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m

    def library(self) -> list[str]:
        return list(self._ccfx().LIBRARY)

    def installed(self) -> list[dict]:
        """Installed donorless effects as tile dicts {effect_id, title, md5} (what ctx.network.add_tiles expects)."""
        import json
        try:
            ix = json.loads((ROOT / "scratch" / "_ccfx_index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [{"effect_id": str(v["id"]), "title": v["label"], "md5": v["md5"]} for v in ix.values()]

    def install(self, name: str) -> None:
        self._ccfx().install(name)

    def grid_items(self) -> list[dict]:
        """Installed effects as CCMOD-grid items (editable cover + own slider config); see ccmod_sdk.grid."""
        from . import grid
        return grid.grid_items()

    def transition_items(self) -> list[dict]:
        """Installed donorless transitions as CCMOD-grid items (Transitions panel)."""
        from . import grid
        return grid.transition_items()

    def install_borrowed(self, state_dir) -> list[str]:
        """Install our packages under the real stock ids the grid proxy borrowed (so a native drag applies OUR effect)."""
        from . import grid
        return grid.install_borrowed(Path(state_dir))

    def apply(self, project: str, name: str) -> None:
        self._ccfx().apply(project, name)

    def set_param(self, key: str, value) -> str:
        """Drive the selected effect's adjust parameter live (no reload)."""
        return self._b().set_effect_param(key, str(value))


class Draft(_Namespace):
    permission = "draft"

    def save(self, project: str) -> int:
        import draftguard
        return draftguard.save(project)

    def restore(self, project: str) -> int:
        import draftguard
        return draftguard.restore(project)

    def timeline(self, project: str):
        """Open a project's timeline for reading and editing (see ccmod_sdk.timeline). Call .save() to write it."""
        from .timeline import Timeline
        return Timeline.open(project)

    def bake(self, timeline, clip_id: str, prop: str, formula: str, fps: float = 30.0) -> int:
        """Drive a clip property with a formula (see ccmod_sdk.expressions) by baking it to keyframes. Returns the keyframe count."""
        from . import expressions
        return expressions.bake(timeline, clip_id, prop, formula, fps=fps)

    def format_of(self, project: str):
        import draftguard
        fs = draftguard._files(draftguard.drafts_root() / project)
        return draftguard.format_of(fs[0]) if fs else None


class Builds(_Namespace):
    permission = "builds"

    def installed(self) -> list[dict]:
        import ccversion
        return [{"version": b.version, "renders": b.renders, "path": str(b.root), "note": b.profile.get("note", "")}
                for b in ccversion.installed()]

    def preferred(self):
        import ccversion
        b = ccversion.pick()
        return b.version if b else None


class Hooks(_Namespace):
    permission = "render"

    def resolve(self, name: str, build_version: str | None = None):
        """RVA of a named engine function in a CapCut build, found by byte signature."""
        import ccsig
        import ccversion
        b = ccversion.pick(build_version)
        return ccsig.resolve(name, b) if b else None


class Network(_Namespace):
    """Local redirects: when CapCut requests a URL matching `pattern`, it is answered from `local_file`.
    Rules are persisted to ccmod-redirects.json; the Cronet layer applies them (see docs/reference/SDK.md)."""
    permission = "network"

    def _file(self) -> Path:
        return self._ctx.data_dir.parent / "ccmod-redirects.json"

    def rules(self) -> list[dict]:
        try:
            return json.loads(self._file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def redirect(self, pattern: str, local_file: str | Path) -> None:
        rules = [r for r in self.rules() if not (r["plugin"] == self._ctx.manifest.id and r["pattern"] == pattern)]
        rules.append({"plugin": self._ctx.manifest.id, "pattern": pattern, "file": str(Path(local_file).resolve())})
        self._file().parent.mkdir(parents=True, exist_ok=True)
        self._file().write_text(json.dumps(rules, indent=2), encoding="utf-8")

    def clear(self) -> None:
        rules = [r for r in self.rules() if r["plugin"] != self._ctx.manifest.id]
        self._file().write_text(json.dumps(rules, indent=2), encoding="utf-8")

    # ---- catalog rules: extend CapCut's real Effects grid (see ccmod_sdk/catalog_rules.py) ----
    def _proxy(self, pattern: str) -> tuple[list[dict], dict]:
        rules = self.rules()
        for r in rules:
            if r.get("plugin") == self._ctx.manifest.id and r.get("pattern") == pattern and isinstance(r.get("proxy"), dict):
                return rules, r["proxy"]
        spec: dict = {}
        rules.append({"plugin": self._ctx.manifest.id, "pattern": pattern, "proxy": spec})
        return rules, spec

    def _save(self, rules: list[dict]) -> None:
        self._file().parent.mkdir(parents=True, exist_ok=True)
        self._file().write_text(json.dumps(rules, indent=2), encoding="utf-8")

    def add_category(self, category_id: str, name: str, position: int = 0, key: str | None = None) -> None:
        """Add a category to the Effects strip (rewrites the get_panel_info reply)."""
        rules, spec = self._proxy("*get_panel_info*")
        cats = [c for c in spec.get("categories", []) if str(c["category_id"]) != str(category_id)]
        cats.append({"category_id": str(category_id), "name": name, "position": position, **({"key": key} if key else {})})
        spec["categories"] = cats
        self._save(rules)

    def add_tiles(self, items: list[dict], effect_type: int = 7, mode: str = "append") -> None:
        """Add tiles (dicts with effect_id/title/md5 of PRE-INSTALLED packages) to the get_panel_info grid."""
        rules, spec = self._proxy("*get_panel_info*")
        spec["tiles"] = {"effect_type": effect_type, "mode": mode, "items": list(items)}
        self._save(rules)

    def serve_category(self, category_id: str, items: list[dict], effect_type: int = 7) -> None:
        """Answer requests for OUR category id locally with these tiles (it has no server-side list)."""
        rules, spec = self._proxy("*get_resources_by_category_id*")
        spec["serve_category"] = {"category_id": str(category_id), "items": list(items), "effect_type": effect_type}
        self._save(rules)


    def set_grid(self, items: list[dict], name: str = "ccmod", extras_name: str = "ccmod extras", main_count: int = 8,
                 transitions: list[dict] | None = None) -> None:
        """Put these effects in a CCMOD category (+ an extras tab for the overflow) in the REAL Effects grid."""
        from . import grid
        mine = grid.build_rules([dict(i) for i in items], self._ctx.manifest.id, name, extras_name, main_count,
                                transitions=[dict(i) for i in transitions] if transitions else None)
        self._save([r for r in self.rules() if r.get("plugin") != self._ctx.manifest.id] + mine)

    @property
    def catalog_state_dir(self) -> Path:
        """Where the proxy keeps per-session bookkeeping (pins, borrowed ids)."""
        return self._file().parent / "plugin-state-live" / "_catalog"


_IMPORT_QML = r"""
import QtQuick 2.15
Item {
    id: job; objectName: "%NAME%"
    property string report: "pending"
    width: 0; height: 0
    function typeName(it) { var s = String(it); var i = s.indexOf("("); return i > 0 ? s.substring(0, i) : s; }
    Timer { interval: 150; running: true; repeat: false; onTriggered: job.run() }
    Timer { interval: 6000; running: true; repeat: false; onTriggered: job.destroy() }
    function run() {
        try {
            var urls = %URLS%;
            var root = job; while (root.parent) root = root.parent;
            var stack = [root], best = null, bestName = "";
            while (stack.length && !best) {
                var it = stack.pop(), t = typeName(it);
                if (t.indexOf("LocalMedia") === 0) {
                    for (var k in it) {
                        if (!/iewModel$/.test(k)) continue;
                        var vm = it[k];
                        if (vm && typeof vm.importFiles === "function") { best = vm; bestName = t + "." + k; break; }
                    }
                }
                var ch = it.children;
                for (var i = 0; i < ch.length; i++) stack.push(ch[i]);
            }
            if (!best) { report = "error: no media panel found (open a project first)"; return; }
            var list = []; for (var u = 0; u < urls.length; u++) list.push(Qt.url(urls[u]));
            best.importFiles(null, list);
            report = "imported " + list.length + " via " + bestName;
        } catch (e) { report = "error: " + e; }
    }
}
"""


class Media(_Namespace):
    permission = "media"

    def import_files(self, paths: list[str | Path], timeout: float = 5.0) -> str:
        """Add files to CapCut's media pool (the same path as the Import button). The editor must be open on a project.
        Returns the report text ("imported N via ..." or "error: ...")."""
        import time as _t
        files = [Path(p).resolve() for p in paths]
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            raise FileNotFoundError(missing[0])
        name = f"ccmodImport{int(_t.time() * 1000)}"
        urls = json.dumps([f.as_uri() for f in files])
        qml = _IMPORT_QML.replace("%NAME%", name).replace("%URLS%", urls)
        self._ctx.ui.inject_qml("materialPanelParent", qml)
        end = _t.time() + timeout
        while _t.time() < end:
            r = str(self._b().get_prop(name, "report") or "")
            if r and r != "pending" and "not found" not in r.lower():
                return r
            _t.sleep(0.15)
        return "error: no answer from CapCut"

    def import_file(self, path: str | Path) -> str:
        return self.import_files([path])


class Process(_Namespace):
    permission = "process"

    def which(self, name: str, extra_dirs: list[str] | None = None, env_var: str | None = None) -> str | None:
        """Find an external program: an env var override, then PATH, then the extra directories (globs allowed, newest match wins).
        e.g. which("blender", ["C:/Program Files/Blender Foundation/Blender*"], env_var="CCMOD_BLENDER"). None when not installed."""
        import glob
        import os
        import shutil
        if env_var and os.environ.get(env_var) and Path(os.environ[env_var]).is_file():
            return os.environ[env_var]
        hit = shutil.which(name)
        if hit:
            return hit
        exe = name if name.lower().endswith(".exe") else name + ".exe"
        for d in extra_dirs or []:
            for base in sorted(glob.glob(d)):
                cand = Path(base) / exe
                if cand.is_file():
                    last = str(cand)
        return locals().get("last")

    def run(self, cmd: list[str], timeout: float = 600, cwd: str | Path | None = None, env: dict | None = None) -> tuple[int, str]:
        """Run an external program to completion (no console window). Returns (exit code, last 4000 chars of output)."""
        import os
        import subprocess
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None,
                           env={**os.environ, **(env or {})}, creationflags=0x08000000, encoding="utf-8", errors="replace")
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-4000:]

    def run_async(self, cmd: list[str], on_done: Callable[[int, str], None], **kw) -> None:
        """Same as run() on a background thread; `on_done(code, output)` is called when it finishes."""
        def work():
            try:
                code, out = self.run(cmd, **kw)
            except Exception as e:
                code, out = -1, f"{type(e).__name__}: {e}"
            try:
                on_done(code, out)
            except Exception:
                self._ctx.log.exception("run_async callback failed")
        threading.Thread(target=work, name="ccmod-process", daemon=True).start()


class Render(_Namespace):
    """Render agent access (frame history, uniform overrides, external live textures). See ccmod_sdk.renderagent."""
    permission = "render"

    def agent(self, transport=None):
        """A RenderAgent whose clock is the editor's playhead. Configure it, then agent.start() while a project is open."""
        from .renderagent import RenderAgent
        clock = (lambda: Engine(self._ctx).playhead_seconds()) if "engine" in self._ctx.manifest.permissions else None
        return RenderAgent(transport, clock=clock)


class Apps(_Namespace):
    """External programs described by JSON specs (apps/*.json, or `register`): find, run a command, import the result."""
    permission = "apps"

    def _specs(self) -> dict:
        from . import apps
        if not hasattr(self._ctx, "_app_specs"):
            self._ctx._app_specs = {}
        return {**apps.discover(), **self._ctx._app_specs}

    def register(self, spec: dict) -> str:
        """Add an app spec at runtime (validated). Returns its id."""
        from . import apps
        apps.validate(spec)
        self._specs()
        self._ctx._app_specs[spec["id"]] = spec
        return spec["id"]

    def find(self, app_id: str) -> str | None:
        """Path of the app's executable, or None when it is not installed."""
        spec = self._specs().get(app_id)
        if spec is None:
            raise KeyError(f"unknown app {app_id!r}; known: {', '.join(sorted(self._specs())) or 'none'}")
        f = spec["find"]
        return Process(self._ctx).which(f["exe"], f.get("dirs"), f.get("env"))

    def list(self) -> list[dict]:
        out = []
        for aid, spec in self._specs().items():
            exe = self.find(aid)
            out.append({"id": aid, "name": spec["name"], "installed": bool(exe), "exe": exe,
                        "commands": {k: c.get("description", "") for k, c in spec["commands"].items()}})
        return out

    def run(self, app_id: str, command: str, **inputs) -> dict:
        """Run `command` of the app. Returns {ok, code, output, outputs: {name: path}, imported: {name: report}}.
        Bad inputs raise apps.AppError; a missing program returns ok=False with an install hint."""
        from . import apps
        spec = self._specs().get(app_id)
        if spec is None:
            raise KeyError(f"unknown app {app_id!r}")
        cmd = spec["commands"].get(command)
        if cmd is None:
            raise KeyError(f"{app_id} has no command {command!r}; it has: {', '.join(spec['commands'])}")
        exe = self.find(app_id)
        if not exe:
            env = spec["find"].get("env")
            return {"ok": False, "error": f"{spec['name']} not found. Install it" + (f" or set {env} to its exe" if env else "") + "."}
        out_dir = self._ctx.data_dir / "apps" / app_id
        argv, outs = apps.build_command(exe, cmd, inputs, out_dir, apps.stamp())
        code, text = Process(self._ctx).run(argv, timeout=float(cmd.get("timeout", 600)))
        res = {"ok": code == 0, "code": code, "output": text, "outputs": {}, "imported": {}}
        if code != 0:
            res["error"] = f"{spec['name']} exited with code {code}"
            return res
        for k, path in outs.items():
            if not path.is_file():
                res["ok"], res["error"] = False, f"{spec['name']} finished but did not create the {k!r} file"
                continue
            res["outputs"][k] = str(path)
            if cmd["outputs"][k].get("import"):
                try:
                    res["imported"][k] = Media(self._ctx).import_file(path)
                except Exception as e:                          # no editor open: the file is still produced
                    res["imported"][k] = f"error: {e}"
        return res

    def expose_tools(self, app_id: str | None = None) -> list[str]:
        """Register every command as an MCP/plugin tool named "<app>_<command>" (needs the 'tools' permission)."""
        names = []
        for aid, spec in self._specs().items():
            if app_id and aid != app_id:
                continue
            for cname, c in spec["commands"].items():
                props = {k: {"type": "number" if v.get("type") == "number" else "string",
                             "description": ("path to a file" if v.get("type") == "file" else "")}
                         for k, v in c.get("inputs", {}).items()}
                req = [k for k, v in c.get("inputs", {}).items() if "default" not in v]
                fn = (lambda a=aid, cn=cname: (lambda **kw: self.run(a, cn, **kw)))()
                names.append(Tools(self._ctx).register(f"{aid}_{cname}", f"{spec['name']}: {c.get('description', cname)}", fn,
                                                        {"type": "object", "properties": props, "required": req}))
        return names


class Tools(_Namespace):
    permission = "tools"

    def register(self, name: str, description: str, fn: Callable[..., object], schema: dict | None = None) -> str:
        """Expose `fn(**arguments)` as the tool "<plugin-id>.<name>" to MCP clients (ccmod_mcp.py) and the CCMOD tool server.
        `schema` is a JSON-Schema object for the arguments (default: none). Returns the full tool name."""
        full = f"{self._ctx.manifest.id}.{name}"
        self._ctx.tool_registry[full] = {"name": full, "description": description, "fn": fn,
                                          "schema": schema or {"type": "object", "properties": {}}, "plugin": self._ctx.manifest.id}
        return full

    def unregister(self, name: str) -> None:
        self._ctx.tool_registry.pop(f"{self._ctx.manifest.id}.{name}", None)


class Storage(_Namespace):
    permission = "files"

    @property
    def folder(self) -> Path:
        self._ctx.data_dir.mkdir(parents=True, exist_ok=True)
        return self._ctx.data_dir

    def _safe(self, name: str) -> Path:
        p = (self.folder / name).resolve()
        if self.folder.resolve() not in p.parents and p != self.folder.resolve():
            raise PermissionError(f"{name!r} escapes the plugin's data folder")
        return p

    def read_json(self, name: str, default=None):
        try:
            return json.loads(self._safe(name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def write_json(self, name: str, data) -> None:
        self._safe(name).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def path(self, name: str) -> Path: return self._safe(name)


class Events:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = {}

    def on(self, event: str, fn: Callable) -> None:
        self._subs.setdefault(event, []).append(fn)

    def emit(self, event: str, *args, **kw) -> None:
        for fn in list(self._subs.get(event, [])):
            fn(*args, **kw)


class _Gate:
    """Wraps a namespace; raises PermissionError unless the manifest declared its permission."""

    def __init__(self, ns: _Namespace, granted: set[str]):
        object.__setattr__(self, "_ns", ns)
        object.__setattr__(self, "_granted", granted)

    def __getattr__(self, name):
        ns = object.__getattribute__(self, "_ns")
        if ns.permission not in object.__getattribute__(self, "_granted"):
            raise PermissionError(
                f"plugin {ns._ctx.manifest.id!r} used ctx.{type(ns).__name__.lower()} without the "
                f"{ns.permission!r} permission (add it to plugin.json 'permissions')")
        return getattr(ns, name)


class Context:
    def __init__(self, manifest: Manifest, backend: Backend, data_dir: Path, capcut_version: str = "",
                 logger: logging.Logger | None = None, tool_registry: dict | None = None):
        self.manifest = manifest
        self.tool_registry: dict = tool_registry if tool_registry is not None else {}
        self._buttons: dict[str, list] = {}       # objectName -> [handler, last click count]
        self._panels: dict[str, object] = {}      # objectName -> uikit.Panel
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self.backend = backend
        self.data_dir = Path(data_dir) / manifest.id
        self.capcut_version = capcut_version
        self.log = logger or logging.getLogger(f"ccmod.plugin.{manifest.id}")
        self.events = Events()
        g = set(manifest.permissions)
        self.ui = _Gate(UI(self), g)
        self.engine = _Gate(Engine(self), g)
        self.effects = _Gate(Effects(self), g)
        self.draft = _Gate(Draft(self), g)
        self.builds = _Gate(Builds(self), g)
        self.hooks = _Gate(Hooks(self), g)
        self.network = _Gate(Network(self), g)
        self.storage = _Gate(Storage(self), g)
        self.tools = _Gate(Tools(self), g)
        self.media = _Gate(Media(self), g)
        self.process = _Gate(Process(self), g)
        self.apps = _Gate(Apps(self), g)
        self.render = _Gate(Render(self), g)

    # ---- button click polling: the QML button counts clicks, one thread per plugin reads the counters ----
    def _register_button(self, name: str, handler: Callable) -> None:
        try:
            cur = int(float(self.backend.get_prop(name, "clicks") or 0))
        except ValueError:
            cur = 0
        self._buttons[name] = [handler, cur]
        self._ensure_poller()

    def _register_panel(self, panel) -> None:
        self._panels[panel.name] = panel
        self._ensure_poller()

    def _ensure_poller(self) -> None:
        if not self._poller or not self._poller.is_alive():
            self._stop.clear()
            self._poller = threading.Thread(target=self._poll_buttons, name=f"ccmod-buttons-{self.manifest.id}", daemon=True)
            self._poller.start()

    def _poll_buttons(self) -> None:
        while not self._stop.is_set():
            for name, st in list(self._buttons.items()):
                try:
                    n = int(float(self.backend.get_prop(name, "clicks") or 0))
                except Exception:
                    continue
                if n < st[1]:                      # the editor was reopened: a fresh button starts at 0 again
                    st[1] = n
                while n > st[1]:
                    st[1] += 1
                    try:
                        st[0]()
                    except Exception:
                        self.log.exception("button %s handler failed", name)
            for panel in list(self._panels.values()):
                try:
                    panel.poll()
                except Exception:
                    self.log.exception("panel %s poll failed", getattr(panel, "id", "?"))
            self._stop.wait(0.2)

    def close(self) -> None:
        """Stop background threads and drop this plugin's tools (called by the host on unload)."""
        self._stop.set()
        for k in [k for k, v in self.tool_registry.items() if v.get("plugin") == self.manifest.id]:
            self.tool_registry.pop(k, None)
