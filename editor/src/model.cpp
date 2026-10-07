#include "model.h"
#include <algorithm>
#include <cmath>
#include <cstring>

static const double PI = 3.14159265358979323846;

// ---------------------------------------------------------------------------------------------- easing
struct EaseDef { const char* name; const char* label; };
static const EaseDef kEase[(int)Ease::Count] = {
    {"linear", "Linear"}, {"hold", "Hold (step)"}, {"bezier", "Custom bezier"},
    {"inSine", "In Sine"}, {"outSine", "Out Sine"}, {"inOutSine", "In-Out Sine"},
    {"inQuad", "In Quad"}, {"outQuad", "Out Quad"}, {"inOutQuad", "In-Out Quad"},
    {"inCubic", "In Cubic"}, {"outCubic", "Out Cubic"}, {"inOutCubic", "In-Out Cubic"},
    {"inQuart", "In Quart"}, {"outQuart", "Out Quart"}, {"inOutQuart", "In-Out Quart"},
    {"inQuint", "In Quint"}, {"outQuint", "Out Quint"}, {"inOutQuint", "In-Out Quint"},
    {"inExpo", "In Expo"}, {"outExpo", "Out Expo"}, {"inOutExpo", "In-Out Expo"},
    {"inCirc", "In Circ"}, {"outCirc", "Out Circ"}, {"inOutCirc", "In-Out Circ"},
    {"inBack", "In Back"}, {"outBack", "Out Back"}, {"inOutBack", "In-Out Back"},
    {"inElastic", "In Elastic"}, {"outElastic", "Out Elastic"}, {"inOutElastic", "In-Out Elastic"},
    {"inBounce", "In Bounce"}, {"outBounce", "Out Bounce"}, {"inOutBounce", "In-Out Bounce"},
};
const char* easeName(Ease e) { return kEase[(int)e].name; }
const char* easeLabel(Ease e) { return kEase[(int)e].label; }
bool easeFromName(const std::string& s, Ease& out) {
    for (int i = 0; i < (int)Ease::Count; i++) if (s == kEase[i].name) { out = (Ease)i; return true; }
    return false;
}

static double bounceOut(double t) {
    const double n = 7.5625, d = 2.75;
    if (t < 1 / d) return n * t * t;
    if (t < 2 / d) { t -= 1.5 / d; return n * t * t + 0.75; }
    if (t < 2.5 / d) { t -= 2.25 / d; return n * t * t + 0.9375; }
    t -= 2.625 / d; return n * t * t + 0.984375;
}
static double bezierSolve(const double b[4], double u) {
    // x(s) = u for the cubic with control x: 0, b0, b2, 1; then return y(s)
    auto X = [&](double s) { double m = 1 - s; return 3 * m * m * s * b[0] + 3 * m * s * s * b[2] + s * s * s; };
    auto Y = [&](double s) { double m = 1 - s; return 3 * m * m * s * b[1] + 3 * m * s * s * b[3] + s * s * s; };
    double lo = 0, hi = 1, s = u;
    for (int i = 0; i < 40; i++) { s = 0.5 * (lo + hi); if (X(s) < u) lo = s; else hi = s; }
    return Y(s);
}
static double pw(double t, int n, int mode) {          // mode 0 in, 1 out, 2 inOut
    if (mode == 0) return std::pow(t, n);
    if (mode == 1) return 1 - std::pow(1 - t, n);
    return t < 0.5 ? std::pow(2, n - 1) * std::pow(t, n) : 1 - std::pow(-2 * t + 2, n) / 2;
}

double easeApply(Ease e, double u, const double* bz) {
    if (u <= 0) return 0;
    if (u >= 1) return e == Ease::Hold ? 0 : 1;           // hold: stays at the start value until the next key
    const double t = u;
    int id = (int)e;
    switch (e) {
        case Ease::Linear: return t;
        case Ease::Hold: return 0;
        case Ease::Bezier: { static const double d[4] = {0.25, 0.1, 0.25, 1.0}; return bezierSolve(bz ? bz : d, t); }
        default: break;
    }
    int fam = (id - (int)Ease::InSine) / 3, mode = (id - (int)Ease::InSine) % 3;     // 0 sine 1 quad 2 cubic 3 quart 4 quint 5 expo 6 circ 7 back 8 elastic 9 bounce
    switch (fam) {
        case 0: return mode == 0 ? 1 - std::cos(t * PI / 2) : mode == 1 ? std::sin(t * PI / 2) : -(std::cos(PI * t) - 1) / 2;
        case 1: return pw(t, 2, mode);
        case 2: return pw(t, 3, mode);
        case 3: return pw(t, 4, mode);
        case 4: return pw(t, 5, mode);
        case 5:
            if (mode == 0) return std::pow(2, 10 * t - 10);
            if (mode == 1) return 1 - std::pow(2, -10 * t);
            return t < 0.5 ? std::pow(2, 20 * t - 10) / 2 : (2 - std::pow(2, -20 * t + 10)) / 2;
        case 6:
            if (mode == 0) return 1 - std::sqrt(1 - t * t);
            if (mode == 1) return std::sqrt(1 - (t - 1) * (t - 1));
            return t < 0.5 ? (1 - std::sqrt(1 - 4 * t * t)) / 2 : (std::sqrt(1 - (-2 * t + 2) * (-2 * t + 2)) + 1) / 2;
        case 7: {
            const double c1 = 1.70158, c2 = c1 * 1.525, c3 = c1 + 1;
            if (mode == 0) return c3 * t * t * t - c1 * t * t;
            if (mode == 1) return 1 + c3 * std::pow(t - 1, 3) + c1 * std::pow(t - 1, 2);
            return t < 0.5 ? (std::pow(2 * t, 2) * ((c2 + 1) * 2 * t - c2)) / 2
                           : (std::pow(2 * t - 2, 2) * ((c2 + 1) * (2 * t - 2) + c2) + 2) / 2;
        }
        case 8: {
            const double c4 = 2 * PI / 3, c5 = 2 * PI / 4.5;
            if (mode == 0) return -std::pow(2, 10 * t - 10) * std::sin((10 * t - 10.75) * c4);
            if (mode == 1) return std::pow(2, -10 * t) * std::sin((10 * t - 0.75) * c4) + 1;
            return t < 0.5 ? -(std::pow(2, 20 * t - 10) * std::sin((20 * t - 11.125) * c5)) / 2
                           : (std::pow(2, -20 * t + 10) * std::sin((20 * t - 11.125) * c5)) / 2 + 1;
        }
        default:
            if (mode == 0) return 1 - bounceOut(1 - t);
            if (mode == 1) return bounceOut(t);
            return t < 0.5 ? (1 - bounceOut(1 - 2 * t)) / 2 : (1 + bounceOut(2 * t - 1)) / 2;
    }
}

// ---------------------------------------------------------------------------------------------- tracks
static const TrackInfo kInfo[kTracks] = {
    {"a_x", "Position X", "Outgoing clip (A)", 0, -1.5, 1.5},
    {"a_y", "Position Y", "Outgoing clip (A)", 0, -1.5, 1.5},
    {"a_scale", "Scale", "Outgoing clip (A)", 1, 0, 4},
    {"a_rot", "Rotation", "Outgoing clip (A)", 0, -360, 360},
    {"a_opacity", "Opacity", "Outgoing clip (A)", 1, 0, 1},
    {"a_rgb", "RGB split", "Outgoing clip (A)", 0, 0, 0.1},
    {"a_pix", "Pixelate", "Outgoing clip (A)", 0, 0, 1},
    {"a_bright", "Brightness", "Outgoing clip (A)", 0, -1, 2},
    {"b_x", "Position X", "Incoming clip (B)", 0, -1.5, 1.5},
    {"b_y", "Position Y", "Incoming clip (B)", 0, -1.5, 1.5},
    {"b_scale", "Scale", "Incoming clip (B)", 1, 0, 4},
    {"b_rot", "Rotation", "Incoming clip (B)", 0, -360, 360},
    {"b_opacity", "Opacity", "Incoming clip (B)", 1, 0, 1},
    {"b_rgb", "RGB split", "Incoming clip (B)", 0, 0, 0.1},
    {"b_pix", "Pixelate", "Incoming clip (B)", 0, 0, 1},
    {"b_bright", "Brightness", "Incoming clip (B)", 0, -1, 2},
    {"g_shake", "Camera shake", "Whole frame", 0, 0, 0.1},
    {"g_flash", "White flash", "Whole frame", 0, 0, 2},
    {"mask", "Reveal amount", "Mask on B", 1, 0, 1},
};
const TrackInfo& trackInfo(int i) { return kInfo[i]; }
int trackIndex(const std::string& id) {
    for (int i = 0; i < kTracks; i++) if (id == kInfo[i].id) return i;
    return -1;
}
const char* maskLabel(MaskType m) {
    static const char* L[] = {"None", "Linear wipe", "Circle iris", "Box", "Barn doors (horizontal)", "Barn doors (vertical)", "Diamond"};
    return L[(int)m];
}

void Track::sort() { std::stable_sort(keys.begin(), keys.end(), [](const Key& a, const Key& b) { return a.t < b.t; }); }
int Track::add(double t, double v, Ease e) {
    t = std::min(1.0, std::max(0.0, t));
    for (size_t i = 0; i < keys.size(); i++)
        if (std::fabs(keys[i].t - t) < 1e-6) { keys[i].v = v; keys[i].ease = e; return (int)i; }
    Key k; k.t = t; k.v = v; k.ease = e;
    keys.push_back(k);
    sort();
    for (size_t i = 0; i < keys.size(); i++) if (std::fabs(keys[i].t - t) < 1e-9) return (int)i;
    return 0;
}
double Track::eval(double t, double def) const {
    if (keys.empty()) return def;
    if (t <= keys.front().t) return keys.front().v;
    if (t >= keys.back().t) return keys.back().v;
    for (size_t i = 0; i + 1 < keys.size(); i++) {
        const Key& a = keys[i]; const Key& b = keys[i + 1];
        if (t <= b.t) {
            double span = b.t - a.t;
            if (span < 1e-9) return b.v;
            double u = (t - a.t) / span;
            if (a.ease == Ease::Hold) return a.v;
            return a.v + (b.v - a.v) * easeApply(a.ease, u, a.bez);
        }
    }
    return keys.back().v;
}

// ---------------------------------------------------------------------------------------------- baking
const char* tileLabel(TileMode m) {
    switch (m) {
        case TileMode::Mirror: return "Mirror (seamless)";
        case TileMode::Repeat: return "Repeat";
        case TileMode::Edge: return "Stretch edge";
        default: return "Off";
    }
}

Baked bakeTrack(const Track& tr, double def) {
    Baked out;
    if (tr.keys.empty() || tr.keys.size() == 1) {
        out.n = 1; out.t[0] = 0; out.v[0] = tr.keys.empty() ? def : tr.keys[0].v;
        return out;
    }
    std::vector<std::pair<double, double>> pts;
    const int N = 240;
    for (int i = 0; i <= N; i++) { double t = (double)i / N; pts.emplace_back(t, tr.eval(t, def)); }
    for (size_t k = 0; k < tr.keys.size(); k++) {          // exact key instants, and a step just before/after for holds
        const Key& key = tr.keys[k];
        pts.emplace_back(key.t, tr.eval(key.t, def));
        if (key.ease == Ease::Hold && k + 1 < tr.keys.size()) {
            double nt = tr.keys[k + 1].t;
            pts.emplace_back(std::max(key.t, nt - 1e-4), key.v);
            pts.emplace_back(nt, tr.keys[k + 1].v);
        }
    }
    std::sort(pts.begin(), pts.end());
    std::vector<std::pair<double, double>> dd;
    for (auto& p : pts) if (dd.empty() || p.first - dd.back().first > 1e-7) dd.push_back(p); else dd.back() = p;
    // thin: drop points a straight line between kept neighbours reproduces; raise the tolerance until it fits
    double lo = dd[0].second, hi = dd[0].second;
    for (auto& p : dd) { lo = std::min(lo, p.second); hi = std::max(hi, p.second); }
    double range = std::max(hi - lo, 1e-6), tol = range * 0.0008;
    std::vector<std::pair<double, double>> keep;
    for (int pass = 0; pass < 40; pass++, tol *= 1.4) {
        keep.clear(); keep.push_back(dd[0]);
        size_t anchor = 0;
        for (size_t k = 2; k < dd.size(); k++) {
            bool ok = true;
            for (size_t m = anchor + 1; m < k && ok; m++) {
                double span = dd[k].first - dd[anchor].first;
                double exp = dd[anchor].second + (dd[k].second - dd[anchor].second) * ((dd[m].first - dd[anchor].first) / (span > 0 ? span : 1));
                if (std::fabs(exp - dd[m].second) > tol) ok = false;
            }
            if (!ok) { keep.push_back(dd[k - 1]); anchor = k - 1; }
        }
        keep.push_back(dd.back());
        if ((int)keep.size() <= kMaxPts) break;
    }
    out.n = (int)std::min<size_t>(keep.size(), kMaxPts);
    for (int i = 0; i < out.n; i++) { out.t[i] = keep[i].first; out.v[i] = keep[i].second; }
    return out;
}
bool keyRange(const Project& p, double& tmin, double& tmax) {
    bool any = false;
    for (int i = 0; i < kTracks; i++)
        for (const Key& k : p.tracks[i].keys) {
            if (!any) { tmin = tmax = k.t; any = true; }
            else { tmin = std::min(tmin, k.t); tmax = std::max(tmax, k.t); }
        }
    return any;
}
bool fitToKeys(Project& p) {
    double a, b;
    if (!keyRange(p, a, b) || b - a < 1e-6) return false;
    if (a < 1e-6 && b > 1 - 1e-6) return false;
    for (int i = 0; i < kTracks; i++)
        for (Key& k : p.tracks[i].keys) k.t = std::min(1.0, std::max(0.0, (k.t - a) / (b - a)));
    return true;
}
void bakeProject(const Project& p, Baked out[kTracks]) {
    for (int i = 0; i < kTracks; i++) out[i] = bakeTrack(p.tracks[i], kInfo[i].def);
    auto hide = [&](const char* id) { int i = trackIndex(id); if (i >= 0) { out[i].n = 1; out[i].t[0] = 0; out[i].v[0] = 0; } };
    if (!p.showA) hide("a_opacity");
    if (!p.showB) hide("b_opacity");
}
double evalBaked(const Baked& b, double t) {
    if (b.n <= 0) return 0;
    if (t <= b.t[0]) return b.v[0];
    for (int i = 1; i < b.n; i++)
        if (t <= b.t[i]) {
            double span = b.t[i] - b.t[i - 1];
            return span > 1e-9 ? b.v[i - 1] + (b.v[i] - b.v[i - 1]) * ((t - b.t[i - 1]) / span) : b.v[i];
        }
    return b.v[b.n - 1];
}

// ---------------------------------------------------------------------------------------------- json
Json Project::toJson() const {
    Json j = Json::object();
    j.set("format", Json::string("ccmod-transition-project"));
    j.set("version", Json::number(1));
    Json m = Json::object();
    m.set("name", Json::string(name)); m.set("label", Json::string(label)); m.set("description", Json::string(description));
    m.set("duration", Json::number(duration)); m.set("mask", Json::number((int)mask));
    m.set("maskSoftness", Json::number(maskSoftness)); m.set("maskAngle", Json::number(maskAngle)); m.set("invertY", Json::boolean(invertY)); m.set("tile", Json::number((int)tile)); m.set("showA", Json::boolean(showA)); m.set("showB", Json::boolean(showB));
    j.set("meta", m);
    Json t = Json::object();
    for (int i = 0; i < kTracks; i++) {
        if (tracks[i].keys.empty()) continue;
        Json arr = Json::array();
        for (const Key& k : tracks[i].keys) {
            Json kj = Json::object();
            kj.set("t", Json::number(k.t)); kj.set("v", Json::number(k.v)); kj.set("ease", Json::string(easeName(k.ease)));
            if (k.ease == Ease::Bezier) { Json b = Json::array(); for (int q = 0; q < 4; q++) b.push(Json::number(k.bez[q])); kj.set("bez", b); }
            arr.push(kj);
        }
        t.set(kInfo[i].id, arr);
    }
    j.set("tracks", t);
    return j;
}
bool Project::fromJson(const Json& j, Project& out, std::string* err) {
    if (j.type != Json::Obj || j.str("format", "") != "ccmod-transition-project") { if (err) *err = "not a ccmod transition project"; return false; }
    Project p;
    if (const Json* m = j.get("meta")) {
        p.name = m->str("name", p.name); p.label = m->str("label", p.label); p.description = m->str("description", p.description);
        p.duration = std::min(10.0, std::max(0.1, m->num("duration", 1.0)));
        int mk = (int)m->num("mask", 0); p.mask = (MaskType)std::min(std::max(mk, 0), (int)MaskType::Count - 1);
        p.maskSoftness = std::min(0.5, std::max(0.01, m->num("maskSoftness", 0.1)));
        p.maskAngle = m->num("maskAngle", 0); p.invertY = m->boolean("invertY", false);
        auto tl = [&](const char* k) { int v = (int)m->num(k, 0); return (TileMode)std::min(std::max(v, 0), (int)TileMode::Count - 1); };
        p.tile = tl("tile");
        p.showA = m->boolean("showA", true); p.showB = m->boolean("showB", true);
    }
    if (const Json* t = j.get("tracks")) {
        for (auto& kv : t->o) {
            int ti = trackIndex(kv.first);
            if (ti < 0 || kv.second.type != Json::Arr) continue;
            for (const Json& kj : kv.second.a) {
                Key k; k.t = std::min(1.0, std::max(0.0, kj.num("t", 0))); k.v = kj.num("v", 0);
                Ease e = Ease::Linear; easeFromName(kj.str("ease", "linear"), e); k.ease = e;
                if (const Json* b = kj.get("bez")) if (b->type == Json::Arr && b->a.size() == 4) for (int q = 0; q < 4; q++) k.bez[q] = b->a[q].n;
                p.tracks[ti].keys.push_back(k);
            }
            p.tracks[ti].sort();
        }
    }
    out = p;
    return true;
}

// ---------------------------------------------------------------------------------------------- templates
static void K(Project& p, const char* id, double t, double v, Ease e = Ease::Linear) { p.tracks[trackIndex(id)].add(t, v, e); }

static Project tSlide() {
    Project p; p.name = "slide_push"; p.label = "Slide Push"; p.description = "Incoming clip pushes the outgoing one left";
    K(p, "a_x", 0, 0, Ease::InOutCubic); K(p, "a_x", 1, -1);
    K(p, "b_x", 0, 1, Ease::InOutCubic); K(p, "b_x", 1, 0);
    return p;
}
static Project tZoom() {
    Project p; p.name = "zoom_through"; p.label = "Zoom Through"; p.description = "Zoom into the outgoing clip, land on the new one";
    K(p, "a_scale", 0, 1, Ease::InQuint); K(p, "a_scale", 0.6, 3.2); K(p, "a_opacity", 0.35, 1, Ease::Linear); K(p, "a_opacity", 0.65, 0);
    K(p, "b_scale", 0.3, 0.4, Ease::OutCubic); K(p, "b_scale", 1, 1); K(p, "b_opacity", 0.3, 0); K(p, "b_opacity", 0.7, 1);
    return p;
}
static Project tSpin() {
    Project p; p.name = "spin_swap"; p.label = "Spin Swap"; p.description = "Spin and scale into the next clip";
    K(p, "a_rot", 0, 0, Ease::InOutBack); K(p, "a_rot", 1, 180); K(p, "a_scale", 0, 1, Ease::InOutCubic); K(p, "a_scale", 1, 0.2);
    K(p, "a_opacity", 0.4, 1); K(p, "a_opacity", 0.8, 0);
    K(p, "b_rot", 0, -180, Ease::InOutBack); K(p, "b_rot", 1, 0); K(p, "b_scale", 0, 2.5, Ease::InOutCubic); K(p, "b_scale", 1, 1);
    K(p, "b_opacity", 0.2, 0); K(p, "b_opacity", 0.6, 1);
    return p;
}
static Project tIris() {
    Project p; p.name = "iris_open"; p.label = "Iris Open"; p.description = "A circle opens onto the next clip";
    p.mask = MaskType::Iris; p.maskSoftness = 0.05;
    K(p, "mask", 0, 0, Ease::InOutQuart); K(p, "mask", 1, 1);
    return p;
}
static Project tWhip() {
    Project p; p.name = "whip_pan"; p.label = "Whip Pan"; p.description = "Fast pan with RGB split and a flash";
    K(p, "a_x", 0, 0, Ease::InExpo); K(p, "a_x", 0.5, -1.2);
    K(p, "b_x", 0.5, 1.2, Ease::OutExpo); K(p, "b_x", 1, 0);
    K(p, "a_rgb", 0, 0, Ease::OutQuad); K(p, "a_rgb", 0.3, 0.05); K(p, "a_rgb", 0.5, 0);
    K(p, "b_rgb", 0.5, 0.05, Ease::OutQuad); K(p, "b_rgb", 1, 0);
    K(p, "g_flash", 0.4, 0, Ease::OutQuad); K(p, "g_flash", 0.5, 0.6, Ease::OutQuad); K(p, "g_flash", 0.7, 0);
    return p;
}
static Project tPixel() {
    Project p; p.name = "pixel_swap"; p.label = "Pixel Swap"; p.description = "Dissolve through growing pixels";
    K(p, "a_pix", 0, 0, Ease::InQuad); K(p, "a_pix", 0.5, 0.85); K(p, "a_opacity", 0.5, 1, Ease::Hold); K(p, "a_opacity", 0.51, 0);
    K(p, "b_pix", 0.5, 0.85, Ease::OutQuad); K(p, "b_pix", 1, 0); K(p, "b_opacity", 0, 0, Ease::Hold); K(p, "b_opacity", 0.5, 1);
    return p;
}
static Project tBounce() {
    Project p; p.name = "bounce_in"; p.label = "Bounce In"; p.description = "Incoming clip drops in and bounces";
    K(p, "b_y", 0, -1.3, Ease::OutBounce); K(p, "b_y", 1, 0);
    K(p, "a_scale", 0, 1, Ease::OutQuad); K(p, "a_scale", 0.5, 0.85);
    return p;
}
static Project tBlank() { Project p; p.name = "my_transition"; return p; }

const std::vector<Template>& templates() {
    static const std::vector<Template> t = {
        {"Blank", tBlank}, {"Slide push", tSlide}, {"Zoom through", tZoom}, {"Spin swap", tSpin},
        {"Iris open", tIris}, {"Whip pan", tWhip}, {"Pixel swap", tPixel}, {"Bounce in", tBounce},
    };
    return t;
}
