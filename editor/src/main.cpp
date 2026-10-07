// ccmod transition editor: a standalone app (not part of CapCut) for designing a transition visually and exporting it to ccmod.
// Dear ImGui + Direct3D 11. The workspace (preview) is a 1:1 square.
#include <windows.h>
#include <commdlg.h>
#include <objbase.h>
#include <shellapi.h>
#include <shlobj.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "imgui.h"
#include "imgui_impl_dx11.h"
#include "imgui_impl_win32.h"
#include "codegen.h"
#include "model.h"
#include "render.h"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam);

// ------------------------------------------------------------------------------------------------ helpers
static std::string readFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    std::stringstream ss; ss << f.rdbuf();
    return ss.str();
}
static bool writeFile(const std::string& path, const std::string& data) {
    std::ofstream f(path, std::ios::binary);
    if (!f) return false;
    f << data;
    return (bool)f;
}
static std::string toUtf8(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), &s[0], n, nullptr, nullptr);
    return s;
}
static std::wstring toWide(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &w[0], n);
    return w;
}
static bool pickFile(bool save, const wchar_t* filter, const wchar_t* defExt, std::wstring& out, const wchar_t* initialName = L"") {
    wchar_t buf[MAX_PATH] = {};
    wcsncpy_s(buf, initialName, _TRUNCATE);
    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof ofn; ofn.hwndOwner = GetActiveWindow(); ofn.lpstrFilter = filter;
    ofn.lpstrFile = buf; ofn.nMaxFile = MAX_PATH; ofn.lpstrDefExt = defExt;
    ofn.Flags = OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST | (save ? OFN_OVERWRITEPROMPT : OFN_FILEMUSTEXIST);
    if (!(save ? GetSaveFileNameW(&ofn) : GetOpenFileNameW(&ofn))) return false;
    out = buf;
    return true;
}
static std::string sanitizeName(const std::string& in) {
    std::string r;
    for (char c : in) {
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_') r += c;
        else if (c == ' ' || c == '-') r += '_';
    }
    if (r.empty() || !(r[0] >= 'a' && r[0] <= 'z')) r = "t_" + r;
    if (r.size() > 31) r.resize(31);
    return r;
}
static std::wstring exeDir() {
    wchar_t p[MAX_PATH]; GetModuleFileNameW(nullptr, p, MAX_PATH);
    std::wstring s = p; return s.substr(0, s.find_last_of(L"\\/"));
}
static std::wstring findRoot() {
    wchar_t env[MAX_PATH];
    if (GetEnvironmentVariableW(L"CCMOD_HOME", env, MAX_PATH) && GetFileAttributesW((std::wstring(env) + L"\\ccmod_api.py").c_str()) != INVALID_FILE_ATTRIBUTES) return env;
    std::wstring d = exeDir();
    for (int i = 0; i < 5; i++) {
        if (GetFileAttributesW((d + L"\\ccmod_api.py").c_str()) != INVALID_FILE_ATTRIBUTES) return d;
        size_t k = d.find_last_of(L"\\/");
        if (k == std::wstring::npos) break;
        d = d.substr(0, k);
    }
    return L"";
}
// Runs a command with no console window and returns its output (empty + ok=false when it cannot start).
static std::string runHidden(std::wstring cmd, const std::wstring& cwd, bool& ok) {
    SECURITY_ATTRIBUTES sa = {sizeof sa, nullptr, TRUE};
    HANDLE rd = nullptr, wr = nullptr;
    CreatePipe(&rd, &wr, &sa, 0);
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);
    STARTUPINFOW si = {}; si.cb = sizeof si; si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW; si.wShowWindow = SW_HIDE;
    si.hStdOutput = wr; si.hStdError = wr;
    PROCESS_INFORMATION pi = {};
    ok = CreateProcessW(nullptr, &cmd[0], nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, cwd.empty() ? nullptr : cwd.c_str(), &si, &pi) != 0;
    CloseHandle(wr);
    std::string out;
    if (ok) {
        char buf[4096]; DWORD n;
        while (ReadFile(rd, buf, sizeof buf, &n, nullptr) && n) out.append(buf, n);
        WaitForSingleObject(pi.hProcess, 60000);
        CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
    }
    CloseHandle(rd);
    return out;
}

// ------------------------------------------------------------------------------------------------ app state
static ImU32 groupColor(int ti, int alpha = 255) {
    char g = trackInfo(ti).id[0];
    if (g == 'a') return IM_COL32(255, 150, 70, alpha);
    if (g == 'b') return IM_COL32(80, 170, 255, alpha);
    if (g == 'g') return IM_COL32(120, 210, 120, alpha);
    return IM_COL32(190, 130, 255, alpha);
}
static const ImU32 kAccent = IM_COL32(0, 193, 205, 255);

struct App {
    Renderer r;
    Project proj;
    std::vector<Project> undo, redo;
    Baked baked[kTracks];
    bool dirty = true;                 // project changed since last bake
    bool modified = false;             // unsaved changes
    std::wstring file;                 // current project path

    double progress = 0.0;             // playhead 0..1
    bool playing = true;
    int loopMode = 0;                  // 0 loop, 1 ping-pong, 2 once
    double speed = 1.0;
    int pingDir = 1;

    int selTrack = 0, selKey = -1;
    Ease defaultEase = Ease::InOutCubic;
    bool showSpeed = false;
    std::string status = "Pick a template (File > New) or start keyframing.";
    double statusUntil = 0;
    std::string shaderError;
    bool showGlsl = false, showHelp = false;
    std::string glslText;

    // drag state
    enum Kind { None, Scrub, TimelineKey, GraphKey, BezA, BezB } drag = None;
    int dTrack = 0, dKey = 0;
    bool dPushed = false;
    double gYMin = 0, gYMax = 1;       // frozen graph range during a drag

    void say(const std::string& s, double secs = 6) { status = s; statusUntil = ImGui::GetTime() + secs; }
    void pushUndo() { undo.push_back(proj); if (undo.size() > 200) undo.erase(undo.begin()); redo.clear(); modified = true; dirty = true; }
    void doUndo() { if (undo.empty()) return; redo.push_back(proj); proj = undo.back(); undo.pop_back(); selKey = -1; dirty = true; modified = true; }
    void doRedo() { if (redo.empty()) return; undo.push_back(proj); proj = redo.back(); redo.pop_back(); selKey = -1; dirty = true; modified = true; }
    void setProject(const Project& p, bool keepUndo = false) { if (!keepUndo) { undo.clear(); redo.clear(); } proj = p; selTrack = 0; selKey = -1; dirty = true; progress = 0; }
    double duration() const { return proj.duration; }
    Key* selectedKey() {
        if (selTrack < 0 || selTrack >= kTracks) return nullptr;
        auto& ks = proj.tracks[selTrack].keys;
        return (selKey >= 0 && selKey < (int)ks.size()) ? &ks[selKey] : nullptr;
    }
    void addKey(int ti, double t, double v) {
        pushUndo();
        selTrack = ti; selKey = proj.tracks[ti].add(t, v, defaultEase);
    }
    void deleteSelectedKey() {
        if (!selectedKey()) return;
        pushUndo();
        proj.tracks[selTrack].keys.erase(proj.tracks[selTrack].keys.begin() + selKey);
        selKey = -1;
    }
    void rebake() { if (dirty) { bakeProject(proj, baked); dirty = false; } }
};

static App app;

// ------------------------------------------------------------------------------------------------ file actions
static void actionNew(int idx) {
    app.setProject(templates()[idx].make());
    app.file.clear(); app.modified = false;
    app.say(std::string("New transition from template: ") + templates()[idx].name);
}
static bool actionSaveAs() {
    std::wstring p;
    std::wstring init = toWide(app.proj.name) + L".cctrans";
    if (!pickFile(true, L"ccmod transition project (*.cctrans)\0*.cctrans\0", L"cctrans", p, init.c_str())) return false;
    app.file = p;
    return writeFile(toUtf8(p), app.proj.toJson().dump()) ? (app.modified = false, app.say("Saved " + toUtf8(p)), true) : (app.say("Could not save the file"), false);
}
static void actionSave() {
    if (app.file.empty()) { actionSaveAs(); return; }
    if (writeFile(toUtf8(app.file), app.proj.toJson().dump())) { app.modified = false; app.say("Saved"); }
    else app.say("Could not save the file");
}
static void actionOpen() {
    std::wstring p;
    if (!pickFile(false, L"ccmod transition project (*.cctrans)\0*.cctrans\0", L"cctrans", p)) return;
    Json j; std::string err; Project q;
    if (!Json::parse(readFile(toUtf8(p)), j, &err) || !Project::fromJson(j, q, &err)) { app.say("Could not open: " + err); return; }
    app.setProject(q); app.file = p; app.modified = false; app.say("Opened " + toUtf8(p));
}
static std::string exportJson() {
    app.rebake();
    codegen::Export ex = codegen::glsl(app.proj, app.baked);
    Json j = Json::object();
    j.set("format", Json::string("ccmod-transition")); j.set("version", Json::number(1));
    j.set("name", Json::string(sanitizeName(app.proj.name))); j.set("label", Json::string(app.proj.label));
    j.set("description", Json::string(app.proj.description)); j.set("duration", Json::number(app.proj.duration));
    j.set("helpers", Json::string(ex.helpers)); j.set("body", Json::string(ex.body));
    j.set("project", app.proj.toJson());
    return j.dump();
}
static void actionExport() {
    std::wstring p;
    std::wstring init = toWide(sanitizeName(app.proj.name)) + L".ccmodtrans";
    if (!pickFile(true, L"ccmod transition (*.ccmodtrans)\0*.ccmodtrans\0", L"ccmodtrans", p, init.c_str())) return;
    if (writeFile(toUtf8(p), exportJson())) app.say("Exported. In ccmod run:  python ccmod_api.py import-transition \"" + toUtf8(p) + "\"", 12);
    else app.say("Could not write the file");
}
static void actionInstall() {
    std::wstring root = findRoot();
    if (root.empty()) { app.say("Cannot find your ccmod folder. Set CCMOD_HOME, or put this app inside the ccmod folder, or use File > Export."); return; }
    std::wstring dir = root + L"\\recipes\\transitions";
    SHCreateDirectoryExW(nullptr, dir.c_str(), nullptr);
    std::wstring f = dir + L"\\" + toWide(sanitizeName(app.proj.name)) + L".ccmodtrans";
    if (!writeFile(toUtf8(f), exportJson())) { app.say("Could not write " + toUtf8(f)); return; }
    bool ok = false;
    std::string out = runHidden(L"python \"" + root + L"\\ccmod_api.py\" import-transition \"" + f + L"\"", root, ok);
    if (!ok) out = runHidden(L"py \"" + root + L"\\ccmod_api.py\" import-transition \"" + f + L"\"", root, ok);
    if (!ok) { app.say("Python was not found. Run ccmod's 'Install ccmod' first, or use File > Export."); return; }
    Json j; std::string msg = out;
    if (Json::parse(out, j)) msg = j.str("message", out);
    app.say(msg, 14);
}

// ------------------------------------------------------------------------------------------------ UI pieces
static void sampleCurve(const Track& tr, int ti, std::vector<ImVec2>& out, double ymin, double ymax, ImVec2 p0, ImVec2 size, int n = 220) {
    out.clear();
    for (int i = 0; i <= n; i++) {
        double t = (double)i / n, v = app.proj.value(ti, t);
        out.push_back(ImVec2(p0.x + (float)t * size.x, p0.y + size.y - (float)((v - ymin) / (ymax - ymin)) * size.y));
    }
    (void)tr;
}

static void drawEaseThumb(ImDrawList* dl, ImVec2 p, float s, Ease e, ImU32 col, const double* bez = nullptr) {
    dl->AddRectFilled(p, ImVec2(p.x + s, p.y + s), IM_COL32(28, 28, 30, 255), 4);
    // value range includes overshoot (back / elastic)
    double lo = 0, hi = 1;
    for (int i = 0; i <= 40; i++) { double v = e == Ease::Hold ? 0 : easeApply(e, i / 40.0, bez); lo = std::min(lo, v); hi = std::max(hi, v); }
    float pad = 7;
    std::vector<ImVec2> pts;
    for (int i = 0; i <= 28; i++) {
        double u = i / 28.0, v = e == Ease::Hold ? (i == 28 ? 1.0 : 0.0) : easeApply(e, u, bez);
        pts.push_back(ImVec2(p.x + pad + (float)u * (s - 2 * pad), p.y + s - pad - (float)((v - lo) / (hi - lo)) * (s - 2 * pad)));
    }
    dl->AddPolyline(pts.data(), (int)pts.size(), col, 0, 1.6f);
}

static void easingGallery() {
    Key* k = app.selectedKey();
    ImGui::TextUnformatted("Easing");
    ImGui::SameLine();
    ImGui::TextDisabled(k ? "(for the selected key's segment)" : "(select a key first)");
    ImGui::BeginChild("easeGrid", ImVec2(0, 0), ImGuiChildFlags_Borders);
    float s = 62, gap = 6, w = ImGui::GetContentRegionAvail().x;
    int perRow = std::max(1, (int)((w + gap) / (s + gap)));
    int col = 0;
    for (int i = 0; i < (int)Ease::Count; i++) {
        Ease e = (Ease)i;
        ImVec2 p = ImGui::GetCursorScreenPos();
        ImGui::PushID(i);
        bool active = k && k->ease == e;
        if (ImGui::InvisibleButton("##e", ImVec2(s, s)) && k) {
            app.pushUndo();
            app.selectedKey()->ease = e;
        }
        bool hov = ImGui::IsItemHovered();
        ImDrawList* dl = ImGui::GetWindowDrawList();
        drawEaseThumb(dl, p, s, e, active ? kAccent : (hov ? IM_COL32(255, 255, 255, 255) : IM_COL32(170, 170, 175, 255)),
                      e == Ease::Bezier && k ? k->bez : nullptr);
        if (active) dl->AddRect(p, ImVec2(p.x + s, p.y + s), kAccent, 4, 0, 2);
        if (hov) ImGui::SetTooltip("%s", easeLabel(e));
        ImGui::PopID();
        if (++col < perRow) ImGui::SameLine(0, gap); else col = 0;
    }
    ImGui::EndChild();
}

static void inspector() {
    Project& p = app.proj;
    ImGui::TextUnformatted("Transition");
    char buf[256];
    std::snprintf(buf, sizeof buf, "%s", p.name.c_str());
    ImGui::SetNextItemWidth(-1);
    if (ImGui::InputText("##name", buf, sizeof buf)) { p.name = buf; app.modified = true; }
    ImGui::SameLine(0, 0); ImGui::Dummy(ImVec2(0, 0));
    ImGui::TextDisabled("id: %s", sanitizeName(p.name).c_str());
    std::snprintf(buf, sizeof buf, "%s", p.label.c_str());
    ImGui::SetNextItemWidth(-1);
    if (ImGui::InputTextWithHint("##label", "Name shown in CapCut", buf, sizeof buf)) { p.label = buf; app.modified = true; }
    std::snprintf(buf, sizeof buf, "%s", p.description.c_str());
    ImGui::SetNextItemWidth(-1);
    if (ImGui::InputTextWithHint("##desc", "Short description", buf, sizeof buf)) { p.description = buf; app.modified = true; }
    float dur = (float)p.duration;
    ImGui::SetNextItemWidth(-1);
    if (ImGui::SliderFloat("##dur", &dur, 0.2f, 4.0f, "Preview length %.2f s")) { p.duration = dur; app.modified = true; }

    ImGui::Separator();
    ImGui::TextUnformatted("Reveal mask on the incoming clip");
    int m = (int)p.mask;
    ImGui::SetNextItemWidth(-1);
    if (ImGui::BeginCombo("##mask", maskLabel(p.mask))) {
        for (int i = 0; i < (int)MaskType::Count; i++)
            if (ImGui::Selectable(maskLabel((MaskType)i), i == m)) { app.pushUndo(); p.mask = (MaskType)i; if (i && p.tracks[trackIndex("mask")].keys.empty()) { p.tracks[trackIndex("mask")].add(0, 0, Ease::InOutCubic); p.tracks[trackIndex("mask")].add(1, 1); } }
        ImGui::EndCombo();
    }
    if (p.mask != MaskType::None) {
        float s = (float)p.maskSoftness;
        ImGui::SetNextItemWidth(-1);
        if (ImGui::SliderFloat("##soft", &s, 0.01f, 0.5f, "Edge softness %.2f")) { p.maskSoftness = s; app.modified = true; }
        if (p.mask == MaskType::Wipe) {
            float a = (float)p.maskAngle;
            ImGui::SetNextItemWidth(-1);
            if (ImGui::SliderFloat("##ang", &a, 0.f, 360.f, "Wipe angle %.0f deg")) { p.maskAngle = a; app.modified = true; }
        }
        ImGui::TextDisabled("Animate it with the 'Reveal amount' track.");
    }
    ImGui::Separator();
    {
        double kmin, kmax;
        if (keyRange(p, kmin, kmax) && kmax - kmin > 1e-6 && (kmin > 0.01 || kmax < 0.99)) {
            ImGui::TextColored(ImVec4(1.0f, 0.75f, 0.3f, 1.0f), "Empty time: %.0f%% before, %.0f%% after the keys", kmin * 100, (1 - kmax) * 100);
            ImGui::TextDisabled("The transition still plays over this time, so it feels late/slow.");
            if (ImGui::Button("Fit timeline to keys")) { app.pushUndo(); fitToKeys(p); }
        } else {
            ImGui::TextDisabled("Timing: keys fill the whole transition.");
        }
    }
    ImGui::Separator();
    ImGui::TextUnformatted("Motion tile (fills empty screen area)");
    ImGui::SetNextItemWidth(-1);
    if (ImGui::BeginCombo("##tile", tileLabel(p.tile))) {
        for (int m = 0; m < (int)TileMode::Count; m++)
            if (ImGui::Selectable(tileLabel((TileMode)m), (int)p.tile == m)) { app.pushUndo(); p.tile = (TileMode)m; }
        ImGui::EndCombo();
    }
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("Wherever neither clip covers the screen (clips slid, shrunk or rotated away), show a mirrored/repeated copy of the picture instead of black bars.");
    bool inv = p.invertY;
    if (ImGui::Checkbox("Flip vertical on export", &inv)) { app.pushUndo(); p.invertY = inv; }
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("Turn on if the transition runs upside-down inside CapCut.");

    ImGui::Separator();
    const TrackInfo& ti = trackInfo(app.selTrack);
    ImGui::Text("Track: %s - %s", ti.group, ti.label);
    if (ImGui::Button("Add key at playhead")) app.addKey(app.selTrack, app.progress, app.proj.value(app.selTrack, app.progress));
    ImGui::SameLine();
    if (ImGui::Button("Clear track")) { app.pushUndo(); p.tracks[app.selTrack].keys.clear(); app.selKey = -1; }
    ImGui::SetNextItemWidth(-1);
    if (ImGui::BeginCombo("##defEase", (std::string("New keys ease: ") + easeLabel(app.defaultEase)).c_str())) {
        for (int i = 0; i < (int)Ease::Count; i++) if (ImGui::Selectable(easeLabel((Ease)i), app.defaultEase == (Ease)i)) app.defaultEase = (Ease)i;
        ImGui::EndCombo();
    }

    Key* k = app.selectedKey();
    ImGui::Separator();
    if (!k) { ImGui::TextDisabled("Select a key to edit it (click one in the timeline or graph)."); return; }
    ImGui::Text("Key %d of %d", app.selKey + 1, (int)p.tracks[app.selTrack].keys.size());
    auto& keys = p.tracks[app.selTrack].keys;
    double lo = app.selKey > 0 ? keys[app.selKey - 1].t + 0.001 : 0.0, hi = app.selKey + 1 < (int)keys.size() ? keys[app.selKey + 1].t - 0.001 : 1.0;
    float tv = (float)(k->t * p.duration);
    ImGui::SetNextItemWidth(-1);
    if (ImGui::DragFloat("##kt", &tv, 0.005f, (float)(lo * p.duration), (float)(hi * p.duration), "Time %.3f s")) { if (!app.dPushed) app.pushUndo(); k->t = tv / p.duration; app.dirty = true; }
    if (ImGui::IsItemDeactivatedAfterEdit()) app.dPushed = false; else if (ImGui::IsItemActivated()) app.dPushed = false;
    float vv = (float)k->v;
    ImGui::SetNextItemWidth(-1);
    if (ImGui::DragFloat("##kv", &vv, (float)((ti.hi - ti.lo) / 400.0), (float)(ti.lo * 3), (float)(ti.hi * 3), "Value %.3f")) { if (!app.dPushed) { app.pushUndo(); app.dPushed = true; } k->v = vv; app.dirty = true; }
    if (ImGui::IsItemDeactivatedAfterEdit()) app.dPushed = false;
    ImGui::SetNextItemWidth(-1);
    if (ImGui::BeginCombo("##kease", easeLabel(k->ease))) {
        for (int i = 0; i < (int)Ease::Count; i++) if (ImGui::Selectable(easeLabel((Ease)i), k->ease == (Ease)i)) { app.pushUndo(); k->ease = (Ease)i; }
        ImGui::EndCombo();
    }
    if (k->ease == Ease::Bezier) {
        float b[4] = {(float)k->bez[0], (float)k->bez[1], (float)k->bez[2], (float)k->bez[3]};
        ImGui::SetNextItemWidth(-1);
        if (ImGui::DragFloat4("##bez", b, 0.01f, -1.0f, 2.0f, "%.2f")) { for (int i = 0; i < 4; i++) k->bez[i] = b[i]; k->bez[0] = std::min(1.0, std::max(0.0, k->bez[0])); k->bez[2] = std::min(1.0, std::max(0.0, k->bez[2])); app.dirty = true; }
        ImGui::TextDisabled("or drag the handles in the graph");
    }
    if (ImGui::Button("Delete key")) app.deleteSelectedKey();
}

static void timelinePanel() {
    ImGuiIO& io = ImGui::GetIO();
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const float labelW = 170, rulerH = 26, rowH = 22, headH = 20, pad = 10;
    ImVec2 origin = ImGui::GetCursorScreenPos();
    float avail = ImGui::GetContentRegionAvail().x;
    float x0 = origin.x + labelW, xw = std::max(60.0f, avail - labelW - pad);

    // layout rows
    struct Row { int track; float y; bool header; const char* text; };
    std::vector<Row> rows;
    float y = origin.y + rulerH;
    const char* lastGroup = nullptr;
    for (int i = 0; i < kTracks; i++) {
        if (!lastGroup || std::strcmp(lastGroup, trackInfo(i).group) != 0) { rows.push_back({-1, y, true, trackInfo(i).group}); y += headH; lastGroup = trackInfo(i).group; }
        rows.push_back({i, y, false, trackInfo(i).label}); y += rowH;
    }
    ImGui::Dummy(ImVec2(avail, y - origin.y + 6));
    bool windowHover = ImGui::IsWindowHovered();

    // ruler
    dl->AddRectFilled(ImVec2(origin.x, origin.y), ImVec2(x0 + xw + pad, origin.y + rulerH), IM_COL32(34, 34, 38, 255));
    int ticks = 10;
    for (int i = 0; i <= ticks; i++) {
        float x = x0 + xw * i / ticks;
        dl->AddLine(ImVec2(x, origin.y + 14), ImVec2(x, origin.y + rulerH), IM_COL32(120, 120, 128, 255));
        char b[24]; std::snprintf(b, sizeof b, "%.2fs", app.duration() * i / ticks);
        if (i % 2 == 0) dl->AddText(ImVec2(x + 3, origin.y + 1), IM_COL32(170, 170, 178, 255), b);
    }
    // rows
    for (const Row& r : rows) {
        if (r.header) {
            dl->AddText(ImVec2(origin.x + 4, r.y + 2), IM_COL32(150, 150, 158, 255), r.text);
            bool isA = std::strncmp(r.text, "Outgoing", 8) == 0, isB = std::strncmp(r.text, "Incoming", 8) == 0;
            if (isA || isB) {
                bool& flag = isA ? app.proj.showA : app.proj.showB;
                bool on = flag;
                ImGui::SetCursorScreenPos(ImVec2(origin.x + 128, r.y));
                ImGui::PushID(isA ? "showA" : "showB");
                ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(2, 0));
                if (ImGui::Checkbox("show", &on)) { app.pushUndo(); flag = on; }
                ImGui::PopStyleVar();
                ImGui::PopID();
            }
            dl->AddLine(ImVec2(origin.x, r.y + headH - 1), ImVec2(x0 + xw + pad, r.y + headH - 1), IM_COL32(60, 60, 66, 255));
            continue;
        }
        bool sel = r.track == app.selTrack;
        dl->AddRectFilled(ImVec2(origin.x, r.y), ImVec2(x0 + xw + pad, r.y + rowH), sel ? IM_COL32(52, 56, 62, 255) : IM_COL32(40, 40, 44, 255));
        dl->AddRectFilled(ImVec2(origin.x, r.y), ImVec2(origin.x + 3, r.y + rowH), groupColor(r.track));
        dl->AddText(ImVec2(origin.x + 10, r.y + 3), sel ? IM_COL32(255, 255, 255, 255) : IM_COL32(190, 190, 196, 255), r.text);
        char vb[32]; std::snprintf(vb, sizeof vb, "%.2f", app.proj.value(r.track, app.progress));
        ImVec2 ts = ImGui::CalcTextSize(vb);
        dl->AddText(ImVec2(x0 - ts.x - 8, r.y + 3), IM_COL32(120, 200, 205, 255), vb);
        // the thin track line and its keys
        const auto& keys = app.proj.tracks[r.track].keys;
        for (size_t k = 0; k < keys.size(); k++) {
            float kx = x0 + (float)keys[k].t * xw, ky = r.y + rowH / 2;
            if (k + 1 < keys.size()) dl->AddLine(ImVec2(kx, ky), ImVec2(x0 + (float)keys[k + 1].t * xw, ky), groupColor(r.track, 90), 2.0f);
        }
        for (size_t k = 0; k < keys.size(); k++) {
            float kx = x0 + (float)keys[k].t * xw, ky = r.y + rowH / 2, d = (r.track == app.selTrack && (int)k == app.selKey) ? 7.0f : 5.5f;
            ImVec2 pts[4] = {ImVec2(kx, ky - d), ImVec2(kx + d, ky), ImVec2(kx, ky + d), ImVec2(kx - d, ky)};
            bool selk = r.track == app.selTrack && (int)k == app.selKey;
            dl->AddConvexPolyFilled(pts, 4, selk ? IM_COL32(255, 255, 255, 255) : groupColor(r.track));
            dl->AddPolyline(pts, 4, IM_COL32(20, 20, 20, 255), ImDrawFlags_Closed, 1.0f);
        }
    }
    // playhead
    float px = x0 + (float)app.progress * xw;
    dl->AddLine(ImVec2(px, origin.y), ImVec2(px, y), kAccent, 2.0f);
    dl->AddTriangleFilled(ImVec2(px - 6, origin.y), ImVec2(px + 6, origin.y), ImVec2(px, origin.y + 10), kAccent);

    // ---- input
    ImVec2 m = io.MousePos;
    auto toT = [&](float mx) { return std::min(1.0, std::max(0.0, (double)((mx - x0) / xw))); };
    auto snap = [&](double t) { return io.KeyAlt ? t : std::round(t * 100.0) / 100.0; };
    if (windowHover && ImGui::IsMouseClicked(0)) {
        bool onRuler = m.y >= origin.y && m.y < origin.y + rulerH && m.x >= x0 - 8;
        if (onRuler) { app.drag = App::Scrub; app.playing = false; app.progress = toT(m.x); }
        else {
            // key hit test first, else row select / double-click add
            int hitT = -1, hitK = -1;
            for (const Row& r : rows) {
                if (r.header || m.y < r.y || m.y >= r.y + rowH) continue;
                const auto& keys = app.proj.tracks[r.track].keys;
                for (size_t k = 0; k < keys.size(); k++)
                    if (std::fabs(m.x - (x0 + (float)keys[k].t * xw)) < 8) { hitT = r.track; hitK = (int)k; }
                if (hitT < 0 && m.x > origin.x) {
                    app.selTrack = r.track; app.selKey = -1;
                    if (ImGui::IsMouseDoubleClicked(0) && m.x >= x0) { double t = snap(toT(m.x)); app.addKey(r.track, t, app.proj.value(r.track, t)); }
                }
            }
            if (hitT >= 0) { app.selTrack = hitT; app.selKey = hitK; app.drag = App::TimelineKey; app.dTrack = hitT; app.dKey = hitK; app.dPushed = false; }
        }
    }
    if (windowHover && ImGui::IsMouseDoubleClicked(0) && app.drag == App::None) {
        for (const Row& r : rows) if (!r.header && m.y >= r.y && m.y < r.y + rowH && m.x >= x0) { double t = snap(toT(m.x)); app.addKey(r.track, t, app.proj.value(r.track, t)); }
    }
    if (app.drag == App::Scrub) { if (io.MouseDown[0]) app.progress = toT(m.x); else app.drag = App::None; }
    if (app.drag == App::TimelineKey) {
        if (io.MouseDown[0]) {
            auto& keys = app.proj.tracks[app.dTrack].keys;
            if (app.dKey < (int)keys.size()) {
                double lo = app.dKey > 0 ? keys[app.dKey - 1].t + 0.001 : 0.0, hi = app.dKey + 1 < (int)keys.size() ? keys[app.dKey + 1].t - 0.001 : 1.0;
                double nt = std::min(hi, std::max(lo, snap(toT(m.x))));
                if (std::fabs(nt - keys[app.dKey].t) > 1e-9) { if (!app.dPushed) { app.pushUndo(); app.dPushed = true; } keys[app.dKey].t = nt; app.dirty = true; }
            }
        } else app.drag = App::None;
    }
}

static void graphPanel() {
    ImGuiIO& io = ImGui::GetIO();
    ImDrawList* dl = ImGui::GetWindowDrawList();
    int ti = app.selTrack;
    const TrackInfo& info = trackInfo(ti);
    Track& tr = app.proj.tracks[ti];

    ImGui::TextColored(ImVec4(1, 1, 1, 1), "%s - %s", info.group, info.label);
    ImGui::SameLine(); ImGui::TextDisabled("   Ctrl+click or double-click adds a key. Drag keys and handles. Delete removes.");
    ImGui::SameLine(ImGui::GetContentRegionAvail().x - 110);
    ImGui::Checkbox("Show speed", &app.showSpeed);

    ImVec2 avail = ImGui::GetContentRegionAvail();
    ImVec2 o = ImGui::GetCursorScreenPos();
    const float left = 54, bottom = 22, top = 6, right = 14;
    ImVec2 p0(o.x + left, o.y + top), size(std::max(40.0f, avail.x - left - right), std::max(40.0f, avail.y - bottom - top - 4));
    ImGui::InvisibleButton("##graph", avail);
    bool hover = ImGui::IsItemHovered();

    // value range
    double ymin, ymax;
    if (app.drag == App::GraphKey || app.drag == App::BezA || app.drag == App::BezB) { ymin = app.gYMin; ymax = app.gYMax; }
    else {
        ymin = info.def; ymax = info.def;
        for (int i = 0; i <= 120; i++) { double v = app.proj.value(ti, i / 120.0); ymin = std::min(ymin, v); ymax = std::max(ymax, v); }
        for (auto& k : tr.keys) { ymin = std::min(ymin, k.v); ymax = std::max(ymax, k.v); }
        double span = std::max(ymax - ymin, (info.hi - info.lo) * 0.15);
        double mid = (ymin + ymax) / 2;
        ymin = mid - span * 0.62; ymax = mid + span * 0.62;
    }
    auto sx = [&](double t) { return p0.x + (float)t * size.x; };
    auto sy = [&](double v) { return p0.y + size.y - (float)((v - ymin) / (ymax - ymin)) * size.y; };
    auto fromX = [&](float x) { return std::min(1.0, std::max(0.0, (double)((x - p0.x) / size.x))); };
    auto fromY = [&](float y) { return ymin + (1.0 - (double)((y - p0.y) / size.y)) * (ymax - ymin); };

    dl->AddRectFilled(p0, ImVec2(p0.x + size.x, p0.y + size.y), IM_COL32(26, 26, 29, 255));
    for (int i = 0; i <= 10; i++) {
        float x = sx(i / 10.0);
        dl->AddLine(ImVec2(x, p0.y), ImVec2(x, p0.y + size.y), i % 5 == 0 ? IM_COL32(70, 70, 76, 255) : IM_COL32(44, 44, 48, 255));
        if (i % 2 == 0) { char b[16]; std::snprintf(b, sizeof b, "%.2fs", app.duration() * i / 10); dl->AddText(ImVec2(x - 14, p0.y + size.y + 3), IM_COL32(150, 150, 158, 255), b); }
    }
    for (int i = 0; i <= 4; i++) {
        double v = ymin + (ymax - ymin) * i / 4; float y = sy(v);
        dl->AddLine(ImVec2(p0.x, y), ImVec2(p0.x + size.x, y), IM_COL32(44, 44, 48, 255));
        char b[24]; std::snprintf(b, sizeof b, "%.2f", v); dl->AddText(ImVec2(o.x + 2, y - 7), IM_COL32(150, 150, 158, 255), b);
    }
    if (ymin < 0 && ymax > 0) dl->AddLine(ImVec2(p0.x, sy(0)), ImVec2(p0.x + size.x, sy(0)), IM_COL32(90, 90, 98, 255));
    if (ymin < info.def && ymax > info.def) dl->AddLine(ImVec2(p0.x, sy(info.def)), ImVec2(p0.x + size.x, sy(info.def)), IM_COL32(80, 120, 120, 120), 1.0f);

    // the curve, and (optionally) its speed
    std::vector<ImVec2> pts;
    sampleCurve(tr, ti, pts, ymin, ymax, p0, size);
    for (auto& q : pts) q.y = std::min(std::max(q.y, p0.y - 2.0f), p0.y + size.y + 2.0f);
    dl->PushClipRect(p0, ImVec2(p0.x + size.x, p0.y + size.y), true);
    if (app.showSpeed) {
        std::vector<double> sp; double mx = 1e-9;
        for (int i = 0; i <= 220; i++) { double a = app.proj.value(ti, std::max(0.0, (i - 1) / 220.0)), b = app.proj.value(ti, std::min(1.0, (i + 1) / 220.0)); double d = std::fabs(b - a); sp.push_back(d); mx = std::max(mx, d); }
        std::vector<ImVec2> sv;
        for (int i = 0; i <= 220; i++) sv.push_back(ImVec2(p0.x + size.x * i / 220.0f, p0.y + size.y - (float)(sp[i] / mx) * size.y * 0.9f));
        dl->AddPolyline(sv.data(), (int)sv.size(), IM_COL32(240, 200, 80, 150), 0, 1.4f);
    }
    dl->AddPolyline(pts.data(), (int)pts.size(), groupColor(ti), 0, 2.4f);

    // bezier handles for the selected key's segment
    Key* sel = app.selectedKey();
    ImVec2 hA, hB, kA, kB; bool showBez = false;
    if (sel && sel->ease == Ease::Bezier && app.selKey + 1 < (int)tr.keys.size()) {
        const Key& n = tr.keys[app.selKey + 1];
        double dt = n.t - sel->t, dv = n.v - sel->v;
        kA = ImVec2(sx(sel->t), sy(sel->v)); kB = ImVec2(sx(n.t), sy(n.v));
        hA = ImVec2(sx(sel->t + sel->bez[0] * dt), sy(sel->v + sel->bez[1] * dv));
        hB = ImVec2(sx(sel->t + sel->bez[2] * dt), sy(sel->v + sel->bez[3] * dv));
        dl->AddLine(kA, hA, IM_COL32(255, 255, 255, 110), 1.0f); dl->AddLine(kB, hB, IM_COL32(255, 255, 255, 110), 1.0f);
        dl->AddCircleFilled(hA, 5, IM_COL32(255, 220, 120, 255)); dl->AddCircleFilled(hB, 5, IM_COL32(255, 220, 120, 255));
        showBez = true;
    }
    for (size_t k = 0; k < tr.keys.size(); k++) {
        ImVec2 c(sx(tr.keys[k].t), sy(tr.keys[k].v));
        bool s = (int)k == app.selKey;
        dl->AddRectFilled(ImVec2(c.x - (s ? 6 : 4.5f), c.y - (s ? 6 : 4.5f)), ImVec2(c.x + (s ? 6 : 4.5f), c.y + (s ? 6 : 4.5f)), s ? IM_COL32(255, 255, 255, 255) : groupColor(ti));
        dl->AddRect(ImVec2(c.x - 5, c.y - 5), ImVec2(c.x + 5, c.y + 5), IM_COL32(15, 15, 15, 255));
    }
    // playhead + value dot
    float px = sx(app.progress);
    dl->AddLine(ImVec2(px, p0.y), ImVec2(px, p0.y + size.y), kAccent, 1.6f);
    dl->AddCircleFilled(ImVec2(px, sy(app.proj.value(ti, app.progress))), 4.5f, kAccent);
    dl->PopClipRect();

    // ---- input
    ImVec2 m = io.MousePos;
    auto near2 = [&](ImVec2 a, float r) { float dx = m.x - a.x, dy = m.y - a.y; return dx * dx + dy * dy <= r * r; };
    if (hover && ImGui::IsMouseClicked(0) && app.drag == App::None) {
        app.gYMin = ymin; app.gYMax = ymax;
        if (showBez && near2(hA, 8)) app.drag = App::BezA;
        else if (showBez && near2(hB, 8)) app.drag = App::BezB;
        else {
            int hit = -1;
            for (size_t k = 0; k < tr.keys.size(); k++) if (near2(ImVec2(sx(tr.keys[k].t), sy(tr.keys[k].v)), 9)) hit = (int)k;
            if (hit >= 0) { app.selKey = hit; app.drag = App::GraphKey; app.dTrack = ti; app.dKey = hit; app.dPushed = false; }
            else if (io.KeyCtrl || ImGui::IsMouseDoubleClicked(0)) {
                if (m.x >= p0.x && m.x <= p0.x + size.x && m.y >= p0.y && m.y <= p0.y + size.y) app.addKey(ti, std::round(fromX(m.x) * 200) / 200, fromY(m.y));
            }
            else if (m.x >= p0.x && m.y >= p0.y && m.y <= p0.y + size.y) { app.selKey = -1; app.drag = App::Scrub; app.playing = false; app.progress = fromX(m.x); }
        }
    }
    if (app.drag == App::GraphKey) {
        if (io.MouseDown[0] && app.dKey < (int)tr.keys.size()) {
            Key& k = tr.keys[app.dKey];
            double lo = app.dKey > 0 ? tr.keys[app.dKey - 1].t + 0.001 : 0.0, hi = app.dKey + 1 < (int)tr.keys.size() ? tr.keys[app.dKey + 1].t - 0.001 : 1.0;
            double nt = std::min(hi, std::max(lo, io.KeyAlt ? fromX(m.x) : std::round(fromX(m.x) * 200) / 200)), nv = fromY(m.y);
            if (io.KeyShift) nv = k.v;                          // shift = time only
            if (std::fabs(nt - k.t) > 1e-9 || std::fabs(nv - k.v) > 1e-9) { if (!app.dPushed) { app.pushUndo(); app.dPushed = true; } k.t = nt; k.v = nv; app.dirty = true; }
        } else app.drag = App::None;
    }
    if (app.drag == App::BezA || app.drag == App::BezB) {
        if (io.MouseDown[0] && sel && app.selKey + 1 < (int)tr.keys.size()) {
            const Key& n = tr.keys[app.selKey + 1];
            double dt = n.t - sel->t, dv = n.v - sel->v;
            double bx = dt > 1e-9 ? std::min(1.0, std::max(0.0, (fromX(m.x) - sel->t) / dt)) : 0.0;
            double by = std::fabs(dv) > 1e-9 ? (fromY(m.y) - sel->v) / dv : 0.0;
            if (!app.dPushed) { app.pushUndo(); app.dPushed = true; }
            if (app.drag == App::BezA) { sel->bez[0] = bx; sel->bez[1] = by; } else { sel->bez[2] = bx; sel->bez[3] = by; }
            app.dirty = true;
        } else app.drag = App::None;
    }
    if (app.drag == App::Scrub) { if (io.MouseDown[0]) app.progress = fromX(m.x); else app.drag = App::None; }
    if (hover && ImGui::IsMouseClicked(1)) {
        for (size_t k = 0; k < tr.keys.size(); k++) if (near2(ImVec2(sx(tr.keys[k].t), sy(tr.keys[k].v)), 9)) { app.selKey = (int)k; ImGui::OpenPopup("keyMenu"); }
    }
    if (ImGui::BeginPopup("keyMenu")) {
        if (ImGui::MenuItem("Delete key")) app.deleteSelectedKey();
        if (ImGui::BeginMenu("Easing to next key")) {
            for (int i = 0; i < (int)Ease::Count; i++) if (ImGui::MenuItem(easeLabel((Ease)i))) { app.pushUndo(); if (app.selectedKey()) app.selectedKey()->ease = (Ease)i; }
            ImGui::EndMenu();
        }
        if (ImGui::MenuItem("Set value to default") && app.selectedKey()) { app.pushUndo(); app.selectedKey()->v = info.def; }
        ImGui::EndPopup();
    }
}

static void transport(float S) {
    if (ImGui::Button(app.playing ? "Pause" : "Play", ImVec2(70, 0))) { app.playing = !app.playing; if (app.playing && app.progress >= 1.0) app.progress = 0; }
    ImGui::SameLine();
    if (ImGui::Button("Restart")) { app.progress = 0; app.pingDir = 1; }
    ImGui::SameLine();
    ImGui::SetNextItemWidth(120);
    const char* modes[] = {"Loop", "Ping-pong", "Once"};
    ImGui::Combo("##loop", &app.loopMode, modes, 3);
    ImGui::SameLine();
    float sp = (float)app.speed;
    ImGui::SetNextItemWidth(S - 330 > 70 ? S - 330 : 70);
    if (ImGui::SliderFloat("##speed", &sp, 0.1f, 2.0f, "%.1fx")) app.speed = sp;
    float pr = (float)app.progress;
    ImGui::SetNextItemWidth(S);
    char fmt[48]; std::snprintf(fmt, sizeof fmt, "%%.3f  (%.2f s)", app.progress * app.duration());
    if (ImGui::SliderFloat("##scrub", &pr, 0.0f, 1.0f, fmt)) { app.progress = pr; app.playing = false; }
    if (ImGui::Button("Picture A...")) {
        std::wstring p; std::string err;
        if (pickFile(false, L"Pictures\0*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff\0All files\0*.*\0", L"png", p)) { if (!app.r.loadImage(0, p.c_str(), err)) app.say(err); }
    }
    ImGui::SameLine();
    if (ImGui::Button("Picture B...")) {
        std::wstring p; std::string err;
        if (pickFile(false, L"Pictures\0*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff\0All files\0*.*\0", L"png", p)) { if (!app.r.loadImage(1, p.c_str(), err)) app.say(err); }
    }
    ImGui::SameLine();
    if (ImGui::Button("Sample pictures")) { app.r.useSample(0); app.r.useSample(1); }
}

static void applyStyle() {
    ImGuiStyle& s = ImGui::GetStyle();
    s.WindowRounding = 0; s.FrameRounding = 4; s.ChildRounding = 6; s.GrabRounding = 4; s.PopupRounding = 6; s.TabRounding = 4;
    s.FramePadding = ImVec2(8, 4); s.ItemSpacing = ImVec2(8, 6); s.ScrollbarSize = 12; s.WindowPadding = ImVec2(10, 8);
    ImVec4* c = s.Colors;
    c[ImGuiCol_WindowBg] = ImVec4(0.105f, 0.105f, 0.115f, 1); c[ImGuiCol_ChildBg] = ImVec4(0.135f, 0.135f, 0.148f, 1);
    c[ImGuiCol_PopupBg] = ImVec4(0.14f, 0.14f, 0.155f, 1); c[ImGuiCol_Border] = ImVec4(0.24f, 0.24f, 0.27f, 1);
    c[ImGuiCol_FrameBg] = ImVec4(0.19f, 0.19f, 0.21f, 1); c[ImGuiCol_FrameBgHovered] = ImVec4(0.24f, 0.24f, 0.27f, 1); c[ImGuiCol_FrameBgActive] = ImVec4(0.28f, 0.28f, 0.31f, 1);
    c[ImGuiCol_Button] = ImVec4(0.22f, 0.22f, 0.25f, 1); c[ImGuiCol_ButtonHovered] = ImVec4(0.0f, 0.55f, 0.6f, 1); c[ImGuiCol_ButtonActive] = ImVec4(0.0f, 0.65f, 0.7f, 1);
    c[ImGuiCol_Header] = ImVec4(0.0f, 0.45f, 0.5f, 0.7f); c[ImGuiCol_HeaderHovered] = ImVec4(0.0f, 0.55f, 0.6f, 0.8f); c[ImGuiCol_HeaderActive] = ImVec4(0.0f, 0.65f, 0.7f, 1);
    c[ImGuiCol_SliderGrab] = ImVec4(0.0f, 0.76f, 0.8f, 1); c[ImGuiCol_SliderGrabActive] = ImVec4(0.2f, 0.9f, 0.95f, 1); c[ImGuiCol_CheckMark] = ImVec4(0.0f, 0.76f, 0.8f, 1);
    c[ImGuiCol_Separator] = ImVec4(0.24f, 0.24f, 0.27f, 1); c[ImGuiCol_MenuBarBg] = ImVec4(0.09f, 0.09f, 0.1f, 1);
    c[ImGuiCol_TitleBgActive] = ImVec4(0.09f, 0.09f, 0.1f, 1);
}

static void drawUi(float dt) {
    ImGuiIO& io = ImGui::GetIO();
    // playback
    if (app.playing) {
        app.progress += dt * app.speed / std::max(0.05, app.duration()) * app.pingDir;
        if (app.loopMode == 0 && app.progress > 1.0) app.progress -= 1.0;
        else if (app.loopMode == 1) { if (app.progress > 1.0) { app.progress = 1.0; app.pingDir = -1; } else if (app.progress < 0.0) { app.progress = 0.0; app.pingDir = 1; } }
        else if (app.loopMode == 2 && app.progress > 1.0) { app.progress = 1.0; app.playing = false; }
    }
    app.progress = std::min(1.0, std::max(0.0, app.progress));
    app.rebake();

    // shortcuts (not while typing)
    if (!io.WantTextInput) {
        if (ImGui::IsKeyPressed(ImGuiKey_Space, false)) { app.playing = !app.playing; }
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) { if (io.KeyShift) app.doRedo(); else app.doUndo(); }
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Y)) app.doRedo();
        if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) actionSave();
        if (ImGui::IsKeyPressed(ImGuiKey_Delete) || ImGui::IsKeyPressed(ImGuiKey_Backspace)) app.deleteSelectedKey();
        if (ImGui::IsKeyPressed(ImGuiKey_K)) app.addKey(app.selTrack, app.progress, app.proj.value(app.selTrack, app.progress));
        if (ImGui::IsKeyPressed(ImGuiKey_LeftArrow)) { app.playing = false; app.progress = std::max(0.0, app.progress - 0.01); }
        if (ImGui::IsKeyPressed(ImGuiKey_RightArrow)) { app.playing = false; app.progress = std::min(1.0, app.progress + 0.01); }
        if (ImGui::IsKeyPressed(ImGuiKey_UpArrow) && app.selTrack > 0) { app.selTrack--; app.selKey = -1; }
        if (ImGui::IsKeyPressed(ImGuiKey_DownArrow) && app.selTrack < kTracks - 1) { app.selTrack++; app.selKey = -1; }
    }

    app.r.renderPreview(app.proj, app.baked, app.progress);

    const ImGuiViewport* vp = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(vp->WorkPos);
    ImGui::SetNextWindowSize(vp->WorkSize);
    ImGui::Begin("root", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_MenuBar);

    if (ImGui::BeginMenuBar()) {
        if (ImGui::BeginMenu("File")) {
            if (ImGui::BeginMenu("New from template")) { for (size_t i = 0; i < templates().size(); i++) if (ImGui::MenuItem(templates()[i].name)) actionNew((int)i); ImGui::EndMenu(); }
            if (ImGui::MenuItem("Open...")) actionOpen();
            if (ImGui::MenuItem("Save", "Ctrl+S")) actionSave();
            if (ImGui::MenuItem("Save as...")) actionSaveAs();
            ImGui::Separator();
            if (ImGui::MenuItem("Install into ccmod")) actionInstall();
            if (ImGui::MenuItem("Export for ccmod...")) actionExport();
            if (ImGui::MenuItem("Show shader code")) { app.rebake(); app.glslText = codegen::glsl(app.proj, app.baked).preview; app.showGlsl = true; }
            ImGui::Separator();
            if (ImGui::MenuItem("Quit")) PostQuitMessage(0);
            ImGui::EndMenu();
        }
        if (ImGui::BeginMenu("Edit")) {
            if (ImGui::MenuItem("Undo", "Ctrl+Z", false, !app.undo.empty())) app.doUndo();
            if (ImGui::MenuItem("Redo", "Ctrl+Y", false, !app.redo.empty())) app.doRedo();
            ImGui::EndMenu();
        }
        if (ImGui::BeginMenu("Help")) { if (ImGui::MenuItem("Shortcuts and tips")) app.showHelp = true; ImGui::EndMenu(); }
        ImGui::SameLine(ImGui::GetContentRegionAvail().x - 260);
        ImGui::TextDisabled("%s%s", app.proj.label.c_str(), app.modified ? " *" : "");
        ImGui::EndMenuBar();
    }

    ImVec2 avail = ImGui::GetContentRegionAvail();
    float gap = 8, statusH = 26;
    float W = avail.x, H = avail.y - statusH;
    float graphH = std::min(340.0f, std::max(210.0f, H * 0.34f));
    float topH = H - graphH - gap;
    float S = std::floor(std::min(topH - 96, W * 0.36f));             // square preview
    S = std::max(S, 200.0f);
    float rightW = std::min(380.0f, std::max(300.0f, W * 0.24f));
    float midW = W - S - rightW - 2 * gap - 20;

    ImGui::BeginChild("left", ImVec2(S + 20, topH), ImGuiChildFlags_None);
    ImVec2 ip = ImGui::GetCursorScreenPos();
    ImGui::Image((ImTextureID)(intptr_t)app.r.previewSRV(), ImVec2(S, S));
    ImGui::GetWindowDrawList()->AddRect(ip, ImVec2(ip.x + S, ip.y + S), IM_COL32(70, 70, 78, 255));
    ImGui::GetWindowDrawList()->AddText(ImVec2(ip.x + 8, ip.y + 6), IM_COL32(255, 255, 255, 140), "1:1");
    transport(S);
    ImGui::EndChild();
    ImGui::SameLine(0, gap);
    ImGui::BeginChild("timeline", ImVec2(midW, topH), ImGuiChildFlags_Borders);
    timelinePanel();
    ImGui::EndChild();
    ImGui::SameLine(0, gap);
    ImGui::BeginChild("inspector", ImVec2(rightW, topH), ImGuiChildFlags_Borders);
    inspector();
    ImGui::EndChild();

    ImGui::BeginChild("graph", ImVec2(W - 372 - gap, graphH), ImGuiChildFlags_Borders);
    graphPanel();
    ImGui::EndChild();
    ImGui::SameLine(0, gap);
    ImGui::BeginChild("easing", ImVec2(372, graphH), ImGuiChildFlags_None);
    easingGallery();
    ImGui::EndChild();

    // status bar
    ImGui::Separator();
    if (!app.shaderError.empty()) ImGui::TextColored(ImVec4(1, 0.4f, 0.4f, 1), "Preview shader error: %s", app.shaderError.c_str());
    else ImGui::TextUnformatted(ImGui::GetTime() < app.statusUntil ? app.status.c_str() : "Space play/pause   K add key   Del delete key   Ctrl+Z undo   Double-click a row to add a key");
    ImGui::End();

    if (app.showGlsl) {
        ImGui::SetNextWindowSize(ImVec2(760, 560), ImGuiCond_FirstUseEver);
        if (ImGui::Begin("Shader code (GLSL for ccmod)", &app.showGlsl)) {
            if (ImGui::Button("Copy to clipboard")) ImGui::SetClipboardText(app.glslText.c_str());
            ImGui::SameLine(); ImGui::TextDisabled("Helpers go before main(); the body goes inside it.");
            ImGui::BeginChild("code", ImVec2(0, 0), ImGuiChildFlags_Borders, ImGuiWindowFlags_HorizontalScrollbar);
            ImGui::TextUnformatted(app.glslText.c_str());
            ImGui::EndChild();
        }
        ImGui::End();
    }
    if (app.showHelp) {
        ImGui::SetNextWindowSize(ImVec2(560, 460), ImGuiCond_FirstUseEver);
        if (ImGui::Begin("Shortcuts and tips", &app.showHelp)) {
            ImGui::TextWrapped("A transition has two clips: A (going out) and B (coming in). Each has its own position, scale, rotation, opacity, RGB split, pixelate and brightness tracks, "
                               "and the whole frame has shake and a white flash. B can also be revealed through a mask (wipe, iris, box, barn doors, diamond).");
            ImGui::Separator();
            ImGui::BulletText("Space: play / pause     Left/Right: step     Up/Down: pick track");
            ImGui::BulletText("K or double-click a timeline row: add a key at the playhead / the click");
            ImGui::BulletText("Drag a key in the timeline (time) or the graph (time and value). Shift keeps the value, Alt turns snapping off.");
            ImGui::BulletText("Ctrl+click in the graph adds a key at the mouse.");
            ImGui::BulletText("Pick an easing in the grid for the selected key's segment. 'Custom bezier' shows two handles you can drag.");
            ImGui::BulletText("Delete removes the selected key. Ctrl+Z / Ctrl+Y undo and redo.");
            ImGui::BulletText("File > Install into ccmod builds the transition so it shows in CapCut's Transitions > ccmod category after ccmod restarts.");
            ImGui::Separator();
            ImGui::TextWrapped("The preview uses the same maths as the exported shader. The picture orientation inside CapCut can differ; if a transition runs upside-down there, tick 'Flip vertical on export'.");
        }
        ImGui::End();
    }
}

// ------------------------------------------------------------------------------------------------ window
static LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (ImGui_ImplWin32_WndProcHandler(hWnd, msg, wParam, lParam)) return true;
    switch (msg) {
        case WM_SIZE:
            if (wParam != SIZE_MINIMIZED && app.r.device()) app.r.resize((int)LOWORD(lParam), (int)HIWORD(lParam));
            return 0;
        case WM_CLOSE:
            if (app.modified && MessageBoxW(hWnd, L"You have unsaved changes. Quit anyway?", L"ccmod transition editor", MB_YESNO | MB_ICONQUESTION) != IDYES) return 0;
            DestroyWindow(hWnd); return 0;
        case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, PWSTR cmdLine, int) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ImGui_ImplWin32_EnableDpiAwareness();
    WNDCLASSEXW wc = {sizeof wc, CS_CLASSDC, WndProc, 0, 0, hInst, LoadIconW(hInst, MAKEINTRESOURCEW(1)), LoadCursorW(nullptr, IDC_ARROW), nullptr, nullptr, L"ccmodTransitionEditor", nullptr};
    if (!wc.hIcon) wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    RegisterClassExW(&wc);
    float dpi = ImGui_ImplWin32_GetDpiScaleForMonitor(MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY));
    HWND hwnd = CreateWindowW(wc.lpszClassName, L"ccmod transition editor", WS_OVERLAPPEDWINDOW, 80, 60, (int)(1560 * dpi), (int)(940 * dpi), nullptr, nullptr, hInst, nullptr);
    RECT rc; GetClientRect(hwnd, &rc);
    if (!app.r.init(hwnd, rc.right - rc.left, rc.bottom - rc.top)) { MessageBoxW(nullptr, L"Could not start Direct3D 11.", L"ccmod transition editor", MB_ICONERROR); return 1; }
    ShowWindow(hwnd, SW_SHOWDEFAULT); UpdateWindow(hwnd);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    applyStyle();
    float fontPx = std::floor(16.0f * dpi);
    if (!io.Fonts->AddFontFromFileTTF("C:\\Windows\\Fonts\\segoeui.ttf", fontPx)) io.Fonts->AddFontDefault();
    ImGui::GetStyle().ScaleAllSizes(dpi);
    ImGui_ImplWin32_Init(hwnd);
    ImGui_ImplDX11_Init(app.r.device(), app.r.context());

    if (!app.r.compileShader(app.shaderError)) { /* shown in the status bar */ }
    app.setProject(templates()[1].make());
    app.say("Template loaded: Slide push. Drag the keys, change the easing, press Space to play.", 10);
    if (cmdLine && *cmdLine) {                           // a .cctrans passed on the command line (double-click association)
        std::wstring a = cmdLine; if (a.size() > 1 && a.front() == L'"') a = a.substr(1, a.find(L'"', 1) - 1);
        Json j; Project q; std::string err;
        if (Json::parse(readFile(toUtf8(a)), j, &err) && Project::fromJson(j, q, &err)) { app.setProject(q); app.file = a; app.modified = false; }
    }

    LARGE_INTEGER freq, last, now; QueryPerformanceFrequency(&freq); QueryPerformanceCounter(&last);
    bool done = false;
    while (!done) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg); DispatchMessageW(&msg);
            if (msg.message == WM_QUIT) done = true;
        }
        if (done) break;
        QueryPerformanceCounter(&now);
        float dt = (float)((double)(now.QuadPart - last.QuadPart) / freq.QuadPart); last = now;
        dt = std::min(dt, 0.1f);

        ImGui_ImplDX11_NewFrame(); ImGui_ImplWin32_NewFrame(); ImGui::NewFrame();
        drawUi(dt);
        ImGui::Render();
        const float clear[4] = {0.09f, 0.09f, 0.1f, 1};
        app.r.beginFrame(clear);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
        app.r.present();
    }
    ImGui_ImplDX11_Shutdown(); ImGui_ImplWin32_Shutdown(); ImGui::DestroyContext();
    app.r.shutdown();
    DestroyWindow(hwnd); UnregisterClassW(wc.lpszClassName, hInst);
    CoUninitialize();
    return 0;
}
