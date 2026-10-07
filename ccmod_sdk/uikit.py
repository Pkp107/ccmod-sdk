"""UI toolkit: floating panels with CapCut-styled controls, described in Python and rendered as real QML inside the editor.

    panel = ctx.ui.panel("tools", "My tools", [
        {"type": "label",    "text": "Glow settings"},
        {"type": "slider",   "id": "radius", "label": "Radius", "min": 0, "max": 50, "value": 12, "step": 1},
        {"type": "toggle",   "id": "bright", "label": "Bright pass only", "value": True},
        {"type": "dropdown", "id": "mode",   "label": "Mode", "options": ["Screen", "Add", "Soft"], "value": "Screen"},
        {"type": "text",     "id": "name",   "label": "Name", "value": "glow"},
        {"type": "button",   "id": "go",     "label": "Apply"},
    ], on_change=lambda id, value: print(id, value), x=60, y=80)

    panel.get("radius"); panel.set("radius", 20); panel.show(); panel.hide(); panel.close()

Every control reports changes to `on_change(id, value)` on a background thread (button presses report `True`). The panel is draggable by its
title bar and has a close button. Values are polled about four times a second, the same mechanism as `ctx.ui.add_button`.
Nothing in a spec is executed: text is escaped into QML string literals and numbers are checked.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

TYPES = ("label", "slider", "toggle", "dropdown", "text", "button", "separator")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
MAX_WIDGETS = 40

# CapCut's own palette
BG, HEADER, FIELD, BORDER, TEXT, MUTED, ACCENT = "#262626", "#1c1c1c", "#303030", "#3b3b3b", "#ffffff", "#9a9a9a", "#00c1cd"


class UiError(ValueError):
    pass


def _q(s: Any) -> str:
    """A QML/JS string literal for any text (JSON string syntax is valid QML)."""
    return json.dumps(str(s), ensure_ascii=True)


def _num(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise UiError(f"{what} must be a number") from None
    if f != f or abs(f) > 1e9:
        raise UiError(f"{what} is out of range")
    return f


def validate(widgets: list[dict]) -> list[dict]:
    if not isinstance(widgets, list) or not widgets or len(widgets) > MAX_WIDGETS:
        raise UiError(f"a panel needs 1 to {MAX_WIDGETS} widgets")
    seen: set[str] = set()
    out = []
    for w in widgets:
        t = w.get("type")
        if t not in TYPES:
            raise UiError(f"unknown widget type {t!r}; use one of {TYPES}")
        w = dict(w)
        if t not in ("label", "separator"):
            wid = w.get("id")
            if not isinstance(wid, str) or not _ID.match(wid):
                raise UiError(f"{t} needs an 'id' (lowercase letters, digits, underscore): got {wid!r}")
            if wid in seen:
                raise UiError(f"duplicate widget id {wid!r}")
            seen.add(wid)
        if t == "slider":
            lo, hi = _num(w.get("min", 0), "slider min"), _num(w.get("max", 1), "slider max")
            if hi <= lo:
                raise UiError("slider max must be greater than min")
            w["min"], w["max"] = lo, hi
            w["value"] = min(max(_num(w.get("value", lo), "slider value"), lo), hi)
            w["step"] = _num(w.get("step", 0), "slider step")
            if w["step"] < 0:
                raise UiError("slider step cannot be negative")
        elif t == "dropdown":
            opts = w.get("options")
            if not isinstance(opts, list) or not opts or len(opts) > 50:
                raise UiError("dropdown needs 1 to 50 options")
            w["options"] = [str(o) for o in opts]
            w["value"] = str(w.get("value", w["options"][0]))
            if w["value"] not in w["options"]:
                raise UiError(f"dropdown value {w['value']!r} is not one of its options")
        elif t == "toggle":
            w["value"] = bool(w.get("value", False))
        elif t == "text":
            w["value"] = str(w.get("value", ""))[:500]
        out.append(w)
    return out


def object_name(plugin_id: str, panel_id: str, widget_id: str = "") -> str:
    base = f"ccmodUi_{plugin_id.replace('-', '_').replace('.', '_')}_{panel_id}"
    return f"{base}_{widget_id}" if widget_id else base


def _widget_qml(w: dict, name: str, y: int) -> tuple[str, int]:
    """(qml, height) for one widget placed at vertical offset y."""
    t = w["type"]
    lab = _q(w.get("label", ""))
    if t == "label":
        return (f'Text {{ x: 12; y: {y}; width: parent.width - 24; text: {_q(w.get("text", ""))}; color: "{MUTED}"; font.pixelSize: 12; wrapMode: Text.Wrap }}', 24)
    if t == "separator":
        return (f'Rectangle {{ x: 12; y: {y + 6}; width: parent.width - 24; height: 1; color: "{BORDER}" }}', 14)
    if t == "button":
        return (f'''Rectangle {{ objectName: "{name}"; property int value: 0; x: 12; y: {y}; width: parent.width - 24; height: 30; radius: 6
    color: bma{name}.containsPress ? "{BORDER}" : (bma{name}.containsMouse ? "{FIELD}" : "{HEADER}"); border.color: "{BORDER}"
    Text {{ anchors.centerIn: parent; text: {lab}; color: "{TEXT}"; font.pixelSize: 12 }}
    MouseArea {{ id: bma{name}; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.value = parent.value + 1 }} }}''', 38)
    if t == "toggle":
        return (f'''Item {{ objectName: "{name}"; property bool value: {str(w["value"]).lower()}; x: 12; y: {y}; width: parent.width - 24; height: 26
    Text {{ text: {lab}; color: "{TEXT}"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }}
    Rectangle {{ width: 36; height: 18; radius: 9; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; color: parent.value ? "{ACCENT}" : "{FIELD}"
        Rectangle {{ width: 14; height: 14; radius: 7; y: 2; x: parent.parent.value ? 20 : 2; color: "{TEXT}" }} }}
    MouseArea {{ anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.value = !parent.value }} }}''', 32)
    if t == "slider":
        lo, hi, step = w["min"], w["max"], w["step"]
        return (f'''Item {{ objectName: "{name}"; property real value: {w["value"]}; x: 12; y: {y}; width: parent.width - 24; height: 44
    property real lo: {lo}; property real hi: {hi}; property real step: {step}
    Text {{ text: {lab}; color: "{TEXT}"; font.pixelSize: 12 }}
    Text {{ text: (Math.round(parent.value * 100) / 100).toString(); color: "{MUTED}"; font.pixelSize: 12; anchors.right: parent.right }}
    Rectangle {{ x: 0; y: 26; width: parent.width; height: 4; radius: 2; color: "{FIELD}"
        Rectangle {{ width: parent.width * (parent.parent.value - parent.parent.lo) / (parent.parent.hi - parent.parent.lo); height: parent.height; radius: 2; color: "{ACCENT}" }}
        Rectangle {{ width: 14; height: 14; radius: 7; color: "{TEXT}"; y: -5
            x: parent.width * (parent.parent.value - parent.parent.lo) / (parent.parent.hi - parent.parent.lo) - 7 }} }}
    MouseArea {{ x: 0; y: 16; width: parent.width; height: 28; cursorShape: Qt.PointingHandCursor
        function setFrom(mx) {{ var k = Math.max(0, Math.min(1, mx / width)); var v = parent.lo + k * (parent.hi - parent.lo);
            if (parent.step > 0) v = Math.round(v / parent.step) * parent.step; parent.value = Math.max(parent.lo, Math.min(parent.hi, v)); }}
        onPressed: (mouse) => setFrom(mouse.x); onPositionChanged: (mouse) => {{ if (pressed) setFrom(mouse.x) }} }} }}''', 50)
    if t == "dropdown":
        opts = json.dumps(w["options"])
        n = len(w["options"])
        return (f'''Item {{ id: {name}; objectName: "{name}"; property string value: {_q(w["value"])}; property var options: {opts}; property bool open: false
    x: 12; y: {y}; width: parent.width - 24; height: 46; z: open ? 100 : 0
    Text {{ text: {lab}; color: "{TEXT}"; font.pixelSize: 12 }}
    Rectangle {{ y: 18; width: parent.width; height: 26; radius: 6; color: "{FIELD}"; border.color: "{BORDER}"
        Text {{ x: 8; anchors.verticalCenter: parent.verticalCenter; text: parent.parent.value; color: "{TEXT}"; font.pixelSize: 12 }}
        Text {{ anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "v"; color: "{MUTED}"; font.pixelSize: 11 }}
        MouseArea {{ anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.parent.open = !parent.parent.open }} }}
    Rectangle {{ visible: parent.open; y: 46; width: parent.width; height: {min(n, 8) * 26}; radius: 6; color: "{HEADER}"; border.color: "{BORDER}"; clip: true
        Column {{ Repeater {{ model: parent.parent.parent.options
            Rectangle {{ width: parent.parent.width; height: 26; color: opma.containsMouse ? "{FIELD}" : "transparent"
                Text {{ x: 8; anchors.verticalCenter: parent.verticalCenter; text: modelData; color: "{TEXT}"; font.pixelSize: 12 }}
                MouseArea {{ id: opma; anchors.fill: parent; hoverEnabled: true; onClicked: {{ {name}.value = modelData; {name}.open = false }} }} }} }} }} }} }}''', 52)
    # text
    return (f'''Item {{ objectName: "{name}"; property string value: {_q(w["value"])}; x: 12; y: {y}; width: parent.width - 24; height: 46
    Text {{ text: {lab}; color: "{TEXT}"; font.pixelSize: 12 }}
    Rectangle {{ y: 18; width: parent.width; height: 26; radius: 6; color: "{FIELD}"; border.color: "{BORDER}"
        TextInput {{ x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; color: "{TEXT}"; font.pixelSize: 12; clip: true
            text: parent.parent.value; onTextChanged: parent.parent.value = text }} }} }}''', 52)


def build_panel_qml(plugin_id: str, panel_id: str, title: str, widgets: list[dict], x: int = 80, y: int = 80, width: int = 280) -> str:
    """QML for a floating, draggable panel. `widgets` must already be validated."""
    pname = object_name(plugin_id, panel_id)
    body, y_off = [], 40
    for w in widgets:
        wname = object_name(plugin_id, panel_id, w.get("id", "")) if w.get("id") else ""
        q, h = _widget_qml(w, wname, y_off)
        body.append(q)
        y_off += h
    height = y_off + 12
    return f'''import QtQuick 2.15
Rectangle {{
    objectName: "{pname}"
    x: {int(x)}; y: {int(y)}; width: {int(width)}; height: {height}; z: 99999; radius: 10; color: "{BG}"; border.color: "{BORDER}"
    Rectangle {{ x: 0; y: 0; width: parent.width; height: 32; radius: 10; color: "{HEADER}"
        Rectangle {{ y: 20; width: parent.width; height: 12; color: "{HEADER}" }}
        Text {{ x: 12; anchors.verticalCenter: parent.verticalCenter; text: {_q(title)}; color: "{TEXT}"; font.pixelSize: 13; font.bold: true }}
        Text {{ anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "x"; color: "{MUTED}"; font.pixelSize: 14
            MouseArea {{ anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: parent.parent.parent.visible = false }} }}
        MouseArea {{ anchors.fill: parent; anchors.rightMargin: 30; drag.target: parent.parent; cursorShape: Qt.SizeAllCursor }} }}
    {chr(10).join(body)}
}}
'''


class Panel:
    """A live panel inside the editor. Created by `ctx.ui.panel(...)`."""

    def __init__(self, ctx, panel_id: str, title: str, widgets: list[dict], on_change: Callable[[str, Any], None] | None,
                 x: int, y: int, width: int, parent: str):
        self._ctx = ctx
        self.id = panel_id
        self.title = title
        self.widgets = validate(widgets)
        self.on_change = on_change
        self.parent, self.x, self.y, self.width = parent, x, y, width
        self._types = {w["id"]: w["type"] for w in self.widgets if "id" in w}
        self._last: dict[str, Any] = {w["id"]: (0 if w["type"] == "button" else w["value"]) for w in self.widgets if "id" in w}
        self.name = object_name(ctx.manifest.id, panel_id)
        self.created = False

    def _wname(self, wid: str) -> str:
        return object_name(self._ctx.manifest.id, self.id, wid)

    def create(self) -> bool:
        """Inject the panel (idempotent). False when the editor doesn't exist yet."""
        b = self._ctx.backend
        existing = str(b.get_prop(self.name, "visible") or "")
        if existing and "not found" not in existing.lower() and "error" not in existing.lower():
            self.created = True
            self._ctx._register_panel(self)
            return True
        qml = build_panel_qml(self._ctx.manifest.id, self.id, self.title, self.widgets, self.x, self.y, self.width)
        res = self._ctx.ui.inject_qml(self.parent, qml)
        if "not found" in str(res).lower():
            return False
        self.created = True
        self._ctx._register_panel(self)
        return True

    def get(self, widget_id: str):
        self._known(widget_id)
        return self._read(widget_id)

    def set(self, widget_id: str, value) -> None:
        self._known(widget_id)
        if self._types[widget_id] == "button":
            raise UiError("buttons have no value to set")
        if self._types[widget_id] == "toggle":
            value = "true" if value else "false"
        self._ctx.backend.set_prop(self._wname(widget_id), "value", str(value))
        self._last[widget_id] = self._coerce(widget_id, value if self._types[widget_id] != "toggle" else value == "true")

    def show(self) -> None:
        self._ctx.backend.set_prop(self.name, "visible", "true")

    def hide(self) -> None:
        self._ctx.backend.set_prop(self.name, "visible", "false")

    def close(self) -> None:
        self.hide()
        self._ctx._panels.pop(self.name, None)

    def _known(self, widget_id: str) -> None:
        if widget_id not in self._types:
            raise UiError(f"no widget {widget_id!r} in panel {self.id!r}")

    def _coerce(self, wid: str, raw):
        t = self._types[wid]
        if t == "slider":
            return float(raw)
        if t == "toggle":
            return str(raw).lower() in ("true", "1")
        if t == "button":
            return int(float(raw))
        return str(raw)

    def _read(self, wid: str):
        raw = self._ctx.backend.get_prop(self._wname(wid), "value")
        if raw in (None, "") or "not found" in str(raw).lower():
            return self._last[wid]
        try:
            return self._coerce(wid, raw)
        except (TypeError, ValueError):
            return self._last[wid]

    def poll(self) -> None:
        """Compare every control to its last value and report changes (called by the context's poller)."""
        for wid, t in self._types.items():
            cur = self._read(wid)
            if t == "button":
                while cur > self._last[wid]:
                    self._last[wid] += 1
                    self._fire(wid, True)
                if cur < self._last[wid]:
                    self._last[wid] = cur
            elif cur != self._last[wid]:
                self._last[wid] = cur
                self._fire(wid, cur)

    def _fire(self, wid: str, value) -> None:
        if self.on_change:
            try:
                self.on_change(wid, value)
            except Exception:
                self._ctx.log.exception("panel %s handler failed for %s", self.id, wid)
