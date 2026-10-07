"""Expression engine: safe evaluation, rejected syntax, sampling/thinning, baking onto a timeline."""
import json
import math

import pytest

from ccmod_sdk import expressions as ex
from ccmod_sdk.timeline import Timeline


def test_arithmetic_and_variables():
    f = ex.compile("50 + 10 * sin(t * pi) + p * 2")
    assert f(t=0.5, dur=2.0) == pytest.approx(50 + 10 + 0.5)
    assert ex.compile("i / n")(i=1, n=4) == 0.25
    assert ex.compile("1 if t > 1 else 0")(t=2) == 1 and ex.compile("1 if t > 1 else 0")(t=0) == 0
    assert ex.compile("clamp(t, 0, 1)")(t=5) == 1
    assert ex.compile("lerp(10, 20, 0.5)")() == 15
    assert ex.compile("ease_out(0.5)")() == pytest.approx(0.75) and ex.compile("bounce(1)")() == pytest.approx(1.0)
    assert ex.compile("audio(t)")(t=1, audio=lambda x: 0.4) == 0.4 and ex.compile("audio(t)")(t=1) == 0.0


def test_wiggle_is_bounded_and_repeatable():
    f = ex.compile("wiggle(3, 10, 7)")
    vals = [f(t=k / 10) for k in range(100)]
    assert all(-10 <= v <= 10 for v in vals) and vals == [f(t=k / 10) for k in range(100)]
    assert len(set(round(v, 3) for v in vals)) > 20


@pytest.mark.parametrize("bad", [
    "__import__('os').system('x')", "open('f')", "t.real", "[1,2][0]", "'text'", "lambda: 1", "t if", "unknown + 1",
    "nofunc(1)", "2 ** 9999", "(1).__class__", "x = 1", "sin(t, key=1)", "", "a" * 600, "True", "[i for i in t]",
])
def test_rejects_anything_that_is_not_a_formula(bad):
    with pytest.raises(ex.ExpressionError):
        ex.compile(bad)


def test_runtime_errors_are_reported_not_crashed():
    assert ex.compile("1 / (t - 1)")(t=1) == 0.0                     # division by zero yields 0, like a shader
    with pytest.raises(ex.ExpressionError):
        ex.compile("sin(1, 2)")(t=0)


def test_thin_keeps_curve_shape():
    line = [(k / 10, k / 10 * 3) for k in range(11)]
    assert ex.thin(line) == [line[0], line[-1]]
    s = ex.sample("sin(t * 6)", 2.0, fps=30)
    th = ex.thin(s, 0.01)
    assert 3 < len(th) < len(s)
    # linear interpolation of the thinned points stays within tolerance of every sample
    for t, v in s:
        a = max((p for p in th if p[0] <= t), key=lambda p: p[0])
        b = min((p for p in th if p[0] >= t), key=lambda p: p[0])
        lerp = a[1] if a[0] == b[0] else a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0])
        assert abs(lerp - v) <= 0.0101


def test_bake_writes_keyframes_on_the_clip(tmp_path):
    seg = lambda i, s: {"id": i, "material_id": "m", "speed": 1.0, "source_timerange": {"start": 0, "duration": 2_000_000},
                        "target_timerange": {"start": s, "duration": 2_000_000}, "common_keyframes": []}
    p = tmp_path / "draft_content.json"
    p.write_text(json.dumps({"duration": 4_000_000, "tracks": [{"type": "video", "segments": [seg("A", 0), seg("B", 2_000_000)]}]}))
    tl = Timeline.open(p)
    n = ex.bake(tl, "B", "scale", "1 + i * 0.5 + 0.1 * sin(t * 4)", fps=20)
    kf = tl.keyframes("B")["scale"]
    assert len(kf) == n > 4 and kf[0]["time"] == 0.0 and kf[-1]["time"] == pytest.approx(2.0)
    assert kf[0]["value"] == pytest.approx(1.5)                      # i = 1 for the second clip
    assert "scale" not in tl.keyframes("A")
    ex.bake(tl, "B", "scale", "2", fps=10)                           # clear=True replaces; constant thins to two keys
    assert len(tl.keyframes("B")["scale"]) == 2
    with pytest.raises(ex.ExpressionError):
        ex.bake(tl, "nope", "scale", "1")


def test_sampling_limits():
    with pytest.raises(ex.ExpressionError):
        ex.sample("t", 1e9, fps=30)
    with pytest.raises(ex.ExpressionError):
        ex.sample("t", 0)
