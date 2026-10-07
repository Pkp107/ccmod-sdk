---
title: UI toolkit
section: Building
order: 90
---

# UI toolkit

Build real panels inside CapCut's editor from Python, with controls styled to match CapCut. No QML needed.

```python
panel = self.ctx.ui.panel("tools", "Glow tools", [
    {"type": "label",    "text": "Glow settings"},
    {"type": "slider",   "id": "radius", "label": "Radius", "min": 0, "max": 50, "value": 12, "step": 1},
    {"type": "toggle",   "id": "bright", "label": "Bright pass only", "value": True},
    {"type": "dropdown", "id": "mode",   "label": "Mode", "options": ["Screen", "Add", "Soft"], "value": "Screen"},
    {"type": "text",     "id": "name",   "label": "Name", "value": "glow"},
    {"type": "separator"},
    {"type": "button",   "id": "go",     "label": "Apply"},
], on_change=self.changed, x=60, y=80)

def changed(self, widget_id, value):       # called on a background thread
    self.ctx.log.info("%s = %r", widget_id, value)
```

The panel floats over the editor, drags by its title bar and closes with the x. Values are checked about four times a second, like `add_button`.

| Widget | Fields | Reports |
|---|---|---|
| `label` | `text` | nothing |
| `separator` | none | nothing |
| `slider` | `id, label, min, max, value, step` | a float |
| `toggle` | `id, label, value` | a bool |
| `dropdown` | `id, label, options, value` | the chosen text |
| `text` | `id, label, value` | the text |
| `button` | `id, label` | `True` per press (two quick presses give two events) |

`panel.get(id)`, `panel.set(id, value)`, `panel.show()`, `panel.hide()`, `panel.close()`, and `panel.create()` to re-inject after the editor reopens (call it from `on_editor_open`). `UiError` is raised for bad specs (unknown type, duplicate id, a slider with `max <= min`, more than 40 widgets). Text is escaped into QML string literals, so a title like `x"; Qt.quit()` stays text.

## Verified

The generated QML is compiled with Qt 6 offscreen in the test suite (zero errors), and real mouse clicks on the slider, toggle, button and dropdown change their values as expected. The injection into CapCut's own scene uses the same route as `add_button`, which is proven on screen; seeing a *panel* inside CapCut has not been done yet.

## Not here yet

Tabs, docked panels using CapCut's own docking, workspaces (saved layouts), a graph editor and a node editor. For those, inject your own QML with `ctx.ui.inject_qml` today.
