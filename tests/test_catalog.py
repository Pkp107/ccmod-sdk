"""Catalog rewriting + the redirect server's proxy mode (a fake upstream stands in for CapCut's real server)."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ccmod_sdk import catalog  # noqa: E402
from ccmod_sdk.netredirect import RedirectServer  # noqa: E402

TILE = {"common_attr": {"id": "7399464661671775493", "effect_id": "7399464661671775493", "title": "Sharpen Edges",
                        "md5": "a" * 32, "third_resource_id_str": "7399464661671775493", "effect_type": 7},
        "cover_url": {"url_list": ["https://x/y.png"]}}
PANEL = {"data": {"categories": [{"category_id": "1001", "category_name": "Trending", "category_key": "trending"}],
                  "effect_item_list": [TILE]}}


def test_add_tiles_clones_and_repoints():
    out = json.loads(catalog.add_tiles(json.dumps(PANEL), [
        {"effect_id": "8849954550253485357", "title": "CCMOD Easedown", "md5": "df34b01300ddefbfd8b04bee900ae432"}]))
    lst = out["data"]["effect_item_list"]
    assert len(lst) == 2 and lst[0]["common_attr"]["title"] == "Sharpen Edges"       # original untouched
    ca = lst[1]["common_attr"]
    assert ca["id"] == ca["effect_id"] == ca["third_resource_id_str"] == "8849954550253485357"
    assert ca["title"] == "CCMOD Easedown" and ca["md5"] == "df34b01300ddefbfd8b04bee900ae432" and ca["effect_type"] == 7
    assert lst[1]["cover_url"] == TILE["cover_url"]                                   # unknown fields preserved


def test_add_tiles_replace_and_unknown_shape():
    out = json.loads(catalog.add_tiles(json.dumps(PANEL), [{"effect_id": "1", "title": "A"}, {"effect_id": "2", "title": "B"}], replace=True))
    assert [t["common_attr"]["title"] for t in out["data"]["effect_item_list"]] == ["A", "B"]
    odd = b'{"nothing": []}'
    assert json.loads(catalog.add_tiles(odd, [{"effect_id": "1", "title": "A"}])) == {"nothing": []}


def test_add_category_idempotent_and_position():
    r = catalog.add_category(json.dumps(PANEL), category_id="9990001", name="CCMOD", position=0)
    cats = json.loads(r)["data"]["categories"]
    assert [c["category_name"] for c in cats] == ["CCMOD", "Trending"] and cats[0]["category_id"] == "9990001"
    assert cats[0]["category_key"] == "ccmod"
    again = json.loads(catalog.add_category(r, category_id="9990001", name="CCMOD"))["data"]["categories"]
    assert len(again) == 2                                                             # no duplicate


def test_request_category_id():
    assert catalog.request_category_id(b'{"category_id": "9990001", "x": 1}') == "9990001"
    assert catalog.request_category_id(b'{"req": {"category_id": 55}}') == "55"
    assert catalog.request_category_id(b"category_id=77&a=b") == "77"
    assert catalog.request_category_id(b"nothing") is None


class _Upstream(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        _Upstream.seen.append((self.path, dict(self.headers), body))
        data = json.dumps(PANEL).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_proxy_mode_rewrites_live_response(tmp_path):
    up = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    srv = RedirectServer(tmp_path / "none.json")
    srv.add_proxy("*get_panel_info*", lambda url, req, resp: catalog.add_category(resp, category_id="9990001", name="CCMOD"))
    srv.start()
    try:
        orig = f"{base}/artist/v1/panel/get_panel_info?aid=1"
        assert srv.should_redirect(orig) and not srv.should_redirect(f"{base}/other")
        req = urllib.request.Request(srv.local_url(orig), data=b'{"panel": "effects"}', method="POST",
                                     headers={"X-Sign": "abc", "Accept-Encoding": "gzip"})
        body = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert [c["category_name"] for c in body["data"]["categories"]] == ["CCMOD", "Trending"]
        path, headers, sent = _Upstream.seen[-1]
        assert sent == b'{"panel": "effects"}' and headers.get("X-Sign") == "abc"       # request body + headers forwarded
        assert headers.get("Accept-Encoding") == "identity"                              # asked for an uncompressed reply
        assert srv.hits[-1][1] == "proxy:*get_panel_info*"
    finally:
        srv.stop(); up.shutdown()


def test_proxy_plugin_error_passes_original_through(tmp_path):
    up = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    srv = RedirectServer(tmp_path / "none.json")
    srv.add_proxy("*get_panel_info*", lambda url, req, resp: 1 / 0)
    srv.start()
    try:
        orig = f"{base}/get_panel_info"
        got = json.loads(urllib.request.urlopen(urllib.request.Request(srv.local_url(orig), data=b"{}", method="POST"), timeout=10).read())
        assert got == PANEL and srv.hits[-1][1].startswith("proxy-error")
    finally:
        srv.stop(); up.shutdown()


def test_declarative_rules_end_to_end(tmp_path):
    """ccmod-redirects.json rules: add a category + tiles to get_panel_info; serve our synthetic category locally."""
    class Up(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
            doc = PANEL if "get_panel_info" in self.path else {"data": {"effect_item_list": [TILE, TILE]}}
            data = json.dumps(doc).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    mine = [{"effect_id": "8849954550253485357", "title": "CCMOD Easedown", "md5": "df34b01300ddefbfd8b04bee900ae432"}]
    rules = tmp_path / "ccmod-redirects.json"
    rules.write_text(json.dumps([
        {"plugin": "t", "pattern": "*get_panel_info*", "proxy": {
            "categories": [{"category_id": "9990001", "name": "CCMOD", "position": 0}],
            "tiles": {"effect_type": 7, "mode": "append", "items": mine}}},
        {"plugin": "t", "pattern": "*get_resources_by_category_id*", "proxy": {
            "serve_category": {"category_id": "9990001", "items": mine}}},
    ]), encoding="utf-8")
    srv = RedirectServer(rules)
    srv.start()

    def post(path, body):
        r = urllib.request.Request(srv.local_url(base + path), data=body, method="POST")
        return json.loads(urllib.request.urlopen(r, timeout=10).read())
    try:
        panel = post("/artist/v1/panel/get_panel_info", b"{}")
        assert panel["data"]["categories"][0]["category_name"] == "CCMOD"
        assert [t["common_attr"]["title"] for t in panel["data"]["effect_item_list"]] == ["Sharpen Edges", "CCMOD Easedown"]
        # a real category: passes through (and its reply becomes the envelope template)
        real = post("/artist/v1/effect/get_resources_by_category_id", b'{"category_id": "1001"}')
        assert len(real["data"]["effect_item_list"]) == 2
        # our synthetic category: answered locally from that envelope
        mine_resp = post("/artist/v1/effect/get_resources_by_category_id", b'{"category_id": "9990001"}')
        assert [t["common_attr"]["title"] for t in mine_resp["data"]["effect_item_list"]] == ["CCMOD Easedown"]
        assert [h[1] for h in srv.hits] == ["catalog-rule", "catalog-rule", "serve_category"]
    finally:
        srv.stop(); up.shutdown()


def test_sdk_network_catalog_rules(tmp_path):
    from ccmod_sdk import FakeBackend, Host
    plugins = tmp_path / "plugins"; d = plugins / "cat"; d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"id": "cat", "name": "Cat", "version": "1.0.0", "ccmod": ">=0.1", "capcut": ["*"],
                                               "entry": "main.py", "provides": ["ui"], "permissions": ["network"]}), encoding="utf-8")
    (d / "main.py").write_text("from ccmod_sdk import Plugin\nclass P(Plugin):\n    pass\n", encoding="utf-8")
    h = Host(FakeBackend(), plugins, tmp_path / "state"); h.load_all()
    n = h.plugins["cat"].ctx.network
    mine = [{"effect_id": "1", "title": "A", "md5": "b" * 32}]
    n.add_category("9990001", "CCMOD"); n.add_category("9990001", "CCMOD v2"); n.add_tiles(mine); n.serve_category("9990001", mine)
    rules = {r["pattern"]: r["proxy"] for r in n.rules()}
    assert rules["*get_panel_info*"]["categories"] == [{"category_id": "9990001", "name": "CCMOD v2", "position": 0}]   # idempotent per id
    assert rules["*get_panel_info*"]["tiles"]["items"] == mine and rules["*get_resources_by_category_id*"]["serve_category"]["items"] == mine
    n.clear(); assert n.rules() == []


def test_upstream_url_with_raw_spaces(tmp_path):
    """CapCut sends URLs with raw spaces in the query (cpu=13th Gen Intel(R) ...); the proxy must still reach upstream."""
    up = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    srv = RedirectServer(tmp_path / "none.json")
    srv.add_proxy("*get_panel_info*", lambda url, req, resp: resp)
    srv.start()
    try:
        orig = f"{base}/artist/v1/panel/get_panel_info?cpu=13th Gen Intel(R) Core(TM) i7&x=a%20b"
        got = json.loads(urllib.request.urlopen(urllib.request.Request(srv.local_url(orig), data=b"{}", method="POST"), timeout=10).read())
        assert got == PANEL and "upstream-error" not in srv.hits[-1][1]
        assert "cpu=13th%20Gen" in _Upstream.seen[-1][0] and "x=a%20b" in _Upstream.seen[-1][0]
    finally:
        srv.stop(); up.shutdown()


def test_tile_clears_commercial_flags_and_sets_numeric_ids():
    paid = json.loads(json.dumps(TILE))
    paid["common_attr"].update({"third_resource_id": 7399464661671775493, "is_business": True, "business_scope": ["UNLIMITED"],
                                "business_info": {"json_str": "{\"is_vip\":true}"}, "extra": "{\"is_vip\":true,\"effect_duration\":3000}",
                                "category_ids": [1, 2, 3], "has_favorited": False})
    t = catalog.make_tile(paid, effect_id="8849954550253485357", title="Mine", md5="c" * 32, category_id="9990001")
    ca = t["common_attr"]
    assert ca["third_resource_id"] == 8849954550253485357 and isinstance(ca["third_resource_id"], int)
    assert ca["is_business"] is False and ca["business_scope"] == [] and json.loads(ca["business_info"]["json_str"])["paid_type"] == "free"
    assert "is_vip" not in ca["extra"] and ca["category_ids"] == [9990001]
    assert paid["common_attr"]["is_business"] is True                                  # template untouched


def test_replace_marks_single_page():
    doc = {"data": {"has_more": True, "next_offset": 50, "effect_item_list": [TILE]}}
    out = json.loads(catalog.add_tiles(json.dumps(doc), [{"effect_id": "1", "title": "A"}], replace=True))
    assert out["data"]["has_more"] is False and out["data"]["next_offset"] == 1


def test_effect_type_overridden_from_foreign_template():
    foreign = json.loads(json.dumps(TILE)); foreign["common_attr"]["effect_type"] = 26
    doc = {"data": {"effect_item_list": [foreign]}}
    out = json.loads(catalog.add_tiles(json.dumps(doc), [{"effect_id": "1", "title": "A"}], replace=True, effect_type=7))
    assert out["data"]["effect_item_list"][0]["common_attr"]["effect_type"] == 7


def test_serve_category_works_before_any_real_reply(tmp_path):
    """The launch-time prefetch must get a full answer even when no real reply has been cached yet."""
    from ccmod_sdk.catalog_rules import CatalogProxy
    cp = CatalogProxy(tmp_path / "empty")
    spec = {"serve_category": {"category_id": "9990001", "effect_type": 7,
                               "items": [{"effect_id": "8849954550253485357", "title": "CCMOD Easedown", "md5": "d" * 32}]}}
    out = json.loads(cp.serve_local(spec))
    ca = out["data"]["effect_item_list"][0]["common_attr"]
    assert ca["title"] == "CCMOD Easedown" and ca["effect_type"] == 7 and ca["third_resource_id"] == 8849954550253485357
    assert out["data"]["has_more"] is False and out["ret"] == "0" and ca["category_ids"] == [9990001]


def test_panel_info_reply_is_never_used_as_category_envelope(tmp_path):
    from ccmod_sdk.catalog_rules import CatalogProxy, ENVELOPE_FILE
    cp = CatalogProxy(tmp_path)
    panel = {"data": {"categories": [{"category_id": 1}], "category_resources": {"1": {"effect_item_list": [TILE]}}}}
    cp._remember("https://x/artist/v1/panel/get_panel_info?a=1", json.dumps(panel).encode())
    assert cp.envelope() is None                                                       # not cached at all
    (tmp_path / ENVELOPE_FILE).write_bytes(json.dumps(panel).encode())                 # a stale/poisoned file is rejected too
    assert cp.envelope() is None
    spec = {"serve_category": {"category_id": "9", "items": [{"effect_id": "1", "title": "A"}]}}
    out = json.loads(cp.serve_local(spec))                                             # falls back to the skeleton: right shape
    assert isinstance(out["data"]["effect_item_list"], list) and out["data"]["effect_item_list"][0]["common_attr"]["title"] == "A"
    real = {"ret": "0", "data": {"has_more": True, "effect_item_list": [TILE]}}
    cp._remember("https://x/artist/v1/effect/get_resources_by_category_id?a=1", json.dumps(real).encode())
    assert cp.envelope() is not None


def test_serve_via_real_category(tmp_path):
    """serve_category with via_category: the request is re-pointed at a real category, upstream answers, our tiles replace its list."""
    seen = []

    class Up(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); seen.append(json.loads(self.rfile.read(n)))
            data = json.dumps({"ret": "0", "data": {"has_more": True, "next_offset": 50, "effect_item_list": [TILE, TILE]}}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    rules = tmp_path / "r.json"
    rules.write_text(json.dumps([{"plugin": "t", "pattern": "*get_resources_by_category_id*", "proxy": {"serve_category": [
        {"category_id": "9990011", "via_category": "26918", "via_key": "hot2", "items": [{"effect_id": "5", "title": "Mine"}]}]}}]), encoding="utf-8")
    srv = RedirectServer(rules); srv.start()
    try:
        r = urllib.request.Request(srv.local_url(base + "/artist/v1/effect/get_resources_by_category_id"),
                                   data=b'{"category_id":9990011,"category_key":"ab","count":50}', method="POST")
        out = json.loads(urllib.request.urlopen(r, timeout=10).read())
        assert seen[-1]["category_id"] == 26918 and seen[-1]["category_key"] == "hot2"            # upstream was asked about the REAL category
        assert [t["common_attr"]["title"] for t in out["data"]["effect_item_list"]] == ["Mine"] and out["data"]["has_more"] is False
        assert srv.hits[-1][1] == "serve_via"
    finally:
        srv.stop(); up.shutdown()


def test_via_debug_modes():
    from ccmod_sdk.catalog_rules import CatalogProxy
    import tempfile
    cp = CatalogProxy(Path(tempfile.mkdtemp()))
    up = json.dumps({"data": {"effect_item_list": [{"common_attr": {"id": "1", "title": "T", "md5": "a" * 32, "category_ids": [5]}}]}}).encode()
    sc = {"category_id": "77", "items": [{"effect_id": "9", "title": "Mine", "md5": "b" * 32}]}
    assert cp.apply_via({**sc, "mode": "none"}, up) == up
    mem = json.loads(cp.apply_via({**sc, "mode": "membership"}, up))["data"]["effect_item_list"][0]["common_attr"]
    assert mem["category_ids"] == [5, 77] and mem["title"] == "T"
    mini = json.loads(cp.apply_via({**sc, "mode": "minimal"}, up))["data"]["effect_item_list"][0]["common_attr"]
    assert mini["id"] == "9" and mini["title"] == "Mine" and mini["md5"] == "b" * 32 and mini["category_ids"] == [77]


def test_bisect_first_tile_changes_only_one_thing():
    two = {"data": {"effect_item_list": [
        {"common_attr": {"id": "1", "effect_id": "1", "title": "A", "md5": "a" * 32, "category_ids": [5]}},
        {"common_attr": {"id": "2", "effect_id": "2", "title": "B", "md5": "b" * 32, "category_ids": [5]}}]}}
    item = {"effect_id": "9", "title": "Mine", "md5": "c" * 32}
    for what, expect in (("title", ("1", "Mine", "a")), ("ids", ("9", "A", "a")), ("md5", ("1", "A", "c")), ("all", ("9", "Mine", "c"))):
        out = json.loads(catalog.bisect_first_tile(json.dumps(two), "77", what, item))["data"]["effect_item_list"]
        ca, ca2 = out[0]["common_attr"], out[1]["common_attr"]
        assert (ca["id"], ca["title"], ca["md5"][0]) == expect and 77 in ca["category_ids"]
        assert ca2["id"] == "2" and ca2["title"] == "B" and 77 in ca2["category_ids"]            # second tile untouched (membership only)


def test_inline_category_resources():
    from ccmod_sdk.catalog_rules import CatalogProxy
    import tempfile
    cp = CatalogProxy(Path(tempfile.mkdtemp()))
    panel = {"data": {"categories": [{"category_id": 1, "category_name": "Face"}],
                      "category_resources": {"1": {"has_more": True, "effect_item_list": [TILE, TILE]}}}}
    spec = {"inline": [{"category_id": "9990041", "mode": "full", "effect_type": 7,
                        "items": [{"effect_id": "8849954550253485357", "title": "CCMOD Easedown", "md5": "d" * 32}]}]}
    out = json.loads(cp.rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(panel).encode()))["data"]["category_resources"]
    assert set(out) == {"1", "9990041"} and out["9990041"]["has_more"] is False
    ca = out["9990041"]["effect_item_list"][0]["common_attr"]
    assert ca["title"] == "CCMOD Easedown" and ca["id"] == "8849954550253485357" and ca["md5"] == "d" * 32
    assert out["1"]["effect_item_list"][0]["common_attr"]["title"] == "Sharpen Edges"          # the real inline category is untouched
    bare = {"data": {"categories": [{"category_id": 1}]}}                                       # a panel with no inline resources: one is created
    out2 = json.loads(cp.rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(bare).encode()))["data"]["category_resources"]
    assert out2["9990041"]["effect_item_list"][0]["common_attr"]["title"] == "CCMOD Easedown"


def test_retag_tiles_keeps_ids():
    lst = [{"common_attr": {"id": str(i), "effect_id": str(i), "title": f"T{i}", "md5": "a" * 32, "category_ids": [5]}} for i in range(1, 5)]
    items = [{"effect_id": "x", "title": f"Mine{i}", "md5": chr(98 + i) * 32} for i in range(2)]
    out = json.loads(catalog.retag_tiles(json.dumps({"data": {"effect_item_list": lst}}), "77", "titlemd5", items))["data"]["effect_item_list"]
    assert [t["common_attr"]["id"] for t in out] == ["1", "2", "3", "4"]                         # ids never touched
    assert [t["common_attr"]["title"] for t in out] == ["Mine0", "Mine1", "T3", "T4"]
    assert out[0]["common_attr"]["md5"] == "b" * 32 and out[2]["common_attr"]["md5"] == "a" * 32 and 77 in out[3]["common_attr"]["category_ids"]


def test_default_category_renamed_with_inline_tiles():
    from ccmod_sdk.catalog_rules import CatalogProxy
    import tempfile
    cp = CatalogProxy(Path(tempfile.mkdtemp()))
    other = json.loads(json.dumps(TILE)); other["common_attr"]["effect_type"] = 24
    real = []
    for i in range(12):
        t = json.loads(json.dumps(TILE)); t["common_attr"]["id"] = t["common_attr"]["effect_id"] = str(500 + i); real.append(t)
    panel = {"data": {"categories": [{"category_id": 11, "category_name": "Trending", "category_key": "hot2"},
                                     {"category_id": 12, "category_name": "Face", "category_key": "face"}],
                      "category_resources": {"12": {"effect_item_list": [other]}, "11": {"has_more": True, "effect_item_list": real}}}}
    items = [{"effect_id": str(1000 + i), "title": f"CCMOD {i}", "md5": "d" * 32, "mode": "title_md5"} for i in range(9)]
    spec = {"default_category": {"name": "CCMOD", "effect_type": 7, "mode": "title_md5", "items": items}}
    out = json.loads(cp.rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(panel).encode()))["data"]
    assert [c["category_name"] for c in out["categories"]] == ["CCMOD", "Face"]                # only the type-7 default is renamed
    tiles = out["category_resources"]["11"]["effect_item_list"]
    assert len(tiles) == 9 and tiles[3]["common_attr"]["title"] == "CCMOD 3" and tiles[3]["common_attr"]["id"] == "503"   # real id kept
    assert out["category_resources"]["11"]["has_more"] is False
    assert out["category_resources"]["12"]["effect_item_list"][0]["common_attr"]["effect_type"] == 24     # other panels untouched
    # pins: a re-ranked list still maps each effect to the SAME real tile
    pinned = {t["common_attr"]["id"]: t["common_attr"]["title"] for t in tiles}
    panel["data"]["category_resources"]["11"]["effect_item_list"] = list(reversed(real))
    out2 = json.loads(CatalogProxy(cp.state_dir).rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(panel).encode()))["data"]
    assert {t["common_attr"]["id"]: t["common_attr"]["title"] for t in out2["category_resources"]["11"]["effect_item_list"]} == pinned


def test_cover_url_replaces_thumbnails_and_asset_route(tmp_path):
    import json, urllib.request
    from ccmod_sdk import catalog
    from ccmod_sdk.netredirect import RedirectServer
    tile = {"common_attr": {"id": "1", "title": "x", "md5": "a", "cover_url": {"small": "http://a/s.webp", "static_img": "http://a/i.webp"}}}
    out = catalog.make_tile(tile, effect_id="1", title="T", mode="title_md5", cover="http://127.0.0.1:1/asset/c.png")
    assert out["common_attr"]["cover_url"] == {"small": "http://127.0.0.1:1/asset/c.png", "static_img": "http://127.0.0.1:1/asset/c.png"}
    rules = tmp_path / "ccmod-redirects.json"; rules.write_text("[]")
    (tmp_path / "ccmod-assets").mkdir(); (tmp_path / "ccmod-assets" / "c.png").write_bytes(b"PNGDATA")
    srv = RedirectServer(rules); port = srv.start()
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/asset/c.png").read() == b"PNGDATA"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/asset/..%2Fccmod-redirects.json"); assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_borrowed_ids_get_our_md5_in_every_list(tmp_path):
    import json
    from ccmod_sdk.catalog_rules import CatalogProxy
    cp = CatalogProxy(tmp_path)
    cp._remember_ids([{"real_id": "111", "md5": "OURS"}])
    body = json.dumps({"data": {"effect_item_list": [{"common_attr": {"id": "111", "md5": "stock"}}, {"common_attr": {"id": "222", "md5": "keep"}}]}}).encode()
    out = json.loads(cp._override_md5(body))["data"]["effect_item_list"]
    assert out[0]["common_attr"]["md5"] == "OURS" and out[1]["common_attr"]["md5"] == "keep"


def test_extra_categories_only_on_the_panel_with_the_default_category():
    from ccmod_sdk.catalog_rules import CatalogProxy
    import tempfile
    cp = CatalogProxy(Path(tempfile.mkdtemp()))
    tile = json.loads(json.dumps(TILE))
    video = {"data": {"categories": [{"category_id": 11, "category_name": "Trending", "category_key": "hot2"}],
                      "category_resources": {"11": {"effect_item_list": [tile]}}}}
    lyrics = {"data": {"categories": [{"category_id": 99, "category_name": "Other", "category_key": "o"}], "category_resources": {}}}
    spec = {"default_category": {"name": "CCMOD", "effect_type": 7, "mode": "title_md5",
                                 "items": [{"effect_id": "1", "title": "A", "md5": "d" * 32, "mode": "title_md5"}]},
            "categories": [{"category_id": "9990100", "name": "Extras", "position": 1, "key": "x"}]}
    names = lambda r: [c["category_name"] for c in json.loads(r)["data"]["categories"]]
    assert names(cp.rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(video).encode())) == ["CCMOD", "Extras"]
    assert names(cp.rewrite(spec, "https://x/get_panel_info", b"{}", json.dumps(lyrics).encode())) == ["Other"]


def _tile(i, paid):
    info = {"is_vip": paid, "paid_type": "subscribe" if paid else "free"}
    return {"common_attr": {"id": str(i), "business_info": {"json_str": json.dumps(info)}}}


def test_pick_tiles_prefers_free_stock_tiles_and_reads_only():
    lst = [_tile(1, True), _tile(2, False), _tile(3, True), _tile(4, False)]
    before = json.dumps(lst)
    pins = {}
    out = catalog.pick_tiles(lst, [{"effect_id": "a"}, {"effect_id": "b"}], pins)
    assert [t["common_attr"]["id"] for t in out] == ["2", "4"] and json.dumps(lst) == before
    pins2 = {"a": "1"}                                            # a pin on a paid tile moves when enough free tiles exist
    assert catalog.pick_tiles(lst, [{"effect_id": "a"}], pins2)[0]["common_attr"]["id"] == "2"
