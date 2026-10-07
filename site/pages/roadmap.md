---
title: Roadmap
section: Project
order: 10
---

# Roadmap and what's possible

The goal: **give plugin authors enough control that CapCut can look and behave like a different editor**: a 3D tab with its own engine, new tools and icons, other software wired in, and at least as much control as After Effects.

The full, category-by-category comparison is on the [After Effects gap analysis](after-effects.html) page. This page is the short version.

## Possible today

| Capability | How |
|---|---|
| Single-pass shader effects (colour, warps, glitch, procedural, vignette, ...) | [Making effects](making-effects.html) |
| Two-clip transitions | [Making transitions](making-transitions.html) |
| New buttons, tabs, panels, any QML | `ctx.ui` |
| Restyle CapCut | [Themes](making-themes.html) |
| External programs described in JSON, results imported, commands exposed to AI | [External apps](external-apps.html) |
| AI agents drive CapCut | [MCP](mcp.html) |

## Built since this page was first written

| Tool | Where | Status |
|---|---|---|
| External app framework (JSON specs, import, MCP tools) | [External apps](external-apps.html) | built, tested with stand-in programs |
| Timeline API (clips, keyframes, split, trim, move) | [Timeline API](timeline-api.html) | built; real drafts round-trip; not yet opened in CapCut after an edit |
| Multi-pass effects (glow, bloom, soft focus) | [Making effects](making-effects.html#multi-pass-effects-blur-glow-bloom) | built; render not yet seen on screen |
| Creator (effects and transitions from blocks, AI-callable) | [Creator](creator.html) | built; Loader visual editor not built |
| Expression engine (formulas baked to keyframes) | [Expressions](expressions.html) | built and tested |
| Render agent (uniforms, frame history, live textures) | [Render agent](render-agent.html) | uniforms use a proven technique; history and feed are experimental |
| UI toolkit (panels with sliders, toggles, dropdowns) | [UI toolkit](ui-toolkit.html) | built; compiled and clicked in Qt 6; not yet seen inside CapCut |
| Transition editor (standalone app: keyframes, graphs, 33 easings, 1:1 workspace) | [Transition editor](transition-editor.html) | built; exports to ccmod; not yet seen playing in CapCut. Effect editor is next |

## Still needed, in this order

Live (not draft-file) timeline edits; a visual creator and a node-based shader graph in the Loader; docked panels, tabs and saved workspaces; an audio bridge; a third shader pass; a ReShade/Shadertoy importer.

## Needs a tool we haven't built yet

| Missing tool | Unlocks | Route letter |
|---|---|---|
| **Multi-pass shaders** (format supports it; none shipped) | Blur, glow, bloom | B |
| **Render agent** (a hook in CapCut's render process) | Echo, trails, feedback, live textures from other programs | H |
| **Timeline API** (read/write tracks, clips, keyframes live) | Expressions, scripting, automation, rigs | K |
| **Texture feed** | Live 3D and particle engines in the preview | 3D |
| **Expression engine** | After Effects-style property expressions | K |
| **Effect and transition creator** in the Loader | Make effects without hand-writing code | U |

Route letters are explained in the [gap analysis](after-effects.html#2-route-legend).

## Not verified yet

MCP with a real client; audio scrub behaviour; `ctx.process` against a real app; the Blender bridge end to end; layout-changing themes; multi-pass shaders; the transitions extras tab.

## Help wanted

- Try the unverified items above and report what you see.
- Effects and transitions (see [Making effects](making-effects.html)).
- Themes, especially full-layout ones (an After Effects-style workspace is the dream).
- Support for CapCut builds newer than 8.9.1.
