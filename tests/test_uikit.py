"""UI toolkit: spec validation, generated QML, and the poll -> on_change loop through a fake backend."""
import json
import textwrap
import time

import pytest

from ccmod_sdk import FakeBackend, Host, uikit
from ccmod_sdk.uikit import UiError

WIDGETS = [
    {"type": "label", "text": "Glow settings"},
    {"type": "slider", "id": "radius", "label": "Radius", "min": 0, "max": 50, "value": 12, "step": 1},
    {"type": "toggle", "id": "bright", "label": "Bright only", "value": True},
    {"type": "dropdown", "id": "mode", "label": "Mode", "options": ["Screen", "Add"], "value": "Add"},
    {"type": "text", "id": "name", "label": "Name", "value": "glow"},
    {"type": "separator"},
    {"type": "button", "id": "go", "label": "Apply"},
]


def _ctx(tmp_path, perms=("ui",)):
    d = tmp_path / "plugins" / "kit"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"id": "kit", "name": "Kit", "version": "1.0.0", "ccmod": ">=0.1", "capcut": ["*"],
                                               "entry": "main.py", "permissions": list(perms)}))
    (d / "main.py").write_text("from ccmod_sdk import Plugin\nclass P(Plugin):\n    pass\n")
    b = FakeBackend()
    h = Host(b, tmp_path / "plugins", tmp_path / "state")
    h.load_all()
    return h, b, h.plugins["kit"].ctx


def test_qml_contains_every_control_with_stable_names():
    qml = uikit.build_panel_qml("my-plugin", "tools", "My tools", uikit.validate(WIDGETS))
    for n in ("radius", "bright", "mode", "name", "go"):
        assert f'objectName: "ccmodUi_my_plugin_tools_{n}"' in qml
    assert 'objectName: "ccmodUi_my_plugin_tools"' in qml and qml.startswith("import QtQuick 2.15")
    assert qml.count("{") == qml.count("}")


def test_text_is_escaped_into_string_literals():
    evil = 'x"; Qt.quit(); "'
    qml = uikit.build_panel_qml("p1", "t", evil, uikit.validate([{"type": "label", "text": evil}, {"type": "button", "id": "b", "label": evil}]))
    assert 'Qt.quit(); "' not in qml.replace('\\"; Qt.quit(); \\"', "")           # only the escaped form remains
    assert json.dumps(evil) in qml


@pytest.mark.parametrize("bad", [
    [], [{"type": "nope"}], [{"type": "slider"}], [{"type": "slider", "id": "BAD ID"}], [{"type": "button", "id": "a"}, {"type": "button", "id": "a"}],
    [{"type": "slider", "id": "s", "min": 5, "max": 1}], [{"type": "slider", "id": "s", "min": "x"}],
    [{"type": "dropdown", "id": "d", "options": []}], [{"type": "dropdown", "id": "d", "options": ["a"], "value": "z"}],
    [{"type": "label", "text": "x"}] * 41,
])
def test_validation(bad):
    with pytest.raises(UiError):
        uikit.validate(bad)


def test_slider_value_is_clamped():
    w = uikit.validate([{"type": "slider", "id": "s", "min": 0, "max": 10, "value": 99}])[0]
    assert w["value"] == 10


def test_panel_injects_once_and_reports_changes(tmp_path):
    h, b, ctx = _ctx(tmp_path)
    seen = []
    panel = ctx.ui.panel("tools", "My tools", WIDGETS, on_change=lambda i, v: seen.append((i, v)))
    inj = [c for c in b.calls if c[0] == "inject_qml"]
    assert len(inj) == 1
    # the editor moves the controls: change values through the (fake) property store
    b.props[("ccmodUi_kit_tools_radius", "value")] = "30"
    b.props[("ccmodUi_kit_tools_bright", "value")] = "false"
    b.props[("ccmodUi_kit_tools_mode", "value")] = "Screen"
    b.props[("ccmodUi_kit_tools_go", "value")] = "2"
    deadline = time.time() + 3
    while time.time() < deadline and len(seen) < 5:
        time.sleep(0.05)
    assert ("radius", 30.0) in seen and ("bright", False) in seen and ("mode", "Screen") in seen
    assert seen.count(("go", True)) == 2                                   # two presses reported as two events
    assert panel.get("radius") == 30.0 and panel.get("mode") == "Screen"
    n = len(seen)
    time.sleep(0.6)
    assert len(seen) == n                                                  # no repeats without a change
    panel.set("radius", 5)
    assert b.props[("ccmodUi_kit_tools_radius", "value")] == "5"
    panel.set("bright", True)
    assert b.props[("ccmodUi_kit_tools_bright", "value")] == "true"
    with pytest.raises(UiError):
        panel.set("go", 1)
    with pytest.raises(UiError):
        panel.get("missing")
    panel.hide()
    assert b.props[("ccmodUi_kit_tools", "visible")] == "false"
    panel.close()
    h.unload_all()


def test_handler_exception_does_not_stop_polling(tmp_path):
    h, b, ctx = _ctx(tmp_path)
    calls = []

    def handler(i, v):
        calls.append(i)
        raise RuntimeError("boom")
    ctx.ui.panel("p", "P", [{"type": "text", "id": "a", "value": ""}, {"type": "text", "id": "b", "value": ""}], on_change=handler)
    b.props[("ccmodUi_kit_p_a", "value")] = "x"
    b.props[("ccmodUi_kit_p_b", "value")] = "y"
    deadline = time.time() + 3
    while time.time() < deadline and len(calls) < 2:
        time.sleep(0.05)
    assert sorted(calls) == ["a", "b"]
    h.unload_all()


def test_panel_needs_ui_permission(tmp_path):
    h, b, ctx = _ctx(tmp_path, perms=("files",))
    with pytest.raises(PermissionError):
        ctx.ui.panel("p", "P", [{"type": "label", "text": "x"}])
    h.unload_all()


def test_render_namespace_gives_an_agent_with_playhead_clock(tmp_path):
    from ccmod_sdk import renderagent
    h, b, ctx = _ctx(tmp_path, perms=("render", "engine"))
    a = ctx.render.agent(renderagent.FakeTransport())
    assert isinstance(a, renderagent.RenderAgent) and a.clock is not None
    h2, b2, ctx2 = _ctx(tmp_path / "x", perms=("render",))
    assert ctx2.render.agent(renderagent.FakeTransport()).clock is None
    h.unload_all(); h2.unload_all()


