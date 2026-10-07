---
title: Expressions
section: Building
order: 70
---

# Expressions

Drive a property with a formula, After Effects style, and **bake** it into keyframes.

```python
from ccmod_sdk import expressions

f = expressions.compile("1 + 0.2 * sin(t * 6)")      # ExpressionError if it isn't a safe formula
f(t=0.5)                                              # evaluate once

tl = self.ctx.draft.timeline("0216")
self.ctx.draft.bake(tl, clip_id, "scale", "1 + 0.2 * sin(t * 6)", fps=30)
tl.save()
```

Baking samples the formula once per frame, **thins** points a straight line reproduces (so a constant becomes two keyframes), and writes them with the [Timeline API](timeline-api.html).

## The language

Plain arithmetic: `+ - * / %`, comparisons, `and or not`, and `a if cond else b`. No `**` (use `pow`), no attributes, indexing, strings, lambdas, loops or imports. Anything else raises `ExpressionError` before anything runs. Formulas are limited to 500 characters and 200 syntax nodes, and division by zero yields 0, as in a shader.

| Name | Meaning |
|---|---|
| `t` | seconds from the clip's start |
| `dur`, `p` | clip length in seconds; progress 0..1 |
| `i`, `n` | this clip's index and the count of clips on its track (for staggers) |
| `pi`, `e` | constants |

| Functions | |
|---|---|
| maths | `sin cos tan asin acos atan atan2 sqrt abs min max floor ceil round pow exp log` |
| shaping | `clamp(x,lo,hi) lerp(a,b,k) smoothstep(e0,e1,x) step(edge,x) fract(x) mod(a,b)` |
| easing (on 0..1) | `linear ease_in ease_out ease_in_out bounce back` |
| motion | `noise(x)` smooth 0..1; `wiggle(freq, amp, seed=0)` random motion in `-amp..amp`, repeatable |
| audio | `audio(t)` loudness 0..1 from the provider you pass to `bake(audio=...)`; 0 if none |

Examples:

| Effect | Formula |
|---|---|
| Pulse | `1 + 0.1 * sin(t * 8)` |
| Handheld wobble | `wiggle(2, 8)` |
| Staggered fade-in across clips | `clamp((t - i * 0.2) / 0.5, 0, 1)` |
| Bounce in | `bounce(p)` |
| Beat-driven scale | `1 + audio(t) * 0.4` |

## Live drivers

For uniform values driven while CapCut plays (not baked), the [render agent](render-agent.html) accepts the same formulas: `agent.drive("u_amount", "0.5 + 0.5 * sin(t)")`.
