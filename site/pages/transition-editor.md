---
title: Transition editor
section: Using ccmod
order: 15
---

# Transition editor

A separate desktop app (not part of CapCut) for designing a transition by eye. You keyframe a few properties on a **square 1:1 workspace**, watch it play, and send it to ccmod, where it becomes a real transition in CapCut's Transitions > ccmod category.

It lives in `editor/` and is built with C++, Dear ImGui and Direct3D 11. It needs nothing installed at run time: it is one exe with no extra DLLs.

## Start it

Double-click `editor\bin\ccmod-transition-editor.exe` (or build it first: see [Build it](#build-it)).

## The window

| Area | What it does |
|---|---|
| **Preview (top left)** | A square 1:1 view of the transition between picture A (going out) and picture B (coming in). Play, scrub, loop / ping-pong / once, speed. *Picture A / B...* load your own images (centre-cropped to a square) |
| **Timeline (top middle)** | One row per property with its keyframes. Click a row to select it. Drag a key sideways to retime it. Double-click a row to add a key. Click the ruler to move the playhead |
| **Inspector (top right)** | Name and description, the preview length, the reveal mask, and the selected key's time, value and easing |
| **Graph (bottom left)** | The selected property as a curve. Drag keys in time and value, drag bezier handles, optionally show the speed curve |
| **Easing library (bottom right)** | Thumbnails of every easing curve; click one to apply it to the selected key |

## What you can animate

Every property is a track of keyframes over the transition's progress, 0 to 1.

| Group | Tracks |
|---|---|
| **Outgoing clip (A)** and **Incoming clip (B)** | Position X, Position Y, Scale, Rotation, Opacity, RGB split, Pixelate, Brightness |
| **Whole frame** | Camera shake, White flash |
| **Mask on B** | Reveal amount, for the mask chosen in the inspector: linear wipe (with angle), circle iris, box, barn doors (horizontal or vertical), diamond; with an edge softness |

Each clip group (A and B) has a **show** checkbox in the timeline. Untick it to hide that clip in the preview and in the export, which is handy for building one clip's motion at a time. It is saved with the project.

**Motion tile** (in the inspector) is one setting for the whole screen. Wherever neither clip covers the frame (a clip slid, shrank or rotated away), it shows a copy of the picture instead of black bars: *Mirror* continues it seamlessly, *Repeat* tiles it, *Stretch edge* extends the border pixels. It is part of the export.

**Timing:** the transition plays over its whole length, so if your last key is at 60% the final 40% is dead time. When that happens the inspector shows the empty time and a **Fit timeline to keys** button that rescales every key so the first sits at 0 and the last at 1.

## Keyframes and easing

A key's easing shapes the segment from that key to the next one. 33 easings:

- Linear and **Hold** (step)
- **Custom bezier** with two draggable handles
- In, Out and In-Out versions of Sine, Quad, Cubic, Quart, Quint, Expo, Circ, **Back** (overshoot), **Elastic** and **Bounce**

The graph shows the real curve, including overshoot. *Show speed* overlays how fast the value changes.

## Keys and shortcuts

| Key | Action |
|---|---|
| Space | Play / pause |
| Left / Right | Step the playhead |
| Up / Down | Previous / next track |
| K | Add a key at the playhead |
| Delete | Delete the selected key |
| Ctrl+Z, Ctrl+Y | Undo, redo |
| Ctrl+S | Save |
| Shift (while dragging in the graph) | Move in time only |
| Alt (while dragging) | Turn snapping off |
| Ctrl+click in the graph | Add a key at the mouse |

*File > New from template* starts from Slide push, Zoom through, Spin swap, Iris open, Whip pan, Pixel swap or Bounce in.

## Send it to CapCut

**File > Install into ccmod** writes the transition and tells ccmod to build it. Restart ccmod (`ccmod_run.py` or the *Start ccmod* shortcut) and it is in **Transitions > ccmod**.

If the editor can't find your ccmod folder, set the `CCMOD_HOME` environment variable to it, or keep the editor inside the ccmod folder. Or use **File > Export for ccmod...** to save a `.ccmodtrans` file and install it by hand:

```bash
python ccmod_api.py import-transition my_transition.ccmodtrans
```

**File > Show shader code** shows the generated GLSL, and the project itself saves as a `.cctrans` file you can reopen.

## How it works

The editor bakes every track into a short list of points. The preview shader and the exported shader read **the same points** and run the **same compositing code**, so what you see is what is exported. The export becomes a normal ccmod transition package: ccmod's transition builder adds the editor's helper functions before `main()`, and the transition is installed like any other.

!!! note "What's verified"
    The easing maths, keyframe evaluation, baking, project files and code generation have automated tests, and the preview shader is compiled by Direct3D in those tests. The export path through ccmod is tested with stand-in packages. **A transition made in the editor has not yet been seen playing inside CapCut.** If one plays upside-down, tick *Flip vertical on export* in the inspector and reinstall.

## Build it

You need Visual Studio Build Tools 2022 (the "Desktop development with C++" workload). Then:

```bash
editor\build.bat          # builds editor\bin\ccmod-transition-editor.exe
editor\build_tests.bat    # builds and runs the model and shader tests
```

Dear ImGui (MIT licence) is included under `editor/third_party/imgui`.

## Limits

- Transitions only for now; an effect editor is next.
- Two clips and the properties above. Blur and other multi-pass looks aren't in the editor yet.
- The mask applies to the incoming clip.
- Pictures are cropped to a square in the editor; CapCut uses the real frame aspect.
