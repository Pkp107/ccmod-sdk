"""Creator: recipes -> shaders, validation, slider mapping, installs (through fake packages)."""
import re

import pytest

from ccmod_sdk import creator
from ccmod_sdk.creator import RecipeError, build_effect, build_transition


def _balanced(src: str) -> bool:
    return src.count("{") == src.count("}") and src.count("(") == src.count(")")


RETRO = {"name": "retro", "label": "Retro", "description": "Warm VHS look",
         "slider": {"label": "Amount", "controls": "scanlines.strength"},
         "blocks": [{"block": "wave", "amount": 0.01, "speed": 2}, {"block": "chromatic", "amount": 0.004},
                    {"block": "tint", "color": "#ffb060", "amount": 0.25}, {"block": "scanlines", "strength": 0.4},
                    {"block": "vignette", "strength": 0.5}]}


def test_effect_stages_order_and_slider_mapping():
    e = build_effect(RETRO)
    m = e["main"]
    assert _balanced(m) and m.startswith("void main()") and "FragColor" in m and "lm_take_effect_filter" in m
    assert m.index("sin(uv.y") < m.index("vec4 c =") < m.index("sin(uv0.y")                # uv, sample, colour
    assert "SharpenIntensity" in m and m.count("SharpenIntensity") == 1                        # exactly the controlled param
    assert e["animated"] and e["slider"] == "Amount" and e["name"] == "retro"
    assert "vec3(1.0, 0.690196, 0.376471)" in m                                               # #ffb060


def test_default_slider_is_first_numeric_param_and_static_effect_not_animated():
    e = build_effect({"name": "plain", "blocks": [{"block": "vignette"}, {"block": "grayscale"}]})
    assert "SharpenIntensity" in e["main"] and not e["animated"]
    assert e["slider"] == "Amount"


def test_second_use_of_a_block_can_be_controlled():
    r = {"name": "two", "slider": {"controls": "tint#2.amount"},
         "blocks": [{"block": "tint", "color": "#ff0000"}, {"block": "tint", "color": "#0000ff"}]}
    m = build_effect(r)["main"]
    assert m.count("SharpenIntensity") == 1 and m.index("vec3(1.0, 0.0, 0.0)") < m.index("SharpenIntensity")


@pytest.mark.parametrize("bad", [
    {"name": "Bad Name", "blocks": [{"block": "vignette"}]},
    {"name": "ok", "blocks": []},
    {"name": "ok", "blocks": [{"block": "nope"}]},
    {"name": "ok", "blocks": [{"block": "vignette", "strength": 5}]},
    {"name": "ok", "blocks": [{"block": "vignette", "strength": "lots"}]},
    {"name": "ok", "blocks": [{"block": "tint", "color": "red"}]},
    {"name": "ok", "blocks": [{"block": "chromatic"}, {"block": "chromatic"}]},
    {"name": "ok", "slider": {"controls": "grain.amount"}, "blocks": [{"block": "vignette"}]},
    {"name": "ok", "slider": {"controls": "vignette.nope"}, "blocks": [{"block": "vignette"}]},
    {"name": "ok", "slider": {"controls": "garbage"}, "blocks": [{"block": "vignette"}]},
])
def test_effect_validation(bad):
    with pytest.raises(RecipeError):
        build_effect(bad)


def test_no_recipe_value_can_inject_code():
    with pytest.raises(RecipeError):
        build_effect({"name": "ok", "blocks": [{"block": "tint", "color": "#ff0000; discard;"}]})
    with pytest.raises(RecipeError):
        build_effect({"name": "ok", "blocks": [{"block": "wave", "amount": "0.01); discard; ("}]})


def test_every_block_builds_with_defaults():
    for name, d in creator.BLOCKS.items():
        m = build_effect({"name": "t_" + name, "blocks": [{"block": name}]})["main"]
        assert _balanced(m), name
        assert not re.search(r"\{[a-z_]+\}", m), name                                          # no unfilled placeholder


def test_blocks_doc_lists_ranges():
    doc = {b["block"]: b for b in creator.blocks_doc()}
    assert doc["vignette"]["params"]["strength"] == {"default": 0.6, "min": 0.0, "max": 1.0}
    assert doc["tint"]["colors"] == {"color": "#ffb060"} and doc["chromatic"]["stage"] == "sample"


def test_transitions_build_for_every_base_and_overlay():
    for base in creator.BASES:
        r = {"name": "t_" + base, "base": {"type": base}, "overlays": [{"type": o} for o in creator.OVERLAYS]}
        t = build_transition(r)
        assert _balanced(t["body"]) and "c" in t["body"] and t["label"]
        assert "A(" in t["body"] and "B(" in t["body"]
    t = build_transition({"name": "whip", "base": {"type": "slide", "direction": "right"}, "overlays": [{"type": "flash", "strength": 0.5}]})
    assert "uv.x - p" in t["body"] and "0.5" in t["body"]


@pytest.mark.parametrize("bad", [
    {"name": "ok", "base": {"type": "teleport"}},
    {"name": "ok", "base": {"type": "slide", "direction": "sideways"}},
    {"name": "ok", "base": {"type": "wipe", "angle": 9999}},
    {"name": "ok", "base": {"type": "dissolve"}, "overlays": [{"type": "lasers"}]},
    {"name": "BAD", "base": {"type": "dissolve"}},
])
def test_transition_validation(bad):
    with pytest.raises(RecipeError):
        build_transition(bad)


def test_install_transition_registers_and_builds(tmp_path, monkeypatch):
    from ccmod_sdk import transitions
    built = []
    monkeypatch.setattr(transitions, "build", lambda key, d=None: built.append(key) or {})
    monkeypatch.setattr(creator, "_remember", lambda kind, recipe: None)
    monkeypatch.setitem(transitions.LIBRARY, "keepme", transitions.LIBRARY["slide"])
    t = creator.install_transition({"name": "mine", "base": {"type": "dissolve"}})
    assert built == ["mine"] and transitions.LIBRARY["mine"][0] == t["label"]
    transitions.LIBRARY.pop("mine")


# ---- transitions exported by the standalone editor (.ccmodtrans) ----
GOOD_EXPORT = {"format": "ccmod-transition", "version": 1, "name": "editor_demo", "label": "Editor Demo", "description": "d",
               "helpers": "#define AR (float(inputWidth) / float(inputHeight))\nfloat sat1(float x)\n{\n    return clamp(x, 0.0, 1.0);\n}\n",
               "body": "    float t = clamp(progress, 0.0, 1.0);\n    c = vec4(A(uv).x, B(uv).y, t, 1.0);\n"}


def test_editor_export_validation():
    t = creator.validate_transition_export(dict(GOOD_EXPORT))
    assert t["name"] == "editor_demo" and t["label"] == "Editor Demo" and "sat1" in t["helpers"]
    for patch in ({"format": "x"}, {"version": 2}, {"name": "Bad Name"}, {"body": "c = 1;"}, {"body": GOOD_EXPORT["body"] + "{"},
                  {"helpers": "#version 300 es\n"}, {"helpers": "void main() {}\n"}, {"helpers": "#include <x>\n"}, {"body": 5},
                  {"helpers": "x" * 200_000}):
        with pytest.raises(RecipeError):
            creator.validate_transition_export({**GOOD_EXPORT, **patch})
    with pytest.raises(RecipeError):
        creator.validate_transition_export([])


def test_editor_export_installs_with_helpers_before_main(tmp_path, monkeypatch):
    import json
    from ccmod_sdk import transitions
    f = tmp_path / "t.ccmodtrans"
    f.write_text(json.dumps(GOOD_EXPORT))
    built = []
    monkeypatch.setattr(transitions, "build", lambda key, d=None: built.append(key) or {})
    monkeypatch.setattr(creator, "Path", creator.Path)
    keep = creator.Path(creator.__file__).resolve().parent.parent / "recipes" / "transitions" / "editor_demo.ccmodtrans"
    try:
        creator.install_transition_export(f)
        assert built == ["editor_demo"]
        entry = transitions.LIBRARY["editor_demo"]
        assert len(entry) == 4 and entry[3].startswith("#define AR")
    finally:
        transitions.LIBRARY.pop("editor_demo", None)
        if keep.exists():
            keep.unlink()


def test_helpers_land_between_prelude_and_main():
    from ccmod_sdk import transitions
    assert transitions._HEAD.rstrip().endswith("float ease(float x) { return x * x * (3.0 - 2.0 * x); }") or "uniform float progress" in transitions._HEAD
    assert transitions._MAIN.startswith("void main() {") and "vec4 c;" in transitions._MAIN
    assert "void main" not in transitions._HEAD
