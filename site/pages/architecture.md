---
title: How it works
section: Reference
order: 30
---

# How ccmod works

CapCut Desktop is a Qt6/QML application with a Chromium network stack (Cronet) and an ANGLE/GLES renderer. ccmod changes **none of CapCut's program files**. It works by runtime injection and a local helper.

```
 ccmod_run.py ──► launches pinned CapCut ──► Frida attaches
      │                                         │
      │  Python SDK (plugins)                   ▼
      │      ctx.ui / engine / media ────►  ccmod_inject.dll  (inside CapCut's UI process)
      │                                         │  Qt metaobject reflection: call slots, read/write properties,
      │                                         │  inject QML into the live scene
      ▼
 local catalog proxy ◄── CapCut's panel requests (Effects / Transitions)
      │  rewrites the real default category into "ccmod"
      ▼
 package cache  %LOCALAPPDATA%\CapCut\User Data\Cache\effect\<id>\<md5>\   (our shader packages)
```

## The four control surfaces

1. **Qt metaobject injection.** A small DLL inside CapCut lists CapCut's live view-models and lets us call their methods, read/write properties, and inject QML. This powers buttons, tabs, themes, seek, media import.
2. **Donorless effect packages.** A fabricated effect id plus a local package (shader, config, slider declaration) that CapCut resolves and renders. No donor effect, no catalog entry, no download.
3. **The catalog proxy.** CapCut asks a server which tiles to show in a panel. A local proxy answers: it renames the real default category to **ccmod** and fills it with real stock tiles whose ids are kept but whose titles, covers and package hashes are ours. Our package is installed under each borrowed id, so a native drag applies *our* effect.
4. **Project drafts.** A project is JSON; effects can be written directly (with backups) when a live route isn't needed.

## Why borrowed ids

CapCut drops tiles whose ids it doesn't recognise. So each ccmod tile keeps a real id (preferring tiles that are *free*, so your tiles never carry a Pro badge), and the proxy pins the assignment (`pins.json`) so it's stable even though CapCut re-ranks its lists on each request. ccmod only *reads* whether a stock tile is free to choose which to borrow; it never edits any licensing or subscription data.

## Effects vs transitions

They differ fundamentally, which is why they have separate pipelines:

| | Effect | Transition |
|---|---|---|
| Inputs | one clip texture | outgoing + incoming clip textures |
| Animation | slider, `iTime` | `progress` 0..1 across the cut |
| Panel | effect type 7, category 26918 | effect type 19, category 27186 |
| Package skeleton | cached stock effect (Sharpen Edges) | cached stock transition (Rotational Blur) |
| Our entry point | `scratch/ccfx.py` | `ccmod_sdk/transitions.py` |

## Plugins and isolation

- Plugins are Python modules loaded by the Host, each with its own Context, storage folder and permission set.
- An exception in a hook disables that plugin for the session; nothing else is affected.
- Plugin tools are registered in a shared registry exposed through the local tool server and MCP.

## Themes

One injected QML object (the theme engine) walks the live UI tree and installs reversible `Binding`s. See [Themes](themes.html).

## Pinned build

Newer CapCut builds change internals; 8.9.1.3802 is the reference. `ccversion.py` knows per-build facts (draft format number, whether packages render) and `ccmod_run.py` launches the right build rather than the auto-updating stub.

## Deeper reading

- [SDK vision & levers](sdk-vision.html): every lever found by recon
- [Legacy .ccpack transition spec](ccpack-spec.html) and [authoring](ccpack-authoring.html)
- Capability matrix and moddability model in `docs/reference/` in the repository
