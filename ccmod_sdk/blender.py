"""Blender as a CCMOD render engine: build a bpy job script, run Blender headless, get a video file back.

    exe = find_blender()
    script = job_script({"kind": "monkey", "color": "#ff8800", "seconds": 3, "out": "C:/.../monkey.mp4"})
    # run:  blender -b --factory-startup -P script.py   (see render_primitive)

A plugin then imports the file into CapCut with ctx.media.import_file(...). Nothing here touches account, Pro or licensing.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

KINDS = ("monkey", "cube", "sphere", "torus", "cone", "text")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def find_blender() -> str | None:
    env = os.environ.get("CCMOD_BLENDER")
    if env and Path(env).is_file():
        return env
    pats = [r"C:\Program Files\Blender Foundation\Blender*\blender.exe", r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe"]
    found = sorted(p for pat in pats for p in glob.glob(pat))
    return found[-1] if found else None


def normalize(job: dict) -> dict:
    kind = job.get("kind", "monkey")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    color = job.get("color", "#ff8800")
    bg = job.get("background", "#101216")
    if not _HEX.match(color) or not _HEX.match(bg):
        raise ValueError("colors must look like #rrggbb")
    return {"kind": kind, "color": color, "background": bg, "text": str(job.get("text", "CCMOD"))[:40],
            "seconds": max(0.5, min(float(job.get("seconds", 3)), 30.0)), "fps": int(job.get("fps", 30)),
            "width": int(job.get("width", 1280)), "height": int(job.get("height", 720)),
            "spin": bool(job.get("spin", True)), "out": str(job["out"])}


_SCRIPT = r'''
import bpy, math, json, sys
job = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

def rgb(h):
    h = h.lstrip("#")
    return tuple((int(h[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4))

kind = job["kind"]
if kind == "monkey":   bpy.ops.mesh.primitive_monkey_add(size=2.2)
elif kind == "cube":   bpy.ops.mesh.primitive_cube_add(size=2)
elif kind == "sphere": bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, segments=64, ring_count=32)
elif kind == "torus":  bpy.ops.mesh.primitive_torus_add(major_radius=1.1, minor_radius=0.42, major_segments=64, minor_segments=32)
elif kind == "cone":   bpy.ops.mesh.primitive_cone_add(radius1=1.1, depth=2.2, vertices=64)
else:
    bpy.ops.object.text_add()
    t = bpy.context.active_object
    t.data.body = job["text"]
    t.data.extrude = 0.25
    t.data.align_x = "CENTER"
    t.data.size = 1.2
obj = bpy.context.active_object
if obj.type == "MESH":
    bpy.ops.object.shade_smooth()
c = rgb(job["color"])
mat = bpy.data.materials.new("ccmod")
mat.diffuse_color = (c[0], c[1], c[2], 1.0)
obj.data.materials.append(mat)

bpy.ops.object.camera_add(location=(0, -7.5, 0), rotation=(math.pi / 2, 0, 0))
scene.camera = bpy.context.active_object

fps = job["fps"]
scene.render.fps = fps
scene.frame_start = 1
scene.frame_end = max(2, int(job["seconds"] * fps))
if job["spin"]:
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    obj.rotation_euler = (0.2, 0, 0)
    obj.keyframe_insert("rotation_euler", frame=1)
    obj.rotation_euler = (0.2, 0, math.pi * 2)
    obj.keyframe_insert("rotation_euler", frame=scene.frame_end + 1)

world = bpy.data.worlds.new("w")
world.color = rgb(job["background"])
scene.world = world
scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading
sh.light = "STUDIO"
sh.color_type = "MATERIAL"
sh.show_cavity = True
scene.render.resolution_x = job["width"]
scene.render.resolution_y = job["height"]
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = job["out"]
bpy.ops.render.render(animation=True)
print("CCMOD_RENDER_DONE", job["out"])
'''


def job_script() -> str:
    return _SCRIPT


def render(job: dict, timeout: float = 600, blender: str | None = None) -> Path:
    """Render a primitive turntable to job['out'] (an .mp4 path). Raises RuntimeError with Blender's output on failure."""
    exe = blender or find_blender()
    if not exe:
        raise RuntimeError("Blender not found (install it, or set CCMOD_BLENDER to blender.exe)")
    j = normalize(job)
    out = Path(j["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf = Path(tempfile.mkdtemp(prefix="ccmod_blender_")) / "job.py"
    sf.write_text(_SCRIPT, encoding="utf-8")
    p = subprocess.run([exe, "-b", "--factory-startup", "-P", str(sf), "--", json.dumps(j)], capture_output=True, text=True,
                       timeout=timeout, creationflags=0x08000000, encoding="utf-8", errors="replace")
    f = out if out.suffix else out.with_suffix(".mp4")
    cands = [f, *out.parent.glob(out.stem + "*.mp4")]
    hit = next((c for c in cands if c.is_file()), None)
    if p.returncode != 0 or hit is None:
        raise RuntimeError("Blender failed:\n" + (p.stdout + p.stderr)[-1500:])
    return hit
