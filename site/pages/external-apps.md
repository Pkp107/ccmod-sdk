---
title: External apps
section: Building
order: 50
---

# Using other software from CapCut

## The fast way: describe the app in JSON

You don't need Python to connect a program. Drop a spec in `apps/` and ccmod can find the program, run its commands, import the results into CapCut, and offer every command as an MCP tool. ffmpeg and Blender ship as examples (`apps/ffmpeg.json`, `apps/blender.json`).

```json
{
  "id": "ffmpeg",
  "name": "FFmpeg",
  "find": { "exe": "ffmpeg", "env": "CCMOD_FFMPEG", "dirs": ["C:/ffmpeg*/bin"] },
  "commands": {
    "grayscale": {
      "description": "Remove the colour from a video.",
      "args": ["-y", "-i", "{input}", "-vf", "hue=s=0", "{output}"],
      "inputs":  { "input":  { "type": "file" } },
      "outputs": { "output": { "ext": ".mp4", "import": true } },
      "timeout": 1800
    }
  }
}
```

| Field | Meaning |
|---|---|
| `find.exe` / `env` / `dirs` | How to locate the program: the env var wins, then PATH, then the folders (globs allowed, newest match) |
| `args` | The argument list; **no shell is used**. `{name}` is filled from an input or an output |
| `inputs` | Each has `type` = `file` (must exist), `number` or `text`, and an optional `default` |
| `outputs` | Each has an `ext`; ccmod picks the path in your plugin's folder. `"import": true` puts the file in CapCut's media pool |
| `timeout` | Seconds before the run is abandoned |

Use it from a plugin (permission `apps`; `tools` too if you expose tools):

```python
res = self.ctx.apps.run("ffmpeg", "grayscale", input="C:/clips/a.mp4")
# {"ok": True, "code": 0, "output": "...", "outputs": {"output": ".../output_1700.mp4"}, "imported": {"output": "imported 1 via ..."}}

self.ctx.apps.list()                  # every known app: installed?, exe path, commands
self.ctx.apps.expose_tools()          # every command becomes an MCP tool, e.g. ffmpeg_grayscale
self.ctx.apps.register({...spec...})  # add a spec at runtime, no file needed
```

Failure is reported, not hidden: a missing program returns `ok: false` with an install hint, a non-zero exit gives the code and the last 4000 characters of output, and a command that finishes without creating its output file is flagged. Bad inputs raise `AppError`.

Anything with a command line fits: ffmpeg filters, Blender (`render_blend`, or `run_script` with your own bpy script), Natron, ImageMagick, Real-ESRGAN, Whisper, Krita scripts.

## The Python way

For logic a template can't express, call the lower-level APIs yourself.

ccmod doesn't try to rebuild Blender or ffmpeg inside CapCut. A plugin **runs the program, takes its output, and imports it into CapCut's media pool**. That gives you 3D, ML tools, audio analysis, anything with a command line.

Two APIs do the work (permissions `process` and `media`):

```python
code, output = self.ctx.process.run(["ffmpeg", "-i", src, "-vf", "hue=s=0", dst], timeout=600)
self.ctx.media.import_file(dst)       # appears in CapCut's media pool
```

## `ctx.process`

| Call | Meaning |
|---|---|
| `which(name, extra_dirs=None, env_var=None)` | Find an executable on PATH, in `extra_dirs` (globs allowed, for example `C:/Program Files/Blender*`) or via an environment variable |
| `run(cmd, timeout=600, cwd=None, env=None)` | Run, wait, return `(exit_code, combined_output)` |
| `run_async(cmd, on_done, **kw)` | Run on a thread; `on_done(code, output)` is called when finished |

Run slow work asynchronously, or from a button handler thread, so CapCut's UI doesn't wait.

## `ctx.media`

| Call | Meaning |
|---|---|
| `import_file(path)` | Import one file into the media pool. Returns a status string (`imported 1 ...` or `error ...`) |
| `import_files([paths], timeout=5.0)` | Several at once |

It raises `FileNotFoundError` for a missing file. Import is proven live: it drives CapCut's own import view-model, so the clip appears just like a drag-in.

## Worked example: Blender

The bundled `blender-bridge` plugin renders a spinning 3D object and imports the video:

```python
out = self.ctx.storage.path(f"renders/{kind}_{int(time.time())}.mp4")
path = blender.render({"kind": "monkey", "color": "#ff8800", "seconds": 3, "out": str(out)})
self.ctx.media.import_file(path)
```

`ccmod_sdk/blender.py` finds Blender (`ccmod_blender` env var, then `C:/Program Files/Blender Foundation/Blender*`), writes a small `bpy` job script, runs `blender --background --python job.py`, and returns the file. It exposes a **3D object** timeline button and an MCP tool `blender-bridge__render_3d` (kinds: monkey, torus, sphere, cube, cone, text).

!!! note "Status"
    The job helpers and import are unit-tested. The Blender render itself hasn't been run end to end because Blender isn't installed on the dev PC. Install Blender (or set `ccmod_blender`) and report what happens.

## Your own bridge: a template

```python
from ccmod_sdk import Plugin

class MyBridge(Plugin):
    def on_load(self):
        self.exe = self.ctx.process.which("mytool", ["C:/Program Files/MyTool*"], env_var="MYTOOL")
        self.ctx.tools.register("run_mytool", "Process a file with MyTool.", self.run,
                                {"type": "object", "properties": {"src": {"type": "string"}}, "required": ["src"]})

    def on_editor_open(self):
        self.ctx.ui.add_button("MyTool", lambda: self.ctx.process.run_async(
            [self.exe, "--demo", str(self.ctx.storage.path("out.mp4"))],
            lambda code, out: self.ctx.media.import_file(self.ctx.storage.path("out.mp4")) if code == 0 else None))

    def run(self, src: str) -> dict:
        out = self.ctx.storage.path("out.mp4")
        code, text = self.ctx.process.run([self.exe, src, str(out)])
        return {"ok": code == 0, "log": text[-500:], "imported": self.ctx.media.import_file(out) if code == 0 else None}
```

Manifest permissions: `["ui", "files", "tools", "process", "media"]`.

## Ideas that fit this pattern

| Idea | Tool |
|---|---|
| 3D objects and titles | Blender |
| Denoise, upscale, interpolate | ffmpeg filters, Real-ESRGAN, RIFE |
| Background removal, tracking | ML models in Python |
| Speech to subtitles | Whisper |
| Stabilise | ffmpeg `vidstab`, OpenCV |
| "Render with ReShade/2D effects" | Run the clip through a ReShade-style pass offline, import the result |
| Loudness / audio clean-up | ffmpeg, sox |

The limit: results arrive as **files**, not a live preview in the timeline. A live feed needs a render agent; see the [Roadmap](roadmap.html).
