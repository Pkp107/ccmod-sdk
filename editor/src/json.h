// Tiny JSON value, parser and writer (enough for project files and exports; no external dependency).
#pragma once
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

struct Json {
    enum Type { Null, Bool, Num, Str, Arr, Obj } type = Null;
    bool b = false;
    double n = 0;
    std::string s;
    std::vector<Json> a;
    std::vector<std::pair<std::string, Json>> o;

    Json() {}
    static Json boolean(bool v) { Json j; j.type = Bool; j.b = v; return j; }
    static Json number(double v) { Json j; j.type = Num; j.n = v; return j; }
    static Json string(const std::string& v) { Json j; j.type = Str; j.s = v; return j; }
    static Json array() { Json j; j.type = Arr; return j; }
    static Json object() { Json j; j.type = Obj; return j; }

    Json& set(const std::string& k, Json v) {
        for (auto& kv : o) if (kv.first == k) { kv.second = std::move(v); return *this; }
        o.emplace_back(k, std::move(v));
        return *this;
    }
    Json& push(Json v) { a.push_back(std::move(v)); return *this; }
    const Json* get(const std::string& k) const {
        for (auto& kv : o) if (kv.first == k) return &kv.second;
        return nullptr;
    }
    double num(const std::string& k, double d) const { auto* j = get(k); return j && j->type == Num ? j->n : d; }
    std::string str(const std::string& k, const std::string& d) const { auto* j = get(k); return j && j->type == Str ? j->s : d; }
    bool boolean(const std::string& k, bool d) const { auto* j = get(k); return j && j->type == Bool ? j->b : d; }

    // ---- writer ----
    static void esc(std::string& out, const std::string& v) {
        out += '"';
        for (unsigned char c : v) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20) { char buf[8]; std::snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
                    else out += (char)c;
            }
        }
        out += '"';
    }
    void write(std::string& out, int indent = 0, bool pretty = true) const {
        auto nl = [&](int d) { if (pretty) { out += '\n'; out.append(d * 2, ' '); } };
        switch (type) {
            case Null: out += "null"; break;
            case Bool: out += b ? "true" : "false"; break;
            case Num: {
                char buf[40];
                if (n == std::floor(n) && std::fabs(n) < 1e15) std::snprintf(buf, sizeof buf, "%.0f", n);
                else std::snprintf(buf, sizeof buf, "%.6g", n);
                out += buf; break;
            }
            case Str: esc(out, s); break;
            case Arr:
                if (a.empty()) { out += "[]"; break; }
                out += '[';
                for (size_t i = 0; i < a.size(); i++) { if (i) out += ','; nl(indent + 1); a[i].write(out, indent + 1, pretty); }
                nl(indent); out += ']'; break;
            case Obj:
                if (o.empty()) { out += "{}"; break; }
                out += '{';
                for (size_t i = 0; i < o.size(); i++) {
                    if (i) out += ',';
                    nl(indent + 1); esc(out, o[i].first); out += pretty ? ": " : ":";
                    o[i].second.write(out, indent + 1, pretty);
                }
                nl(indent); out += '}'; break;
        }
    }
    std::string dump(bool pretty = true) const { std::string r; write(r, 0, pretty); return r; }

    // ---- parser ----
    static bool parse(const std::string& text, Json& out, std::string* err = nullptr) {
        const char* p = text.c_str();
        Json j;
        if (!value(p, j, 0, err)) return false;
        ws(p);
        if (*p) { if (err) *err = "trailing characters"; return false; }
        out = std::move(j);
        return true;
    }

private:
    static void ws(const char*& p) { while (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t') p++; }
    static bool fail(std::string* e, const char* m) { if (e) *e = m; return false; }
    static bool value(const char*& p, Json& j, int depth, std::string* e) {
        if (depth > 64) return fail(e, "too deep");
        ws(p);
        if (*p == '{') {
            p++; j = object(); ws(p);
            if (*p == '}') { p++; return true; }
            for (;;) {
                ws(p); Json k;
                if (*p != '"' || !str(p, k, e)) return fail(e, "expected a key");
                ws(p); if (*p != ':') return fail(e, "expected ':'"); p++;
                Json v; if (!value(p, v, depth + 1, e)) return false;
                j.o.emplace_back(k.s, std::move(v)); ws(p);
                if (*p == ',') { p++; continue; }
                if (*p == '}') { p++; return true; }
                return fail(e, "expected ',' or '}'");
            }
        }
        if (*p == '[') {
            p++; j = array(); ws(p);
            if (*p == ']') { p++; return true; }
            for (;;) {
                Json v; if (!value(p, v, depth + 1, e)) return false;
                j.a.push_back(std::move(v)); ws(p);
                if (*p == ',') { p++; continue; }
                if (*p == ']') { p++; return true; }
                return fail(e, "expected ',' or ']'");
            }
        }
        if (*p == '"') return str(p, j, e);
        if (!std::strncmp(p, "true", 4)) { p += 4; j = boolean(true); return true; }
        if (!std::strncmp(p, "false", 5)) { p += 5; j = boolean(false); return true; }
        if (!std::strncmp(p, "null", 4)) { p += 4; j = Json(); return true; }
        char* end = nullptr;
        double v = std::strtod(p, &end);
        if (end == p) return fail(e, "unexpected character");
        p = end; j = number(v); return true;
    }
    static bool str(const char*& p, Json& j, std::string* e) {
        p++; std::string r;
        while (*p && *p != '"') {
            if (*p == '\\') {
                p++;
                switch (*p) {
                    case 'n': r += '\n'; break; case 't': r += '\t'; break; case 'r': r += '\r'; break;
                    case 'b': r += '\b'; break; case 'f': r += '\f'; break;
                    case 'u': {
                        unsigned cp = 0; for (int i = 1; i <= 4; i++) { char c = p[i]; cp <<= 4; cp |= (c >= '0' && c <= '9') ? c - '0' : (c | 32) - 'a' + 10; }
                        p += 4;
                        if (cp < 0x80) r += (char)cp;
                        else if (cp < 0x800) { r += (char)(0xC0 | (cp >> 6)); r += (char)(0x80 | (cp & 0x3F)); }
                        else { r += (char)(0xE0 | (cp >> 12)); r += (char)(0x80 | ((cp >> 6) & 0x3F)); r += (char)(0x80 | (cp & 0x3F)); }
                        break;
                    }
                    default: r += *p;
                }
                p++;
            } else r += *p++;
        }
        if (*p != '"') return fail(e, "unterminated string");
        p++; j = string(r); return true;
    }
};
