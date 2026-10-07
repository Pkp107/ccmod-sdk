"""Render agent: a small script injected into CapCut's render process (the one that draws effects, libGLESv2 of VEAngle).

It gives ccmod what the single-frame shader contract cannot:

  uniforms      override ANY shader uniform by name, every frame, from Python (a number, or a formula of time/playhead)
                -> `agent.set_uniform("u_strength", 0.7)`, `agent.drive("iTime", "t * 2")`
  history       give an effect the previous frame: declare `uniform sampler2D u_ccmodPrev;` in your shader and call
                `agent.enable_history()`; the agent binds last frame's output to it and refreshes it after every draw
                -> echo, trails, feedback, motion smear
  external feed give an effect a live picture from another program: declare `uniform sampler2D u_ccmodExt;`,
                `feed = agent.external_feed(1280, 720)`, then `feed.write(rgba_bytes)` from Blender, a game, OpenCV ...
                -> live 3D / particle / generated layers inside an effect

Status (6 Oct 2026): the uniform override uses the same hook technique as scratch/ccmod_scrubtime.py, which is proven on
screen. History and the external feed are new GL code: the generated script is syntax-checked and the controller is unit-tested,
but neither has been seen rendering in CapCut yet. Treat them as experimental until a live run says otherwise.

    agent = RenderAgent()
    agent.start()                     # attaches to CapCut's render process(es); needs CapCut open on a project
    agent.set_uniform("u_amount", 0.5)
    ...
    agent.stop()
"""
from __future__ import annotations

import csv
import ctypes
import io
import json
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

FEED_HEADER = 16                       # bytes: u32 sequence, u32 width, u32 height, u32 reserved


class AgentError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------- the injected script
AGENT_JS = r"""
'use strict';
var CFG = __CONFIG__;
var U = {};                      // uniform name -> [floats]
var histOn = !!CFG.history, ext = CFG.ext || null;
var stats = { hooked: 0, over: 0, histDraws: 0, extUploads: 0, errors: 0 };
recv('U', function onU(m) { if (m.v === null) delete U[m.name]; else U[m.name] = m.v; recv('U', onU); });
recv('H', function onH(m) { histOn = !!m.on; recv('H', onH); });

var GL_ACTIVE_TEXTURE = 0x84E0, GL_TEXTURE_BINDING_2D = 0x8069, GL_VIEWPORT = 0x0BA2, GL_TEXTURE_2D = 0x0DE1, GL_TEXTURE0 = 0x84C0;
var GL_RGBA = 0x1908, GL_UNSIGNED_BYTE = 0x1401, GL_LINEAR = 0x2601, GL_CLAMP = 0x812F, GL_MIN = 0x2801, GL_MAG = 0x2800, GL_WS = 0x2802, GL_WT = 0x2803;
var applied = {};

function hook() {
  Process.enumerateModules().filter(function (x) { return /libGLESv2/i.test(x.name); }).forEach(function (g) {
    if (applied[g.base]) return; applied[g.base] = 1;
    var X = function (n) { return g.findExportByName(n); };
    var nf = function (n, r, a) { var p = X(n); return p ? new NativeFunction(p, r, a) : null; };
    var gGetLoc = nf('glGetUniformLocation', 'int', ['int', 'pointer']);
    var gActive = nf('glActiveTexture', 'void', ['int']);
    var gBind = nf('glBindTexture', 'void', ['int', 'int']);
    var gGetInt = nf('glGetIntegerv', 'void', ['int', 'pointer']);
    var gGen = nf('glGenTextures', 'void', ['int', 'pointer']);
    var gTexImage = nf('glTexImage2D', 'void', ['int', 'int', 'int', 'int', 'int', 'int', 'int', 'int', 'pointer']);
    var gTexSub = nf('glTexSubImage2D', 'void', ['int', 'int', 'int', 'int', 'int', 'int', 'int', 'int', 'pointer']);
    var gCopySub = nf('glCopyTexSubImage2D', 'void', ['int', 'int', 'int', 'int', 'int', 'int', 'int', 'int']);
    var gTexPar = nf('glTexParameteri', 'void', ['int', 'int', 'int']);
    var gU1i = nf('glUniform1i', 'void', ['int', 'int']);
    var tmp = Memory.alloc(64);
    var cur = 0, locName = {}, progLocs = {}, probed = {}, hist = { tex: 0, w: 0, h: 0 }, extTex = { tex: 0, w: 0, h: 0, seq: -1 };

    function getInt(pname, n) { gGetInt(pname, tmp); return n === 1 ? tmp.readS32() : [tmp.readS32(), tmp.add(4).readS32(), tmp.add(8).readS32(), tmp.add(12).readS32()]; }
    function makeTex() { gGen(1, tmp); var t = tmp.readU32(); gBind(GL_TEXTURE_2D, t);
      gTexPar(GL_TEXTURE_2D, GL_MIN, GL_LINEAR); gTexPar(GL_TEXTURE_2D, GL_MAG, GL_LINEAR); gTexPar(GL_TEXTURE_2D, GL_WS, 0x812F); gTexPar(GL_TEXTURE_2D, GL_WT, 0x812F); return t; }

    function record(prog, loc, name) { locName[prog + ':' + loc] = name; (progLocs[prog] = progLocs[prog] || {})[name] = loc; }
    function probe(prog) {            // programs linked before we attached: look the interesting names up ourselves
      if (!gGetLoc || !prog || probed[prog]) return; probed[prog] = 1;
      var names = ['u_ccmodPrev', 'u_ccmodExt'].concat(Object.keys(U));
      names.forEach(function (n) { var l = gGetLoc(prog, Memory.allocUtf8String(n)); if (l >= 0) record(prog, l, n); });
    }
    var gUse = X('glUseProgram');
    if (gUse) Interceptor.attach(gUse, { onEnter: function (a) { cur = a[0].toInt32(); probe(cur); } });
    var gLoc = X('glGetUniformLocation');
    if (gLoc) Interceptor.attach(gLoc, { onEnter: function (a) { this.p = a[0].toInt32(); this.n = a[1].readUtf8String(); },
                                         onLeave: function (r) { var l = r.toInt32(); if (l >= 0) record(this.p, l, this.n); } });

    // ---- uniform overrides: float setters ----
    function override(loc, vals) { var v = U[locName[cur + ':' + loc]]; if (v === undefined) return null; stats.over++; return v; }
    ['glUniform1f', 'glUniform2f', 'glUniform3f', 'glUniform4f'].forEach(function (fn, k) {
      var p = X(fn); if (!p) return; var n = k + 1;
      var orig = new NativeFunction(p, 'void', ['int'].concat(Array(n).fill('float')));
      Interceptor.replace(p, new NativeCallback(function () {
        var args = Array.prototype.slice.call(arguments), v = override(args[0]);
        if (v) for (var i = 0; i < n; i++) if (v[i] !== undefined) args[i + 1] = v[i];
        orig.apply(null, args);
      }, 'void', ['int'].concat(Array(n).fill('float'))));
    });
    ['glUniform1fv', 'glUniform2fv', 'glUniform3fv', 'glUniform4fv'].forEach(function (fn, k) {
      var p = X(fn); if (!p) return; var n = k + 1;
      Interceptor.attach(p, { onEnter: function (a) { var v = override(a[0].toInt32()); if (v && a[1].toInt32() >= 1) for (var i = 0; i < n; i++) if (v[i] !== undefined) a[2].add(4 * i).writeFloat(v[i]); } });
    });

    // ---- frame history + external feed: bind our textures before a draw, refresh after ----
    function beforeDraw() {
      var pl = progLocs[cur]; if (!pl) return null;
      var st = { act: 0, bind: 0, did: false };
      var wantPrev = histOn && pl['u_ccmodPrev'] !== undefined, wantExt = ext && pl['u_ccmodExt'] !== undefined;
      if (!wantPrev && !wantExt) return null;
      st.act = getInt(GL_ACTIVE_TEXTURE, 1); st.bind = getInt(GL_TEXTURE_BINDING_2D, 1);
      if (wantPrev) {
        var vp = getInt(GL_VIEWPORT, 4), w = vp[2], h = vp[3];
        if (!hist.tex || hist.w !== w || hist.h !== h) {
          if (!hist.tex) hist.tex = makeTex();
          gActive(GL_TEXTURE0 + CFG.histUnit); gBind(GL_TEXTURE_2D, hist.tex);
          gTexImage(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, ptr(0)); hist.w = w; hist.h = h; hist.fresh = true;
        }
        gActive(GL_TEXTURE0 + CFG.histUnit); gBind(GL_TEXTURE_2D, hist.tex); gU1i(pl['u_ccmodPrev'], CFG.histUnit); st.prev = true; st.vp = vp;
      }
      if (wantExt && extMap) {
        var seq = extMap.readU32(), ew = extMap.add(4).readU32(), eh = extMap.add(8).readU32();
        if (ew > 0 && eh > 0) {
          if (!extTex.tex) extTex.tex = makeTex();
          gActive(GL_TEXTURE0 + CFG.extUnit); gBind(GL_TEXTURE_2D, extTex.tex);
          if (extTex.w !== ew || extTex.h !== eh) { gTexImage(GL_TEXTURE_2D, 0, GL_RGBA, ew, eh, 0, GL_RGBA, GL_UNSIGNED_BYTE, extMap.add(CFG.header)); extTex.w = ew; extTex.h = eh; extTex.seq = seq; stats.extUploads++; }
          else if (extTex.seq !== seq) { gTexSub(GL_TEXTURE_2D, 0, 0, 0, ew, eh, GL_RGBA, GL_UNSIGNED_BYTE, extMap.add(CFG.header)); extTex.seq = seq; stats.extUploads++; }
          gU1i(pl['u_ccmodExt'], CFG.extUnit);
        }
      }
      return st;
    }
    function afterDraw(st) {
      if (!st) return;
      if (st.prev) {                        // keep this frame's output for the next draw
        gActive(GL_TEXTURE0 + CFG.histUnit); gBind(GL_TEXTURE_2D, hist.tex);
        gCopySub(GL_TEXTURE_2D, 0, 0, 0, st.vp[0], st.vp[1], hist.w, hist.h); stats.histDraws++;
      }
      gBind(GL_TEXTURE_2D, 0); gActive(st.act); gBind(GL_TEXTURE_2D, st.bind);
    }
    var extMap = null;
    if (ext) {
      try {
        var k32 = Process.getModuleByName('kernel32.dll');
        var open = new NativeFunction(k32.getExportByName('OpenFileMappingA'), 'pointer', ['uint', 'int', 'pointer']);
        var mapv = new NativeFunction(k32.getExportByName('MapViewOfFile'), 'pointer', ['pointer', 'uint', 'uint', 'uint', 'size_t']);
        var hm = open(4, 0, Memory.allocUtf8String(ext.name));
        if (!hm.isNull()) extMap = mapv(hm, 4, 0, 0, 0); else send({ t: 'ERR', msg: 'external feed mapping not found: ' + ext.name });
      } catch (e) { stats.errors++; send({ t: 'ERR', msg: 'external feed: ' + e }); }
    }
    ['glDrawElements', 'glDrawArrays', 'glDrawElementsInstanced', 'glDrawArraysInstanced'].forEach(function (fn) {
      var p = X(fn); if (!p) return;
      Interceptor.attach(p, {
        onEnter: function () { try { this.st = beforeDraw(); } catch (e) { stats.errors++; this.st = null; } },
        onLeave: function () { try { afterDraw(this.st); } catch (e) { stats.errors++; } }
      });
    });
    stats.hooked++;
    send({ t: 'HOOKED', mod: g.name, pid: Process.id });
  });
}
hook(); setInterval(hook, 1500);
setInterval(function () { send({ t: 'STATS', pid: Process.id, stats: stats }); }, 2000);
"""


def build_script(history: bool = False, hist_unit: int = 15, ext: dict | None = None, ext_unit: int = 14) -> str:
    """The injected JavaScript with its configuration filled in."""
    if hist_unit == ext_unit:
        raise AgentError("history and external feed need different texture units")
    cfg = {"history": history, "histUnit": int(hist_unit), "extUnit": int(ext_unit), "header": FEED_HEADER, "ext": ext}
    return AGENT_JS.replace("__CONFIG__", json.dumps(cfg))


# --------------------------------------------------------------------------------------------- external feed (Python side)
class ExternalFeed:
    """A named Windows shared-memory frame the render agent uploads as the `u_ccmodExt` texture (RGBA8, bottom-up like OpenGL)."""

    def __init__(self, width: int, height: int, name: str | None = None):
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise AgentError("feed size must be 1..4096 pixels")
        self.width, self.height = int(width), int(height)
        self.name = name or f"ccmod_feed_{int(time.time() * 1000)}"
        self.size = FEED_HEADER + self.width * self.height * 4
        self._seq = 0
        self._handle = None
        self._view = None
        k = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
        if k is None:
            self._buf = bytearray(self.size)                       # non-Windows: in-memory only (tests)
        else:
            k.CreateFileMappingW.restype = ctypes.c_void_p
            k.MapViewOfFile.restype = ctypes.c_void_p
            self._handle = k.CreateFileMappingW(ctypes.c_void_p(-1), None, 0x04, 0, self.size, self.name)
            if not self._handle:
                raise AgentError("could not create the shared-memory feed")
            self._view = k.MapViewOfFile(ctypes.c_void_p(self._handle), 0x0006, 0, 0, self.size)
            self._buf = (ctypes.c_char * self.size).from_address(self._view)
            self._k = k
        self._buf[0:FEED_HEADER] = struct.pack("<IIII", 0, self.width, self.height, 0)

    def write(self, rgba: bytes) -> int:
        """Publish one frame. Returns its sequence number. Raises if the byte count doesn't match width*height*4."""
        if len(rgba) != self.width * self.height * 4:
            raise AgentError(f"expected {self.width * self.height * 4} bytes (RGBA {self.width}x{self.height}), got {len(rgba)}")
        self._buf[FEED_HEADER:self.size] = rgba
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self._buf[0:4] = struct.pack("<I", self._seq)             # sequence last: the agent uploads only complete frames
        return self._seq

    def read_header(self) -> tuple[int, int, int]:
        return struct.unpack("<III", bytes(self._buf[0:12]))

    def close(self) -> None:
        if self._view and hasattr(self, "_k"):
            self._k.UnmapViewOfFile(ctypes.c_void_p(self._view))
            self._k.CloseHandle(ctypes.c_void_p(self._handle))
            self._view = self._handle = None

    def spec(self) -> dict:
        return {"name": self.name, "width": self.width, "height": self.height}


# --------------------------------------------------------------------------------------------- transports
class FakeTransport:
    """Records what would be sent; used by tests and `--dry-run`."""

    def __init__(self):
        self.script: str | None = None
        self.sent: list[dict] = []
        self.stopped = False

    def start(self, script: str, on_message: Callable[[dict], None]) -> list[int]:
        self.script, self.on_message = script, on_message
        return [0]

    def post(self, message: dict) -> None:
        self.sent.append(message)

    def stop(self) -> None:
        self.stopped = True


class FridaTransport:
    """Attaches the script to every CapCut process that has the effect renderer's GLES loaded."""

    def __init__(self):
        self._scripts: list = []
        self._sessions: list = []

    @staticmethod
    def render_pids() -> list[int]:
        import psutil
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        pids = [int(r[1]) for r in csv.reader(io.StringIO(out)) if len(r) > 1 and r[0] == "CapCut.exe"]
        hits = []
        for pid in pids:
            try:
                if any("libglesv2" in m.path.lower() for m in psutil.Process(pid).memory_maps()):
                    hits.append(pid)
            except Exception:
                pass
        return hits

    def start(self, script: str, on_message: Callable[[dict], None]) -> list[int]:
        import frida
        pids = self.render_pids()
        if not pids:
            raise AgentError("no CapCut process with the effect renderer loaded; open CapCut on a project first")
        attached = []
        for pid in pids:
            box: dict = {}

            def work(pid=pid, box=box):
                try:
                    sess = frida.attach(pid)
                    sc = sess.create_script(script)
                    sc.on("message", lambda m, d: on_message(m.get("payload") or {"t": "ERR", "msg": m.get("description", "")}))
                    sc.load()
                    box["v"] = (sess, sc)
                except Exception as e:
                    box["e"] = e
            th = threading.Thread(target=work, daemon=True)
            th.start()
            th.join(10)
            if "v" in box:
                self._sessions.append(box["v"][0])
                self._scripts.append(box["v"][1])
                attached.append(pid)
        if not attached:
            raise AgentError("could not attach to CapCut's render process")
        return attached

    def post(self, message: dict) -> None:
        for sc in self._scripts:
            try:
                sc.post(message)
            except Exception:
                pass

    def stop(self) -> None:
        for sc in self._scripts:
            try:
                sc.unload()
            except Exception:
                pass
        for s in self._sessions:
            try:
                s.detach()
            except Exception:
                pass
        self._scripts, self._sessions = [], []


# --------------------------------------------------------------------------------------------- the controller
class RenderAgent:
    def __init__(self, transport=None, clock: Callable[[], float] | None = None):
        self.transport = transport or FridaTransport()
        self.clock = clock                                   # returns the playhead in seconds (e.g. ctx.engine.playhead_seconds)
        self.stats: dict[int, dict] = {}
        self.errors: list[str] = []
        self.pids: list[int] = []
        self._history = False
        self._feed: ExternalFeed | None = None
        self._drivers: dict[str, object] = {}
        self._values: dict[str, list[float]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def enable_history(self, on: bool = True) -> None:
        """Bind the previous frame to `uniform sampler2D u_ccmodPrev` in shaders that declare it."""
        self._history = on
        if self.pids:
            self.transport.post({"type": "H", "on": on})

    def external_feed(self, width: int, height: int) -> ExternalFeed:
        """Create the shared-memory picture bound to `uniform sampler2D u_ccmodExt`. Call before start()."""
        if self.pids:
            raise AgentError("create the external feed before start()")
        self._feed = ExternalFeed(width, height)
        return self._feed

    def set_uniform(self, name: str, value) -> None:
        """Force a shader uniform (float, vec2, vec3 or vec4 given as a number or a list) every time CapCut sets it."""
        vals = [float(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
        if not 1 <= len(vals) <= 4:
            raise AgentError("a uniform has 1 to 4 components")
        self._valid_name(name)
        self._values[name] = vals
        if self.pids:
            self.transport.post({"type": "U", "name": name, "v": vals})

    def clear_uniform(self, name: str) -> None:
        self._values.pop(name, None)
        self._drivers.pop(name, None)
        if self.pids:
            self.transport.post({"type": "U", "name": name, "v": None})

    def drive(self, name: str, formula: str, scale: float = 1.0) -> None:
        """Set a uniform every 30 ms from a formula (see ccmod_sdk.expressions); `t` is the playhead in seconds when a clock is set,
        otherwise the seconds since start()."""
        from . import expressions
        self._valid_name(name)
        self._drivers[name] = (expressions.compile(formula), scale)

    @staticmethod
    def _valid_name(name: str) -> None:
        import re
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", name):
            raise AgentError(f"bad uniform name {name!r}")

    def start(self) -> list[int]:
        ext = self._feed.spec() if self._feed else None
        script = build_script(history=self._history, ext=ext)
        self.pids = self.transport.start(script, self._on_message)
        for n, v in self._values.items():
            self.transport.post({"type": "U", "name": n, "v": v})
        self._t0 = time.time()
        self._stop.clear()
        if self._drivers:
            self._thread = threading.Thread(target=self._drive_loop, name="ccmod-agent-drive", daemon=True)
            self._thread.start()
        return self.pids

    def _on_message(self, p: dict) -> None:
        if p.get("t") == "STATS":
            self.stats[p.get("pid", 0)] = p.get("stats", {})
        elif p.get("t") == "ERR":
            self.errors.append(str(p.get("msg")))

    def _drive_loop(self) -> None:
        while not self._stop.is_set():
            t = self.clock() if self.clock else time.time() - self._t0
            for name, (f, scale) in list(self._drivers.items()):
                try:
                    self.transport.post({"type": "U", "name": name, "v": [f(t=t, dur=1e9) * scale]})
                except Exception as e:
                    self.errors.append(f"{name}: {e}")
                    self._drivers.pop(name, None)
            self._stop.wait(0.03)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(1)
        self.transport.stop()
        if self._feed:
            self._feed.close()
        self.pids = []
