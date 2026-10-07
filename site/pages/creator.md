---
title: Creator (no code)
section: Building
order: 15
---

# Creator: effects and transitions without code

Describe an effect or transition from building blocks and ccmod writes the shader, builds the package and installs it. No GLSL.

## An effect

An effect is a list of **blocks**. They run in three stages: `uv` blocks bend the coordinates, the picture is sampled (`chromatic` replaces the plain sample), then `color` blocks grade the pixels.

```json
{ "name": "retro", "label": "Retro", "description": "Warm VHS look",
  "slider": { "label": "Scan", "controls": "scanlines.strength" },
  "blocks": [
    { "block": "wave", "amount": 0.01, "speed": 2 },
    { "block": "chromatic", "amount": 0.004 },
    { "block": "tint", "color": "#ffb060", "amount": 0.25 },
    { "block": "scanlines", "strength": 0.4 },
    { "block": "vignette", "strength": 0.5 }
  ] }
```

`slider.controls` names the parameter the CapCut slider (0..1) drives across its range: `block.param`, or `tint#2.amount` for the second tint. Without it the slider drives the first block's first number.

| Stage | Blocks |
|---|---|
| `uv` | `mirror`, `pixelate`, `wave`, `shake`, `zoom`, `rotate`, `swirl`, `kaleido`, `slide` |
| `sample` | `chromatic` (at most one) |
| `color` | `grayscale`, `invert`, `brightness`, `contrast`, `saturation`, `vignette`, `scanlines`, `grain`, `posterize`, `tint`, `duotone` |

Every parameter has a default and a range (out-of-range values are rejected). List them all with `python -m ccmod_sdk.creator blocks` or the MCP tool `ccmod_create_blocks`.

## A transition

```json
{ "name": "whip", "label": "Whip", "description": "Fast slide with RGB split",
  "base": { "type": "slide", "direction": "left" },
  "overlays": [ { "type": "rgbsplit", "amount": 0.04 }, { "type": "flash", "strength": 0.4 } ] }
```

| Base | Options |
|---|---|
| `slide` | `direction`: left, right, up, down |
| `wipe` | `angle` 0..360, `softness` 0.01..0.5 |
| `zoom` | `amount` 0.2..3 |
| `spin` | `turns` 0.1..2 |
| `dissolve` | none |
| `split` | `axis`: vertical, horizontal |
| `pixelate` | `max_blocks` 8..120 |

Overlays: `flash` (`strength`), `rgbsplit` (`amount`), `shake` (`amount`).

## Using it

```bash
python -m ccmod_sdk.creator effect retro.json              # print the shader
python -m ccmod_sdk.creator effect retro.json --install    # build + install
python -m ccmod_sdk.creator transition whip.json --install
python ccmod_api.py create effect retro.json               # same, as the Loader/scripts call it
```

From Python: `creator.build_effect(recipe)`, `creator.install_effect(recipe)`, `creator.build_transition(recipe)`, `creator.install_transition(recipe)`. Installed recipes are saved in `recipes/effects` and `recipes/transitions` so you can edit and rebuild them.

**From an AI:** the MCP tools `ccmod_create_blocks`, `ccmod_create_effect` and `ccmod_create_transition` let an assistant design effects for you ("make a warm VHS look with a slider for scanline strength").

## Safety

Nothing in a recipe is executed. Every value is converted to a number or `#rrggbb` colour and range-checked before it reaches the shader, so a recipe cannot inject code. Bad recipes raise `RecipeError` with the reason.

## Status

Recipes build and install, and the generated shaders were read through, but only the hand-written library effects have been seen rendering in CapCut. Restart `ccmod_run.py` after creating something so the grid picks it up, and report any block that renders wrong. A visual editor page in the Loader is not built yet; the JSON recipe is the interface for now.
