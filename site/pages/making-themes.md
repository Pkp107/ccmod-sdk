---
title: Making themes
section: Building
order: 40
---

# Making themes

A theme is a folder `themes/<id>/` with a `theme.json`. The Loader and `ctx.ui.themes()` discover it automatically; invalid themes are skipped.

```json
{
  "id": "ember",
  "name": "Ember",
  "author": "you",
  "version": "1.0.0",
  "description": "Warm dark.",
  "preview": { "background": "#241c1a", "accent": "#ff8a3d" },
  "colors": {
    "#262626": "#241c1a",
    "#00c1cd": "#ff8a3d"
  },
  "rules": [
    { "match": { "type": "QQuickRectangle", "radiusMin": 3 }, "set": { "radius": 2 } }
  ],
  "qml": []
}
```

## Colours

`colors` maps one exact colour to another, applied to every `Rectangle`/`Text` colour and `border.color`. CapCut's UI uses a small palette. The key ones:

| Colour | Where |
|---|---|
| `#262626` | main panel |
| `#1c1c1c`, `#1b1b1c` | darker panels |
| `#141414` | timeline / deep background |
| `#070709` | window backdrop |
| `#303030`, `#3b3b3b`, `#4f4f4f` | raised surfaces and borders |
| `#00c1cd` | accent |

Always remap `#262626` and `#00c1cd` at least. The test suite requires bundled themes to.

## Rules

A rule picks UI items and sets properties on them.

```json
{ "match": { "type": "QQuickRectangle", "objectName": "panel*", "color": "#303030", "radiusMin": 3 },
  "set":   { "radius": 0, "opacity": 0.9 } }
```

| `match` key | Meaning |
|---|---|
| `type` | QML type name, for example `QQuickRectangle`, `QQuickText` |
| `objectName` | exact name, or a prefix ending in `*` |
| `color` | only items currently of that colour |
| `radiusMin` | only items whose `radius` is at least this |

`set` values can be any property: `radius`, `visible`, `opacity`, `x`, `width`... Because every change is a QML `Binding` with `RestoreBindingOrValue`, **reverting always restores CapCut's own values**.

## Find things to restyle

With CapCut and ccmod running:

```python
ctx.ui.inspect(type="QQuickRectangle", limit=40)
ctx.ui.inspect(objectName="MainTimeLine*")
```

Each line lists the item type, its objectName, position and size. Or call it over MCP via the live tools.

## Adding your own QML

`qml` is a list of `{ "file": "extra.qml", "parent": "<selector>" }` entries. Each file is injected under the selector when the theme applies. This is how a theme can add new UI (a banner, a custom toolbar) rather than only restyle.

## Try it

```bash
python ccmod_api.py theme-apply ember
python ccmod_api.py theme-revert
```

## Limits

- Colour and radius changes are proven. Moving and hiding items uses the same engine but has not yet been shown on screen; test carefully, since a rule that hides a needed control is only undone by reverting.
- The tree is rescanned every 2 seconds, so panels that open later pick the theme up with a short delay.
- Restarting CapCut clears a theme; the `ccmod-themes` plugin re-applies the saved one.
