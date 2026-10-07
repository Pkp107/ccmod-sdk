// Console tests for the editor's model and code generation (no window needed). Exit code 0 = all passed.
#include <cmath>
#include <cstdio>
#include <string>
#include <d3dcompiler.h>
#include <windows.h>
#include "../src/codegen.h"
#include "../src/model.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)
static bool nearv(double a, double b, double e = 1e-6) { return std::fabs(a - b) <= e; }

static void testEasing() {
    for (int i = 0; i < (int)Ease::Count; i++) {
        Ease e = (Ease)i;
        if (e == Ease::Hold) continue;
        CHECK(nearv(easeApply(e, 0.0), 0.0));
        CHECK(nearv(easeApply(e, 1.0), 1.0));
        Ease back; CHECK(easeFromName(easeName(e), back) && back == e);          // names round-trip
        for (double u = 0.05; u < 1; u += 0.05) CHECK(std::isfinite(easeApply(e, u)));
    }
    CHECK(nearv(easeApply(Ease::Linear, 0.3), 0.3));
    CHECK(nearv(easeApply(Ease::InQuad, 0.5), 0.25));
    CHECK(nearv(easeApply(Ease::OutCubic, 0.5), 0.875));
    CHECK(nearv(easeApply(Ease::InOutQuad, 0.5), 0.5));
    CHECK(easeApply(Ease::OutBack, 0.7) > 1.0);                    // overshoots
    CHECK(easeApply(Ease::InBack, 0.2) < 0.0);                     // dips below zero
    CHECK(nearv(easeApply(Ease::OutBounce, 0.5), 0.765625));
    double lin[4] = {0, 0, 1, 1};
    CHECK(nearv(easeApply(Ease::Bezier, 0.4, lin), 0.4, 1e-4));     // (0,0,1,1) bezier is linear
    double fast[4] = {0.9, 0.0, 1.0, 0.0};
    CHECK(easeApply(Ease::Bezier, 0.5, fast) < 0.2);
}

static void testTracks() {
    Track t;
    t.add(0.0, 0.0, Ease::Linear); t.add(1.0, 10.0);
    CHECK(nearv(t.eval(0.5, 0), 5.0));
    CHECK(nearv(t.eval(-1, 0), 0.0) && nearv(t.eval(2, 0), 10.0));
    int i = t.add(0.5, 100.0);
    CHECK(i == 1 && t.keys.size() == 3);
    CHECK(nearv(t.eval(0.25, 0), 50.0));
    t.add(0.5, 7.0);                                               // same time replaces
    CHECK(t.keys.size() == 3 && nearv(t.eval(0.5, 0), 7.0));
    Track h; h.add(0, 1, Ease::Hold); h.add(1, 5);
    CHECK(nearv(h.eval(0.99, 0), 1.0) && nearv(h.eval(1.0, 0), 5.0));
    Track empty; CHECK(nearv(empty.eval(0.5, 3.0), 3.0));
}

static void testBake() {
    Track t; t.add(0, 0, Ease::InOutCubic); t.add(1, 1);
    Baked b = bakeTrack(t, 0);
    CHECK(b.n > 4 && b.n <= kMaxPts);
    double worst = 0;
    for (int i = 0; i <= 200; i++) { double x = i / 200.0; worst = std::fmax(worst, std::fabs(evalBaked(b, x) - t.eval(x, 0))); }
    CHECK(worst < 0.01);
    Track c; c.add(0, 0.3);
    Baked bc = bakeTrack(c, 0); CHECK(bc.n == 1 && nearv(bc.v[0], 0.3));
    Track lin; lin.add(0, 0); lin.add(1, 1);
    CHECK(bakeTrack(lin, 0).n <= 3);                               // a straight line stays tiny
    Track bounce; bounce.add(0, 0, Ease::OutBounce); bounce.add(1, 1);
    Baked bb = bakeTrack(bounce, 0); CHECK(bb.n <= kMaxPts && bb.n > 8);
    double w2 = 0; for (int i = 0; i <= 200; i++) { double x = i / 200.0; w2 = std::fmax(w2, std::fabs(evalBaked(bb, x) - bounce.eval(x, 0))); }
    CHECK(w2 < 0.06);
    Track h; h.add(0, 0, Ease::Hold); h.add(0.5, 1);
    Baked bh = bakeTrack(h, 0); CHECK(nearv(evalBaked(bh, 0.49), 0.0, 0.02) && nearv(evalBaked(bh, 0.5), 1.0));
}

static void testJson() {
    Project p; p.name = "roundtrip"; p.mask = MaskType::Iris; p.maskSoftness = 0.2; p.invertY = true;
    p.tracks[trackIndex("b_x")].add(0, 1, Ease::Bezier);
    p.tracks[trackIndex("b_x")].keys[0].bez[1] = 0.77;
    p.tracks[trackIndex("b_x")].add(1, 0);
    std::string text = p.toJson().dump();
    Json j; std::string err; CHECK(Json::parse(text, j, &err));
    Project q; CHECK(Project::fromJson(j, q, &err));
    CHECK(q.name == "roundtrip" && q.mask == MaskType::Iris && q.invertY && nearv(q.maskSoftness, 0.2));
    const Track& t = q.tracks[trackIndex("b_x")];
    CHECK(t.keys.size() == 2 && t.keys[0].ease == Ease::Bezier && nearv(t.keys[0].bez[1], 0.77));
    Json bad; CHECK(!Json::parse("{\"a\": [1,2", bad));
    Project r; CHECK(!Project::fromJson(Json::object(), r));
    Json uni; CHECK(Json::parse("{\"s\":\"caf\\u00e9\\n\"}", uni) && uni.str("s", "") == "caf\xC3\xA9\n");
}

static void testTemplates() {
    CHECK(templates().size() >= 7);
    for (auto& t : templates()) {
        Project p = t.make();
        CHECK(!p.name.empty());
        Baked b[kTracks]; bakeProject(p, b);
        for (int i = 0; i < kTracks; i++) CHECK(b[i].n >= 1);
        auto ex = codegen::glsl(p, b);
        CHECK(ex.body.find("c = vec4") != std::string::npos);
        CHECK(ex.helpers.find("void main") == std::string::npos);                 // helpers must not define main
        int open = 0; for (char ch : ex.helpers) open += (ch == '{') - (ch == '}'); CHECK(open == 0);
    }
}

static void testTile() {
    Project p; p.tile = TileMode::Mirror;
    Project q; std::string err;
    CHECK(Project::fromJson(p.toJson(), q, &err));
    CHECK(q.tile == TileMode::Mirror);
    Baked b[kTracks]; bakeProject(p, b);
    auto ex = codegen::glsl(p, b);
    CHECK(ex.helpers.find("#define TILE_MODE 1") != std::string::npos);
    CHECK(ex.body.find("TILE_MODE > 0") != std::string::npos);
    CHECK(ex.helpers.find("tile_q") != std::string::npos);
}

static void testFit() {
    Project p; p.tracks[0].add(0.2, 0, Ease::Linear); p.tracks[0].add(0.6, 1, Ease::Linear); p.tracks[5].add(0.4, 0.5);
    double a, b; CHECK(keyRange(p, a, b) && a == 0.2 && b == 0.6);
    CHECK(fitToKeys(p));
    CHECK(keyRange(p, a, b) && a < 1e-9 && b > 1 - 1e-9);
    CHECK(std::fabs(p.tracks[5].keys[0].t - 0.5) < 1e-9);
    CHECK(!fitToKeys(p));
}

static void testHlslCompiles() {
    std::string src = codegen::hlsl();
    ID3DBlob *code = nullptr, *err = nullptr;
    HRESULT hr = D3DCompile(src.data(), src.size(), "preview.hlsl", nullptr, nullptr, "main", "ps_5_0", 0, 0, &code, &err);
    if (FAILED(hr)) std::printf("HLSL error: %s\n", err ? (const char*)err->GetBufferPointer() : "?");
    CHECK(SUCCEEDED(hr));
    if (code) code->Release();
    if (err) err->Release();
    CHECK(codegen::kCbufBytes < 65536);
    CHECK(sizeof(codegen::Cbuf) % 16 == 0);
}

int main() {
    testEasing(); testTracks(); testBake(); testJson(); testTemplates(); testTile(); testFit(); testHlslCompiles();
    if (failures) { std::printf("%d check(s) failed\n", failures); return 1; }
    std::printf("all editor model tests passed\n");
    return 0;
}
