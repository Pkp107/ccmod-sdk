// Turns a Project into shader code. One shared body (written in the GLSL/HLSL common subset) is wrapped two ways:
//   * HLSL for the live preview (track values come from a constant buffer, so editing never recompiles), and
//   * GLSL for ccmod's transition package (track values are generated functions with the same baked points).
#pragma once
#include <string>
#include "model.h"

namespace codegen {

// Constant-buffer layout the HLSL shader expects (16-byte aligned, 4 floats per row).
struct Cbuf {
    float progress;
    float aspect;
    int mask;
    float softness;
    float angle;            // radians
    int tile;
    int padI;
    float pad;
    int counts[(kTracks + 3) / 4 * 4];          // point count per track
    float pts[kTracks * kMaxPts * 4];           // (t, v, 0, 0) per point
};
constexpr int kCbufBytes = (int)sizeof(Cbuf);

// The full HLSL pixel shader (vertex shader is a fullscreen triangle, see render.cpp).
std::string hlsl();
void fillCbuf(const Project& p, const Baked baked[kTracks], double progress, double aspect, Cbuf& out);

struct Export {
    std::string helpers;     // functions placed before main()
    std::string body;        // statements placed inside main(); ends with `c = vec4(...)`
    std::string preview;     // helpers + body in one block for the "copy GLSL" window
};
// GLSL for ccmod_sdk/transitions.py (uses A(), B(), progress, uv and c from its prelude).
Export glsl(const Project& p, const Baked baked[kTracks]);

// Self-check helpers used by tests.
std::string sharedBody(MaskType mask, bool invertY);

}  // namespace codegen
