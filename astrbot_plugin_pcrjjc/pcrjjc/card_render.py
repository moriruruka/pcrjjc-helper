"""作业结果图片卡片渲染。

只依赖 Pillow。把 pcrdfans 的一条作业渲染成：
进攻方 5 个头像 → 防守方 5 个头像，头像下可显示名字，右侧显示赞/踩。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import fonts

try:  # Pillow 9/10/11+
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    _LANCZOS = Image.LANCZOS

IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}

AVATAR = 64
AVATAR_GAP = 6
GROUP_WIDTH = AVATAR * 5 + AVATAR_GAP * 4
PAD = 24
ARROW_GAP = 18
ARROW_WIDTH = 34
MIN_WIDTH = 940
MAX_ITEMS = 8


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """字体查找交给 ``pcrjjc.fonts``（跨平台 + 可用环境变量覆盖）。"""

    return fonts.load(size, bold=bold)


def _has_kana(text: str) -> bool:
    return any("\u3040" <= char <= "\u30ff" for char in text)


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def pick_display_name(official: str, aliases: Sequence[str], mode: str) -> str:
    """按 show_names 选展示名。

    slang = 别称里第一个「带汉字、不带假名、不是纯英文」的名字；找不到就用官译。
    """

    mode = str(mode or "slang").lower()
    if mode == "none":
        return ""
    if mode == "official":
        return str(official or "")
    for alias in aliases or []:
        text = str(alias or "").strip()
        if not text or _has_kana(text):
            continue
        if not _has_cjk(text):
            continue
        return text
    return str(official or "")


def parse_ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 1_000_000_000_000:  # 毫秒
        number /= 1000.0
    return number


def _ratio(entry: Mapping[str, Any]) -> float:
    up = max(0, int(entry.get("up") or 0))
    down = max(0, int(entry.get("down") or 0))
    return up / (up + down + 1.0)


def sort_entries(
    entries: Sequence[Mapping[str, Any]],
    mode: str,
    def_ids: Sequence[int],
) -> list[dict[str, Any]]:
    """按配置排序，返回新的 list（不修改 API / 缓存里的原始顺序）。"""

    indexed = list(enumerate(entries))
    mode = str(mode or "ratio").lower()
    now = time.time()

    if mode == "time":
        ordered = [dict(entry) for _index, entry in indexed]
    elif mode == "relevance":
        query = {int(value) for value in def_ids}
        def relevance(pair: tuple[int, Mapping[str, Any]]) -> tuple[int, float, int]:
            index, entry = pair
            members = entry.get("def") or entry.get("atk") or []
            ids = {int(member.get("id") or 0) for member in members}
            overlap = len(query & ids)
            return -overlap, -_ratio(entry), index

        ordered = [dict(entry) for _index, entry in sorted(indexed, key=relevance)]
    else:  # ratio（默认）
        def score(pair: tuple[int, Mapping[str, Any]]) -> tuple[float, int]:
            index, entry = pair
            value = _ratio(entry)
            ts = parse_ts(entry.get("ts"))
            if ts is not None:
                age_days = max(0.0, (now - ts) / 86400.0)
                # 30 天衰减到约一半；没有 ts 就完全不衰减，按列表顺序兜底。
                value *= 1.0 / (1.0 + age_days / 30.0)
            return -value, index

        ordered = [dict(entry) for _index, entry in sorted(indexed, key=score)]

    return ordered


class AvatarStore:
    """从本地 avatars 目录按 4 位 id 取一张头像，优先 6★/3★/1★。"""

    def __init__(self, avatars_dir: str | Path) -> None:
        self.avatars_dir = Path(avatars_dir)
        self._paths: dict[int, Path] = {}
        self._scan()

    def _scan(self) -> None:
        try:
            paths = [
                path
                for path in self.avatars_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ]
        except OSError:
            paths = []
        for path in paths:
            stem = path.stem
            if len(stem) < 4 or not stem[:4].isdigit():
                continue
            char_id = int(stem[:4])
            current = self._paths.get(char_id)
            if current is None or self._variant_key(path.name) < self._variant_key(
                current.name
            ):
                self._paths[char_id] = path

    @staticmethod
    def _variant_key(name: str) -> tuple[int, str]:
        suffix = Path(name).stem[4:6]
        return {"61": 0, "31": 1, "11": 2}.get(suffix, 3), name

    def get(self, char_id: int, size: int = AVATAR) -> Image.Image | None:
        value = int(char_id)
        uid4 = value // 100 if value >= 100000 else value
        path = self._paths.get(uid4)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                image.load()
                picture = image.convert("RGBA")
            return _rounded_avatar(picture, size)
        except Exception:
            return None


def _rounded_avatar(image: Image.Image, size: int, radius: int = 10) -> Image.Image:
    picture = ImageOps.fit(image, (size, size), method=_LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=radius,
        fill=255,
    )
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(picture, (0, 0), mask)
    return result


def _placeholder(size: int, text: str) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=10,
        fill=(214, 218, 226, 255),
        outline=(196, 201, 212, 255),
        width=1,
    )
    label = (text or "?").strip()[:1] or "?"
    font = _load_font(max(18, size // 3), bold=True)
    draw.text(
        (size / 2, size / 2),
        label,
        font=font,
        fill=(88, 94, 108, 255),
        anchor="mm",
    )
    return image


def _truncate(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: float) -> str:
    text = str(text or "")
    if not text:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _ts_label(entry: Mapping[str, Any]) -> str:
    ts = parse_ts(entry.get("ts"))
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OSError, ValueError):
        return ""


def render_job_card(
    *,
    def_ids: Sequence[int],
    entries: Sequence[Mapping[str, Any]],
    out_dir: str | Path,
    avatars_dir: str | Path,
    name_for: Callable[[int, str], str],
    official_name_for: Callable[[int], str],
    show_names: str = "slang",
    max_items: int = MAX_ITEMS,
    note: str = "",
    title: str = "作业查询",
    show_likes: bool = True,
    show_time: bool = True,
) -> Path:
    """渲染一张作业卡片，返回 PNG 路径。

    name_for(char_id, mode) 负责按 show_names 模式取名；official_name_for
    用于灰色占位块里的首字。调用方负责在发送后清理 PNG。
    """

    show_names = str(show_names or "slang").lower()
    if show_names not in {"none", "official", "slang"}:
        show_names = "slang"
    limit = max(1, min(MAX_ITEMS, int(max_items or MAX_ITEMS)))
    rows = [dict(entry) for entry in list(entries)[:limit]]

    store = AvatarStore(avatars_dir)
    title_font = _load_font(28, bold=True)
    count_font = _load_font(16)
    note_font = _load_font(13)
    name_font = _load_font(14)
    like_font = _load_font(13, bold=True)
    footer_font = _load_font(12)

    probe = Image.new("RGB", (10, 10), (255, 255, 255))
    measure = ImageDraw.Draw(probe)

    like_texts = [
        f"赞 {int(row.get('up') or 0)} / 踩 {int(row.get('down') or 0)}"
        for row in rows
    ]
    likes_width = (
        max([int(measure.textlength(text, font=like_font)) for text in like_texts] or [90])
        + 16
        if show_likes
        else 0
    )
    row_width = (
        PAD * 2
        + GROUP_WIDTH * 2
        + ARROW_GAP * 2
        + ARROW_WIDTH
        + likes_width
    )

    title_width = int(measure.textlength(title, font=title_font))
    count_text = f"找到 {len(rows)} 队" if rows else "没有查到作业"
    count_width = int(measure.textlength(count_text, font=count_font))
    mini_size = 38
    mini_gap = 4
    mini_width = len(def_ids) * (mini_size + mini_gap) if def_ids else 0
    header_width = PAD * 2 + title_width + 18 + mini_width + 24 + count_width
    width = max(MIN_WIDTH, row_width, header_width)
    width = min(width, 1600)

    header_height = 94 if note else 76
    name_height = 23 if show_names != "none" else 0
    row_height = AVATAR + name_height + 14
    footer_height = 28
    height = header_height + max(1, len(rows)) * row_height + footer_height + 8
    if not rows:
        height = header_height + 110 + footer_height

    image = Image.new("RGB", (width, height), (244, 246, 250))
    draw = ImageDraw.Draw(image)

    # 顶部标题、查询角色小头像、结果条数
    draw.text((PAD, 16), title, font=title_font, fill=(38, 43, 56))
    mini_x = PAD + title_width + 18
    mini_y = 16
    for char_id in list(def_ids)[:5]:
        avatar = store.get(int(char_id), mini_size)
        if avatar is None:
            avatar = _placeholder(mini_size, official_name_for(int(char_id)))
        image.paste(avatar, (mini_x, mini_y), avatar)
        mini_x += mini_size + mini_gap
    draw.text(
        (width - PAD, 24),
        count_text,
        font=count_font,
        fill=(92, 99, 116),
        anchor="ra",
    )
    if note:
        note_text = _truncate(measure, note, note_font, width - PAD * 2)
        draw.text((PAD, 62), note_text, font=note_font, fill=(124, 131, 146))

    if not rows:
        draw.rounded_rectangle(
            (PAD, header_height, width - PAD, header_height + 82),
            radius=14,
            fill=(255, 255, 255),
        )
        draw.text(
            (width / 2, header_height + 41),
            "没有查到这组防守的作业，可以换个服或去 pcrdfans.com 手动看看。",
            font=count_font,
            fill=(100, 106, 122),
            anchor="mm",
        )
    else:
        for row_index, entry in enumerate(rows):
            top = header_height + row_index * row_height
            draw.rounded_rectangle(
                (12, top + 2, width - 12, top + row_height - 6),
                radius=14,
                fill=(255, 255, 255),
            )
            if row_index % 2 == 1:
                draw.rounded_rectangle(
                    (12, top + 2, width - 12, top + row_height - 6),
                    radius=14,
                    fill=(250, 251, 253),
                )

            atk_x = PAD
            def_x = PAD + GROUP_WIDTH + ARROW_GAP * 2 + ARROW_WIDTH
            avatar_y = top + 10

            for team_key, start_x in (("atk", atk_x), ("def", def_x)):
                members = list(entry.get(team_key) or [])[:5]
                for slot in range(5):
                    x = start_x + slot * (AVATAR + AVATAR_GAP)
                    if slot >= len(members):
                        continue
                    member = members[slot]
                    try:
                        char_id = int(member.get("id") or 0)
                    except (TypeError, ValueError):
                        continue
                    avatar = store.get(char_id, AVATAR)
                    if avatar is None:
                        avatar = _placeholder(
                            AVATAR,
                            official_name_for(char_id) or str(char_id),
                        )
                    image.paste(avatar, (x, avatar_y), avatar)
                    if show_names != "none":
                        label = name_for(char_id, show_names) or official_name_for(
                            char_id
                        )
                        label = _truncate(
                            measure,
                            label,
                            name_font,
                            AVATAR - 2,
                        )
                        draw.text(
                            (x + AVATAR / 2, avatar_y + AVATAR + 3),
                            label,
                            font=name_font,
                            fill=(86, 92, 106),
                            anchor="mt",
                        )

            # 箭头
            arrow_x = PAD + GROUP_WIDTH + ARROW_GAP
            arrow_y = avatar_y + AVATAR // 2
            arrow_end = arrow_x + ARROW_WIDTH
            draw.line(
                (arrow_x, arrow_y, arrow_end - 7, arrow_y),
                fill=(126, 134, 150),
                width=3,
            )
            draw.polygon(
                [
                    (arrow_end, arrow_y),
                    (arrow_end - 9, arrow_y - 7),
                    (arrow_end - 9, arrow_y + 7),
                ],
                fill=(126, 134, 150),
            )

            if show_likes:
                like_text = like_texts[row_index]
                draw.text(
                    (width - PAD, top + 12),
                    like_text,
                    font=like_font,
                    fill=(112, 119, 134),
                    anchor="ra",
                )
            ts_label = _ts_label(entry) if show_time else ""
            if ts_label:
                draw.text(
                    (width - PAD, top + 34),
                    ts_label,
                    font=note_font,
                    fill=(154, 160, 173),
                    anchor="ra",
                )

    draw.text(
        (width - PAD, height - 22),
        "pcrdfans.com · PCRBot",
        font=footer_font,
        fill=(158, 164, 176),
        anchor="ra",
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    target = out_path / f"pcrbot_job_{uuid.uuid4().hex}.png"
    image.save(target, "PNG", optimize=True)
    return target
