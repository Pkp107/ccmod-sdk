---
title: Using effects & transitions
section: Using ccmod
order: 20
---

# Using effects & transitions

## What ships

**Effects** (shader effects, one slider each):

| Key | Slider | Look |
|---|---|---|
| `easedown` | Ease | Looping down-slide whose motion follows the chosen easing curve. The flagship |
| `easegraph` | Ease | Draws the chosen easing curve as a graph (a visual picker for the curve) |
| `chromatic` | Aberration | RGB channel split |
| `vignette` | Strength | Darkened edges |
| `pixelate` | Blocks | Mosaic |
| `duotone` | Mix | Two-tone grade |
| `mirror` | Amount | Kaleidoscope mirror |
| `scanlines` | Intensity | VHS scanlines with slight RGB shift |
| `shake`, `pulse`, `wave`, `strobe`, `rgbdrift` | Amount / Depth / Intensity | Animated effects driven by time |

(`gradtest` and `scrubtest` are diagnostics for developers.)

**Transitions**: Slide, Zoom, Glitch, Wipe, Flash, Spin, Pixel Dissolve, Swing.

**Easing curves** (the `Ease` slider picks one of eight): linear, ease-in, ease-out, ease-in-out, cubic-in, cubic-out, bounce, back (overshoot).

![Installed effects in the Loader](assets/loader-effects.png)

## Installing them

```bash
python scratch/ccfx.py install easedown chromatic pixelate     # effects
python -m ccmod_sdk.transitions install                        # all 8 transitions
python scratch/ccfx.py list                                    # what exists / is installed
```

or use the **Effects** page of the [Loader](loader.html), or the MCP tool `ccmod_install`.

After installing, restart `ccmod_run.py` (or press the Loader's refresh) so the grid rules are rebuilt before CapCut asks for the panel.

## Using them in CapCut

1. **Effects** (or **Transitions**) tab, then the **ccmod** category.
2. Drag a tile onto a clip (or between two clips for transitions).
3. Use the slider in the right-hand panel.

Each tile keeps a real CapCut id behind the scenes (CapCut drops tiles with unknown ids). ccmod pins which stock tile each of your effects borrows (`pins.json`), so the assignment is stable between launches.

## Sharing effects

Export an effect as a single portable file, import someone else's:

```bash
python scratch/ccfx.py pack chromatic chromatic.ccpack       # export
python scratch/ccfx.py installpack chromatic.ccpack          # import
```

The Loader's Effects page has Import and Export buttons for the same thing. A `.ccpack` (schema `ccfx-1`) is a zip of `manifest.json` and `shader.frag`; see [Making effects](making-effects.html).

## Known limits

- Pinned to CapCut **8.9.1**. Other builds can show passthrough.
- One slider per effect. A custom-named slider shows on the applied clip; custom keys are dropped on the grid tile path.
- Transitions show CapCut's stock duration (2.0 s) in the panel.
- Effects see the current frame only (no frame history yet), see [Roadmap](roadmap.html).
