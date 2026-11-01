"""图片可用性判断：表情包/动图/缩略图不该被当成竞技场头像。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from pcrjjc import images


def test_normal_portrait_is_accepted(tmp_path: Path):
    path = tmp_path / "avatar.png"
    Image.new("RGB", (200, 200), (120, 120, 200)).save(path)
    assert images.reject_reason(path) == ""
    assert images.looks_like_portrait(path)


def test_tiny_sticker_is_rejected(tmp_path: Path):
    path = tmp_path / "sticker.png"
    Image.new("RGB", (80, 80), (255, 255, 255)).save(path)
    assert "太小" in images.reject_reason(path)


def test_animated_sticker_is_rejected(tmp_path: Path):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (200, 200), (i * 30, 100, 100)) for i in range(3)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    assert "动图" in images.reject_reason(path)


def test_banner_is_rejected(tmp_path: Path):
    path = tmp_path / "banner.png"
    Image.new("RGB", (1200, 200), (10, 10, 10)).save(path)
    assert "比例" in images.reject_reason(path)


def test_broken_file_is_rejected(tmp_path: Path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    assert images.reject_reason(path) == "这张图打不开"
