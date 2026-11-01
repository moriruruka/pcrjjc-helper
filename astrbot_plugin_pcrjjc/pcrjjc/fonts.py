"""跨平台中文字体查找。

原来写死 ``C:\\Windows\\Fonts\\msyh.ttc``，在 Linux/macOS 或者精简版 Windows 上
卡片会退化成 Pillow 的默认位图字体（中文会变方框）。这里改成「按平台列候选 +
允许用环境变量指定 + 允许内置字体」三档兜底。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ENV_FONT = "PCRJJC_FONT"

WINDOWS_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)
MACOS_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)
LINUX_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def bundled_fonts() -> list[Path]:
    """放在包内 ``assets/fonts`` 的字体（可选，仓库默认不带，避免体积）。"""

    here = Path(__file__).resolve().parent
    for folder in (here / "assets" / "fonts", here.parent / "assets" / "fonts"):
        if folder.is_dir():
            return sorted(folder.glob("*.tt[fc]")) + sorted(folder.glob("*.otf"))
    return []


def font_candidates() -> list[Path]:
    """按「用户指定 → 内置 → 本平台系统字体」的顺序给出候选。"""

    out: list[Path] = []
    override = (os.environ.get(ENV_FONT) or "").strip()
    if override:
        out.append(Path(override).expanduser())
    out.extend(bundled_fonts())
    import sys

    if sys.platform.startswith("win"):
        out.extend(Path(p) for p in WINDOWS_CANDIDATES)
    elif sys.platform == "darwin":
        out.extend(Path(p) for p in MACOS_CANDIDATES)
    else:
        out.extend(Path(p) for p in LINUX_CANDIDATES)
    return out


@lru_cache(maxsize=64)
def _load_cached(path: str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except Exception:  # noqa: BLE001 - 字体文件坏了就换下一个
        return None


def load(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """拿一个字号为 ``size`` 的字体；全找不到就退到 Pillow 默认字体。"""

    candidates = font_candidates()
    if bold and candidates:
        # 粗体优先挑文件名里带 bold/bd/hei 的，没有再按原顺序
        preferred = [p for p in candidates if any(k in p.name.lower() for k in ("bd", "bold", "hei"))]
        candidates = preferred + [p for p in candidates if p not in preferred]
    for path in candidates:
        if not path.is_file():
            continue
        font = _load_cached(str(path), int(size))
        if font is not None:
            return font
    try:
        return ImageFont.load_default(size=int(size))
    except Exception:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def describe() -> dict[str, object]:
    """给 ``--selftest`` / 排障用：现在用的是哪个字体。"""

    for path in font_candidates():
        if path.is_file() and _load_cached(str(path), 16) is not None:
            return {"font": str(path), "bundled": str(path.parent).endswith("fonts")}
    return {"font": None, "bundled": False}
