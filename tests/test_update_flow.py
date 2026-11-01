"""更新流程回归：/units 只给日文名时，不能把已有中文名刷掉。

这是线上真实出过的事故：一次自动更新把 129 个角色的中文名覆盖成日文名，
黑话模式因此退化成显示日文名（带 `*`）。这里用最小数据复现并守住。
"""

from __future__ import annotations

from pathlib import Path

from pcrjjc import pcr_data

CHAR_ID = 118601
UID4 = CHAR_ID // 100


def _units_payload(unit_id: int, jp_name: str) -> dict:
    return {
        "unitObject": {str(unit_id // 100): {"id": unit_id, "name": jp_name}},
        "cn": [unit_id],
        "us": [],
    }


def test_units_only_update_keeps_previous_chinese_names(tmp_path: Path):
    previous = {
        "updated_at": "2026-11-01 21:33:56",
        "characters": [
            {
                "id": CHAR_ID,
                "uid4": UID4,
                "name": "伊绪（新年）",
                "name_jp": "イオ（ニューイヤー）",
                "name_lang": "zh",
                "name_source": "wiki",
                "aliases": ["新年伊绪"],
                "all_names": ["伊绪（新年）", "新年伊绪", "イオ（ニューイヤー）"],
            }
        ],
        "stats": {},
    }

    fresh = pcr_data.build_characters_from_units(
        _units_payload(CHAR_ID, "イオ（ニューイヤー）"),
        updated_at="2026-11-03 03:00:00",
    )
    # 先确认这个 id 没有内置中文名，否则测试就失去意义
    assert fresh["characters"][0]["name_lang"] == "ja", "该 id 现在有内置中文名，换一个测试 id"

    restored = pcr_data.merge_previous_names(fresh, previous)
    assert restored == 1
    char = fresh["characters"][0]
    assert char["name"] == "伊绪（新年）"
    assert char["name_lang"] == "zh"
    assert "新年伊绪" in char["aliases"]


def test_saved_payload_survives_roundtrip(tmp_path: Path):
    payload = {
        "updated_at": "2026-11-03 03:00:00",
        "characters": [
            {"id": CHAR_ID, "uid4": UID4, "name": "伊绪（新年）", "name_lang": "zh", "aliases": []}
        ],
    }
    target = tmp_path / "characters.json"
    pcr_data.save_characters(target, payload)
    loaded = pcr_data.load_characters(target)
    assert loaded is not None
    assert loaded["characters"][0]["name"] == "伊绪（新年）"
    assert not (tmp_path / "characters.json.tmp").exists()


def test_merge_does_not_touch_new_chinese_names(tmp_path: Path):
    previous = {"characters": [{"id": CHAR_ID, "name": "旧译名", "name_lang": "zh"}]}
    fresh = {
        "characters": [
            {"id": CHAR_ID, "name": "新译名", "name_lang": "zh", "aliases": []},
        ],
        "stats": {},
    }
    assert pcr_data.merge_previous_names(fresh, previous) == 0
    assert fresh["characters"][0]["name"] == "新译名"
