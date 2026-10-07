---
title: Home
section: Getting started
order: 0
---

# ccmod

**ccmod is a plugin platform for CapCut Desktop.** It runs next to CapCut on your PC and lets you add what CapCut doesn't have:

- **Your own effects and transitions**, written in GLSL, that show up in CapCut's *real* Effects and Transitions panels (a **ccmod** category) and drag onto the timeline like any stock effect.
- **New buttons, tabs and panels** anywhere in the editor, whose clicks run your Python code.
- **Themes** that recolour and restyle the whole CapCut UI, live and reversible.
- **Tools** that AI agents can call through **MCP**, and that your own plugins can expose.
- **External apps**: hand work to Blender, ffmpeg or any program, then import the result straight into CapCut's media pool.

!!! warning "Unofficial, research-grade"
    ccmod is independent and not affiliated with CapCut or ByteDance. It injects into a running CapCut process, which may violate CapCut's terms. Use it at your own risk, on software you own. It currently targets **CapCut 8.9.1.3802** on Windows.

!!! danger "Additive only"
    ccmod never touches the watermark, Pro/subscription features, accounts, licensing or payment, and the SDK has no API for any of them. Plugins that try are not accepted. See [Safety rules](safety.html).

## Start here

| I want to... | Read |
|---|---|
| Install ccmod (double-click setup) and open CapCut with it | [Install](install.html), then [Quick start](quickstart.html) |
| Use the Loader app | [The Loader](loader.html) |
| Use the effects and transitions that ship with ccmod | [Using effects & transitions](using-effects.html) |
| Change how CapCut looks | [Themes](themes.html) |
| Let Claude or another AI drive CapCut | [MCP](mcp.html) |
| Write my first plugin | [Your first plugin](first-plugin.html) |
| Design a transition visually (keyframes, graphs, easing) | [Transition editor](transition-editor.html) |
| Make an effect or transition with no code | [Creator](creator.html) |
| Make my own effect | [Making effects](making-effects.html) |
| Make my own transition | [Making transitions](making-transitions.html) |
| Make my own theme | [Making themes](making-themes.html) |
| Connect Blender, ffmpeg or any program | [External apps](external-apps.html) |
| Edit clips and keyframes from code | [Timeline API](timeline-api.html), [Expressions](expressions.html) |
| Echo, trails, live textures in an effect | [Render agent](render-agent.html) |
| Build panels and controls inside CapCut | [UI toolkit](ui-toolkit.html) |
| Look up every API call | [SDK reference](sdk-reference.html) |
| Know what's possible vs After Effects | [Roadmap & After Effects gap](roadmap.html) |

## What works today

| Capability | Status |
|---|---|
| Custom effects in the real Effects grid, drag to apply, own slider | proven on screen |
| Custom transitions in the real Transitions grid | proven on screen |
| Buttons that call Python | proven on screen |
| Themes (colours, radii), live apply/revert | proven on screen |
| Import a file into CapCut's media pool from Python | proven on screen |
| MCP server and tool server | built, handshake tested; not yet tried with a real MCP client |
| `ctx.process` (run Blender etc.) | built, unit-tested; not tried against a real app |
| Multi-pass shaders, frame history, live timeline editing | not yet; see [Roadmap](roadmap.html) |

Every page marks what is proven and what is not, so you know where the edges are.
