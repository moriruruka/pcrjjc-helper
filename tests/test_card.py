"""卡片渲染：无头像也能出图，有头像时能贴上去。"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from pcrjjc import pcr_data
from pcrjjc.card_render import render_job_card, sort_entries

TEAM = [100701, 107101, 100501, 100901, 101001]


def _payload(seed_dir: Path) -> dict:
    return pcr_data.load_characters(seed_dir / "characters.json") or {}


def _entry(up: int = 12, down: int = 3) -> dict:
    return {
        "id": "abc",
        "def": [{"id": i} for i in TEAM],
        "atk": [{"id": i} for i in TEAM],
        "up": up,
        "down": down,
        "views": 345,
        "ts": int(time.time()),
    }


def _render(tmp_path: Path, payload: dict, entries: list[dict], avatars: Path | None = None) -> Image.Image:
    index = pcr_data.CharacterIndex(payload)
    out = render_job_card(
        def_ids=TEAM,
        entries=entries,
        out_dir=tmp_path,
        avatars_dir=avatars or (tmp_path / "no-avatars"),
        name_for=lambda cid, mode: index.by_id[cid].display_name if cid in index.by_id else str(cid),
        official_name_for=lambda cid: index.by_id[cid].display_name if cid in index.by_id else str(cid),
        show_names="slang",
    )
    image = Image.open(out)
    image.load()
    return image


def test_render_without_avatars(tmp_path: Path, seed_dir: Path):
    image = _render(tmp_path, _payload(seed_dir), [_entry()])
    assert image.width >= 900
    assert image.height > 100


def test_render_with_avatars(tmp_path: Path, seed_dir: Path):
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    for i, char_id in enumerate(TEAM):
        Image.new("RGB", (128, 128), (40 + i * 30, 90, 160 - i * 20)).save(avatars / f"{char_id}.webp")
    image = _render(tmp_path, _payload(seed_dir), [_entry()], avatars)
    assert image.width >= 900


def test_render_many_entries_respects_limit(tmp_path: Path, seed_dir: Path):
    entries = [_entry(up=i, down=1) for i in range(12)]
    image = _render(tmp_path, _payload(seed_dir), entries)
    assert image.height > 200


def test_sort_entries_by_ratio(seed_dir: Path):
    entries = [_entry(1, 9), _entry(20, 1)]
    sorted_entries = sort_entries(entries, mode="ratio", def_ids=TEAM)
    assert sorted_entries[0]["up"] == 20


def test_pick_display_name_modes(seed_dir: Path):
    from pcrjjc.card_render import pick_display_name

    assert pick_display_name("克莉丝提娜", ["克总"], "slang") == "克总"
    assert pick_display_name("克莉丝提娜", ["克总"], "official") == "克莉丝提娜"
    assert pick_display_name("克莉丝提娜", ["克总"], "none") == ""
