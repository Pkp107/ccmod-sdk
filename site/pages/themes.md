---
title: Themes
section: Using ccmod
order: 30
---

# Themes

A ccmod theme restyles **CapCut itself**, not the Loader: panel colours, accent colour, corner radii, and (with rules) visibility and other properties of individual UI items. It applies live, can be reverted instantly, and is remembered for your next launches.

## Bundled themes

| Theme | Look |
|---|---|
| Graphite | Cool graphite panels, light CapCut blue |
| Midnight | Deep navy |
| Crimson | Dark with red accent |
| Aurora | Dark teal/green |
| Studio | Neutral dark, high contrast |

![The Themes page in the Loader](assets/loader-themes.png)

## Applying

- **Loader**: Themes page, pick a card; **Revert** goes back to stock.
- **MCP / tools**: `ccmod_theme_apply {"id": "midnight"}`, `ccmod_theme_revert`, `ccmod_themes`.
- **Python**: `ctx.ui.apply_theme("midnight")` / `ctx.ui.revert_theme()`.
- **From a shell**: `python ccmod_api.py theme-apply midnight`.

The `ccmod-themes` plugin re-applies your saved theme every time an editor opens (the engine lives inside the editor window). The choice is stored in `plugin-state/theme.json`.

## How it works

ccmod injects one small QML object, the *theme engine*, into the editor. A theme is pushed in as JSON. The engine walks CapCut's live UI tree and, for every item whose colour you mapped (or that matches a rule), installs a QML `Binding` with `restoreMode: RestoreBindingOrValue`. Reverting switches the bindings off and CapCut's own values return. The tree is rescanned every 2 seconds so panels that open later are themed too.

Build your own: [Making themes](making-themes.html).

!!! note "What's proven"
    Colour remapping and corner radii are proven on screen. Layout changes (moving/hiding items) use the same rules engine but haven't been shown on screen yet.
