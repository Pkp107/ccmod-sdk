"""The CCMOD tool server: the tools of the running CCMOD host (built-ins + whatever plugins registered) over local HTTP.

    server = ToolServer(host, state_dir)      # host = ccmod_sdk.Host
    server.start()                            # 127.0.0.1:<random port>, token in <state_dir>/toolserver.json
    ...
    server.stop()

    GET  /tools                 -> {"tools": [{name, description, inputSchema}, ...]}
    POST /call {"name", "arguments"} -> {"ok": true, "result": ...} | {"ok": false, "error": ...}

Local only: it binds 127.0.0.1 and every request needs the token from toolserver.json (readable by this Windows user).
`ccmod_mcp.py` is the MCP (stdio) front end for it. Nothing here touches account, Pro, watermark or licensing.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .context import Engine, UI


def builtin_tools(host) -> dict[str, dict]:
    """Tools every CCMOD host offers (they use the host's backend directly; plugins add their own via ctx.tools)."""
    sys_ctx = types.SimpleNamespace(backend=host.backend)
    engine, ui = Engine(sys_ctx), UI(sys_ctx)

    def tool(name, description, fn, properties=None, required=()):
        return {"name": name, "description": description, "fn": fn, "plugin": "ccmod",
                "schema": {"type": "object", "properties": properties or {}, "required": list(required)}}

    tools = [
        tool("ccmod.plugins", "List loaded CCMOD plugins with their enabled state and last error.", host.summary),
        tool("ccmod.playhead", "Current playhead position in seconds and the timeline length.",
             lambda: {"playhead_seconds": engine.playhead_seconds(), "timeline_seconds": engine.timeline_duration_seconds()}),
        tool("ccmod.seek", "Move the playhead to a time in seconds.", lambda seconds: engine.seek(float(seconds)),
             {"seconds": {"type": "number"}}, ["seconds"]),
        tool("ccmod.ui_get", "Read a property of a live CapCut UI object (objectName or class name).",
             lambda selector, prop: ui.get_prop(selector, prop), {"selector": {"type": "string"}, "prop": {"type": "string"}}, ["selector", "prop"]),
        tool("ccmod.ui_click", "Click a live CapCut UI item by objectName.", lambda selector: ui.click(selector),
             {"selector": {"type": "string"}}, ["selector"]),
        tool("ccmod.engine_objects", "Class names of CapCut's live view-model objects.", lambda: engine.list_objects()),
    ]
    return {t["name"]: t for t in tools}


class ToolServer:
    def __init__(self, host, state_dir: Path | str):
        self.host = host
        self.state_dir = Path(state_dir)
        self.token = secrets.token_hex(16)
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None
        self.builtins = builtin_tools(host)

    # ---- the tool table (built-ins + plugin-registered) ----
    def tools(self) -> dict[str, dict]:
        return {**self.builtins, **self.host.tools}

    def list_tools(self) -> list[dict]:
        return [{"name": t["name"], "description": t["description"], "inputSchema": t["schema"]} for t in self.tools().values()]

    def call(self, name: str, arguments: dict | None) -> dict:
        t = self.tools().get(name)
        if t is None:
            return {"ok": False, "error": f"unknown tool {name!r}"}
        try:
            return {"ok": True, "result": t["fn"](**(arguments or {}))}
        except Exception as e:                                     # a broken plugin tool must not take the server down
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---- http ----
    @property
    def info_file(self) -> Path:
        return self.state_dir / "toolserver.json"

    def start(self) -> int:
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _auth(self) -> bool:
                if self.headers.get("X-CCMOD-Token") == server.token:
                    return True
                self._send(401, {"ok": False, "error": "bad token"})
                return False

            def _send(self, code: int, obj) -> None:
                data = json.dumps(obj, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self._auth():
                    self._send(200, {"tools": server.list_tools()} if self.path == "/tools" else {"ok": False, "error": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                try:
                    req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    self._send(200, server.call(req.get("name", ""), req.get("arguments")))
                except ValueError:
                    self._send(400, {"ok": False, "error": "bad json"})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="ccmod-toolserver", daemon=True).start()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.info_file.write_text(json.dumps({"port": self.port, "token": self.token, "pid": os.getpid()}), encoding="utf-8")
        return self.port

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
        try:
            self.info_file.unlink()
        except OSError:
            pass
