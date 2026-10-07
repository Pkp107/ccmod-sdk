#include "codegen.h"
#include <cmath>
#include <cstdio>
#include <cstring>

namespace codegen {

static std::string f6(double v) {
    char b[48];
    std::snprintf(b, sizeof b, "%.6f", v);
    return b;
}

// Helpers shared by both targets. Only the GLSL/HLSL common subset is used (no mat2, no arrays, no single-argument vector splats).
static std::string layerFn(char x) {
    std::string X(1, x);
    std::string S = x == 'a' ? "SA" : "SB";
    return
        "vec4 layer_" + X + "(vec2 uv, float t, int tm)\n{\n"
        "    vec2 q = uv - vec2(0.5, 0.5);\n"
        "    q = q - vec2(T_" + X + "_x(t), T_" + X + "_y(t));\n"
        "    q = rot2(q, -T_" + X + "_rot(t));\n"
        "    q = q / max(T_" + X + "_scale(t), 0.001);\n"
        "    q = q + vec2(0.5, 0.5);\n"
        "    float inside = step(0.0, q.x) * step(q.x, 1.0) * step(0.0, q.y) * step(q.y, 1.0);\n"
        "    if (tm > 0) {\n"
        "        inside = 1.0;\n"
        "        q = tile_q(q, tm);\n"
        "    }\n"
        "    float pix = T_" + X + "_pix(t);\n"
        "    if (pix > 0.001) {\n"
        "        float n = mix(400.0, 6.0, pix);\n"
        "        q = (floor(q * n) + vec2(0.5, 0.5)) / n;\n"
        "    }\n"
        "    float o = T_" + X + "_rgb(t);\n"
        "    vec3 col = vec3(" + S + "(q + vec2(o, 0.0)).x, " + S + "(q).y, " + S + "(q - vec2(o, 0.0)).z);\n"
        "    float br = T_" + X + "_bright(t);\n"
        "    col = col + vec3(br, br, br);\n"
        "    return vec4(col.x, col.y, col.z, inside * sat1(T_" + X + "_opacity(t)));\n"
        "}\n\n";
}

static std::string commonHelpers() {
    return
        "float sat1(float x)\n{\n    return clamp(x, 0.0, 1.0);\n}\n\n"
        "vec2 rot2(vec2 d, float deg)\n{\n"
        "    float a = deg * 0.0174532925;\n"
        "    float cs = cos(a);\n"
        "    float sn = sin(a);\n"
        "    float dx = d.x * AR;\n"
        "    return vec2((dx * cs - d.y * sn) / AR, dx * sn + d.y * cs);\n"
        "}\n\n"
        "vec2 tile_q(vec2 q, int m)\n{\n"
        "    if (m == 1) {\n"
        "        vec2 w = q - vec2(2.0, 2.0) * floor(q * 0.5);\n"
        "        return vec2(1.0 - abs(1.0 - w.x), 1.0 - abs(1.0 - w.y));\n"
        "    }\n"
        "    if (m == 2) {\n"
        "        return q - floor(q);\n"
        "    }\n"
        "    return clamp(q, 0.0, 1.0);\n}\n\n"
        + layerFn('a') + layerFn('b') +
        "float cover_area(float px, float py, float sc)\n{\n"
        "    float h = 0.5 * max(sc, 0.001);\n"
        "    float wx = max(0.0, min(0.5, px + h) - max(-0.5, px - h));\n"
        "    float wy = max(0.0, min(0.5, py + h) - max(-0.5, py - h));\n"
        "    return wx * wy;\n}\n\n"
        "float mask_b(vec2 uv, float m)\n{\n"
        "    if (MASK_TYPE == 0) {\n        return 1.0;\n    }\n"
        "    vec2 c = uv - vec2(0.5, 0.5);\n"
        "    float d = 0.0;\n"
        "    if (MASK_TYPE == 1) {\n"
        "        float ca = cos(MASK_ANGLE);\n"
        "        float sa = sin(MASK_ANGLE);\n"
        "        d = (c.x * ca + c.y * sa) / (abs(ca) + abs(sa)) + 0.5;\n"
        "    } else if (MASK_TYPE == 2) {\n"
        "        d = length(vec2(c.x * AR, c.y)) / (0.5 * sqrt(AR * AR + 1.0));\n"
        "    } else if (MASK_TYPE == 3) {\n"
        "        d = max(abs(c.x), abs(c.y)) * 2.0;\n"
        "    } else if (MASK_TYPE == 4) {\n"
        "        d = abs(c.x) * 2.0;\n"
        "    } else if (MASK_TYPE == 5) {\n"
        "        d = abs(c.y) * 2.0;\n"
        "    } else {\n"
        "        d = abs(c.x) + abs(c.y);\n"
        "    }\n"
        "    float e1 = m * (1.0 + MASK_SOFT);\n"
        "    return 1.0 - smoothstep(e1 - MASK_SOFT, e1, d);\n"
        "}\n\n";
}

std::string sharedBody(MaskType, bool invertY) {
    std::string s =
        "    float t = clamp(progress, 0.0, 1.0);\n"
        "    vec2 u = uv;\n";
    if (invertY) s += "    u = vec2(u.x, 1.0 - u.y);\n";
    s +=
        "    float sh = T_g_shake(t);\n"
        "    u = u + vec2(sin(t * 60.0), cos(t * 47.0)) * sh;\n"
        "    vec4 la = layer_a(u, t, 0);\n"
        "    vec4 lb = layer_b(u, t, 0);\n"
        "    float mb = mask_b(u, T_mask(t));\n"
        "    vec3 col = vec3(0.0, 0.0, 0.0);\n"
        "    if (TILE_MODE > 0) {\n"
        "        vec4 ta = layer_a(u, t, TILE_MODE);\n"
        "        vec4 tb = layer_b(u, t, TILE_MODE);\n"
        "        float wa = cover_area(T_a_x(t), T_a_y(t), T_a_scale(t)) * sat1(T_a_opacity(t)) + 0.0001;\n"
        "        float wb = cover_area(T_b_x(t), T_b_y(t), T_b_scale(t)) * sat1(T_b_opacity(t));\n"
        "        float wt = wa + wb;\n"
        "        col = (vec3(ta.x, ta.y, ta.z) * wa + vec3(tb.x, tb.y, tb.z) * wb) / wt;\n"
        "    }\n"
        "    col = mix(col, vec3(la.x, la.y, la.z), la.w);\n"
        "    col = mix(col, vec3(lb.x, lb.y, lb.z), lb.w * mb);\n"
        "    float fl = T_g_flash(t);\n"
        "    col = col + vec3(fl, fl, fl);\n"
        "    c = vec4(col.x, col.y, col.z, 1.0);\n";
    return s;
}

// ------------------------------------------------------------------------------------------------ HLSL (preview)
std::string hlsl() {
    std::string s =
        "#define vec2 float2\n#define vec3 float3\n#define vec4 float4\n#define mix lerp\n#define fract frac\n"
        "cbuffer C : register(b0) {\n"
        "    float progress; float gAspect; int gMask; float gSoft;\n"
        "    float gAngle; int gTile; int gPadI; float gPad;\n"
        "    int4 cnt[" + std::to_string((kTracks + 3) / 4) + "];\n"
        "    float4 pts[" + std::to_string(kTracks * kMaxPts) + "];\n"
        "};\n"
        "Texture2D texA : register(t0);\nTexture2D texB : register(t1);\nSamplerState smp : register(s0);\n"
        "vec4 SA(vec2 q) { return texA.SampleLevel(smp, q, 0); }\n"
        "vec4 SB(vec2 q) { return texB.SampleLevel(smp, q, 0); }\n"
        "#define AR gAspect\n#define MASK_TYPE gMask\n#define MASK_SOFT gSoft\n#define MASK_ANGLE gAngle\n#define TILE_MODE gTile\n"
        "float trk(int ti, float p)\n{\n"
        "    int n = cnt[ti / 4][ti % 4];\n"
        "    int b = ti * " + std::to_string(kMaxPts) + ";\n"
        "    if (n <= 0) { return 0.0; }\n"
        "    if (p <= pts[b].x) { return pts[b].y; }\n"
        "    [loop] for (int i = 1; i < n; i++) {\n"
        "        if (p <= pts[b + i].x) {\n"
        "            float a = pts[b + i - 1].x;\n"
        "            float d = pts[b + i].x - a;\n"
        "            float k = d > 0.000001 ? (p - a) / d : 1.0;\n"
        "            return lerp(pts[b + i - 1].y, pts[b + i].y, k);\n"
        "        }\n"
        "    }\n"
        "    return pts[b + n - 1].y;\n"
        "}\n";
    for (int i = 0; i < kTracks; i++)
        s += std::string("float T_") + trackInfo(i).id + "(float p) { return trk(" + std::to_string(i) + ", p); }\n";
    s += "\n" + commonHelpers();
    s +=
        "struct PSIn { float4 pos : SV_Position; float2 uv : TEXCOORD0; };\n"
        "float4 main(PSIn pin) : SV_Target\n{\n"
        "    vec2 uv = pin.uv;\n"
        "    vec4 c = vec4(0.0, 0.0, 0.0, 1.0);\n"
        + sharedBody(MaskType::None, false) +
        "    return c;\n}\n";
    return s;
}

void fillCbuf(const Project& p, const Baked baked[kTracks], double progress, double aspect, Cbuf& o) {
    std::memset(&o, 0, sizeof o);
    o.progress = (float)progress; o.aspect = (float)aspect; o.mask = (int)p.mask; o.softness = (float)p.maskSoftness;
    o.angle = (float)(p.maskAngle * 3.14159265358979 / 180.0);
    o.tile = (int)p.tile;
    for (int i = 0; i < kTracks; i++) {
        o.counts[i] = baked[i].n;
        for (int k = 0; k < baked[i].n && k < kMaxPts; k++) {
            o.pts[(i * kMaxPts + k) * 4 + 0] = (float)baked[i].t[k];
            o.pts[(i * kMaxPts + k) * 4 + 1] = (float)baked[i].v[k];
        }
    }
}

// ------------------------------------------------------------------------------------------------ GLSL (export)
static std::string trackFn(int i, const Baked& b) {
    std::string name = std::string("T_") + trackInfo(i).id;
    std::string s = "float " + name + "(float p)\n{\n";
    if (b.n <= 1) return s + "    return " + f6(b.n ? b.v[0] : trackInfo(i).def) + ";\n}\n";
    s += "    if (p <= " + f6(b.t[0]) + ") { return " + f6(b.v[0]) + "; }\n";
    for (int k = 1; k < b.n; k++) {
        double span = b.t[k] - b.t[k - 1];
        s += "    if (p <= " + f6(b.t[k]) + ") { return ";
        if (span < 1e-6) s += f6(b.v[k]);
        else s += "mix(" + f6(b.v[k - 1]) + ", " + f6(b.v[k]) + ", (p - " + f6(b.t[k - 1]) + ") / " + f6(span) + ")";
        s += "; }\n";
    }
    return s + "    return " + f6(b.v[b.n - 1]) + ";\n}\n";
}

Export glsl(const Project& p, const Baked baked[kTracks]) {
    Export e;
    e.helpers =
        "#define AR (float(inputWidth) / float(inputHeight))\n"
        "#define TILE_MODE " + std::to_string((int)p.tile) + "\n"
        "#define MASK_TYPE " + std::to_string((int)p.mask) + "\n"
        "#define MASK_SOFT " + f6(p.maskSoftness) + "\n"
        "#define MASK_ANGLE " + f6(p.maskAngle * 3.14159265358979 / 180.0) + "\n"
        "vec4 SA(vec2 q) { return A(q); }\n"
        "vec4 SB(vec2 q) { return B(q); }\n\n";
    for (int i = 0; i < kTracks; i++) e.helpers += trackFn(i, baked[i]) + "\n";
    e.helpers += commonHelpers();
    e.body = sharedBody(p.mask, p.invertY);
    e.preview = e.helpers + "// ---- inside main() ----\n" + e.body;
    return e;
}

}  // namespace codegen
