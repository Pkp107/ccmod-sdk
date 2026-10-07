"""Local redirect layer: answer CapCut's server requests from local files (or a Python function).

CapCut runs on this PC, so a request it would send to a server can be re-pointed at a tiny local HTTP server and
answered with whatever we want — a complete catalog response with extra tiles, a modified resource list, a plugin's
own content. This module is the pure-Python half (rules, matching, the server). The process-side half rewrites the URL
CapCut passes to Cronet (`Cronet_UrlRequest_InitWithParams`) — see scratch/ccmod_netredirect.py.

Rules live in ccmod-redirects.json (written by `ctx.network.redirect`):
    [{"plugin": "my-plugin", "pattern": "*get_panel_info*", "file": "C:/.../panel.json"}]
A pattern is a case-insensitive glob (* ?) against the FULL original URL.

    srv = RedirectServer(rules_file); port = srv.start()
    url = srv.local_url("https://api.example/get_panel_info?x=1")  ->  http://127.0.0.1:<port>/r?u=<urlencoded>
    # CapCut requests that URL; the server finds the matching rule and returns its file.
"""
from __future__ import annotations

import fnmatch
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

Transform = Callable[[str, bytes], bytes]          # (original_url, request_body) -> response body
ProxyTransform = Callable[[str, bytes, bytes], bytes]   # (original_url, request_body, UPSTREAM response body) -> response body


def match(pattern: str, url: str) -> bool:
    return fnmatch.fnmatchcase(url.lower(), pattern.lower())


def load_rules(rules_file: Path) -> list[dict]:
    try:
        data = json.loads(Path(rules_file).read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict) and "pattern" in r]
    except (OSError, json.JSONDecodeError):
        return []


def find_rule(rules: list[dict], url: str) -> dict | None:
    for r in reversed(rules):                      # later rules win
        if match(r["pattern"], url):
            return r
    return None


class RedirectServer:
    def __init__(self, rules_file: Path, host: str = "127.0.0.1", port: int = 0):
        self.rules_file = Path(rules_file)
        self.host, self.port = host, port
        self.transforms: list[tuple[str, Transform]] = []
        self.proxies: list[tuple[str, ProxyTransform]] = []   # forward to the real server, then rewrite the reply
        self.upstream_timeout = 20.0
        self.state_dir = self.rules_file.parent / "plugin-state-live" / "_catalog"
        self.assets_dir = self.rules_file.parent / "ccmod-assets"      # editable tile covers etc.: served at /asset/<name>
        self.hits: list[tuple[str, str]] = []      # (original url, served from)
        self._srv: ThreadingHTTPServer | None = None

    # ---- in-process transforms (plugins may register a function instead of a file) ----
    def add_transform(self, pattern: str, fn: Transform) -> None:
        self.transforms.append((pattern, fn))

    def add_proxy(self, pattern: str, fn: ProxyTransform) -> None:
        """Pass matching requests to the REAL server unchanged, then let `fn` rewrite the response body.
        This is how a plugin adds categories/tiles to a live catalog response without replacing all of it."""
        self.proxies.append((pattern, fn))

    def _upstream(self, url: str, method: str, headers: dict, body: bytes) -> tuple[bytes, str]:
        import urllib.request
        from urllib.parse import quote
        url = quote(url, safe="%:/?#[]@!$&'()*+,;=-._~")        # CapCut's URLs carry raw spaces (cpu=13th Gen Intel...); keep existing %XX
        skip = {"host", "content-length", "accept-encoding", "connection", "transfer-encoding"}
        h = {k: v for k, v in headers.items() if k.lower() not in skip}
        h["Accept-Encoding"] = "identity"                      # we rewrite the body, so ask for it uncompressed
        req = urllib.request.Request(url, data=body if method == "POST" else None, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=self.upstream_timeout) as r:
            return r.read(), r.headers.get("Content-Type", "application/json")

    def _debug_append(self, name: str, text: str) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_dir / name, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def _debug_dump(self, name: str, data: bytes) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / name).write_bytes(data)
        except OSError:
            pass

    def _declarative(self, url: str) -> dict | None:
        r = find_rule(load_rules(self.rules_file), url)
        return r["proxy"] if r and isinstance(r.get("proxy"), dict) else None

    def resolve_proxy(self, url: str, method: str, headers: dict, body: bytes) -> tuple[bytes, str] | None:
        spec = self._declarative(url)
        if spec is not None:
            keep = {k: v for k, v in headers.items() if k.lower() in ("content-type", "x-tt-logid", "x-ss-stub")}
            self._debug_append("requests.log", "%s %s" % (method, url[:140]) + chr(10) + "  H: " + json.dumps(keep) + chr(10) + "  B: " + repr(body[:600]) + chr(10))
            from .catalog_rules import CatalogProxy
            cp = CatalogProxy(self.state_dir, asset_base=f"http://{self.host}:{self.port}/asset/", assets_dir=self.assets_dir)
            via = cp.via(spec, body)
            if via is not None:                                  # ask the REAL server about a real category, then swap in our tiles
                try:
                    data, ctype = self._upstream(url, method, headers, via[0])
                    out = cp._override_md5(cp.apply_via(via[1], data))
                    self.hits.append((url, "serve_via"))
                    self._debug_dump("served_via.json", out)
                    return out, ctype
                except Exception as e:
                    self.hits.append((url, f"via-error:{type(e).__name__}"))
                    return None
            if cp.wants_local(spec, body):                       # our synthetic category: answer locally, no upstream
                out = cp.serve_local(spec, body)
                if out is not None:
                    self.hits.append((url, "serve_category"))
                    self._debug_dump("served_category.json", out)
                    return out, "application/json"
            try:
                data, ctype = self._upstream(url, method, headers, body)
            except Exception as e:
                self.hits.append((url, f"upstream-error:{type(e).__name__}"))
                return None
            try:
                out = cp.rewrite(spec, url, body, data)
                self.hits.append((url, "catalog-rule"))
                if "get_panel_info" in url:
                    self._debug_dump("panel_info_rewritten.json", out)
                return out, ctype
            except Exception as e:
                self.hits.append((url, f"catalog-error:{type(e).__name__}"))
                return data, ctype
        for pat, fn in reversed(self.proxies):
            if match(pat, url):
                try:
                    data, ctype = self._upstream(url, method, headers, body)
                except Exception as e:
                    self.hits.append((url, f"upstream-error:{type(e).__name__}"))
                    return None
                try:
                    out = fn(url, body, data)
                    self.hits.append((url, f"proxy:{pat}"))
                    return out, ctype
                except Exception as e:                           # a broken plugin must not break CapCut: pass the original through
                    self.hits.append((url, f"proxy-error:{type(e).__name__}"))
                    return data, ctype
        return None

    def resolve(self, url: str, body: bytes = b"") -> tuple[bytes, str] | None:
        """(response bytes, content-type) for an original URL, or None if no rule matches."""
        for pat, fn in reversed(self.transforms):
            if match(pat, url):
                self.hits.append((url, f"transform:{pat}"))
                return fn(url, body), "application/json"
        r = find_rule(load_rules(self.rules_file), url)
        if r and r.get("file"):
            p = Path(r["file"])
            if p.exists():
                self.hits.append((url, str(p)))
                return p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/json"
        return None

    def should_redirect(self, url: str) -> bool:
        return any(match(p, url) for p, _ in self.transforms) or any(match(p, url) for p, _ in self.proxies) or find_rule(load_rules(self.rules_file), url) is not None

    def local_url(self, original: str) -> str:
        return f"http://{self.host}:{self.port}/r?u={quote(original, safe='')}"

    # ---- server ----
    def start(self) -> int:
        outer = self

        class H(BaseHTTPRequestHandler):
            def _serve(self):
                if self.path.startswith("/asset/"):
                    name = Path(urlparse(self.path).path[len("/asset/"):]).name        # no path traversal: bare file name only
                    f = outer.assets_dir / name
                    if not f.is_file():
                        self.send_response(404); self.end_headers(); return
                    data = f.read_bytes(); ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
                    self.end_headers(); self.wfile.write(data); return
                q = parse_qs(urlparse(self.path).query)
                orig = (q.get("u") or [""])[0]
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                res = outer.resolve_proxy(orig, self.command, dict(self.headers.items()), body) or outer.resolve(orig, body)
                if res is None:
                    self.send_response(404); self.end_headers(); return
                data, ctype = res
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _serve

            def log_message(self, *a):             # keep the console quiet
                pass

        self._srv = ThreadingHTTPServer((self.host, self.port), H)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self.port

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown(); self._srv.server_close(); self._srv = None
