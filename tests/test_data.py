"""角色表与索引：数据完整性 + 别称解析 + 模糊搜索。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pcrjjc import pcr_data


@pytest.fixture(scope="module")
def payload():
    from tests.conftest import DATA

    data = pcr_data.load_characters(DATA / "characters.json")
    assert data is not None, "包里必须带 characters.json"
    return data


def test_characters_have_unique_ids(payload):
    chars = payload["characters"]
    ids = [c["id"] for c in chars]
    assert len(chars) > 300
    assert len(set(ids)) == len(ids)


def test_character_ids_are_six_digits(payload):
    for char in payload["characters"]:
        assert isinstance(char["id"], int)
        assert 100000 <= char["id"] <= 999999


def test_every_character_has_a_name(payload):
    for char in payload["characters"]:
        assert (char.get("name") or char.get("name_jp") or "").strip()


def test_index_resolves_common_aliases(payload):
    index = pcr_data.CharacterIndex(payload)
    assert index.resolve_token("布丁") == 100701
    assert index.resolve_token("宫子") == 100701
    assert index.resolve_token("克总") == 107101
    assert index.resolve_token("107101") == 107101


def test_index_rejects_unknown(payload):
    index = pcr_data.CharacterIndex(payload)
    assert index.resolve_token("这不是角色") is None
    assert index.resolve_token("") is None


def test_search_returns_ranked_hits(payload):
    index = pcr_data.CharacterIndex(payload)
    hits = index.search("克莉丝", limit=3)
    assert hits
    assert hits[0].character.id == 107101
    assert hits[0].score >= hits[-1].score


def test_similarity_prefers_closer_strings():
    assert pcr_data.similarity("克莉丝提娜", "克莉丝提娜") == pytest.approx(1.0)
    assert pcr_data.similarity("克莉丝", "克莉丝提娜") > pcr_data.similarity("克莉丝", "宫子")


def test_display_name_marks_japanese_only(payload):
    index = pcr_data.CharacterIndex(payload)
    ja_only = [c for c in index.characters if c.name_lang == "ja"]
    for char in ja_only[:5]:
        assert char.display_name.endswith("*")


def test_load_characters_returns_none_for_missing_file(tmp_path: Path):
    assert pcr_data.load_characters(tmp_path / "nope.json") is None


def test_load_characters_returns_none_for_broken_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pcr_data.load_characters(bad) is None
