"""Creator: make effects and transitions from a recipe, with no shader code.

An effect recipe is a list of blocks. Blocks run in three stages: `uv` blocks bend the coordinates, the picture is sampled (a
`sample` block such as chromatic can replace the plain sample), then `color` blocks grade the pixels.

    {"name": "retro", "label": "Retro", "description": "Warm VHS look",
     "slider": {"label": "Amount", "controls": "scanlines.strength"},
     "blocks": [{"block": "wave", "amount": 0.01, "speed": 2},
                {"block": "chromatic", "amount": 0.004},
                {"block": "tint", "color": "#ffb060", "amount": 0.25},
                {"block": "scanlines", "strength": 0.4},
                {"block": "vignette", "strength": 0.5}]}

`slider.controls` is "<block>.<param>" (or "<block>#2.<param>" for the second use of a block): the CapCut slider (0..1) then
drives that parameter across its range. Without it the slider is the first block's first number parameter.

A transition recipe picks a base motion and optional overlays:

    {"name": "whip", "label": "Whip", "description": "Fast slide with RGB split",
     "base": {"type": "slide", "direction": "left"}, "overlays": [{"type": "rgbsplit", "amount": 0.04}, {"type": "flash", "strength": 0.4}]}

`build_effect(recipe)` / `build_transition(recipe)` return what the installers take; `install_effect` / `install_transition`
also install them (needs CapCut's template packages cached, like every other ccmod effect).
Nothing is executed from a recipe: every value is checked and turned into a number or a colour before it reaches the shader.
"""
from __future__ import annotations

import re
from pathlib import Path

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class RecipeError(ValueError):
    pass


def _glsl_float(v) -> str:
    return repr(round(float(v), 6)) if float(v) != int(float(v)) else f"{int(float(v))}.0"


def _col(h: str) -> str:
    return "vec3(%s, %s, %s)" % tuple(_glsl_float(int(h[i:i + 2], 16) / 255) for i in (1, 3, 5))


# ---- effect blocks: stage, params {name: (default, lo, hi)} or colour params {name: "#hex"}, code template using {param} ----
# code uses `uv` (vec2), `c` (vec4), `iTime`; {param} is replaced with a GLSL float expression (or a vec3 for colours).
BLOCKS: dict[str, dict] = {
    # uv stage
    "mirror":   {"stage": "uv", "params": {"amount": (0.5, 0.0, 1.0)}, "doc": "Mirror the left half onto the right",
                 "code": "uv.x = mix(uv.x, uv.x < 0.5 ? uv.x : 1.0 - uv.x, {amount});"},
    "pixelate": {"stage": "uv", "params": {"blocks": (60.0, 8.0, 240.0)}, "doc": "Mosaic of N blocks across",
                 "code": "{ float _n = {blocks}; uv = (floor(uv * _n) + 0.5) / _n; }"},
    "wave":     {"stage": "uv", "params": {"amount": (0.02, 0.0, 0.08), "frequency": (12.0, 1.0, 40.0), "speed": (2.0, 0.0, 10.0)},
                 "doc": "Ripple the picture", "code": "uv.x += sin(uv.y * {frequency} + iTime * {speed}) * {amount};"},
    "shake":    {"stage": "uv", "params": {"amount": (0.01, 0.0, 0.06), "speed": (30.0, 1.0, 80.0)}, "doc": "Camera shake",
                 "code": "uv += vec2(sin(iTime * {speed}), cos(iTime * {speed} * 1.3)) * {amount};"},
    "zoom":     {"stage": "uv", "params": {"amount": (1.2, 0.5, 3.0)}, "doc": "Zoom into the centre (1 = none)",
                 "code": "uv = (uv - 0.5) / {amount} + 0.5;"},
    "rotate":   {"stage": "uv", "params": {"degrees": (15.0, -180.0, 180.0)}, "doc": "Rotate around the centre",
                 "code": "{ float _a = radians({degrees}); vec2 _d = uv - 0.5; uv = mat2(cos(_a), -sin(_a), sin(_a), cos(_a)) * _d + 0.5; }"},
    "swirl":    {"stage": "uv", "params": {"strength": (2.0, -6.0, 6.0)}, "doc": "Twist around the centre",
                 "code": "{ vec2 _d = uv - 0.5; float _r = length(_d); float _a = {strength} * (0.5 - min(_r, 0.5)); "
                         "uv = mat2(cos(_a), -sin(_a), sin(_a), cos(_a)) * _d + 0.5; }"},
    "kaleido":  {"stage": "uv", "params": {"segments": (6.0, 2.0, 16.0)}, "doc": "Kaleidoscope",
                 "code": "{ vec2 _d = uv - 0.5; float _a = atan(_d.y, _d.x); float _s = 6.2831853 / floor({segments}); "
                         "_a = abs(mod(_a, _s) - _s * 0.5); uv = vec2(cos(_a), sin(_a)) * length(_d) + 0.5; }"},
    "slide":    {"stage": "uv", "params": {"speed": (0.35, 0.0, 2.0)}, "doc": "Endless downward scroll",
                 "code": "uv.y = fract(uv.y + iTime * {speed});"},
    # sample stage
    "chromatic": {"stage": "sample", "params": {"amount": (0.006, 0.0, 0.03)}, "doc": "Split the red and blue channels",
                  "code": "vec4 c = vec4(texture(u_inputTexture, clamp(uv + vec2({amount}, 0.0), 0.001, 0.999)).r, "
                          "texture(u_inputTexture, clamp(uv, 0.001, 0.999)).g, "
                          "texture(u_inputTexture, clamp(uv - vec2({amount}, 0.0), 0.001, 0.999)).b, 1.0);"},
    # colour stage
    "grayscale": {"stage": "color", "params": {"amount": (1.0, 0.0, 1.0)}, "doc": "Remove colour",
                  "code": "c.rgb = mix(c.rgb, vec3(dot(c.rgb, vec3(0.299, 0.587, 0.114))), {amount});"},
    "invert":    {"stage": "color", "params": {"amount": (1.0, 0.0, 1.0)}, "doc": "Invert colours",
                  "code": "c.rgb = mix(c.rgb, 1.0 - c.rgb, {amount});"},
    "brightness": {"stage": "color", "params": {"amount": (0.2, -0.5, 0.5)}, "doc": "Lighter or darker",
                   "code": "c.rgb += {amount};"},
    "contrast":  {"stage": "color", "params": {"amount": (1.3, 0.5, 2.5)}, "doc": "Contrast (1 = none)",
                  "code": "c.rgb = (c.rgb - 0.5) * {amount} + 0.5;"},
    "saturation": {"stage": "color", "params": {"amount": (1.5, 0.0, 3.0)}, "doc": "Colour strength (1 = none)",
                   "code": "c.rgb = mix(vec3(dot(c.rgb, vec3(0.299, 0.587, 0.114))), c.rgb, {amount});"},
    "vignette":  {"stage": "color", "params": {"strength": (0.6, 0.0, 1.0)}, "doc": "Darker edges",
                  "code": "c.rgb *= mix(1.0, smoothstep(0.85, 0.25, distance(uv0, vec2(0.5))), {strength});"},
    "scanlines": {"stage": "color", "params": {"strength": (0.3, 0.0, 0.8), "lines": (360.0, 60.0, 1080.0)}, "doc": "VHS scanlines",
                  "code": "c.rgb *= 1.0 - {strength} * (0.5 + 0.5 * sin(uv0.y * {lines} * 3.14159));"},
    "grain":     {"stage": "color", "params": {"amount": (0.08, 0.0, 0.4)}, "doc": "Film grain (animated)",
                  "code": "c.rgb += ({hash} - 0.5) * {amount};"},
    "posterize": {"stage": "color", "params": {"levels": (5.0, 2.0, 16.0)}, "doc": "Fewer colour steps",
                  "code": "c.rgb = floor(c.rgb * {levels} + 0.5) / {levels};"},
    "tint":      {"stage": "color", "params": {"amount": (0.3, 0.0, 1.0)}, "colors": {"color": "#ffb060"}, "doc": "Colour wash",
                  "code": "c.rgb = mix(c.rgb, c.rgb * {color} * 1.6, {amount});"},
    "duotone":   {"stage": "color", "params": {"amount": (1.0, 0.0, 1.0)}, "colors": {"shadow": "#101840", "light": "#ffd070"}, "doc": "Two-colour grade",
                  "code": "c.rgb = mix(c.rgb, mix({shadow}, {light}, dot(c.rgb, vec3(0.299, 0.587, 0.114))), {amount});"},
}

_HASH = "fract(sin(dot(uv0 * 1000.0 + vec2(iTime), vec2(12.9898, 78.233))) * 43758.5453)"


def blocks_doc() -> list[dict]:
    """What a UI or an AI needs to offer the blocks: name, stage, description, parameters with ranges and defaults."""
    return [{"block": k, "stage": v["stage"], "description": v["doc"],
             "params": {p: {"default": d, "min": lo, "max": hi} for p, (d, lo, hi) in v["params"].items()},
             "colors": dict(v.get("colors", {}))} for k, v in BLOCKS.items()]


def _check_name(recipe: dict) -> str:
    name = str(recipe.get("name", ""))
    if not _NAME.match(name):
        raise RecipeError("'name' must be lowercase letters, digits, underscore (2-31 chars, starting with a letter)")
    return name


def _resolve_control(recipe: dict, uses: list[tuple[str, int]]) -> tuple[int, str] | None:
    """Which (block index, param) the slider drives."""
    ctl = (recipe.get("slider") or {}).get("controls")
    if not ctl:
        return (0, next(iter(BLOCKS[uses[0][0]]["params"]))) if uses and BLOCKS[uses[0][0]]["params"] else None
    m = re.match(r"^([a-z]+)(?:#(\d+))?\.([a-z_]+)$", str(ctl))
    if not m:
        raise RecipeError("slider.controls must look like 'vignette.strength' or 'tint#2.amount'")
    block, nth, param = m.group(1), int(m.group(2) or 1), m.group(3)
    seen = 0
    for i, (b, _) in enumerate(uses):
        if b == block:
            seen += 1
            if seen == nth:
                if param not in BLOCKS[b]["params"]:
                    raise RecipeError(f"{block} has no parameter {param!r}")
                return i, param
    raise RecipeError(f"slider.controls refers to {ctl!r} but the recipe has no such block")


def build_effect(recipe: dict) -> dict:
    """Recipe -> {"name", "slider", "desc", "main"} in the shape of a ccfx library entry."""
    name = _check_name(recipe)
    blocks = recipe.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 12:
        raise RecipeError("'blocks' must be a list of 1 to 12 blocks")
    uses = [(str(b.get("block", "")), i) for i, b in enumerate(blocks)]
    for b, _ in uses:
        if b not in BLOCKS:
            raise RecipeError(f"unknown block {b!r}; known: {', '.join(sorted(BLOCKS))}")
    if sum(1 for b, _ in uses if BLOCKS[b]["stage"] == "sample") > 1:
        raise RecipeError("only one sampling block (chromatic) is allowed")
    ctl = _resolve_control(recipe, uses)
    stages: dict[str, list[str]] = {"uv": [], "sample": [], "color": []}
    uses_time = False
    for i, blk in enumerate(blocks):
        d = BLOCKS[blk["block"]]
        vals: dict[str, str] = {}
        for p, (default, lo, hi) in d["params"].items():
            v = blk.get(p, default)
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise RecipeError(f"{blk['block']}.{p} must be a number") from None
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise RecipeError(f"{blk['block']}.{p}={v} is outside {lo}..{hi}")
            vals[p] = (f"({_glsl_float(lo)} + ({_glsl_float(hi)} - {_glsl_float(lo)}) * clamp(SharpenIntensity, 0.0, 1.0))"
                       if ctl == (i, p) else _glsl_float(v))
        for p, default in d.get("colors", {}).items():
            c = str(blk.get(p, default))
            if not _COLOR.match(c):
                raise RecipeError(f"{blk['block']}.{p} must be a colour like #ff8800")
            vals[p] = _col(c)
        code = d["code"].replace("{hash}", _HASH)
        for k, v in vals.items():
            code = code.replace("{" + k + "}", v)
        if "iTime" in code:
            uses_time = True
        stages[d["stage"]].append("    " + code)
    sample = stages["sample"][0] if stages["sample"] else "    vec4 c = texture(u_inputTexture, clamp(uv, 0.001, 0.999));"
    main = ("void main() {   // ccmod creator: " + name + "\n    vec2 uv = uv0;\n" + "\n".join(stages["uv"]) + ("\n" if stages["uv"] else "")
            + sample + "\n" + "\n".join(stages["color"]) + ("\n" if stages["color"] else "")
            + "    c = lm_take_effect_filter(u_lut, c, LutIntensity);\n    FragColor = clamp(vec4(c.rgb, 1.0), 0.0, 1.0);\n}\n")
    label = (recipe.get("slider") or {}).get("label") or "Amount"
    return {"name": name, "slider": str(label)[:20], "desc": str(recipe.get("description") or recipe.get("label") or name)[:120],
            "main": main, "animated": uses_time}


# ---- transitions ----
BASES = {
    "slide": ({"direction": ("left", "right", "up", "down")}, "Incoming clip pushes the outgoing one away"),
    "wipe": ({"angle": (0.0, 360.0, 45.0), "softness": (0.01, 0.5, 0.1)}, "Edge sweeping across the frame"),
    "zoom": ({"amount": (0.2, 3.0, 1.2)}, "Zoom into the outgoing clip and land on the new one"),
    "spin": ({"turns": (0.1, 2.0, 0.5)}, "Spin and scale into the next clip"),
    "dissolve": ({}, "Plain cross-fade"),
    "split": ({"axis": ("vertical", "horizontal")}, "Two halves slide apart to reveal the next clip"),
    "pixelate": ({"max_blocks": (8.0, 120.0, 40.0)}, "Mosaic grows, cuts, shrinks"),
}
OVERLAYS = {
    "flash": ({"strength": (0.0, 2.0, 1.0)}, "Bright flash on the cut"),
    "rgbsplit": ({"amount": (0.0, 0.1, 0.03)}, "Red/blue channels drift apart during the move"),
    "shake": ({"amount": (0.0, 0.1, 0.02)}, "Camera shake during the move"),
}


def _num(spec: dict, params: dict, key: str) -> str:
    lo, hi, default = params[key]
    v = spec.get(key, default)
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise RecipeError(f"{key} must be a number") from None
    if not (lo <= v <= hi):
        raise RecipeError(f"{key}={v} is outside {lo}..{hi}")
    return _glsl_float(v)


def build_transition(recipe: dict) -> dict:
    """Recipe -> {"name", "label", "desc", "body"} (body is the transition shader body: it sets `c`, see transitions.py)."""
    name = _check_name(recipe)
    base = recipe.get("base") or {}
    bt = base.get("type")
    if bt not in BASES:
        raise RecipeError(f"base.type must be one of {', '.join(BASES)}")
    params = BASES[bt][0]
    lines: list[str] = []
    pre: list[str] = []
    for ov in recipe.get("overlays", []) or []:
        t = ov.get("type")
        if t not in OVERLAYS:
            raise RecipeError(f"overlay type must be one of {', '.join(OVERLAYS)}")
        if t == "shake":
            pre.append(f"    float _sh = sin(clamp(progress, 0.0, 1.0) * 3.14159) * {_num(ov, OVERLAYS[t][0], 'amount')};\n"
                       "    uv += vec2(sin(progress * 60.0), cos(progress * 47.0)) * _sh;")
    if bt == "slide":
        d = base.get("direction", "left")
        if d not in params["direction"]:
            raise RecipeError(f"direction must be one of {params['direction']}")
        vec = {"left": ("uv.x + p", "x < 1.0", "vec2(x, uv.y)", "vec2(x - 1.0, uv.y)", "float x"),
               "right": ("uv.x - p", "x > 0.0", "vec2(x, uv.y)", "vec2(x + 1.0, uv.y)", "float x"),
               "up": ("uv.y + p", "x < 1.0", "vec2(uv.x, x)", "vec2(uv.x, x - 1.0)", "float x"),
               "down": ("uv.y - p", "x > 0.0", "vec2(uv.x, x)", "vec2(uv.x, x + 1.0)", "float x")}[d]
        lines.append(f"    {vec[4]} = {vec[0]};\n    c = {vec[1]} ? A({vec[2]}) : B({vec[3]});")
    elif bt == "wipe":
        ang, soft = _num(base, params, "angle"), _num(base, params, "softness")
        lines.append(f"    float _a = radians({ang});\n    float _d = dot(uv - 0.5, vec2(cos(_a), sin(_a))) + 0.5;\n"
                     f"    float _m = smoothstep(p * (1.0 + {soft}) - {soft}, p * (1.0 + {soft}), _d);\n    c = mix(B(uv), A(uv), _m);")
    elif bt == "zoom":
        amt = _num(base, params, "amount")
        lines.append(f"    float _z = 1.0 + p * {amt};\n    vec2 _q = (uv - 0.5) / _z + 0.5;\n"
                     f"    vec2 _r = (uv - 0.5) * (2.0 - p) * 0.5 + 0.5;\n    c = mix(A(_q), B(mix(uv, _r, 1.0 - p)), smoothstep(0.35, 0.75, p));")
    elif bt == "spin":
        t = _num(base, params, "turns")
        lines.append(f"    float _a = p * 6.2831853 * {t};\n    vec2 _d = uv - 0.5;\n    mat2 _R = mat2(cos(_a), -sin(_a), sin(_a), cos(_a));\n"
                     "    c = mix(A(_R * _d * (1.0 + p) + 0.5), B(_R * _d * (2.0 - p) + 0.5), smoothstep(0.3, 0.7, p));")
    elif bt == "dissolve":
        lines.append("    c = mix(A(uv), B(uv), p);")
    elif bt == "split":
        ax = base.get("axis", "vertical")
        if ax not in params["axis"]:
            raise RecipeError(f"axis must be one of {params['axis']}")
        coord = "uv.x" if ax == "vertical" else "uv.y"
        lines.append(f"    float _e = abs({coord} - 0.5) * 2.0;\n    c = _e < p ? B(uv) : A(uv);")
    else:                                                          # pixelate
        mb = _num(base, params, "max_blocks")
        lines.append(f"    float _s = mix(2.0, {mb}, 1.0 - abs(p * 2.0 - 1.0));\n    vec2 _g = floor(uv * _s) / _s + 0.5 / _s;\n"
                     "    c = mix(A(_g), B(_g), step(0.5, p));")
    post: list[str] = []
    for ov in recipe.get("overlays", []) or []:
        t = ov["type"]
        if t == "flash":
            s = _num(ov, OVERLAYS[t][0], "strength")
            post.append(f"    {{ float _f = 1.0 - abs(p * 2.0 - 1.0); c.rgb += vec3(_f * _f * {s}); }}")
        elif t == "rgbsplit":
            a = _num(ov, OVERLAYS[t][0], "amount")
            post.append(f"    {{ float _o = sin(clamp(progress, 0.0, 1.0) * 3.14159) * {a}; "
                        "c.r = mix(A(uv + vec2(_o, 0.0)).r, B(uv + vec2(_o, 0.0)).r, step(0.5, p)); "
                        "c.b = mix(A(uv - vec2(_o, 0.0)).b, B(uv - vec2(_o, 0.0)).b, step(0.5, p)); }")
    body = "\n" + "\n".join(pre + lines + post) + "\n"
    return {"name": name, "label": str(recipe.get("label") or name.capitalize())[:24],
            "desc": str(recipe.get("description") or BASES[bt][1])[:120], "body": body}


# ---- installing ----
def _ccfx():
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("ccfx_creator", root / "scratch" / "ccfx.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def install_effect(recipe: dict) -> dict:
    """Build the effect and install it like any ccfx effect. Returns the built entry."""
    e = build_effect(recipe)
    cc = _ccfx()
    cc.LIBRARY[e["name"]] = {"slider": e["slider"], "desc": e["desc"], "main": e["main"]}
    cc._build_package(e["name"], e["main"], e["slider"], e["desc"])
    _remember("effects", recipe)
    return e


def install_transition(recipe: dict) -> dict:
    from . import transitions
    t = build_transition(recipe)
    transitions.LIBRARY[t["name"]] = (t["label"], t["desc"], t["body"])
    transitions.build(t["name"])
    _remember("transitions", recipe)
    return t


# ---- transitions made in the standalone ccmod transition editor (editor/) ----
_FORBIDDEN_DIRECTIVES = re.compile(r"^\s*#\s*(version|extension|pragma|include|line|if|ifdef|ifndef|else|elif|endif|undef|error)\b", re.M)


def validate_transition_export(data: dict) -> dict:
    """Check a .ccmodtrans file written by the editor. Raises RecipeError. Nothing is executed: the shader text is only
    stored and later compiled by CapCut's own shader compiler, so the checks are about shape and size, not trust."""
    if not isinstance(data, dict) or data.get("format") != "ccmod-transition":
        raise RecipeError("not a ccmod transition file (format must be 'ccmod-transition')")
    if data.get("version") != 1:
        raise RecipeError("unsupported transition file version")
    name = _check_name(data)
    for field in ("helpers", "body"):
        txt = data.get(field)
        if not isinstance(txt, str) or len(txt) > 150_000:
            raise RecipeError(f"'{field}' must be text under 150 KB")
        if txt.count("{") != txt.count("}") or txt.count("(") != txt.count(")"):
            raise RecipeError(f"'{field}' has unbalanced brackets")
        if _FORBIDDEN_DIRECTIVES.search(txt):
            raise RecipeError(f"'{field}' uses a preprocessor directive that is not allowed (only #define)")
        if "void main" in txt:
            raise RecipeError(f"'{field}' must not define main()")
    if "c = vec4(" not in data["body"]:
        raise RecipeError("the body must set the output colour (c = vec4(...))")
    return {"name": name, "label": str(data.get("label") or name.capitalize())[:24],
            "desc": str(data.get("description") or "Made in the ccmod transition editor")[:120],
            "helpers": data["helpers"], "body": data["body"]}


def install_transition_export(path) -> dict:
    """Install a .ccmodtrans exported from the transition editor so it appears in CapCut's Transitions > ccmod category."""
    import json
    from . import transitions
    t = validate_transition_export(json.loads(Path(path).read_text(encoding="utf-8")))
    transitions.LIBRARY[t["name"]] = (t["label"], t["desc"], t["body"], t["helpers"])
    transitions.build(t["name"])
    d = Path(__file__).resolve().parent.parent / "recipes" / "transitions"
    d.mkdir(parents=True, exist_ok=True)
    keep = d / f"{t['name']}.ccmodtrans"
    if Path(path).resolve() != keep.resolve():
        keep.write_bytes(Path(path).read_bytes())
    return t


def _remember(kind: str, recipe: dict) -> None:
    """Keep the recipe in recipes/<kind>/<name>.json so the creation survives restarts and can be edited and rebuilt."""
    import json
    d = Path(__file__).resolve().parent.parent / "recipes" / kind
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{recipe['name']}.json").write_text(json.dumps(recipe, indent=2), encoding="utf-8")


def load_saved(kind: str) -> list[dict]:
    import json
    d = Path(__file__).resolve().parent.parent / "recipes" / kind
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


if __name__ == "__main__":
    import json
    import sys
    usage = "usage: python -m ccmod_sdk.creator blocks | effect <recipe.json> | transition <recipe.json> [--install]"
    if len(sys.argv) < 2:
        sys.exit(usage)
    if sys.argv[1] == "blocks":
        print(json.dumps({"effects": blocks_doc(), "transition_bases": {k: v[1] for k, v in BASES.items()},
                          "transition_overlays": {k: v[1] for k, v in OVERLAYS.items()}}, indent=2))
    elif sys.argv[1] in ("effect", "transition") and len(sys.argv) >= 3:
        recipe = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        install = "--install" in sys.argv
        try:
            if sys.argv[1] == "effect":
                out = install_effect(recipe) if install else build_effect(recipe)
            else:
                out = install_transition(recipe) if install else build_transition(recipe)
        except RecipeError as e:
            sys.exit(f"recipe error: {e}")
        print(out["main"] if "main" in out else out["body"])
    else:
        sys.exit(usage)
