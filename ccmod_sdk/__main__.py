"""ccmod SDK command line.

    python -m ccmod_sdk list                      installed plugins (and why any were skipped)
    python -m ccmod_sdk validate <plugin folder>  check a plugin.json
    python -m ccmod_sdk new <id> [--dir plugins]  scaffold a new plugin
    python -m ccmod_sdk run [--fake]              load plugins against the running CapCut (or a fake backend)
    python -m ccmod_sdk enable|disable <id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import FakeBackend, FridaBackend, Host, ManifestError, PERMISSIONS, SDK_VERSION
from . import manifest as mf

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
DATA = ROOT / "plugin-state"

TEMPLATE_JSON = {
    "id": "", "name": "", "version": "0.1.0", "author": "", "description": "",
    "ccmod": ">=0.1", "capcut": ["*"], "entry": "main.py", "provides": ["ui"], "permissions": ["ui"],
}
TEMPLATE_PY = '''from ccmod_sdk import Plugin


class {cls}(Plugin):
    """{name}"""

    def on_load(self):
        self.ctx.log.info("{name} loaded")

    def on_editor_open(self):
        # Example: add a button. `ctx.ui.inject_qml(parent_selector, qml_text)`
        pass
'''


def _host(fake: bool) -> Host:
    import ccversion
    b = ccversion.pick()
    backend = FakeBackend() if fake else FridaBackend()
    return Host(backend, PLUGINS, DATA, capcut_version=b.version if b else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ccmod_sdk")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    v = sub.add_parser("validate"); v.add_argument("folder")
    n = sub.add_parser("new"); n.add_argument("id"); n.add_argument("--dir", default=str(PLUGINS))
    r = sub.add_parser("run"); r.add_argument("--fake", action="store_true")
    for c in ("enable", "disable"):
        e = sub.add_parser(c); e.add_argument("id")
    sub.add_parser("permissions")
    a = ap.parse_args(argv)

    if a.cmd in (None, "list"):
        h = Host(FakeBackend(), PLUGINS, DATA)
        ms = h.discover()
        print(f"ccmod SDK {SDK_VERSION} - plugins in {PLUGINS}")
        for m in ms:
            state = "on " if h.is_enabled(m.id) else "off"
            print(f"  [{state}] {m.id:<24} {m.version:<8} perms={m.permissions}  {m.name}")
        for name, why in h.skipped.items():
            print(f"  [skip] {name}: {why}")
        if not ms and not h.skipped:
            print("  (none)")
        return 0
    if a.cmd == "validate":
        try:
            m = mf.load(Path(a.folder))
        except ManifestError as e:
            print(f"INVALID: {e}"); return 1
        print(f"OK: {m.id} {m.version}  permissions={m.permissions}  provides={m.provides}")
        return 0
    if a.cmd == "permissions":
        for k, d in PERMISSIONS.items():
            print(f"  {k:<8} {d}")
        return 0
    if a.cmd == "new":
        pid = a.id
        d = Path(a.dir) / pid
        data = dict(TEMPLATE_JSON, id=pid, name=pid.replace("-", " ").title())
        try:
            mf.parse(data)
        except ManifestError as e:
            print(f"bad id: {e}"); return 1
        if d.exists():
            print(f"{d} already exists"); return 1
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        cls = "".join(p.capitalize() for p in pid.replace(".", "-").replace("_", "-").split("-")) or "MyPlugin"
        (d / "main.py").write_text(TEMPLATE_PY.format(cls=cls, name=data["name"]), encoding="utf-8")
        print(f"created {d}"); return 0
    if a.cmd in ("enable", "disable"):
        _host(True).set_enabled(a.id, a.cmd == "enable"); print(f"{a.id}: {a.cmd}d"); return 0
    if a.cmd == "run":
        h = _host(a.fake)
        ids = h.load_all()
        print(f"loaded {len(ids)} plugin(s): {ids}")
        for s in h.summary():
            print("  ", s)
        for name, why in h.skipped.items():
            print(f"  [skip] {name}: {why}")
        h.emit("editor_open")
        if not a.fake:
            print("running; Ctrl+C to stop")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        h.unload_all()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
