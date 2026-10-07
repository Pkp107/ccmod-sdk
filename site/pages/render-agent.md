---
title: Render agent
section: Building
order: 80
---

# Render agent

The render agent is a small script ccmod injects into CapCut's **render process** (the one that draws effects). A normal effect sees one frame; the agent lifts that limit.

| Capability | What it gives you |
|---|---|
| **Uniform overrides** | Force any shader uniform by name, every frame, from a number or a formula |
| **Frame history** | Give a shader the *previous frame* as a texture: echo, trails, feedback, smear |
| **External feed** | A live picture from another program (Blender, a game, OpenCV, your own renderer) as a texture inside an effect |

```python
agent = self.ctx.render.agent()          # permission `render` (add `engine` so `t` follows the playhead)
agent.enable_history()                   # optional
feed = agent.external_feed(1280, 720)    # optional; create before start()
agent.set_uniform("u_amount", 0.7)
agent.drive("u_wobble", "sin(t * 4)")    # formula, see Expressions
agent.start()                            # attaches to CapCut's render process (a project must be open)

feed.write(rgba_bytes)                   # 1280*720*4 bytes, RGBA, bottom row first
...
agent.stop()
```

## In your shader

```glsl
uniform sampler2D u_ccmodPrev;   // last frame's output (needs enable_history())
uniform sampler2D u_ccmodExt;    // the external feed (needs external_feed())

void main() {
    vec4 now  = texture(u_inputTexture, uv0);
    vec4 prev = texture(u_ccmodPrev, uv0);
    FragColor = vec4(mix(now.rgb, prev.rgb, 0.85), 1.0);     // an echo trail
}
```

The agent binds the history texture to unit 15 and the feed to unit 14 (configurable in `build_script`), and restores CapCut's GL state after each draw.

## API

| Call | Notes |
|---|---|
| `set_uniform(name, value)` | `value` is a float or a list of 1 to 4. Names must be valid identifiers |
| `clear_uniform(name)` | stop overriding |
| `drive(name, formula, scale=1.0)` | evaluated every 30 ms with `t` = playhead seconds (or seconds since start) |
| `enable_history(on=True)` | |
| `external_feed(w, h)` | returns an `ExternalFeed`: `write(rgba)`, `close()`. Windows shared memory, max 4096x4096 |
| `start()` / `stop()` | `AgentError` if no CapCut render process is available |
| `stats`, `errors` | per-process counters (`over`, `histDraws`, `extUploads`, `errors`) and agent-side messages |

## Status: read this before relying on it

- **Uniform override** uses the same hooks as `scratch/ccmod_scrubtime.py`, which is proven on screen.
- **History** and **external feed** are new GL code. The injected script passes a JavaScript syntax check and the controller, the shared-memory feed and the messaging are unit-tested, but **neither has been seen rendering in CapCut yet**. Treat them as experimental. `agent.stats` tells you whether the hooks are firing (`histDraws`, `extUploads`).
- History holds the last frame *drawn by that program*, so while scrubbing it is the previously drawn frame, not strictly the previous timeline frame.
