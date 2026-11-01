"""竞技场截图 → 角色识别（兼容层）。

真正的实现已经搬到 :mod:`recognize`：现在用的是「icon 脸带 + 归一化互相关」，
不再用 dHash / 直方图 / CLIP / ORB。保留本模块只是为了不破坏旧的 import 路径
（``from .image_match import AvatarLibrary, ImageRecognizer``）。

历史结论（别再走回头路）：
* dHash + 4³ 颜色直方图：几乎全错——两张不同角色的人脸在 8×8 梯度上几乎一样。
* CLIP(ViT-B-32) 拿 icon 比：所有候选 0.87~0.93，top1 基本是错的（CLIP 不区分动漫脸）。
* ORB 拿 icon 比：good match 只有 0.03~0.09（128px icon 降采样太狠，关键点撑不住）。
* 卡面 ``card/full`` 里的角色位置不固定，逐张对齐成本高；而 icon 已经是「脸」
  的规范裁切，对齐截图那一格直接比脸带就够准。
"""

from __future__ import annotations

try:  # AstrBot 以包的形式加载
    from .recognize import (  # noqa: F401
        BAND_SIZE,
        COARSE_CROPS,
        DEFAULT_MIN_MARGIN,
        DEFAULT_THRESHOLD,
        QUERY_BLUR,
        REF_BLUR,
        REF_CROP,
        AvatarLibrary,
        ImageRecognizer,
        Match,
        Recognition,
        SlotMatch,
        TeamResult,
    )
except ImportError:  # pragma: no cover - 单文件调试
    from recognize import (  # type: ignore  # noqa: F401
        BAND_SIZE,
        COARSE_CROPS,
        DEFAULT_MIN_MARGIN,
        DEFAULT_THRESHOLD,
        QUERY_BLUR,
        REF_BLUR,
        REF_CROP,
        AvatarLibrary,
        ImageRecognizer,
        Match,
        Recognition,
        SlotMatch,
        TeamResult,
    )

IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}

__all__ = [
    "AvatarLibrary",
    "ImageRecognizer",
    "Match",
    "Recognition",
    "SlotMatch",
    "TeamResult",
    "IMAGE_SUFFIXES",
    "DEFAULT_THRESHOLD",
    "DEFAULT_MIN_MARGIN",
    "BAND_SIZE",
    "COARSE_CROPS",
    "REF_CROP",
    "REF_BLUR",
    "QUERY_BLUR",
]
