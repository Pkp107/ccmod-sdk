"""Render agent: script generation (syntax-checked with node when present), controller messaging, external feed memory."""
import json
import shutil
import struct
import subprocess
import time

import pytest

from ccmod_sdk import renderagent as ra


def test_script_embeds_config_and_is_valid_javascript(tmp_path):
    js = ra.build_script(history=True, hist_unit=13, ext={"name": "ccmod_feed_x", "width": 64, "height": 32}, ext_unit=12)
    assert '"histUnit": 13' in js and '"extUnit": 12' in js and "ccmod_feed_x" in js and "__CONFIG__" not in js
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    f = tmp_path / "agent.js"
    f.write_text("(function(){\n" + js + "\n})", encoding="utf-8")        # frida runs scripts as function bodies; check syntax only
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_same_texture_unit_rejected():
    with pytest.raises(ra.AgentError):
        ra.build_script(hist_unit=5, ext_unit=5)


def test_controller_posts_uniforms_and_history():
    t = ra.FakeTransport()
    a = ra.RenderAgent(t)
    a.set_uniform("u_amount", 0.5)                      # before start: queued and sent at start
    a.enable_history()
    a.start()
    assert '"history": true' in t.script
    assert {"type": "U", "name": "u_amount", "v": [0.5]} in t.sent
    a.set_uniform("u_color", [1, 0.5, 0])
    a.clear_uniform("u_amount")
    a.enable_history(False)
    assert {"type": "U", "name": "u_color", "v": [1.0, 0.5, 0.0]} in t.sent
    assert {"type": "U", "name": "u_amount", "v": None} in t.sent and {"type": "H", "on": False} in t.sent
    a.stop()
    assert t.stopped and not a.pids


@pytest.mark.parametrize("name,val", [("1bad", 1), ("a b", 1), ("ok", []), ("ok", [1, 2, 3, 4, 5]), ("x;y", 1)])
def test_bad_uniforms_rejected(name, val):
    a = ra.RenderAgent(ra.FakeTransport())
    with pytest.raises(ra.AgentError):
        a.set_uniform(name, val)


def test_drive_evaluates_formula_with_the_clock():
    t = ra.FakeTransport()
    now = {"v": 2.0}
    a = ra.RenderAgent(t, clock=lambda: now["v"])
    a.drive("iTime", "t * 10")
    a.start()
    deadline = time.time() + 2
    while time.time() < deadline and not any(m["name"] == "iTime" for m in t.sent):
        time.sleep(0.02)
    a.stop()
    assert {"type": "U", "name": "iTime", "v": [20.0]} in t.sent
    with pytest.raises(Exception):
        ra.RenderAgent(t).drive("x", "__import__('os')")


def test_stats_and_errors_are_collected():
    t = ra.FakeTransport()
    a = ra.RenderAgent(t)
    a.start()
    t.on_message({"t": "STATS", "pid": 7, "stats": {"over": 3}})
    t.on_message({"t": "ERR", "msg": "boom"})
    assert a.stats[7] == {"over": 3} and a.errors == ["boom"]
    a.stop()


def test_external_feed_writes_header_frames_and_checks_size():
    f = ra.ExternalFeed(4, 2)
    assert f.read_header() == (0, 4, 2)
    px = bytes(range(32))
    assert f.write(px) == 1 and f.write(px) == 2
    assert f.read_header() == (2, 4, 2) and bytes(f._buf[ra.FEED_HEADER:f.size]) == px
    with pytest.raises(ra.AgentError):
        f.write(b"short")
    with pytest.raises(ra.AgentError):
        ra.ExternalFeed(0, 10)
    assert f.spec() == {"name": f.name, "width": 4, "height": 2}
    f.close()


def test_feed_must_be_created_before_start():
    a = ra.RenderAgent(ra.FakeTransport())
    feed = a.external_feed(8, 8)
    a.start()
    assert json.dumps({"name": feed.name, "width": 8, "height": 8}, sort_keys=True)[1:-1].split(",")[0].strip('"') and feed.name in a.transport.script
    with pytest.raises(ra.AgentError):
        a.external_feed(8, 8)
    a.stop()
