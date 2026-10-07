"""Donorless CCMOD transitions: stock-style transition packages (AmazingAuto xshader) whose fragment shader is ours.

A CapCut transition package is `config.json + extra.json + AmazingAuto_out/` (xshader). Its fragment shader gets the outgoing
clip (inputImageTexture), the incoming clip (inputImageTexture2) and `progress` (0..1, keyframed by generalEffect.json).
We clone a cached stock transition (the template), replace its shader, and register the result in scratch/_cctrans_index.json
(same shape as the effects index) so the CCMOD grid can offer it in the Transitions panel.

    python -m ccmod_sdk.transitions install      # build every transition below
    python -m ccmod_sdk.transitions list
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "scratch" / "_cctrans_index.json"
EFFECT_DIR = Path(os.path.expandvars(r"%LOCALAPPDATA%\CapCut\User Data\Cache\effect"))
TEMPLATE_ID = "6724226603372515853"                 # a cached stock transition (RotationalBlur): the package skeleton
TEMPLATE_MD5 = "a88b779d96204dc15634c0b9f0e60ee0"
FRAG_REL = "AmazingAuto_out/xshader/resource1/shader/RotationalBlur.frag"

PRE = """precision highp float;
varying vec2 texCoord;
uniform int inputHeight;
uniform int inputWidth;
uniform sampler2D inputImageTexture;
uniform sampler2D inputImageTexture2;
uniform float progress;
uniform float duration;
float ease(float x) { return x * x * (3.0 - 2.0 * x); }
vec4 A(vec2 uv) { return texture2D(inputImageTexture, clamp(uv, 0.001, 0.999)); }
vec4 B(vec2 uv) { return texture2D(inputImageTexture2, clamp(uv, 0.001, 0.999)); }
void main() {
    vec2 uv = texCoord;
    float p = ease(clamp(progress, 0.0, 1.0));
    vec4 c;
"""
POST = "    gl_FragColor = vec4(c.rgb, 1.0);\n}\n"
_HEAD, _MAIN = PRE.split("void main() {", 1)          # helpers (optional 4th field of a LIBRARY entry) go between the two
_MAIN = "void main() {" + _MAIN

LIBRARY = {
    "slide": ("Slide", "Incoming clip pushes the outgoing one left", """
    float x = uv.x + p;
    c = x < 1.0 ? A(vec2(x, uv.y)) : B(vec2(x - 1.0, uv.y));
"""),
    "zoom": ("Zoom", "Zoom into the outgoing clip, land on the new one", """
    float z = 1.0 + p * 1.2;
    vec2 q = (uv - 0.5) / z + 0.5;
    vec2 r = (uv - 0.5) * (2.0 - p) * 0.5 + 0.5;
    c = mix(A(q), B(mix(uv, r, 1.0 - p)), smoothstep(0.35, 0.75, p));
"""),
    "glitch": ("Glitch", "RGB split and block tearing", """
    float band = floor(uv.y * 18.0);
    float n = fract(sin(band * 91.7 + floor(progress * 12.0) * 13.1) * 43758.5);
    float amt = sin(clamp(progress, 0.0, 1.0) * 3.14159) * 0.08;
    vec2 o = vec2((n - 0.5) * amt * 2.0, 0.0);
    vec4 a = vec4(A(uv + o + vec2(amt, 0.0)).r, A(uv + o).g, A(uv + o - vec2(amt, 0.0)).b, 1.0);
    vec4 b = vec4(B(uv + o + vec2(amt, 0.0)).r, B(uv + o).g, B(uv + o - vec2(amt, 0.0)).b, 1.0);
    c = n < progress ? b : a;
"""),
    "wipe": ("Wipe", "Soft diagonal wipe", """
    float d = (uv.x + uv.y) * 0.5;
    float m = smoothstep(p * 1.3 - 0.3, p * 1.3, d);
    c = mix(B(uv), A(uv), m);
"""),
    "flash": ("Flash", "Bright flash cut", """
    float f = 1.0 - abs(p * 2.0 - 1.0);
    c = mix(A(uv), B(uv), step(0.5, p)) + vec4(vec3(f * f * 1.2), 0.0);
"""),
    "spin": ("Spin", "Spin and scale into the next clip", """
    float a = p * 3.14159;
    vec2 d = uv - 0.5;
    mat2 R = mat2(cos(a), -sin(a), sin(a), cos(a));
    vec2 q = R * d * (1.0 + p) + 0.5;
    vec2 q2 = R * d * (2.0 - p) + 0.5;
    c = mix(A(q), B(q2), smoothstep(0.3, 0.7, p));
"""),
    "pixelate": ("Pixel Dissolve", "Dissolve through growing pixels", """
    float s = mix(2.0, 60.0, 1.0 - abs(p * 2.0 - 1.0));
    vec2 g = floor(uv * s) / s + 0.5 / s;
    c = mix(A(g), B(g), step(0.5, p));
"""),
    "swing": ("Swing", "Barn-door open onto the next clip", """
    float edge = abs(uv.x - 0.5) * 2.0;
    float m = smoothstep(p - 0.05, p + 0.05, 1.0 - edge);
    c = mix(A(uv), B(uv), m);
"""),
}


def fab_id(key: str) -> str:
    """Deterministic 19-digit donorless id (prefix 87 = transitions, 88 = effects; in no catalog)."""
    return "87" + str(int(hashlib.sha1(("trans:" + key).encode()).hexdigest(), 16))[:17].rjust(17, "0")


def _load() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def build(key: str, effect_dir: Path | None = None) -> dict:
    """Clone the template package into a fabricated id and swap in the shader. Idempotent."""
    effect_dir = effect_dir or EFFECT_DIR
    label, desc, body, *rest = LIBRARY[key]
    helpers = rest[0] if rest else ""                                  # optional functions placed before main()
    src = effect_dir / TEMPLATE_ID
    if not (src / TEMPLATE_MD5).is_dir():
        raise FileNotFoundError(f"template transition package not cached: {src} (open the Transitions panel and apply a stock transition once)")
    nid = fab_id(key)
    dst = effect_dir / nid
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    frag = dst / TEMPLATE_MD5 / FRAG_REL
    mtime = frag.stat().st_mtime
    frag.write_text(_HEAD + helpers + "\n" + _MAIN + body + POST, encoding="utf-8")
    os.utime(frag, (mtime, mtime))                                   # keep mtime (CapCut's integrity check)
    zp = dst / (TEMPLATE_MD5 + "_tmp")
    if zp.exists():                                                  # CapCut also keeps the package as a zip: patch it the same way
        import packs
        zmt = zp.stat().st_mtime
        packs._patch_zip_shader(zp, [frag], {frag: None})
        os.utime(zp, (zmt, zmt))
    row = {"id": nid, "md5": TEMPLATE_MD5, "label": f"CCMOD {label}", "desc": desc, "kind": "transition",
           "path": str(dst / TEMPLATE_MD5).replace("\\", "/")}
    ix = _load()
    ix[f"trans_{key}"] = row
    INDEX.write_text(json.dumps(ix, indent=2), encoding="utf-8")
    return row


def uninstall(key: str, effect_dir: Path | None = None) -> bool:
    ix = _load()
    row = ix.pop(f"trans_{key}", None)
    if row is None:
        return False
    shutil.rmtree((effect_dir or EFFECT_DIR) / row["id"], ignore_errors=True)
    INDEX.write_text(json.dumps(ix, indent=2), encoding="utf-8")
    return True


def install_all(effect_dir: Path | None = None) -> list[str]:
    return [build(k, effect_dir)["label"] for k in LIBRARY]


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "install":
        print("\n".join(install_all()))
    else:
        print(json.dumps(_load(), indent=2))
