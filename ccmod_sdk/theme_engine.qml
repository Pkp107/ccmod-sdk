import QtQuick 2.15

// CCMOD theme engine. Injected once into CapCut's editor; a theme is pushed in as percent-encoded JSON through `cfg`.
//
//   { "id": "midnight", "active": true,
//     "colors": { "#262626": "#1b2538", ... },           // exact colour -> colour (Rectangle/Text .color, Rectangle border.color)
//     "rules":  [ { "match": {"type": "QQuickRectangle", "radiusMin": 3}, "set": {"radius": 2} },
//                 { "match": {"objectName": "someName*"},               "set": {"visible": false} } ] }
//
// Every change is a QML Binding with RestoreBindingOrValue: switching or reverting a theme destroys the bindings and CapCut's own
// values (and bindings) come back. The tree is rescanned every 2 s so panels that open later get themed as well.
Item {
    id: eng
    objectName: "ccmodThemeEngine2"
    width: 0; height: 0
    property string cfg: ""
    property string report: "idle"
    property var colorMap: ({})
    property var rules: []
    property bool active: false
    property string themeId: ""
    property var seen: new WeakMap()
    property var made: []
    property int generation: 0

    property bool themeOn: false
    Component { id: bindingComp; Binding { restoreMode: Binding.RestoreBindingOrValue; when: eng.themeOn } }

    function typeName(it) { var s = String(it); var i = s.indexOf("("); return i > 0 ? s.substring(0, i) : s; }
    function norm(c) { return String(c).toLowerCase(); }

    function bind(it, prop, value) {
        var b = bindingComp.createObject(eng, { "target": it, "property": prop, "value": value });
        if (b) made.push(b);
    }

    function matches(m, it, t) {
        if (m.type && t.indexOf(m.type) !== 0) return false;
        if (m.objectName) {
            var on = it.objectName || "";
            if (m.objectName.slice(-1) === "*") { if (on.indexOf(m.objectName.slice(0, -1)) !== 0) return false; }
            else if (on !== m.objectName) return false;
        }
        if (m.color !== undefined && (it.color === undefined || norm(it.color) !== norm(m.color))) return false;
        if (m.radiusMin !== undefined && !(it.radius !== undefined && it.radius >= m.radiusMin)) return false;
        return true;
    }

    function themeItem(it) {
        var t = typeName(it);
        var n = 0;
        if (it.color !== undefined) {
            var to = colorMap[norm(it.color)];
            if (to !== undefined) { bind(it, "color", to); n++; }
        }
        if (it.border !== undefined && it.border.color !== undefined) {
            var tb = colorMap[norm(it.border.color)];
            if (tb !== undefined) { bind(it, "border.color", tb); n++; }
        }
        for (var r = 0; r < rules.length; r++) {
            var rule = rules[r];
            if (!matches(rule.match || {}, it, t)) continue;
            for (var k in rule.set) { bind(it, k, rule.set[k]); n++; }
        }
        return n;
    }

    function clear() {
        for (var i = 0; i < made.length; i++) { if (made[i]) made[i].destroy(); }
        made = [];
        seen = new WeakMap();
    }

    function scan() {
        if (!active) return;
        var root = eng; while (root.parent) root = root.parent;
        var items = 0, changed = 0, fresh = 0;
        var stack = [root];
        while (stack.length) {
            var it = stack.pop(); items++;
            if (!seen.has(it)) {
                seen.set(it, 1); fresh++;
                changed += themeItem(it);
            }
            var ch = it.children;
            for (var i = 0; i < ch.length; i++) stack.push(ch[i]);
        }
        report = JSON.stringify({ id: themeId, items: items, newItems: fresh, bindings: made.length, changed: changed, gen: generation });
    }

    // Authoring aid: set `query` to {"type": "QQuickRectangle", "objectName": "x*", "limit": 40} and read `queryResult`.
    property string query: ""
    property string queryResult: ""
    onQueryChanged: {
        if (query === "") return;
        try {
            var q = JSON.parse(decodeURIComponent(query));
            var lim = q.limit || 40, out = [], total = 0;
            var root = eng; while (root.parent) root = root.parent;
            var stack = [root];
            while (stack.length) {
                var it = stack.pop();
                var t = typeName(it);
                if (matches(q, it, t)) {
                    total++;
                    if (out.length < lim)
                        out.push(t + " | " + (it.objectName || "") + " | " + Math.round(it.x) + "," + Math.round(it.y) + " " + Math.round(it.width) + "x" + Math.round(it.height)
                                 + " | vis=" + it.visible + (it.color !== undefined ? " | color=" + it.color : "") + (it.radius !== undefined ? " | r=" + it.radius : ""));
                }
                var ch = it.children;
                for (var i = 0; i < ch.length; i++) stack.push(ch[i]);
            }
            queryResult = JSON.stringify({ total: total, items: out });
        } catch (e) { queryResult = "error: " + e; }
    }

    onCfgChanged: {
        if (cfg === "") return;
        try {
            var c = JSON.parse(decodeURIComponent(cfg));
            themeOn = false;                       // deactivating (not destroying) the old bindings is what restores CapCut's values
            clear();
            themeId = c.id || "";
            colorMap = {};
            var src = c.colors || {};
            for (var k in src) colorMap[norm(k)] = src[k];
            rules = c.rules || [];
            active = c.active !== false;
            themeOn = active;
            generation++;
            if (active) scan(); else report = JSON.stringify({ id: themeId, active: false, gen: generation });
        } catch (e) { report = "error: " + e; }
    }

    Timer { interval: 2000; running: eng.active; repeat: true; onTriggered: eng.scan() }
}
