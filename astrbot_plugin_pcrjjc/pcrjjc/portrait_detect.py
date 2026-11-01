"""竞技场/编成截图 → 头像框定位。

只做定位，不做识别：输入 PIL.Image，输出按行分组的头像框列表，一行 = 一队。

方案（实测在 5 张真实截图上都能稳定切出 5 个头像框）：
  Canny(40,120) → dilate → findContours → 用 boundingRect 的宽高/长宽比/面积/fill 过滤
  → 去重（重叠只留大的）→ 按 y 中心聚成行 → 行内按 x 排序。

为了兼顾不同分辨率，检测前会把图缩放到长边≈1400 再算，最后把坐标映射回原图。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image

# 检测时把长边归一化到这个尺寸，避免大图/小图都要调参数。
DETECT_LONG_SIDE = 1400.0
# 裁出「脸」时相对头像框的内缩比例：避开顶部「等级/战力」和底部「星级 + 职业/属性」。
FACE_INSET_X = 0.06
FACE_INSET_TOP = 0.20
FACE_INSET_BOTTOM = 0.74

MIN_SIDE = 56          # 归一化后头像框的最小边长（px）
MAX_SIDE = 500         # 单个头像框最大的合理边长
ASPECT_RANGE = (0.8, 1.25)
AREA_RANGE = (0.018, 0.30)
RELAXED_AREA_RANGE = (0.003, 0.30)   # 相对全图面积（实测真实头像框 3.5%~13%，文字笔画约 1.6%）
MIN_FILL = 0.55        # 轮廓面积 / boundingRect 面积
ROW_TOLERANCE = 0.5    # 行聚类：y 中心差 < 框高 * 该系数即视为同一行


@dataclass(slots=True)
class Portrait:
    """一个头像框。"""

    box: tuple[int, int, int, int]          # 头像框（原图坐标）
    crop_box: tuple[int, int, int, int]     # 建议裁剪区域（去掉了上下两条 UI）
    team_index: int
    slot_index: int

    @property
    def x0(self) -> int:
        return self.box[0]

    @property
    def y0(self) -> int:
        return self.box[1]

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "box": list(self.box),
            "crop_box": list(self.crop_box),
            "team_index": self.team_index,
            "slot_index": self.slot_index,
        }


def _iou(a: Sequence[int], b: Sequence[int]) -> float:
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / float(aw * ah + bw * bh - inter)


def _detect_scale(width: int, height: int) -> float:
    long_side = max(width, height)
    if long_side <= 0:
        return 1.0
    return min(2.5, max(0.35, DETECT_LONG_SIDE / long_side))


def _find_frames(gray: np.ndarray, scale: float, *, relaxed: bool = False) -> list[list[int]]:
    """返回候选框 [x, y, w, h, area]，坐标是缩放后的图。"""

    height, width = gray.shape[:2]
    edges = cv2.Canny(gray, 30, 90) if relaxed else cv2.Canny(gray, 40, 120)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    area_img = float(height * width)
    area_range = RELAXED_AREA_RANGE if relaxed else AREA_RANGE
    min_side = MIN_SIDE
    max_side = min(MAX_SIDE, int(min(width, height) * 0.98))
    boxes: list[list[int]] = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
            continue
        ratio = bw / float(bh)
        if not (ASPECT_RANGE[0] <= ratio <= ASPECT_RANGE[1]):
            continue
        area = bw * bh
        if not (area_img * area_range[0] <= area <= area_img * area_range[1]):
            continue
        fill = cv2.contourArea(cnt) / float(area)
        if fill < MIN_FILL:
            continue
        boxes.append([int(x), int(y), int(bw), int(bh), int(area)])

    # 同一个框会被里外两层轮廓各命中一次，只保留大的那个。
    boxes.sort(key=lambda item: -item[4])
    kept: list[list[int]] = []
    for box in boxes:
        if all(_iou(box, other) < 0.45 for other in kept):
            kept.append(box)
    return kept


def _group_rows(boxes: list[list[int]]) -> list[list[list[int]]]:
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda item: (item[1] + item[3] / 2.0))
    rows: list[list[list[int]]] = []
    for box in boxes:
        cy = box[1] + box[3] / 2.0
        placed = False
        for row in rows:
            ref = max(row, key=lambda item: item[3])
            ref_cy = sum(item[1] + item[3] / 2.0 for item in row) / len(row)
            if abs(ref_cy - cy) >= max(ref[3], box[3]) * ROW_TOLERANCE:
                continue
            # 同一行的框大小必须接近：对手选择界面「大立绘 + 5 个小图标」同一 y 带里
            # 混着 205px 和 116px 两种框，尺寸不一致就不能算一行。
            if max(ref[2], box[2]) > min(ref[2], box[2]) * 1.35:
                continue
            if max(ref[3], box[3]) > min(ref[3], box[3]) * 1.35:
                continue
            row.append(box)
            placed = True
            break
        if not placed:
            rows.append([box])
    for row in rows:
        row.sort(key=lambda item: item[0])
    rows.sort(key=lambda row: row[0][1])
    return rows


def _row_is_plausible(row: list[list[int]]) -> bool:
    """一行里的框应该大小接近、横向排开，用来排掉零散误检。"""

    if len(row) < 2:
        return True
    heights = [item[3] for item in row]
    widths = [item[2] for item in row]
    if max(heights) > min(heights) * 1.35 or max(widths) > min(widths) * 1.35:
        return False
    # 相邻框不应该几乎完全重合（重复检测）也不应该离得太远。
    ref_w = sorted(widths)[len(widths) // 2]
    for left, right in zip(row, row[1:], strict=False):
        gap = (right[0]) - (left[0] + left[2])
        if gap > ref_w * 1.1:
            return False
    return True


def _complete_row(row: list[list[int]], max_slots: int = 5) -> list[list[int]]:
    """一行里检测到的框不够 5 个时，按已有间距把缺的格子补出来。

    「选择对战对手」界面每队是 5 个 120px 小图标，偶尔有 1~2 个被文字/遮挡
    吞掉检测；补格后仍然要求原框 ≥3 个，避免把噪声拼成一行。
    """

    if not (3 <= len(row) < max_slots):
        return row
    row = sorted(row, key=lambda item: item[0])
    sizes = sorted(item[2] for item in row)
    ref_w = sizes[len(sizes) // 2]
    gaps = [
        right[0] - (left[0] + left[2])
        for left, right in zip(row, row[1:], strict=False)
        if right[0] > left[0]
    ]
    if not gaps:
        return row
    gaps.sort()
    step = ref_w + gaps[len(gaps) // 2]
    if step <= 0:
        return row
    filled = list(row)
    # 往左补
    while len(filled) < max_slots:
        first = filled[0]
        x = int(round(first[0] - step))
        if x < 0:
            break
        filled.insert(0, [x, first[1], first[2], first[3], first[2] * first[3]])
    # 往右补
    while len(filled) < max_slots:
        last = filled[-1]
        filled.append([int(round(last[0] + step)), last[1], last[2], last[3], last[2] * last[3]])
    return filled


def _fallback_rows(size: tuple[int, int], columns: int | None = None) -> list[list[list[int]]]:
    """找不到外框时的兜底：按宽高比（或指定列数）平均切成 n 个方块（一行）。

    用户经常直接截「只含头像的那一条」，那种图里图标紧贴、没有边框，
    Canny 抓不到，但宽高比基本就是 n:1。
    """

    width, height = size
    if width <= 0 or height <= 0:
        return []
    if columns is None:
        columns = max(1, min(5, int(round(width / float(height)))))
    columns = max(1, min(5, int(columns)))
    cell = width / float(columns)
    if cell < 48:
        columns = max(1, int(width // 48))
        if columns <= 0:
            return []
        cell = width / float(columns)
    if cell < 48 or height < 48:
        return []
    row: list[list[int]] = []
    for index in range(columns):
        left = int(round(index * cell))
        right = int(round((index + 1) * cell))
        row.append([left, 0, right - left, height, (right - left) * height])
    return [row]


def fallback_layouts(size: tuple[int, int]) -> list[list[list[int]]]:
    """所有可能的「等分 n 列」布局，按「方块接近正方形」排序，供调用方打分挑选。

    只裁了一条的图，宽高比会因为上面带了一条标题而算错列数（例如 5 个格子被
    算成 4 个），所以不能只靠宽高比，得让识别分数来决定。
    """

    width, height = size
    if width <= 0 or height <= 0:
        return []
    layouts: list[tuple[float, list[list[list[int]]]]] = []
    for columns in (5, 4, 3, 2, 1):
        if width / float(columns) < 48 or height < 48:
            continue
        rows = _fallback_rows(size, columns=columns)
        if not rows:
            continue
        cell = width / float(columns)
        # 头像格是正方形的，越接近 height 越可信。
        layouts.append((abs(cell / float(height) - 1.0), rows))
    layouts.sort(key=lambda item: item[0])
    return [rows for _score, rows in layouts]


def _face_crop(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    return (
        int(round(x0 + width * FACE_INSET_X)),
        int(round(y0 + height * FACE_INSET_TOP)),
        int(round(x0 + width * (1.0 - FACE_INSET_X))),
        int(round(y0 + height * (1.0 - FACE_INSET_BOTTOM))),
    )


def detect_portraits(
    image: Image.Image,
    *,
    allow_fallback: bool = True,
    _forced_columns: int | None = None,
) -> list[list[dict[str, Any]]]:
    """定位截图里的头像框，按行（= 队）分组。

    返回 ``[[{"box", "crop_box", "team_index", "slot_index"}, ...], ...]``，
    外层按队伍从上到下，内层按从左到右。

    ``allow_fallback=False`` 时不做「等分猜格子」，只返回 Canny 真找到的框；
    识别器用它来区分「真的有框」和「只能猜」。
    """

    if image is None:
        return []
    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size
    if width < 60 or height < 60:
        return []

    scale = _detect_scale(width, height)
    if abs(scale - 1.0) > 0.02:
        detect_image = image.resize(
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            Image.BILINEAR,
        )
    else:
        detect_image = image
    gray = cv2.cvtColor(np.asarray(detect_image), cv2.COLOR_RGB2GRAY)

    boxes = _find_frames(gray, scale)
    rows = _group_rows(boxes)
    rows = [row for row in rows if _row_is_plausible(row)]
    rows = [_complete_row(row) for row in rows]
    if max((len(row) for row in rows), default=0) < 3:
        # 第二遍：小图标（对手选择界面 120px 左右）用严格的面积下限会被滤掉
        relaxed_boxes = _find_frames(gray, scale, relaxed=True)
        relaxed_rows = [row for row in _group_rows(relaxed_boxes) if _row_is_plausible(row)]
        if max((len(row) for row in relaxed_rows), default=0) > max((len(row) for row in rows), default=0):
            rows = relaxed_rows

    # 一行是一支队，正常就是 5 个。图里的「胜利 / 失败」标题偶尔会凑出两个
    # 小方框，只要还有成行的（>=3 个）就把它丢掉。
    if rows:
        widest = max(len(row) for row in rows)
        if widest >= 3:
            rows = [row for row in rows if len(row) >= 3]
        elif widest == 2:
            rows = [row for row in rows if len(row) >= 2]

    if (not rows or max(len(row) for row in rows) < 2) and not allow_fallback:
        return []

    if not rows or max(len(row) for row in rows) < 2:
        # 兜底：用户常常直接发「只裁了头像那一条」的图（图标紧贴、没有外框），
        # 那种图 Canny 抓不到框，按宽高比平均切。
        rows = _fallback_rows(detect_image.size, columns=_forced_columns)

    inv = 1.0 / scale if scale else 1.0
    width, height = image.size
    out: list[list[dict[str, Any]]] = []
    team_index = 0
    for row in rows:
        slots: list[dict[str, Any]] = []
        for slot_index, (x, y, bw, bh, _area) in enumerate(row):
            x0 = max(0, min(width - 1, int(round(x * inv))))
            y0 = max(0, min(height - 1, int(round(y * inv))))
            x1 = max(x0 + 2, min(width, int(round((x + bw) * inv))))
            y1 = max(y0 + 2, min(height, int(round((y + bh) * inv))))
            box = (x0, y0, x1, y1)
            slots.append(
                {
                    "box": list(box),
                    "crop_box": list(_face_crop(box)),
                    "team_index": team_index,
                    "slot_index": slot_index,
                }
            )
        out.append(slots)
        team_index += 1
    return out


def portrait_objects(image: Image.Image) -> list[Portrait]:
    """和 :func:`detect_portraits` 一样，只是返回 dataclass，方便内部使用。"""

    result: list[Portrait] = []
    for row in detect_portraits(image):
        for slot in row:
            result.append(
                Portrait(
                    box=tuple(slot["box"]),  # type: ignore[arg-type]
                    crop_box=tuple(slot["crop_box"]),  # type: ignore[arg-type]
                    team_index=int(slot["team_index"]),
                    slot_index=int(slot["slot_index"]),
                )
            )
    return result


def debug_draw(image: Image.Image, rows: Iterable[Iterable[dict[str, Any]]],
               labels: Iterable[Iterable[str]] | None = None) -> Image.Image:
    """在图上画出框，供验证脚本使用。"""

    from PIL import ImageDraw

    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    labels = list(labels) if labels is not None else None
    for row_index, row in enumerate(rows):
        row_labels = labels[row_index] if labels and row_index < len(labels) else None
        for slot_index, slot in enumerate(row):
            x0, y0, x1, y1 = slot["box"]
            draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)
            cx0, cy0, cx1, cy1 = slot["crop_box"]
            draw.rectangle([cx0, cy0, cx1, cy1], outline=(0, 255, 128), width=1)
            text = f"T{row_index + 1}-{slot_index + 1}"
            if row_labels and slot_index < len(row_labels):
                text += " " + row_labels[slot_index]
            ty = max(0, y0 - 12)
            draw.text((x0 + 2, ty), text, fill=(255, 255, 0))
    return canvas


def _unused(*_args: Any) -> None:  # pragma: no cover - 保持 math 引用，避免误删
    math.floor(0)
