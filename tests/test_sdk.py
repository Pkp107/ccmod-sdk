"""CCMOD SDK tests — manifest validation, permission gating, plugin lifecycle and isolation (FakeBackend, no CapCut)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ccmod_sdk import FakeBackend, Host, ManifestError, Plugin, manifest as mf  # noqa: E402
from ccmod_sdk.__main__ import main as sdk_main  # noqa: E402


def make_plugin(root: Path, pid="demo", perms=("ui",), code="", capcut=("*",), ccmod=">=0.1", version="1.0.0"):
    d = root / pid
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({
        "id": pid, "name": pid.title(), "version": version, "ccmod": ccmod, "capcut": list(capcut),
        "entry": "main.py", "provides": ["ui"], "permissions": list(perms)}), encoding="utf-8")
    (d / "main.py").write_text(code or "from ccmod_sdk import Plugin\nclass P(Plugin):\n    pass\n", encoding="utf-8")
    return d


# ---------------- manifest ----------------
def test_manifest_ok():
    m = mf.parse({"id": "my-plugin", "name": "X", "version": "1.2.3", "permissions": ["ui", "engine"]})
    assert m.id == "my-plugin" and m.permissions == ["ui", "engine"] and m.capcut == ["*"]


@pytest.mark.parametrize("bad", [
    {"name": "x", "version": "1.0.0"},                                           # no id
    {"id": "Bad_ID", "name": "x", "version": "1.0.0"},                           # uppercase
    {"id": "ok", "name": "x", "version": "1.0"},                                 # not semver
    {"id": "ok", "name": "x", "version": "1.0.0", "permissions": ["root"]},      # unknown permission
    {"id": "ok", "name": "x", "version": "1.0.0", "provides": ["magic"]},
    {"id": "ok", "name": "x", "version": "1.0.0", "entry": "../evil.py"},        # path escape
    {"id": "ok", "name": "x", "version": "1.0.0", "surprise": 1},                # unknown field
    {"id": "ok", "name": "x", "version": "1.0.0", "capcut": []},
])
def test_manifest_rejects(bad):
    with pytest.raises(ManifestError):
        mf.parse(bad)


def test_version_constraints():
    assert mf._check_constraint(">=0.1", "0.1.0") and mf._check_constraint(">=0.1", "1.0.0")
    assert not mf._check_constraint(">=1.0", "0.9.9") and mf._check_constraint(">=0.1,<1", "0.5.0")
    assert not mf._check_constraint("<0.1", "0.1.0") and mf._check_constraint("*", "9.9.9")
    with pytest.raises(ManifestError):
        mf._check_constraint("~~1", "1.0.0")


def test_capcut_compat():
    m = mf.parse({"id": "ok", "name": "x", "version": "1.0.0", "capcut": ["8.9", "9.2"]})
    assert m.compatible_with_capcut("8.9.1.3802") and m.compatible_with_capcut("9.2.0.3931")
    assert not m.compatible_with_capcut("10.0.0.1")


# ---------------- loading / lifecycle ----------------
def test_discover_skips_invalid_and_incompatible(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "good")
    make_plugin(plugins, "oldcapcut", capcut=("7.0",))
    make_plugin(plugins, "needsnew", ccmod=">=99")
    bad = plugins / "broken"; bad.mkdir(); (bad / "plugin.json").write_text("{not json", encoding="utf-8")
    h = Host(FakeBackend(), plugins, tmp_path / "state", capcut_version="8.9.1.3802")
    ids = [m.id for m in h.discover()]
    assert ids == ["good"]
    assert set(h.skipped) == {"oldcapcut", "needsnew", "broken"}
    assert "invalid manifest" in h.skipped["broken"]


def test_lifecycle_hooks_run(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "life", code=(
        "from ccmod_sdk import Plugin\n"
        "class L(Plugin):\n"
        "    def on_load(self): self.ctx.storage_events = ['load']\n"
        "    def on_editor_open(self): self.ctx.storage_events.append('editor')\n"
        "    def on_unload(self): self.ctx.storage_events.append('unload')\n"))
    h = Host(FakeBackend(), plugins, tmp_path / "state")
    assert h.load_all() == ["life"]
    h.emit("editor_open")
    ctx = h.plugins["life"].ctx
    h.unload_all()
    assert ctx.storage_events == ["load", "editor", "unload"]


def test_crash_isolation(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "crasher", code=(
        "from ccmod_sdk import Plugin\n"
        "class C(Plugin):\n"
        "    def on_editor_open(self): raise RuntimeError('boom')\n"))
    make_plugin(plugins, "fine", code=(
        "from ccmod_sdk import Plugin\n"
        "class F(Plugin):\n"
        "    def on_editor_open(self): self.ctx.opened = True\n"))
    h = Host(FakeBackend(), plugins, tmp_path / "state")
    h.load_all()
    h.emit("editor_open")
    assert "boom" in h.errors["crasher"] and not h.plugins["crasher"].enabled
    assert h.plugins["fine"].ctx.opened is True and "fine" not in h.errors
    h.emit("editor_open")                      # a crashed plugin is not called again
    assert h.errors["crasher"].count("boom") >= 1


def test_import_failure_does_not_stop_others(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "syntaxerr", code="def (:\n")
    make_plugin(plugins, "ok")
    h = Host(FakeBackend(), plugins, tmp_path / "state")
    assert h.load_all() == ["ok"] and "syntaxerr" in h.errors


def test_enable_disable_persists(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "tog")
    h = Host(FakeBackend(), plugins, tmp_path / "state")
    h.load_all()
    h.set_enabled("tog", False)
    h2 = Host(FakeBackend(), plugins, tmp_path / "state")
    h2.load_all()
    assert not h2.plugins["tog"].enabled
    h2.set_enabled("tog", True)
    assert Host(FakeBackend(), plugins, tmp_path / "state").is_enabled("tog")


# ---------------- permissions ----------------
def test_permission_gate(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "narrow", perms=("ui",))
    h = Host(FakeBackend(), plugins, tmp_path / "state")
    h.load_all()
    ctx = h.plugins["narrow"].ctx
    ctx.ui.get_prop("X", "y")                  # allowed
    with pytest.raises(PermissionError, match="engine"):
        ctx.engine.invoke("A", "b")
    with pytest.raises(PermissionError):
        ctx.effects.library()
    with pytest.raises(PermissionError):
        ctx.network.rules()


def test_ui_inject_writes_qml(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "inj", perms=("ui",))
    be = FakeBackend()
    h = Host(be, plugins, tmp_path / "state"); h.load_all()
    h.plugins["inj"].ctx.ui.inject_qml("Toolbar", "Rectangle {}")
    assert ("inject_qml", "Toolbar", "Rectangle {}") in be.calls


def test_engine_playhead_and_seek(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "eng", perms=("engine",))
    be = FakeBackend()
    be.props[("MainTimeLineCursorViewModel", "centerX")] = "277"
    be.props[("MainTimeLineCanvasViewModel", "pixelSize")] = "1.385e-05"
    be.props[("MainTimeLineCanvasViewModel", "timelineDuration")] = "75916666"
    h = Host(be, plugins, tmp_path / "state"); h.load_all()
    e = h.plugins["eng"].ctx.engine
    assert e.playhead_seconds() == pytest.approx(20.0, abs=0.05)
    assert e.timeline_duration_seconds() == pytest.approx(75.916666, rel=1e-6)
    e.seek(12.5)
    assert ("invoke", "MainTimeLineCursorViewModel", "clickSeekByTime", "i:12500000") in be.calls
    assert e.list_objects() == ["MainTimeLineCursorViewModel", "MainTimeLineCanvasViewModel", "EffectTreeViewModel"]


def test_storage_is_sandboxed(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "store", perms=("files",))
    h = Host(FakeBackend(), plugins, tmp_path / "state"); h.load_all()
    s = h.plugins["store"].ctx.storage
    s.write_json("a.json", {"x": 1})
    assert s.read_json("a.json") == {"x": 1} and s.read_json("missing.json", 5) == 5
    with pytest.raises(PermissionError):
        s.write_json("../../escape.json", {})


def test_network_redirect_rules(tmp_path):
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "net", perms=("network",))
    h = Host(FakeBackend(), plugins, tmp_path / "state"); h.load_all()
    n = h.plugins["net"].ctx.network
    f = tmp_path / "panel.json"; f.write_text("{}")
    n.redirect("*get_panel_info*", f)
    n.redirect("*get_panel_info*", f)          # idempotent per (plugin, pattern)
    rules = n.rules()
    assert len(rules) == 1 and rules[0]["plugin"] == "net" and rules[0]["pattern"] == "*get_panel_info*"
    n.clear()
    assert n.rules() == []


# ---------------- CLI ----------------
def test_cli_validate_and_new(tmp_path, capsys):
    d = make_plugin(tmp_path / "p", "cli-ok")
    assert sdk_main(["validate", str(d)]) == 0
    assert sdk_main(["validate", str(tmp_path / "nope")]) == 1
    assert sdk_main(["new", "fresh-plugin", "--dir", str(tmp_path / "out")]) == 0
    assert sdk_main(["validate", str(tmp_path / "out" / "fresh-plugin")]) == 0
    assert sdk_main(["new", "Bad ID", "--dir", str(tmp_path / "out")]) == 1


def test_redirect_match_and_server(tmp_path):
    import urllib.request, urllib.error
    from ccmod_sdk.netredirect import RedirectServer, match, find_rule
    assert match("*get_panel_info*", "https://x.com/effect/api/GET_PANEL_INFO?a=1")
    assert not match("*get_panel_info*", "https://x.com/other")
    f = tmp_path / "panel.json"; f.write_text('{"ok": true, "extra": [1,2,3]}', encoding="utf-8")
    rules = tmp_path / "r.json"
    rules.write_text(json.dumps([{"plugin": "p", "pattern": "*get_panel_info*", "file": str(f)}]), encoding="utf-8")
    assert find_rule(json.loads(rules.read_text()), "https://x/get_panel_info")["plugin"] == "p"
    srv = RedirectServer(rules); srv.start()
    try:
        orig = "https://api.example/effect/get_panel_info?device=1"
        assert srv.should_redirect(orig) and not srv.should_redirect("https://api.example/login")
        body = urllib.request.urlopen(srv.local_url(orig), timeout=5).read()
        assert json.loads(body) == {"ok": True, "extra": [1, 2, 3]}          # response may be ANY size/shape
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(srv.local_url("https://api.example/login"), timeout=5)
        assert e.value.code == 404
        srv.add_transform("*mget_item*", lambda url, body: b'{"items": []}')
        assert json.loads(urllib.request.urlopen(srv.local_url("https://a/mget_item"), timeout=5).read()) == {"items": []}
        assert len(srv.hits) == 2
    finally:
        srv.stop()
