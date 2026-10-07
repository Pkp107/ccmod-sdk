---
title: Making effects
section: Building
order: 20
---

# Making effects

A ccmod effect is a **fragment shader** (GLSL) plus a slider label. ccmod wraps it in a CapCut effect package under a fabricated id, so it needs no donor effect and no download, and it appears in the ccmod grid.

## The shader contract

You write only `main()`. ccmod supplies the rest of the program around it. Available names:

| Name | Type | Meaning |
|---|---|---|
| `uv0` | `vec2` | The pixel's texture coordinate, 0..1 |
| `u_inputTexture` | `sampler2D` | The clip's frame. Sample with `texture(u_inputTexture, uv)` |
| `SharpenIntensity` | `float` | **Your slider**, 0..1 (the name is historical: it is the package's slider uniform) |
| `iTime` | `float` | Seconds. **Advances during playback, not while scrubbing** |
| `LutIntensity`, `u_lut`, `lm_take_effect_filter(u_lut, c, LutIntensity)` | | CapCut's filter pass-through; apply it to `c` so CapCut's own filter slot keeps working |
| `FragColor` | `vec4` | Output |

You can define helper functions above `main()` in the same source.

### A complete effect

```glsl
// Vignette: darken the edges; the slider sets how much.
void main() {
    vec4 c = texture(u_inputTexture, uv0);
    float d = distance(uv0, vec2(0.5));
    float v = smoothstep(0.85, 0.25, d);
    c.rgb *= mix(1.0, v, SharpenIntensity);
    c = lm_take_effect_filter(u_lut, c, LutIntensity);
    FragColor = clamp(vec4(c.rgb, 1.0), 0.0, 1.0);
}
```

### Picking one of N modes with the slider

The flagship `easedown` effect maps the slider to eight easing curves:

```glsl
int et = int(clamp(SharpenIntensity, 0.0, 0.999) * 8.0);   // 0..7
```

### Animation

```glsl
float p = fract(iTime * 0.35);   // looping 0..1
```

!!! warning "iTime and scrubbing"
    `iTime` moves when the clip *plays*. While you drag the playhead it does not advance, so animated effects look still when scrubbing. Test animation by playing.

## Package it

Two files in a zip with the extension `.ccpack`:

`manifest.json`
```json
{ "schema": "ccfx-1", "name": "myvignette", "type": "effect",
  "slider": "Strength", "desc": "Darkened edges" }
```

`shader.frag`: the source above (must contain `void main()`).

Make it with any zip tool, or from Python:

```python
import json, zipfile
with zipfile.ZipFile("myvignette.ccpack", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.json", json.dumps({"schema": "ccfx-1", "name": "myvignette", "type": "effect",
                                            "slider": "Strength", "desc": "Darkened edges"}))
    z.writestr("shader.frag", open("vignette.frag").read())
```

## Install it

```bash
python scratch/ccfx.py installpack myvignette.ccpack
```

or Loader, Effects page, Import. Then restart `ccmod_run.py` so the grid picks it up. It appears in **Effects > ccmod**.

## Built-in library route (for contributors)

Effects in `scratch/ccfx.py`'s `LIBRARY` dict ship with ccmod:

```python
"myvignette": {"slider": "Strength", "desc": "Darkened edges", "main": """void main() { ... }"""},
```

`python scratch/ccfx.py install myvignette`. `python scratch/ccfx.py pack myvignette out.ccpack` exports it.

## Covers

Each tile gets a generated cover in the ccmod assets folder. Replace `<name>.png` with your own picture (it is never overwritten), or use the Loader's cover button.

## Debugging

| Symptom | Likely cause |
|---|---|
| Renders as black or the clip unchanged | A GLSL compile error. The shader fails silently; simplify and bisect |
| Upside down | Flip `uv.y = 1.0 - uv.y` when sampling an extra texture |
| Slider does nothing | You aren't reading `SharpenIntensity` |
| Looks still | It depends on `iTime` and you are scrubbing; press play |
| Not in the grid | Run `python scratch/ccfx.py list`; restart `ccmod_run.py`; check it says installed |

## Multi-pass effects (blur, glow, bloom)

CapCut's effect package is a two-pass pipeline: pass 1 blurs horizontally into an intermediate texture; pass 2 gets the original (`u_inputTexture`) and that intermediate (`u_albedo`). ccmod lets an effect replace **both** shaders:

- `main` is pass 2. Call `ccmodBlur(uv0)` (finishes the gaussian vertically) to get a fully blurred copy, then combine it with the original.
- `pass1` (optional) is the main of pass 1; it can reshape the input before blurring (bloom uses it as a bright-pass).
- `radius` is the blur size in pixels.

Three ship in the library (`glow`, `softfocus`, `bloom`; see `ccmod_sdk/multipass.py`):

```glsl
void main() {                                  // glow
    vec4 c = texture(u_inputTexture, uv0);
    vec4 b = ccmodBlur(uv0);
    c.rgb = 1.0 - (1.0 - c.rgb) * (1.0 - b.rgb * SharpenIntensity * 1.6);    // screen blend
    c = lm_take_effect_filter(u_lut, c, LutIntensity);
    FragColor = clamp(vec4(c.rgb, 1.0), 0.0, 1.0);
}
```

A `.ccpack` can carry them too: add `pass1.frag` and `"radius": 18` to the manifest. Status: the packages build and patch both shaders (tested), on a pass structure CapCut itself uses for Sharpen Edges; an on-screen render of these three hasn't been seen yet.

## Effects with no code, with history, or with live textures

- [Creator](creator.html): build an effect from blocks, or let an AI do it.
- [Render agent](render-agent.html): previous-frame and live external textures (`u_ccmodPrev`, `u_ccmodExt`).

## What you cannot do yet

- **More than two passes.** The template has two; a third needs a new package skeleton.
- **Past frames** need the experimental [render agent](render-agent.html).
- **More than one slider** per effect.
- **Extra input textures** such as a lookup image.

For a one-pass look, though, almost anything colour- or warp-based is fair game: grades, glitches, distortions, procedural patterns, vignettes, chromatic aberration.
