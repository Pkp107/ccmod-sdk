"""Declarative external apps: spec validation, command building, ctx.apps run/import/tools."""
import json
import textwrap

import pytest

from ccmod_sdk import FakeBackend, Host, apps


def test_bundled_specs_are_valid():
    found = apps.discover()
    assert {"ffmpeg", "blender"} <= set(found)
    for s in found.values():
        apps.validate(s)


@pytest.mark.parametrize("bad", [
    {"id": "x"},
    {"id": "ok", "name": "n", "find": {"exe": "e"}, "commands": {}},
    {"id": "ok", "name": "n", "find": {"exe": "e"}, "commands": {"c": {"args": ["{nope}"]}}},
    {"id": "ok", "name": "n", "find": {"exe": "e"}, "commands": {"c": {"args": ["{o}"], "outputs": {"o": {"ext": "mp4"}}}}},
    {"id": "ok", "name": "n", "find": {"exe": "e"}, "commands": {"c": {"args": ["{a}"], "inputs": {"a": {"type": "blob"}}}}},
])
def test_validate_rejects_bad_specs(bad):
    with pytest.raises(apps.AppError):
        apps.validate(bad)


def test_build_command_fills_placeholders(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    cmd = apps.discover()["ffmpeg"]["commands"]["speed"]
    argv, outs = apps.build_command("ffmpeg", cmd, {"input": str(src), "factor": 2.5}, tmp_path / "out", "1")
    assert argv[0] == "ffmpeg" and "setpts=PTS/2.5" in argv and str(outs["output"]) == argv[-1]
    argv, _ = apps.build_command("ffmpeg", cmd, {"input": str(src)}, tmp_path / "out", "1")      # default factor
    assert "setpts=PTS/2" in argv
    with pytest.raises(apps.AppError, match="missing input"):
        apps.build_command("ffmpeg", cmd, {}, tmp_path, "1")
    with pytest.raises(apps.AppError, match="not found"):
        apps.build_command("ffmpeg", cmd, {"input": str(tmp_path / "nope.mp4")}, tmp_path, "1")
    with pytest.raises(apps.AppError, match="unknown input"):
        apps.build_command("ffmpeg", cmd, {"input": str(src), "bogus": 1}, tmp_path, "1")
    with pytest.raises(apps.AppError, match="number"):
        apps.build_command("ffmpeg", cmd, {"input": str(src), "factor": "fast"}, tmp_path, "1")


def _ctx(tmp_path, perms=("apps", "process", "media", "tools", "ui")):
    d = tmp_path / "plugins" / "ap"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"id": "ap", "name": "AP", "version": "1.0.0", "ccmod": ">=0.1", "capcut": ["*"],
                                               "entry": "main.py", "permissions": list(perms)}))
    (d / "main.py").write_text("from ccmod_sdk import Plugin\nclass P(Plugin):\n    pass\n")
    b = FakeBackend()
    h = Host(b, tmp_path / "plugins", tmp_path / "state")
    h.load_all()
    return h, b, h.plugins["ap"].ctx


# a tiny "app": python itself, copying a file (so no external install is needed to test the real run path)
COPY_SPEC = {"id": "copier", "name": "Copier", "find": {"exe": "python"},
             "commands": {"copy": {"description": "copy a file",
                                   "args": ["-c", "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])", "{src}", "{dst}"],
                                   "inputs": {"src": {"type": "file"}}, "outputs": {"dst": {"ext": ".txt", "import": True}}},
                          "fail": {"args": ["-c", "import sys; sys.exit(3)"]},
                          "nofile": {"args": ["-c", "pass", "{dst}"], "outputs": {"dst": {"ext": ".txt"}}}}}


def test_run_imports_output_and_reports(tmp_path):
    h, b, ctx = _ctx(tmp_path)
    ctx.apps.register(COPY_SPEC)
    src = tmp_path / "a.txt"
    src.write_text("hello")
    orig = b.get_prop
    b.get_prop = lambda sel, prop: "imported 1 via X" if prop == "report" else orig(sel, prop)
    res = ctx.apps.run("copier", "copy", src=str(src))
    assert res["ok"] and res["code"] == 0
    out = res["outputs"]["dst"]
    assert open(out).read() == "hello"
    assert res["imported"]["dst"].startswith("imported 1")
    assert any(c[0] == "inject_qml" for c in b.calls)
    h.unload_all()


def test_failure_missing_output_unknown_and_not_installed(tmp_path):
    h, b, ctx = _ctx(tmp_path)
    ctx.apps.register(COPY_SPEC)
    ctx.apps.register({"id": "ghost", "name": "Ghost", "find": {"exe": "definitely-not-installed-xyz", "env": "CCMOD_GHOST"},
                       "commands": {"go": {"args": ["--x"]}}})
    r = ctx.apps.run("copier", "fail")
    assert not r["ok"] and r["code"] == 3 and "code 3" in r["error"]
    r = ctx.apps.run("copier", "nofile")
    assert not r["ok"] and "did not create" in r["error"]
    r = ctx.apps.run("ghost", "go")
    assert not r["ok"] and "not found" in r["error"] and "CCMOD_GHOST" in r["error"]
    with pytest.raises(KeyError):
        ctx.apps.run("nope", "x")
    with pytest.raises(KeyError):
        ctx.apps.run("copier", "nope")
    listing = {a["id"]: a for a in ctx.apps.list()}
    assert listing["copier"]["installed"] and not listing["ghost"]["installed"]
    h.unload_all()


def test_expose_tools_registers_each_command(tmp_path):
    h, b, ctx = _ctx(tmp_path)
    ctx.apps.register(COPY_SPEC)
    names = ctx.apps.expose_tools("copier")
    assert "ap.copier_copy" in names and "ap.copier_fail" in names
    t = h.tools["ap.copier_copy"]
    assert t["schema"]["required"] == ["src"] and t["schema"]["properties"]["src"]["type"] == "string"
    assert h.tools["ap.copier_fail"]["fn"]()["code"] == 3
    h.unload_all()


def test_apps_needs_permission(tmp_path):
    h, b, ctx = _ctx(tmp_path, perms=("ui",))
    with pytest.raises(PermissionError):
        ctx.apps.list()
    h.unload_all()

