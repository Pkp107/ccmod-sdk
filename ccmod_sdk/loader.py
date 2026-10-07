"""Plugin discovery, loading and lifecycle.

    host = Host(backend, plugins_dir, data_dir, capcut_version="8.9.1.3802")
    host.load_all()                 # discover -> validate -> import -> Plugin(ctx).on_load()
    host.emit("editor_open")        # calls on_editor_open() on every enabled plugin
    host.unload_all()

Isolation: a plugin that raises in a hook is recorded in `host.errors` and disabled; it never takes down the host or
the other plugins. Enabled/disabled state persists in <data_dir>/state.json.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
import traceback
from pathlib import Path

from . import manifest as mf
from .backend import Backend
from .context import Context


class Plugin:
    """Subclass this in your entry file. Override any hook; all are optional."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def on_load(self) -> None: ...
    def on_unload(self) -> None: ...
    def on_capcut_start(self) -> None: ...
    def on_editor_open(self) -> None: ...
    def on_project_open(self, project: str = "") -> None: ...


class Loaded:
    def __init__(self, manifest: mf.Manifest, plugin: Plugin, ctx: Context):
        self.manifest, self.plugin, self.ctx = manifest, plugin, ctx
        self.enabled = True


class Host:
    def __init__(self, backend: Backend, plugins_dir: Path, data_dir: Path, capcut_version: str = "",
                 logger: logging.Logger | None = None):
        self.backend = backend
        self.plugins_dir = Path(plugins_dir)
        self.data_dir = Path(data_dir)
        self.capcut_version = capcut_version
        self.log = logger or logging.getLogger("ccmod.host")
        self.plugins: dict[str, Loaded] = {}
        self.errors: dict[str, str] = {}        # plugin id -> last error text
        self.skipped: dict[str, str] = {}       # folder name -> reason it was not loaded
        self.tools: dict[str, dict] = {}        # tool name -> {name, description, schema, fn, plugin}; shared with every plugin context

    # ---- state ----
    def _state_file(self) -> Path:
        return self.data_dir / "state.json"

    def _state(self) -> dict:
        try:
            return json.loads(self._state_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, st: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file().write_text(json.dumps(st, indent=2), encoding="utf-8")

    def is_enabled(self, plugin_id: str) -> bool:
        return self._state().get("disabled", {}).get(plugin_id) is None

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        st = self._state(); dis = st.setdefault("disabled", {})
        if enabled:
            dis.pop(plugin_id, None)
        else:
            dis[plugin_id] = True
        self._save_state(st)
        if plugin_id in self.plugins:
            self.plugins[plugin_id].enabled = enabled
            (self._call(plugin_id, "on_load") if enabled else self._call(plugin_id, "on_unload"))

    # ---- discovery ----
    def discover(self) -> list[mf.Manifest]:
        found: list[mf.Manifest] = []
        self.skipped.clear()
        if not self.plugins_dir.is_dir():
            return found
        for d in sorted(p for p in self.plugins_dir.iterdir() if p.is_dir()):
            if not (d / "plugin.json").exists():
                continue
            try:
                m = mf.load(d)
            except mf.ManifestError as e:
                self.skipped[d.name] = f"invalid manifest: {e}"; continue
            if not m.compatible_with_sdk():
                self.skipped[d.name] = f"needs CCMOD SDK {m.ccmod}"; continue
            if self.capcut_version and not m.compatible_with_capcut(self.capcut_version):
                self.skipped[d.name] = f"not for CapCut {self.capcut_version} (supports {m.capcut})"; continue
            if any(x.id == m.id for x in found):
                self.skipped[d.name] = f"duplicate id {m.id!r}"; continue
            found.append(m)
        return found

    # ---- loading ----
    def _import(self, m: mf.Manifest):
        entry = (m.path / m.entry).resolve()
        name = f"ccmod_plugin_{m.id.replace('-', '_').replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(name, entry, submodule_search_locations=[str(m.path)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        sys.path.insert(0, str(m.path))
        try:
            spec.loader.exec_module(mod)
        finally:
            if sys.path and sys.path[0] == str(m.path):
                sys.path.pop(0)
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, Plugin) and obj is not Plugin and obj.__module__ == name:
                return obj
        raise TypeError(f"{m.entry}: no Plugin subclass found")

    def load_all(self) -> list[str]:
        loaded = []
        for m in self.discover():
            try:
                cls = self._import(m)
                ctx = Context(m, self.backend, self.data_dir / "plugin-data", self.capcut_version, tool_registry=self.tools)
                lp = Loaded(m, cls(ctx), ctx)
                lp.enabled = self.is_enabled(m.id)
                self.plugins[m.id] = lp
            except Exception:
                self.errors[m.id] = traceback.format_exc(limit=3)
                self.log.error("plugin %s failed to import:\n%s", m.id, self.errors[m.id])
                continue
            if lp.enabled:
                self._call(m.id, "on_load")
            loaded.append(m.id)
        return loaded

    def _call(self, plugin_id: str, hook: str, *args):
        lp = self.plugins.get(plugin_id)
        if not lp or not lp.enabled:
            return
        try:
            getattr(lp.plugin, hook)(*args)
        except Exception:
            self.errors[plugin_id] = traceback.format_exc(limit=4)
            self.log.error("plugin %s crashed in %s:\n%s", plugin_id, hook, self.errors[plugin_id])
            lp.enabled = False              # isolate: never call a crashed plugin again this session

    def emit(self, event: str, *args) -> None:
        for pid in list(self.plugins):
            self._call(pid, f"on_{event}", *args)
            try:
                self.plugins[pid].ctx.events.emit(event, *args)
            except Exception:
                self.errors[pid] = traceback.format_exc(limit=4)

    def unload_all(self) -> None:
        for pid in list(self.plugins):
            self._call(pid, "on_unload")
            try:
                self.plugins[pid].ctx.close()
            except Exception:
                pass
        self.plugins.clear()

    def summary(self) -> list[dict]:
        return [{"id": p.manifest.id, "name": p.manifest.name, "version": p.manifest.version,
                 "enabled": p.enabled, "permissions": p.manifest.permissions, "error": self.errors.get(p.manifest.id)}
                for p in self.plugins.values()]
