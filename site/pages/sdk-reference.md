---
title: SDK reference
section: Reference
order: 10
---

# SDK reference

Every plugin gets `self.ctx`. Each namespace needs its permission in `plugin.json`. Using one you didn't declare raises `PermissionError("... needs the 'x' permission")`.

**Conventions.** "Selector" means a live Qt class name (`MainTimeLineCursorViewModel`) or an item's `objectName`. Calls that talk to CapCut return the **report string** CapCut's side produced, or raise if CapCut isn't attached. `ctx.engine`/`ctx.ui` calls made before an editor exists return an empty string or a message containing `not found`; they don't raise.

## Permissions

| Permission | Allows |
|---|---|
| `ui` | Inject QML (buttons, panels, tabs), read/write UI properties, themes |
| `engine` | Call CapCut controllers, seek the playhead, read engine state |
| `render` | Rewrite shaders / hook the render pipeline |
| `draft` | Read and modify project drafts (with backups) |
| `effects` | Install, list and apply ccmod effects and packs |
| `network` | Serve catalog rules / redirect CapCut's requests locally |
| `files` | Read/write inside the plugin's own data folder |
| `builds` | Inspect installed CapCut builds |
| `tools` | Expose tools to MCP clients and the tool server |
| `media` | Import files into CapCut's media pool |
| `process` | Run external programs |
| `apps` | Run external apps described by JSON specs and import their results |

`python -m ccmod_sdk permissions` prints the same list.

## Plugin hooks and events

```python
from ccmod_sdk import Plugin
class P(Plugin):
    def on_load(self): ...                  # plugin loaded; CapCut may not be open
    def on_unload(self): ...                # shutting down / disabled
    def on_capcut_start(self): ...          # CapCut's process found
    def on_editor_open(self): ...           # an editor window exists: inject UI here
    def on_project_open(self, project=""): ...
```

The same moments are delivered on the event bus as the strings `"capcut_start"`, `"editor_open"` and `"project_open"`:

```python
self.ctx.events.on("editor_open", lambda: self.ctx.log.info("editor is up"))
self.ctx.events.emit("my-event", 42)      # your own events; other plugins can listen
```

There are no other built-in events yet (no playhead or selection events; poll `ctx.engine`). An exception in a hook disables that plugin for the session and records the traceback in `host.errors`; other plugins keep running.

## ctx.ui  (`ui`)

| Call | Returns | Notes |
|---|---|---|
| `add_button(label, on_click, where="timeline-toolbar", id=None, icon=None, x=None, y=None, width=110, height=28)` | `bool` | `True` once the button exists, `False` if the place doesn't exist yet (no editor). Idempotent per `id`. `where`: `"timeline-toolbar"`, `"panel"`, `"tab-row"`, or any selector. `on_click()` runs on a background thread within about 0.2 s of the click. An exception in it is logged, not raised |
| `set_button_label(id, label)` | `None` | |
| `remove_button(id)` | `None` | hides it and stops handling clicks |
| `inject_qml(parent_selector, qml)` | `str` report | creates the item; fails silently with a `not found` report if the parent doesn't exist |
| `inject_qml_file(parent_selector, path)` | `str` | same, from a file |
| `get_prop(selector, prop)` | `str` | `""` or text containing `not found` if missing |
| `set_prop(selector, prop, value)` | `str` | value is stringified |
| `click(selector)` | `str` | clicks a live item by objectName |
| `find_tab_row()` | `str | None` | address like `0x1f2e...` of the top tab row |
| `inspect(type="", objectName="", limit=40)` | `dict` | live items matching a QML type prefix / objectName, as parsed JSON from the theme engine (`{"error": ...}` if unreadable). **Raises `RuntimeError` if the engine can't be injected (no editor open)**; takes about 0.5 s |
| `panel(panel_id, title, widgets, on_change=None, x=80, y=80, width=280, parent=...)` | `Panel` | floating panel of CapCut-styled controls; see [UI toolkit](ui-toolkit.html) |
| `themes()` | `list[dict]` | `id, name, description, preview, author, version` |
| `apply_theme(id)` / `revert_theme()` | `str` | |

```python
self.ctx.ui.add_button("Marker", self.add_marker, where="timeline-toolbar", id="marker")
self.ctx.ui.inject_qml("MainTimeLineToolBar_QMLTYPE", 'import QtQuick 2.15\nRectangle { objectName: "badge"; width: 40; height: 20; color: "#00d5e7" }')
```

## ctx.engine  (`engine`)

| Call | Returns | Notes |
|---|---|---|
| `invoke(selector, method, args="")` | `str` | call a slot on a live QObject. `args`: `i:123` int, `sl:a\|b` string list, bare text = string; join several with `\|` |
| `get_prop(selector, prop)` / `set_prop(selector, prop, value)` | `str` | |
| `list_objects(limit=0)` | `list[str]` | class names of live view-models |
| `describe(selector, depth=5)` | `str` | methods and properties of a class |
| `playhead_seconds()` | `float` | `0.0` if no timeline |
| `seek(seconds)` | `str` | |
| `timeline_duration_seconds()` | `float` | |

Pointer and object arguments (such as `QQuickItem*`) aren't supported by `invoke`; inject a QML snippet that calls the view-model from inside the scene instead (this is how `ctx.media` works).

```python
t = self.ctx.engine.playhead_seconds()
self.ctx.engine.seek(t + 1.0)
print(self.ctx.engine.describe("MainTimeLineCursorViewModel"))
```

## ctx.effects  (`effects`)

| Call | Returns | Notes |
|---|---|---|
| `library()` | `list[str]` | built-in effect names |
| `installed()` | `list[dict]` | `{effect_id, title, md5}` per installed effect |
| `install(name)` | `None` | builds the package; exits with an error message for an unknown name (the library script calls `sys.exit`) |
| `grid_items()` / `transition_items()` | `list[dict]` | what the ccmod category lists |
| `install_borrowed(state_dir)` | `list[str]` | puts packages under the stock ids the grid borrowed |
| `apply(project, name)` | `None` | writes the effect into a project's draft (reopen the project to see it) |
| `set_param(key, value)` | `str` | drives the selected effect's slider live, no reload |

## ctx.network  (`network`)

| Call | Notes |
|---|---|
| `set_grid(items, name="ccmod", extras_name="ccmod extras", main_count=8, transitions=None)` | publish the category for effects (and transitions) |
| `add_category`, `add_tiles`, `serve_category` | lower-level catalog rules |
| `redirect(pattern, local_file)`, `rules()`, `clear()` | answer requests from local files; **experimental** |
| `catalog_state_dir` | where the proxy records borrowed ids |

## ctx.media  (`media`)

| Call | Returns | Raises |
|---|---|---|
| `import_file(path)` | `str`: `"imported 1 via ..."` or `"error: ..."` | `FileNotFoundError` |
| `import_files(paths, timeout=5.0)` | same | `FileNotFoundError` |

The editor must be open on a project, otherwise the report is `error: no answer from CapCut`.

## ctx.process  (`process`)

| Call | Returns | Notes |
|---|---|---|
| `which(name, extra_dirs=None, env_var=None)` | `str | None` | PATH, then glob patterns in `extra_dirs`, then the environment variable |
| `run(cmd, timeout=600, cwd=None, env=None)` | `(exit_code, output)` | `cmd` is a list (no shell, no console window). stdout and stderr are combined and only the **last 4000 characters** are returned. Raises `subprocess.TimeoutExpired` on timeout, `FileNotFoundError` if the program doesn't exist |
| `run_async(cmd, on_done, **kw)` | `None` | `on_done(code, output)` is called from a worker thread; failures arrive as `(-1, "ErrorType: message")` instead of raising |

## ctx.apps  (`apps`)

See [External apps](external-apps.html) for the spec format.

| Call | Returns | Notes |
|---|---|---|
| `list()` | `list[dict]` | `{id, name, installed, exe, commands}` for every spec |
| `find(app_id)` | `str | None` | the executable; `KeyError` for an unknown app |
| `run(app_id, command, **inputs)` | `dict` | `{ok, code, output, outputs, imported, error?}`; raises `AppError` for bad inputs, `KeyError` for unknown app/command |
| `register(spec)` | `str` | add a spec at runtime; raises `AppError` if invalid |
| `expose_tools(app_id=None)` | `list[str]` | register each command as a tool (`tools` permission) |

## ctx.tools  (`tools`)

| Call | Returns | Notes |
|---|---|---|
| `register(name, description, fn, schema=None)` | full tool name `<plugin-id>.<name>` (MCP clients see it as `<plugin-id>__<name>`) | `fn(**arguments)` must return JSON-serialisable data; `schema` is a JSON Schema object for the arguments. Exceptions become error results |
| `unregister(name)` | `None` | |

Tools are dropped automatically when the plugin unloads.

## ctx.storage  (`files`)

| Call | Returns | Notes |
|---|---|---|
| `read_json(name, default=None)` | any | `default` if the file is missing or invalid |
| `write_json(name, data)` | `None` | creates the folder |
| `path(name)` | `Path` | inside your folder; **raises `PermissionError` if the path escapes it** (`../x`). Create subfolders yourself |
| `folder` | `Path` | `plugin-state/plugin-data/<plugin-id>/` |

## ctx.render  (`render`)

| Call | Returns | Notes |
|---|---|---|
| `agent(transport=None)` | `RenderAgent` | clock = the playhead when the plugin also has `engine`. See [Render agent](render-agent.html) |

## ctx.draft, ctx.builds, ctx.hooks

| Call | Returns | Notes |
|---|---|---|
| `draft.save(project)` / `restore(project)` | `int` | snapshot / restore a project's draft files; the project is the draft folder name |
| `draft.timeline(project)` | `Timeline` | open the project's timeline for editing; see [Timeline API](timeline-api.html) |
| `draft.bake(timeline, clip_id, prop, formula, fps=30)` | `int` | bake a formula to keyframes; see [Expressions](expressions.html) |
| `draft.format_of(project)` | `str | None` | the draft's format version |
| `builds.installed()` | `list[dict]` | `{version, renders, path, note}` for each CapCut build on this PC |
| `builds.preferred()` | `str | None` | version string ccmod will launch |
| `hooks.resolve(name, build_version=None)` | RVA or `None` | an engine function's address in a build, found by byte signature |

## ctx.log

A standard `logging.Logger` named `ccmod.plugin.<id>`; output appears in the `ccmod_run.py` terminal.

## Backends

`FridaBackend` attaches to the running CapCut. `FakeBackend` records every call in `backend.calls` and keeps in-memory properties, so plugins can be unit-tested without CapCut:

```python
from ccmod_sdk import FakeBackend, Host
host = Host(FakeBackend(), "plugins", "plugin-state-test")
host.load_all()
host.emit("editor_open")
```

## Helpers that need no CapCut

```python
from ccmod_sdk import themes, transitions, blender
themes.discover(); themes.validate(theme)        # list[dict]; raises ThemeError
transitions.build("vsplit")                       # builds a package, returns its index row
blender.find_blender()                            # path or None
```
