"""A minimal get_resources_by_category_id reply, used when no real one has been seen yet.

CapCut prefetches every category at launch - before any real reply has been cached for us to clone - and then keeps whatever
it received for the session. If our synthetic category were answered with an empty list at that moment it would show
"No content" until the next launch (found live, 5 Oct). So the first answer must already be a well-formed reply.
The shape below is the one CapCut 8.9.1 returns (field names only; no real content is copied).
"""
from __future__ import annotations

import json


def skeleton_envelope() -> bytes:
    tile = {
        "common_attr": {
            "id": "0", "effect_id": "0", "effect_type": 7, "source": 1, "title": "", "description": "",
            "cover_url": {}, "item_urls": [], "md5": "0" * 32, "has_favorited": False,
            "third_resource_id": 0, "third_resource_id_str": "0", "create_time": 1700000000, "is_original": True,
            "status": 102, "review_info": {"review_status": 1, "review_code_list": [], "extra_reason": None, "review_reason_list": []},
            "aspect_ratio": 1, "download_info": {"url": "", "format": ""}, "publish_source": "loki",
            "is_business": False, "business_scope": [], "business_info": {"json_str": json.dumps({"is_vip": False, "is_expired": False, "paid_type": "free"}, separators=(",", ":"))}, "category_ids": [],
            "extra": json.dumps({"effect_duration": 3000}, separators=(",", ":")),
            "sdk_extra": json.dumps({"setting": {"effect_adjust_params": []}}, separators=(",", ":")),
            "sdk_model": [], "requirements": [], "model_names": "{}", "vip_name": "",
            "biz_extra": json.dumps({"effect_duration": 3000}, separators=(",", ":")),
        },
        "author": {}, "special_effect": {"effect_duration": 3000}, "template": None,
    }
    return json.dumps({
        "ret": "0", "errmsg": "success", "systime": "0", "logid": "", "log_id": "", "sign": "", "response": "", "svr_time": 0,
        "data": {"has_more": False, "next_offset": 1, "effect_item_list": [tile], "version_code": "1", "request_id": "",
                 "fail_reason": "", "compress_data": False, "specific_item_list": None},
    }, separators=(",", ":")).encode()
