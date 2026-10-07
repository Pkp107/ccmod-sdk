"""Multi-pass effects: shaders that need a blurred copy of the frame (glow, bloom, soft focus, ...).

CapCut's effect package we build on is already a two-pass pipeline:

    pass 1 (GaussianBlurX)  reads the frame (u_inputTexture)           -> writes an intermediate texture
    pass 2 (GaussianBlurY)  reads the original (u_inputTexture) AND the pass-1 result (u_albedo) -> the final image

ccmod lets an effect replace BOTH shaders. `pass1` is the main() of the first pass (it receives RadiusX, SigmaX, Dx and may
reshape the input before blurring, for example a bright-pass for bloom); `main` is the main() of the second pass. Because pass 1 only
blurs horizontally, pass 2 finishes the blur with `ccmodBlur(uv)` (defined below, prepended to your main).

Each entry below is a ccfx library effect: {"slider", "desc", "main", "pass1"?, "radius"?}.
`radius` is the blur radius in pixels (default 6). They install like any other effect:

    python scratch/ccfx.py install glow bloom softfocus

and an effect shipped as a .ccpack may include `pass1.frag` and a `radius` field in its manifest.
Status: the package is built and patched exactly like single-pass effects (tested at file level). It builds on a pass structure
CapCut itself uses for Sharpen Edges; an on-screen render of these three is not yet verified.
"""
from __future__ import annotations

# Finishes the gaussian blur: pass 1 blurred horizontally, this blurs the intermediate (u_albedo) vertically.
BLUR_HELPER = """vec4 ccmodBlur(vec2 uv)
{
    float eps = 0.00001;
    if (RadiusY < eps) return texture(u_albedo, uv);
    float sw = 0.0;
    vec4 sc = vec4(0.0);
    for (float y = -RadiusY; y <= RadiusY + eps; y += Dy) {
        vec2 q = vec2(uv.x, uv.y + y);
        if (q.y >= 0.0 && q.y <= 1.0) {
            float w = gaussianWeight(y, SigmaY);
            sw += w;
            sc += texture(u_albedo, q) * w;
        }
    }
    return sc / max(sw, 0.0001);
}

"""

# Pass-1 body that blurs horizontally and runs `PRE` on every sample first (identity for plain blur).
_BLUR_X = """void main()
{
    float eps = 0.00001;
    if (RadiusX < eps) { FragColor = texture(u_inputTexture, uv0); return; }
    float sumWeight = 0.0;
    vec4 sumColor = vec4(0.0);
    for (float x = -RadiusX; x <= RadiusX + eps; x += Dx) {
        vec2 uv = vec2(uv0.x + x, uv0.y);
        if (uv.x >= 0.0 && uv.x <= 1.0) {
            float weight = gaussianWeight(x, SigmaX);
            vec4 s = texture(u_inputTexture, uv);
%PRE%
            sumWeight += weight;
            sumColor += s * weight;
        }
    }
    FragColor = clamp(sumColor / max(sumWeight, 0.0001), 0.0, 1.0);
}
"""

_FINISH = """    c = lm_take_effect_filter(u_lut, c, LutIntensity);
    FragColor = clamp(vec4(c.rgb, 1.0), 0.0, 1.0);
}
"""

EFFECTS = {
    "glow": {
        "slider": "Intensity", "radius": 18.0,
        "desc": "Soft glow: a blurred copy of the picture added back on top (two passes)",
        "main": BLUR_HELPER + """void main()
{
    vec4 c = texture(u_inputTexture, uv0);
    vec4 b = ccmodBlur(uv0);
    c.rgb = 1.0 - (1.0 - c.rgb) * (1.0 - b.rgb * SharpenIntensity * 1.6);   // screen blend
""" + _FINISH,
    },
    "softfocus": {
        "slider": "Amount", "radius": 14.0,
        "desc": "Dreamy soft focus: mixes the sharp picture with a blurred copy (two passes)",
        "main": BLUR_HELPER + """void main()
{
    vec4 c = texture(u_inputTexture, uv0);
    vec4 b = ccmodBlur(uv0);
    c = mix(c, b, clamp(SharpenIntensity, 0.0, 1.0));
""" + _FINISH,
    },
    "bloom": {
        "slider": "Intensity", "radius": 24.0,
        "desc": "Bloom: only the bright parts bleed light (bright-pass, blur, add back)",
        "pass1": _BLUR_X.replace("%PRE%", "            float l = dot(s.rgb, vec3(0.299, 0.587, 0.114));\n            s.rgb *= smoothstep(0.55, 0.95, l);"),
        "main": BLUR_HELPER + """void main()
{
    vec4 c = texture(u_inputTexture, uv0);
    vec4 b = ccmodBlur(uv0);
    c.rgb = 1.0 - (1.0 - c.rgb) * (1.0 - b.rgb * SharpenIntensity * 2.5);
""" + _FINISH,
    },
}
