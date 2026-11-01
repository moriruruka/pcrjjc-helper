"""截图识别：用合成图验证「找框 → 脸带比对」整条链路（不联网、不用真人截图）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("cv2")
pytest.importorskip("numpy")

from pcrjjc.image_match import AvatarLibrary, ImageRecognizer  # noqa: E402

TEAM = [100701, 107101, 100501, 100901, 101001]


def _avatar(char_id: int, size: int = 128) -> Image.Image:
    """按 id 生成确定性花纹的头像，保证彼此可区分。"""

    seed = char_id % 97
    img = Image.new("RGB", (size, size), (60 + seed, 70, 200 - seed))
    draw = ImageDraw.Draw(img)
    draw.ellipse((18, 18, size - 18, size - 18), fill=(250 - seed, 220, 180))
    draw.rectangle((30, 30 + seed % 40, 60, size - 30), fill=(20, 30 + seed, 90))
    draw.arc((10, 10, size - 10, size - 10), start=seed, end=seed + 200, fill=(10, 10, 10), width=6)
    return img


def _screenshot(panels: list[Image.Image], gap: int = 22) -> Image.Image:
    box = 150
    width = 60 + len(panels) * (box + gap)
    canvas = Image.new("RGB", (width, 260), (245, 246, 248))
    draw = ImageDraw.Draw(canvas)
    for i, panel in enumerate(panels):
        x = 60 + i * (box + gap)
        canvas.paste(panel.resize((box, box)), (x, 55))
        draw.rectangle((x - 3, 52, x + box + 2, 55 + box + 2), outline=(30, 30, 30), width=3)
    return canvas


@pytest.fixture()
def avatars(tmp_path: Path) -> Path:
    folder = tmp_path / "avatars"
    folder.mkdir()
    for char_id in TEAM:
        _avatar(char_id).save(folder / f"{char_id}.webp")
    return folder


def test_library_loads_generated_avatars(avatars: Path):
    library = AvatarLibrary(avatars)
    library.load()
    assert len(library) == len(TEAM)


def test_recognize_five_slot_screenshot(tmp_path: Path, avatars: Path):
    shot = _screenshot([_avatar(cid) for cid in TEAM])
    shot_path = tmp_path / "shot.png"
    shot.save(shot_path)

    library = AvatarLibrary(avatars)
    recognizer = ImageRecognizer(library, threshold=0.6)
    result = recognizer.recognize(Image.open(shot_path))

    assert result.teams, "应该至少识别出一支队伍"
    team = result.teams[0]
    assert len(team.slots) == len(TEAM), "五个格子都要找到"
    ids = [slot.char_id for slot in team.slots]
    # char_id 是 4 位 uid4（100701 -> 1007），换算回 6 位再比对
    assert set(ids).issubset({cid // 100 for cid in TEAM})
    scores = [slot.match.score for slot in team.slots if slot.match]
    assert scores and max(scores) >= 0.9, f"合成图应该高度相似：{scores}"


def test_recognize_handles_blank_image(tmp_path: Path, avatars: Path):
    blank = Image.new("RGB", (900, 300), (250, 250, 250))
    recognizer = ImageRecognizer(AvatarLibrary(avatars), threshold=0.6)
    result = recognizer.recognize(blank)
    assert result.accepted_count == 0
    assert result.library_count == len(TEAM)


def test_recognize_without_avatars(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    recognizer = ImageRecognizer(AvatarLibrary(empty), threshold=0.6)
    err = None
    try:
        result = recognizer.recognize(_screenshot([_avatar(cid) for cid in TEAM]))
    except Exception as exc:  # noqa: BLE001
        err = exc
        result = None
    assert err is not None or (result is not None and result.accepted_count == 0)
