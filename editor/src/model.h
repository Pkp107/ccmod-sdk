// The transition model: keyframed tracks over progress 0..1, easing curves, baking, project files, starter templates.
#pragma once
#include <string>
#include <vector>
#include "json.h"

// ---- easing -------------------------------------------------------------------------------------------------
enum class Ease : int {
    Linear, Hold, Bezier,
    InSine, OutSine, InOutSine, InQuad, OutQuad, InOutQuad, InCubic, OutCubic, InOutCubic,
    InQuart, OutQuart, InOutQuart, InQuint, OutQuint, InOutQuint, InExpo, OutExpo, InOutExpo,
    InCirc, OutCirc, InOutCirc, InBack, OutBack, InOutBack, InElastic, OutElastic, InOutElastic,
    InBounce, OutBounce, InOutBounce,
    Count
};
const char* easeName(Ease e);                 // "inOutCubic" (file/JSON name)
const char* easeLabel(Ease e);                // "In-Out Cubic" (UI)
bool easeFromName(const std::string& s, Ease& out);
// u in 0..1 -> eased 0..1 (may overshoot for back/elastic). bezier = {x1,y1,x2,y2} for Ease::Bezier.
double easeApply(Ease e, double u, const double bezier[4] = nullptr);

// ---- tracks -------------------------------------------------------------------------------------------------
struct Key {
    double t = 0;                     // 0..1 progress
    double v = 0;
    Ease ease = Ease::Linear;         // easing of the segment that STARTS at this key
    double bez[4] = {0.25, 0.1, 0.25, 1.0};
};

struct TrackInfo {
    const char* id;                   // "a_x"
    const char* label;                // "Position X"
    const char* group;                // "Outgoing clip (A)"
    double def, lo, hi;               // default value, UI range
};
constexpr int kTracks = 19;
const TrackInfo& trackInfo(int i);
int trackIndex(const std::string& id);   // -1 if unknown

struct Track {
    std::vector<Key> keys;            // sorted by t
    double eval(double t, double def) const;
    int add(double t, double v, Ease e = Ease::Linear);     // returns index (replaces a key at the same t)
    void sort();
};

enum class MaskType : int { None, Wipe, Iris, Box, BarnH, BarnV, Diamond, Count };
const char* maskLabel(MaskType m);

// Motion tile: what a clip shows outside its own frame (instead of empty/black).
enum class TileMode : int { Off, Mirror, Repeat, Edge, Count };
const char* tileLabel(TileMode m);

struct Project {
    std::string name = "my_transition";
    std::string label = "My Transition";
    std::string description = "Made in the ccmod transition editor";
    double duration = 1.0;            // seconds (informational; CapCut sets the real length)
    MaskType mask = MaskType::None;
    double maskSoftness = 0.1;
    double maskAngle = 0;             // degrees, for wipes
    TileMode tile = TileMode::Off;   // motion tile: fills uncovered screen area with a copy of the clips
    bool showA = true, showB = true;  // clip toggles: a hidden clip is not drawn (preview and export)
    bool invertY = false;             // flip vertical orientation on export
    Track tracks[kTracks];

    double value(int track, double t) const { return tracks[track].eval(t, trackInfo(track).def); }
    Json toJson() const;
    static bool fromJson(const Json& j, Project& out, std::string* err = nullptr);
};

// The time range actually used by keys across all tracks (false if there are no keys).
bool keyRange(const Project& p, double& tmin, double& tmax);
// Rescale every key time so the first key is at 0 and the last at 1 (removes empty time before/after the animation).
bool fitToKeys(Project& p);

// ---- baking: tracks -> thin piecewise-linear point lists (what both the preview and the exported shader evaluate) ----
constexpr int kMaxPts = 48;
struct Baked { int n = 0; double t[kMaxPts]; double v[kMaxPts]; };
Baked bakeTrack(const Track& tr, double def);
void bakeProject(const Project& p, Baked out[kTracks]);
double evalBaked(const Baked& b, double t);

// ---- templates --------------------------------------------------------------------------------------------
struct Template { const char* name; Project (*make)(); };
const std::vector<Template>& templates();
