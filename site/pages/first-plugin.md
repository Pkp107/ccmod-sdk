---
title: Your first plugin
section: Building
order: 10
---

# Your first plugin

A plugin is a folder in `plugins/` with a manifest and a Python entry file. We'll build one that adds a button which reads the playhead, a tool an AI can call, and some saved state.

## 1. Scaffold

```bash
python -m ccmod_sdk new my-plugin
```

creates `plugins/my-plugin/plugin.json` and `main.py`.

## 2. The manifest

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "author": "you",
  "description": "What it does, in one sentence.",
  "ccmod": ">=0.1",
  "capcut": ["8.9"],
  "entry": "main.py",
  "provides": ["ui", "tool"],
  "permissions": ["ui", "engine", "files", "tools"]
}
```

| Field | Notes |
|---|---|
| `id` | lowercase letters, digits, `.`, `_`, `-`; 2 to 63 chars |
| `version` | semver |
| `ccmod` | SDK version range your plugin needs |
| `capcut` | CapCut versions you tested, as prefixes (`"8.9"`). Effects and transitions are only proven on **8.9.1**; use `["*"]` for UI-only plugins that don't depend on the build |
| `provides` | any of `effect`, `transition`, `ui`, `theme`, `engine`, `tool`; shown to users |
| `permissions` | what the plugin may touch; see [permissions](sdk-reference.html#permissions). Undeclared namespaces raise `PermissionError` |

Validate any time: `python -m ccmod_sdk validate plugins/my-plugin`.

## 3. The code

```python
from ccmod_sdk import Plugin


class MyPlugin(Plugin):
    def on_load(self):
        # runs once when ccmod loads the plugin (CapCut may not be open yet)
        self.count = self.ctx.storage.read_json("state.json", {"clicks": 0})["clicks"]
        self.ctx.tools.register(
            "where_am_i", "Report the playhead position in seconds.", self.where,
            {"type": "object", "properties": {}})

    def on_editor_open(self):
        # runs each time an editor window appears; add_button is idempotent so calling it every time is fine
        self.ctx.ui.add_button("Where?", self.press, where="timeline-toolbar", id="where")

    def press(self):
        self.count += 1
        self.ctx.storage.write_json("state.json", {"clicks": self.count})
        t = self.ctx.engine.playhead_seconds()
        self.ctx.ui.set_button_label("where", f"{t:.1f}s")
        self.ctx.log.info("clicked %d times, playhead %.2fs", self.count, t)

    def where(self) -> dict:
        return {"seconds": self.ctx.engine.playhead_seconds()}
```

## 4. Run it

```bash
python ccmod_run.py
```

(or `python -m ccmod_sdk run` to attach plugins only, `python -m ccmod_sdk run --fake` to try without CapCut).

Click the button; the label shows the playhead, and an MCP client now has a `my-plugin__where_am_i` tool.

## Lifecycle hooks

| Hook | When |
|---|---|
| `on_load()` | Plugin loaded |
| `on_unload()` | ccmod shutting down or the plugin disabled; clean up here |
| `on_capcut_start()` | CapCut's process was found |
| `on_editor_open()` | An editor window appeared (the UI exists; inject QML here) |
| `on_project_open(project)` | A project opened |

A plugin that raises in a hook is disabled for the session and recorded in `host.errors`. It cannot take down CapCut integration or other plugins.

## Test without CapCut

```python
from ccmod_sdk import FakeBackend, Host

host = Host(FakeBackend(), "plugins", "plugin-state-test")
host.load_all()
host.plugins["my-plugin"].ctx.engine.playhead_seconds()
```

`FakeBackend` records every call (`backend.calls`) and keeps in-memory properties. Most of ccmod's own tests work this way.

## Raw QML (when a button isn't enough)

```python
self.ctx.ui.inject_qml("MainTimeLineToolBar_QMLTYPE", """
import QtQuick 2.15
Rectangle {
    objectName: "myBadge"
    x: 400; y: 6; width: 90; height: 24; radius: 12; z: 9999; color: "#00C8C8"
    Text { anchors.centerIn: parent; text: "Hello"; font.pixelSize: 12 }
}
""")
```

The first argument is a *selector*: a live QQuickItem class name or objectName. Discover them with `self.ctx.ui.inspect(type="QQuickRow")` and `self.ctx.engine.list_objects()`. See [SDK reference: ui](sdk-reference.html#ctxui).

!!! note "QML is live"
    Injected QML cannot be replaced once created; give objects unique `objectName`s, and change them with `ctx.ui.set_prop`. Restarting CapCut clears everything you injected.

## Next

- Add an [effect](making-effects.html), [transition](making-transitions.html) or [theme](making-themes.html).
- Call other programs: [External apps](external-apps.html).
