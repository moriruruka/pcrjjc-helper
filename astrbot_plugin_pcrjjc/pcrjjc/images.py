"""图片可用性判断：什么样的图不适合当「竞技场头像」去识别。

聊天里混进来的表情包、动图、缩略图，如果直接丢进识别流程，结果一定是
「没认出来」，用户看到的就是“它把我的表情当作业图了”。所以在识别前先做
一道便宜的门槛，把明显不是头像的图挡掉。
"""

from __future__ import annotations

from pathlib import Path

MIN_SIDE = 160
"""短边小于这个值就当作缩略图/表情（头像框在竞技场截图里通常 >100px）。"""

MAX_ASPECT = 3.2
"""长宽比超过这个值就不像单个头像（比如横幅、长截图）。"""


def reject_reason(path: str | Path) -> str:
    """返回不适合当头像图的原因；空字符串表示可以进识别流程。"""

    try:
        from PIL import Image

        with Image.open(Path(path)) as image:
            frames = int(getattr(image, "n_frames", 1) or 1)
            width, height = image.size
    except Exception:  # noqa: BLE001 - 打不开的图直接拒绝
        return "这张图打不开"
    if frames > 1:
        return "这是动图表情"
    if min(width, height) < MIN_SIDE:
        return "这张图太小了"
    if max(width, height) / max(1, min(width, height)) > MAX_ASPECT:
        return "这张图的比例不像头像"
    return ""


def looks_like_portrait(path: str | Path) -> bool:
    return reject_reason(path) == ""
