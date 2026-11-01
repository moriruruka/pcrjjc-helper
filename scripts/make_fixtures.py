"""生成测试素材：5 张合成头像 + 一张 5 格“竞技场截图”。

用途：验证识别链路，同时避免把真实游戏截图放进仓库。

例：
    python scripts/make_fixtures.py --out fixtures
    pcrjjc recognize -i fixtures/screenshot.png --avatars fixtures/avatars
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

TEAM = [100701, 107101, 100501, 100901, 101001]


def avatar(char_id: int, size: int = 128) -> Image.Image:
    seed = char_id % 97
    img = Image.new("RGB", (size, size), (60 + seed, 70, 200 - seed))
    draw = ImageDraw.Draw(img)
    draw.ellipse((18, 18, size - 18, size - 18), fill=(250 - seed, 220, 180))
    draw.rectangle((30, 30 + seed % 40, 60, size - 30), fill=(20, 30 + seed, 90))
    draw.arc((10, 10, size - 10, size - 10), start=seed, end=seed + 200, fill=(10, 10, 10), width=6)
    return img


def screenshot(panels: list[Image.Image], gap: int = 22, box: int = 150) -> Image.Image:
    width = 60 + len(panels) * (box + gap)
    canvas = Image.new("RGB", (width, 260), (245, 246, 248))
    draw = ImageDraw.Draw(canvas)
    for i, panel in enumerate(panels):
        x = 60 + i * (box + gap)
        canvas.paste(panel.resize((box, box)), (x, 55))
        draw.rectangle((x - 3, 52, x + box + 2, 55 + box + 2), outline=(30, 30, 30), width=3)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="生成识别测试素材")
    parser.add_argument("--out", default="fixtures", help="输出目录")
    args = parser.parse_args()

    out = Path(args.out)
    avatars = out / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    for char_id in TEAM:
        avatar(char_id).save(avatars / f"{char_id}.webp")
    shot = screenshot([avatar(cid) for cid in TEAM])
    shot_path = out / "screenshot.png"
    shot.save(shot_path)
    print(f"头像：{avatars}（{len(TEAM)} 张）")
    print(f"截图：{shot_path}（{shot.width}x{shot.height}）")
    print(f"自检：pcrjjc recognize -i {shot_path} --avatars {avatars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
