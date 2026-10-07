"""The CCMOD grid helpers (ccmod_sdk/grid.py) and the ccmod-catalog plugin that uses them."""
import json
from pathlib import Path

from ccmod_sdk import FakeBackend, Host, grid

ROOT = Path(__file__).resolve().parent.parent
MD5 = "d" * 32


def _index(tmp_path, n):
    ix = {f"fx{i}": {"id": str(8000 + i), "md5": MD5, "label": f"CCMOD Fx{i}"} for i in range(n)}
    (tmp_path / "index.json").write_text(json.dumps(ix), encoding="utf-8")
    eff = tmp_path / "effect"
    for i in range(n):
        pkg = eff / str(8000 + i) / MD5
        pkg.mkdir(parents=True)
        (pkg / "extra.json").write_text(json.dumps({"setting": {"effect_adjust_params": [{"effect_key": "effects_adjust_number", "default": 0.5, "min": 0, "max": 1}]}}))
    return tmp_path / "index.json", eff


def test_grid_items_only_installed_with_cover_and_slider(tmp_path):
    index, eff = _index(tmp_path, 3)
    (eff / "8001" / MD5 / "extra.json").unlink()
    import shutil
    shutil.rmtree(eff / "8002")                                   # not installed -> not offered
    items = grid.grid_items(effect_dir=eff, index=index)
    assert [i["effect_id"] for i in items] == ["8000", "8001"]
    assert items[0]["cover"] == "fx0.png" and items[0]["sdk_extra"]["setting"]["effect_adjust_params"][0]["effect_key"] == "effects_adjust_number"
    assert items[1]["sdk_extra"] is None                          # no extra.json -> keep the borrowed tile's own value


def test_build_rules_splits_main_and_extras():
    items = [{"effect_id": str(i), "title": f"T{i}", "md5": MD5} for i in range(11)]
    rules = grid.build_rules(items, "p", main_count=8)
    panel = rules[0]["proxy"]
    assert len(panel["default_category"]["items"]) == 8 and panel["categories"][0]["category_id"] == grid.EXTRAS_ID
    serve = rules[1]["proxy"]["serve_category"]
    assert [s["category_id"] for s in serve] == [grid.DEFAULT_PANEL_CATEGORY, grid.EXTRAS_ID]
    assert len(serve[1]["items"]) == 3 and serve[1]["via_category"] == grid.DEFAULT_PANEL_CATEGORY
    assert all(s["mode"] == "retag_titlemd5" for s in serve)
    assert grid.build_rules(items[:5], "p")[0]["proxy"]["categories"] == []   # no overflow -> no extra tab


def test_install_borrowed_is_idempotent_and_replaces_stale(tmp_path):
    index, eff = _index(tmp_path, 2)
    state = tmp_path / "state"; state.mkdir()
    rows = [{"title": "A", "our_id": "8000", "md5": MD5, "real_id": "7001"}, {"title": "B", "our_id": "8001", "md5": MD5, "real_id": "7002"}]
    (state / "default_category_ids.json").write_text(json.dumps(rows))
    assert len(grid.install_borrowed(state, eff)) == 2
    assert grid.install_borrowed(state, eff) == []                # second run: nothing to do
    assert (eff / "7001" / MD5 / "extra.json").exists() and not list((eff / "7001" / MD5).glob("ccmod_source*"))   # marker BESIDE the package
    rows[0]["our_id"] = "8001"                                    # the slot is reassigned to another effect -> replaced
    (state / "default_category_ids.json").write_text(json.dumps(rows))
    assert len(grid.install_borrowed(state, eff)) == 1


def test_build_rules_with_transitions_adds_a_second_default_category():
    fx = [{"effect_id": str(i), "title": f"T{i}", "md5": MD5} for i in range(10)]
    tr = [{"effect_id": str(900 + i), "title": f"X{i}", "md5": MD5} for i in range(9)]
    rules = grid.build_rules(fx, "p", main_count=8, transitions=tr)
    panel = rules[0]["proxy"]
    assert [d["effect_type"] for d in panel["default_category"]] == [7, 19]
    assert {c["category_id"] for c in panel["categories"]} == {grid.EXTRAS_ID, grid.TRANS_EXTRAS_ID}
    ids = [s["category_id"] for s in rules[1]["proxy"]["serve_category"]]
    assert ids == [grid.DEFAULT_PANEL_CATEGORY, grid.EXTRAS_ID, grid.TRANS_PANEL_CATEGORY, grid.TRANS_EXTRAS_ID]
