"""Backends: how the SDK talks to a running CapCut.

`Backend` is the narrow waist. Everything a plugin can do to the live app goes through these few methods, which map 1:1
onto ccmod_inject.dll exports (Qt metaobject reflection inside CapCut's UI process):

    invoke(selector, method, args)   -> ccmod_invoke      call any Q_INVOKABLE / slot on a live QObject
    get_prop / set_prop              -> ccmod_get_prop / ccmod_set_prop
    click(selector)                  -> ccmod_click_qml   synthetic click on a QML item
    list_custom(n) / dump_meta(sel)  -> reflection (find controllers, see their properties and methods)
    inject_qml(parent_selector, qml) -> ccmod_inject_into add QML (a button, a panel, a tab) under a live item
    set_effect_param(key, value)     -> ccmod_set_effect_param  drive the selected effect's adjust param live

`FridaBackend` is the real thing (attaches to the CapCut UI process). `FakeBackend` records calls and keeps an in-memory
property store, so plugins and the loader can be tested without CapCut.
"""
from __future__ import annotations

import csv
import io
import subprocess
import tempfile
from pathlib import Path


class BackendError(RuntimeError):
    pass


class Backend:
    name = "abstract"

    def invoke(self, selector: str, method: str, args: str = "") -> str: raise NotImplementedError
    def get_prop(self, selector: str, prop: str) -> str: raise NotImplementedError
    def set_prop(self, selector: str, prop: str, value: str) -> str: raise NotImplementedError
    def click(self, selector: str) -> str: raise NotImplementedError
    def list_custom(self, n: int = 0) -> str: raise NotImplementedError
    def dump_meta(self, selector: str, n: int = 5) -> str: raise NotImplementedError
    def inject_qml(self, parent_selector: str, qml_path: str) -> str: raise NotImplementedError
    def set_effect_param(self, key: str, value: str) -> str: raise NotImplementedError
    def positioners(self, n: int = 0) -> str: raise NotImplementedError   # ccmod_list_positioners: Row/Column/Grid items with address, kids, size
    def close(self) -> None: pass


class FakeBackend(Backend):
    """In-memory stand-in. `calls` is a log of (method, *args); props are a dict keyed (selector, prop)."""
    name = "fake"

    def __init__(self):
        self.calls: list[tuple] = []
        self.props: dict[tuple[str, str], str] = {}
        self.classes = ["MainTimeLineCursorViewModel", "MainTimeLineCanvasViewModel", "EffectTreeViewModel"]

    def _log(self, *a): self.calls.append(a)

    def invoke(self, selector, method, args=""):
        self._log("invoke", selector, method, args); return "ok (void)"

    def get_prop(self, selector, prop):
        self._log("get_prop", selector, prop); return self.props.get((selector, prop), "")

    def set_prop(self, selector, prop, value):
        self._log("set_prop", selector, prop, value); self.props[(selector, prop)] = str(value); return "ok"

    def click(self, selector):
        self._log("click", selector); return f"ok: clicked {selector}"

    def list_custom(self, n=0):
        self._log("list_custom", n); return "\n".join(f"0x0  x1  {c}" for c in self.classes)

    def dump_meta(self, selector, n=5):
        self._log("dump_meta", selector, n); return f"=== {selector} ==="

    def inject_qml(self, parent_selector, qml_path):
        self._log("inject_qml", parent_selector, Path(qml_path).read_text(encoding="utf-8")); return "ok"

    def set_effect_param(self, key, value):
        self._log("set_effect_param", key, value); return "ok"

    def positioners(self, n=0):
        self._log("positioners", n); return getattr(self, "positioner_text", "")


_JS = r"""
var DLL = "%DLL%";
var k = Process.getModuleByName("kernel32.dll");
var LL = new NativeFunction(k.getExportByName("LoadLibraryA"), 'pointer', ['pointer']);
var h = LL(Memory.allocUtf8String(DLL));
if (h.isNull()) { throw new Error("LoadLibraryA failed for " + DLL); }
var mod = Process.findModuleByAddress(h), exp = {};
mod.enumerateExports().forEach(function (e) { exp[e.name] = e.address; });
function S(s) { return Memory.allocUtf8String(String(s)); }
function R(p) { return (p && !p.isNull()) ? p.readUtf8String() : ""; }
function F(name, n) {
  var a = exp["ccmod_" + name]; if (!a) return null;
  var t = []; for (var i = 0; i < n; i++) t.push('pointer');
  return new NativeFunction(a, 'pointer', t);
}
var fn = { invoke: F("invoke", 3), get: F("get_prop", 2), set: F("set_prop", 3), click: F("click_qml", 1),
           list: null, meta: null, inject: F("inject_into", 2), param: F("set_effect_param", 2) };
var listCustom = exp["ccmod_list_custom"] ? new NativeFunction(exp["ccmod_list_custom"], 'pointer', ['int']) : null;
var dumpMeta = exp["ccmod_dump_meta"] ? new NativeFunction(exp["ccmod_dump_meta"], 'pointer', ['pointer', 'int']) : null;
var listPos = exp["ccmod_list_positioners"] ? new NativeFunction(exp["ccmod_list_positioners"], 'pointer', ['int']) : null;
function need(f, name) { if (!f) throw new Error("ccmod_inject.dll has no export for " + name + " (restore the full DLL)"); return f; }
rpc.exports = {
  invoke: function (s, m, a) { return R(need(fn.invoke, "invoke")(S(s), S(m), S(a))); },
  getprop: function (s, p) { return R(need(fn.get, "get_prop")(S(s), S(p))); },
  setprop: function (s, p, v) { return R(need(fn.set, "set_prop")(S(s), S(p), S(v))); },
  click: function (s) { return R(need(fn.click, "click_qml")(S(s))); },
  listcustom: function (n) { return R(need(listCustom, "list_custom")(n)); },
  dumpmeta: function (s, n) { return R(need(dumpMeta, "dump_meta")(S(s), n)); },
  injectqml: function (s, p) { return R(need(fn.inject, "inject_into")(S(s), S(p))); },
  positioners: function (n) { return R(need(listPos, "list_positioners")(n)); },
  effectparam: function (k2, v) { return R(need(fn.param, "set_effect_param")(S(k2), S(v))); },
  exports: function () { return Object.keys(exp); }
};
"""


class FridaBackend(Backend):
    """One persistent Frida session to the CapCut UI process (the one hosting FusionUI.dll)."""
    name = "frida"

    def __init__(self, dll: str | Path | None = None, pid: int | None = None):
        try:
            import frida
        except ImportError as e:
            raise BackendError("frida is required: pip install frida frida-tools") from e
        self._frida = frida
        self.dll = str(Path(dll or Path(__file__).resolve().parent.parent / "ccmod_inject.dll"))
        self.pid = pid or self.ui_pid()
        if not self.pid:
            raise BackendError("no running CapCut UI process")
        self._session = frida.attach(self.pid)
        self._script = self._session.create_script(_JS.replace("%DLL%", self.dll.replace("\\", "\\\\")))
        self._script.load()
        self._tmp: list[str] = []

    @staticmethod
    def ui_pid() -> int | None:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/M", "FusionUI.dll"],
                             capture_output=True, text=True).stdout
        for r in csv.reader(io.StringIO(out)):
            if r and r[0] == "CapCut.exe":
                try:
                    return int(r[1])
                except ValueError:
                    pass
        return None

    @property
    def _x(self): return self._script.exports_sync

    def invoke(self, selector, method, args=""): return self._x.invoke(selector, method, args)
    def get_prop(self, selector, prop): return self._x.getprop(selector, prop)
    def set_prop(self, selector, prop, value): return self._x.setprop(selector, prop, str(value))
    def click(self, selector): return self._x.click(selector)
    def list_custom(self, n=0): return self._x.listcustom(n)
    def dump_meta(self, selector, n=5): return self._x.dumpmeta(selector, n)
    def inject_qml(self, parent_selector, qml_path): return self._x.injectqml(parent_selector, str(qml_path))
    def set_effect_param(self, key, value): return self._x.effectparam(key, str(value))
    def positioners(self, n=0): return self._x.positioners(n)

    def close(self):
        try:
            self._session.detach()
        except Exception:
            pass
