"""Expressions: drive a property with a formula, After Effects style, and bake it to keyframes.

    from ccmod_sdk import expressions
    f = expressions.compile("50 + wiggle(2, 10)")       # raises ExpressionError if it is not a safe formula
    f(t=1.25)                                           # evaluate at 1.25 s

    tl = Timeline.open("0216")
    expressions.bake(tl, clip_id, "scale", "1 + 0.2 * sin(t * 6)", fps=30)      # writes keyframes (thinned)
    tl.save()

Formulas are plain arithmetic over these names. Nothing else is allowed (no attributes, indexing, imports, loops or strings):

    t        seconds from the clip's start          dur     the clip's length in seconds
    p        progress through the clip, 0..1        i / n   this clip's index / the number of clips (for staggers)
    pi, e    constants

    sin cos tan asin acos atan atan2 sqrt abs min max floor ceil round pow exp log
    clamp(x, lo, hi)  lerp(a, b, k)  smoothstep(e0, e1, x)  step(edge, x)  fract(x)  mod(a, b)
    linear(p)  ease_in(p)  ease_out(p)  ease_in_out(p)  bounce(p)  back(p)         easing curves on 0..1
    noise(x)   smooth value noise, 0..1            wiggle(freq, amp, seed=0)   random motion in -amp..amp
    audio(t)   loudness 0..1 at time t, from the provider passed to bake(audio=...) (0 when none)

`**` is not allowed; use pow(). `if` is written `a if cond else b`; comparisons and and/or/not work.
"""
from __future__ import annotations

import ast
import math
from typing import Callable

MAX_NODES = 200
MAX_SAMPLES = 20000


class ExpressionError(ValueError):
    pass


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _smoothstep(e0, e1, x):
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    k = _clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return k * k * (3 - 2 * k)


def _hash(n: int, seed: float) -> float:
    x = math.sin(n * 127.1 + seed * 311.7) * 43758.5453
    return x - math.floor(x)


def _noise(x, seed=0.0):
    i = math.floor(x)
    f = x - i
    u = f * f * (3 - 2 * f)
    return _hash(i, seed) * (1 - u) + _hash(i + 1, seed) * u


def _bounce(p):
    p = _clamp(p, 0.0, 1.0)
    d, n = 2.75, 7.5625
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


def _back(p):
    p = _clamp(p, 0.0, 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


FUNCS: dict[str, Callable] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": lambda x: math.asin(_clamp(x, -1, 1)), "acos": lambda x: math.acos(_clamp(x, -1, 1)),
    "atan": math.atan, "atan2": math.atan2, "sqrt": lambda x: math.sqrt(max(x, 0.0)), "abs": abs, "min": min, "max": max,
    "floor": math.floor, "ceil": math.ceil, "round": round, "exp": lambda x: math.exp(_clamp(x, -50, 50)),
    "log": lambda x: math.log(max(x, 1e-12)), "pow": lambda a, b: math.pow(a, _clamp(b, -20, 20)) if not (a < 0 and b != int(b)) else 0.0,
    "clamp": _clamp, "lerp": lambda a, b, k: a + (b - a) * k, "smoothstep": _smoothstep, "step": lambda e, x: 0.0 if x < e else 1.0,
    "fract": lambda x: x - math.floor(x), "mod": lambda a, b: a % b if b else 0.0,
    "linear": lambda p: _clamp(p, 0.0, 1.0),
    "ease_in": lambda p: _clamp(p, 0.0, 1.0) ** 2, "ease_out": lambda p: 1 - (1 - _clamp(p, 0.0, 1.0)) ** 2,
    "ease_in_out": lambda p: (lambda q: 2 * q * q if q < 0.5 else 1 - (-2 * q + 2) ** 2 / 2)(_clamp(p, 0.0, 1.0)),
    "bounce": _bounce, "back": _back, "noise": _noise,
}
CONSTS = {"pi": math.pi, "e": math.e}
VARS = ("t", "dur", "p", "i", "n")
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b else 0.0, ast.Mod: lambda a, b: a % b if b else 0.0, ast.FloorDiv: lambda a, b: a // b if b else 0.0}
_CMP = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


class Compiled:
    def __init__(self, source: str, tree: ast.Expression):
        self.source, self._tree = source, tree

    def __call__(self, t: float = 0.0, dur: float = 1.0, i: int = 0, n: int = 1, audio: Callable[[float], float] | None = None) -> float:
        env = {"t": float(t), "dur": float(dur), "p": (float(t) / dur) if dur else 0.0, "i": float(i), "n": float(n), **CONSTS}
        funcs = dict(FUNCS)
        funcs["audio"] = (lambda x: float(audio(x))) if audio else (lambda x: 0.0)
        funcs["wiggle"] = lambda freq, amp, seed=0.0: (_noise(env["t"] * freq, seed) * 2 - 1) * amp
        try:
            return float(_eval(self._tree.body, env, funcs))
        except ExpressionError:
            raise
        except (ArithmeticError, ValueError, TypeError) as e:
            raise ExpressionError(f"cannot evaluate {self.source!r} at t={t}: {e}") from None


def _eval(node, env, funcs):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise ExpressionError(f"unknown name {node.id!r}")
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, funcs)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.Not):
            return not v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, env, funcs), _eval(node.right, env, funcs))
    if isinstance(node, ast.BoolOp):
        vals = (_eval(v, env, funcs) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, funcs)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env, funcs)
            if type(op) not in _CMP or not _CMP[type(op)](left, right):
                if type(op) not in _CMP:
                    raise ExpressionError("unsupported comparison")
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env, funcs) if _eval(node.test, env, funcs) else _eval(node.orelse, env, funcs)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        f = funcs.get(node.func.id)
        if f is None:
            raise ExpressionError(f"unknown function {node.func.id!r}")
        return f(*[_eval(a, env, funcs) for a in node.args])
    raise ExpressionError(f"not allowed in a formula: {type(node).__name__}")


def compile(source: str) -> Compiled:
    """Parse and check a formula. Raises ExpressionError for anything that is not plain arithmetic over the allowed names."""
    source = str(source).strip()
    if not source or len(source) > 500:
        raise ExpressionError("a formula must be 1 to 500 characters")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"syntax error: {e.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExpressionError("formula is too complicated")
    known = set(VARS) | set(CONSTS)
    for n in nodes:
        if isinstance(n, ast.Name) and n.id not in known and n.id not in FUNCS and n.id not in ("audio", "wiggle"):
            raise ExpressionError(f"unknown name {n.id!r}")
        if isinstance(n, ast.Pow):
            raise ExpressionError("'**' is not allowed; use pow(a, b)")
    c = Compiled(source, tree)
    c(t=0.0, dur=1.0)                                        # dry run: surfaces unsupported syntax immediately
    return c


def sample(source: str, duration: float, fps: float = 30.0, i: int = 0, n: int = 1, audio: Callable[[float], float] | None = None) -> list[tuple[float, float]]:
    """[(t, value)] over the clip, one per frame plus the last instant."""
    f = compile(source)
    if duration <= 0 or fps <= 0:
        raise ExpressionError("duration and fps must be positive")
    steps = max(1, int(round(duration * fps)))
    if steps > MAX_SAMPLES:
        raise ExpressionError("too many frames to sample")
    return [(k * duration / steps, f(t=k * duration / steps, dur=duration, i=i, n=n, audio=audio)) for k in range(steps + 1)]


def thin(points: list[tuple[float, float]], tolerance: float = 1e-3) -> list[tuple[float, float]]:
    """Drop points that a straight line between their neighbours reproduces within `tolerance` (keeps the first and last)."""
    if len(points) <= 2:
        return points
    keep = [points[0]]
    anchor = 0
    for k in range(2, len(points)):
        a, b = points[anchor], points[k]
        for m in range(anchor + 1, k):
            tm, vm = points[m]
            expect = a[1] + (b[1] - a[1]) * ((tm - a[0]) / (b[0] - a[0])) if b[0] != a[0] else a[1]
            if abs(expect - vm) > tolerance:
                keep.append(points[k - 1])
                anchor = k - 1
                break
    keep.append(points[-1])
    return keep


def bake(timeline, clip_id: str, prop: str, source: str, fps: float = 30.0, tolerance: float = 1e-3,
         audio: Callable[[float], float] | None = None, clear: bool = True) -> int:
    """Evaluate `source` across the clip and write it as keyframes on `prop`. Returns the number of keyframes written.
    `t` in the formula is seconds from the clip's start; `i`/`n` are the clip's index among all clips on its track."""
    clips = timeline.clips()
    clip = next((c for c in clips if c.id == clip_id), None)
    if clip is None:
        raise ExpressionError(f"no clip {clip_id!r}")
    same = [c for c in clips if c.track_index == clip.track_index]
    pts = thin(sample(source, clip.duration, fps, i=[c.id for c in same].index(clip_id), n=len(same), audio=audio), tolerance)
    if clear:
        timeline.clear_keyframes(clip_id, prop)
    for t, v in pts:
        timeline.add_keyframe(clip_id, prop, min(t, clip.duration), v)
    return len(pts)
