---
title: Making transitions
section: Building
order: 30
---

# Making transitions

Transitions are **fundamentally different from effects**: a transition shader sees **two clips** (the outgoing and the incoming) and a `progress` value that runs 0 to 1 across the cut. ccmod builds each transition as a clone of a cached CapCut transition package with your fragment shader swapped in, under a fabricated id.

## The shader contract

You write the body that sets `c`. ccmod provides this prelude:

| Name | Meaning |
|---|---|
| `uv` | Texture coordinate, 0..1 |
| `progress` | Raw 0..1 across the transition |
| `p` | `progress` after a smoothstep ease (`ease()` is available too) |
| `A(vec2)` | Sample the **outgoing** clip (coordinates clamped to the frame) |
| `B(vec2)` | Sample the **incoming** clip |
| `c` | `vec4` you assign. The final `gl_FragColor` is `vec4(c.rgb, 1.0)` |

Real, bundled examples:

```glsl
// Slide: the incoming clip pushes the outgoing one left
float x = uv.x + p;
c = x < 1.0 ? A(vec2(x, uv.y)) : B(vec2(x - 1.0, uv.y));
```

```glsl
// Pixel Dissolve: mosaic grows then shrinks, cut at the middle
float s = mix(2.0, 60.0, 1.0 - abs(p * 2.0 - 1.0));
vec2 g = floor(uv * s) / s + 0.5 / s;
c = mix(A(g), B(g), step(0.5, p));
```

```glsl
// Flash: bright flash on the cut
float f = 1.0 - abs(p * 2.0 - 1.0);
c = mix(A(uv), B(uv), step(0.5, p)) + vec4(vec3(f * f * 1.2), 0.0);
```

## Add one

Transitions are registered in a Python table: `label`, one-line description, shader body.

From a plugin or any script:

```python
from ccmod_sdk import transitions

transitions.LIBRARY["vsplit"] = ("Vertical Split", "Two halves slide apart", """
    float d = abs(uv.x - 0.5) * 2.0;
    c = d < p ? B(uv) : A(uv);
""")
transitions.build("vsplit")
```

`build` clones the template package, writes your shader, patches CapCut's zipped copy, and records the transition in `scratch/_cctrans_index.json`. Restart `ccmod_run.py` to refresh the grid. For a permanent addition, add the entry to `LIBRARY` in `ccmod_sdk/transitions.py` and run `python -m ccmod_sdk.transitions install`.

!!! warning "Template needed"
    Building clones a *cached stock transition*. If it isn't cached yet, `build` raises `FileNotFoundError`. Open CapCut's Transitions panel and apply any stock transition once, then retry.

## Rules

- Sample only through `A()` / `B()`; they clamp the UV so you don't read outside the frame.
- Use `progress` or `p` for timing; there is no time uniform for transitions.
- `p` is eased; use `progress` if you want linear motion.
- Tunables are just `const`s in your body. There is no live parameter for transitions.

## What the tile shows

The tile comes from the transition cover (`trans_<key>.png` in the assets folder; replace it freely). The panel shows CapCut's stock duration (2.0 s). The transition does run over the real clip overlap.

## Debugging

| Symptom | Cause |
|---|---|
| Hard cut, nothing animates | A compile error, or your shader doesn't depend on `p` / `progress` |
| Not in the Transitions grid | Check `python -m ccmod_sdk.transitions list`; restart `ccmod_run.py` |
