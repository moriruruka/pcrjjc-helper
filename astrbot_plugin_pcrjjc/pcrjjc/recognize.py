"""竞技场截图 → 角色 id（重写版）。

思路（实测有效，别再回头用 dHash / CLIP / ORB 比 icon）：

1. 头像框定位交给 :mod:`portrait_detect`（Canny 轮廓 + 行聚类）。
2. 游戏里那一格头像和 ``icon/unit/*.webp`` 是**同一张卡面的同一个裁切**——同一个
   角色、同一个「脸在画面里的位置」，只是截图里被放大/缩小了一点。所以不需要
   CLIP 那种语义特征，直接拿「脸那条横带」做归一化互相关（NCC）就非常准：
   正确角色 0.83~0.95，第二名 0.4~0.7。
3. 不同界面（编成 / 战斗结果 / 防守预览）里头像的缩放不一样，所以先用一个粗网格
   试 24 个裁切（横向内缩 0.02~0.22、纵向 0.08~0.24 起、0.68~0.76 止）给候选
   排个序，再对前 15 个候选做局部细化（±0.03 / ±0.045），避免「粗网格最大值的
   噪声」把分数抬高。

单张图（含 3 队 15 格）在 CPU 上约 0.5~1 秒，不依赖 torch。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:  # AstrBot 以包的形式加载；单文件调试时走 fallback。
    from . import portrait_detect
except ImportError:  # pragma: no cover
    import portrait_detect  # type: ignore

try:
    import cv2
except ImportError:  # pragma: no cover - cv2 是 portrait_detect 的硬依赖
    cv2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}

# 比对用的「脸带」尺寸：再大收益很小，88×54 够用且内存省。
BAND_SIZE = (88, 54)
# 参考图（icon）里取脸带的位置：实测 icon 的 5%~95% / 19%~76% 正好是脸。
REF_CROP = (0.05, 0.19, 0.95, 0.76)
# 游戏里的头像往往是把 icon 放大渲染的，略糊；两边各做一点低通再比，
# 分数整体高 0.03~0.06、区分度也更好（实测 40 格中位数 0.921 → 0.961）。
REF_BLUR = 1.0
QUERY_BLUR = 0.7

# 粗网格：横向内缩 × 上边界 × 下边界。
_COARSE_X = (0.02, 0.08, 0.15, 0.22)
_COARSE_TOP = (0.08, 0.16, 0.24)
_COARSE_BOTTOM = (0.68, 0.76)
COARSE_CROPS: tuple[tuple[float, float, float, float], ...] = tuple(
    (xi, top, 1.0 - xi, bottom)
    for xi in _COARSE_X
    for top in _COARSE_TOP
    for bottom in _COARSE_BOTTOM
)
# 细化步长（相对头像框边长）。
REFINE_STEP_X = 0.03
REFINE_STEP_Y = 0.045
SHORTLIST = 15

# 判定阈值：score 是归一化互相关（-1~1），margin 是 top1 与 top2 的差。
DEFAULT_THRESHOLD = 0.70
DEFAULT_MIN_MARGIN = 0.05
HIGH_SCORE = 0.78


@dataclass(slots=True)
class Match:
    """一个头像框的最佳匹配。

    ``score`` 是归一化互相关（-1~1），``margin`` 是与第二名的差——两个一起才能
    判断「准不准」：score 高但 margin 很小说明撞上了同系列的相似角色。
    """

    char_id: int
    filename: str
    score: float
    second_char_id: int = 0
    second_filename: str = ""
    second_score: float = 0.0
    margin: float = 0.0
    accepted: bool = False

    @property
    def level(self) -> str:
        if not self.accepted:
            return "low"
        return "high" if self.score >= HIGH_SCORE and self.margin >= 0.10 else "medium"


@dataclass(slots=True)
class SlotMatch:
    """一个头像框的识别结果（含备选，方便排查）。"""

    box: tuple[int, int, int, int]
    crop_box: tuple[int, int, int, int]
    team_index: int
    slot_index: int
    match: Match | None = None
    alternatives: list[Match] = field(default_factory=list)
    accepted: bool = False

    @property
    def char_id(self) -> int:
        return self.match.char_id if self.match else 0

    @property
    def score(self) -> float:
        return self.match.score if self.match else 0.0


@dataclass(slots=True)
class TeamResult:
    team_index: int
    slots: list[SlotMatch] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        """按框从左到右、去重后的角色 id。"""

        out: list[int] = []
        seen: set[int] = set()
        for slot in self.slots:
            if slot.match is None:
                continue
            char_id = slot.match.char_id
            if char_id in seen:
                continue
            seen.add(char_id)
            out.append(char_id)
        return out

    @property
    def accepted_slots(self) -> list[SlotMatch]:
        return [slot for slot in self.slots if slot.accepted]

    @property
    def uncertain_slots(self) -> list[SlotMatch]:
        return [slot for slot in self.slots if not slot.accepted]

    @property
    def team_no(self) -> int:
        return self.team_index + 1


@dataclass(slots=True)
class Recognition:
    teams: list[TeamResult]
    library_count: int
    threshold: float
    min_margin: float = DEFAULT_MIN_MARGIN
    elapsed: float = 0.0
    image_size: tuple[int, int] = (0, 0)
    note: str = ""

    # ---- 兼容旧接口（main.py / selftest.py 里用过这些名字）----
    @property
    def slots(self) -> list[SlotMatch]:
        return [slot for team in self.teams for slot in team.slots]

    @property
    def ids(self) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        for slot in self.slots:
            if slot.match is None:
                continue
            if slot.match.char_id in seen:
                continue
            seen.add(slot.match.char_id)
            out.append(slot.match.char_id)
        return out

    @property
    def accepted_count(self) -> int:
        return sum(1 for slot in self.slots if slot.accepted)

    @property
    def uncertain_slots(self) -> list[SlotMatch]:
        return [slot for slot in self.slots if not slot.accepted]

    @property
    def grid(self) -> str:
        if not self.teams:
            return "未定位到头像框"
        return f"{len(self.teams)} 队 · " + "/".join(str(len(t.slots)) for t in self.teams)

    @property
    def team_ids(self) -> list[list[int]]:
        return [team.ids for team in self.teams]

    @property
    def best_slot(self) -> SlotMatch | None:
        best: SlotMatch | None = None
        for slot in self.slots:
            if slot.match is None:
                continue
            if best is None or slot.match.score > best.match.score:  # type: ignore[union-attr]
                best = slot
        return best


def _cut(image: Image.Image, box: Sequence[float], size: tuple[int, int] = BAND_SIZE) -> np.ndarray:
    width, height = image.size
    left = int(width * box[0])
    top = int(height * box[1])
    right = int(width * box[2])
    bottom = int(height * box[3])
    if right - left < 4 or bottom - top < 4:
        right, bottom = left + 4, top + 4
    crop = image.crop((left, top, right, bottom))
    return np.asarray(crop.convert("RGB").resize(size, Image.BILINEAR), dtype=np.float32)


def _normalize(mat: np.ndarray) -> np.ndarray:
    """按行做零均值 / 单位范数，之后点积就是归一化互相关。"""

    flat = mat.reshape(mat.shape[0], -1).astype(np.float32)
    flat -= flat.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(flat, axis=1, keepdims=True)
    np.maximum(norm, 1e-6, out=norm)
    flat /= norm
    return flat


def _blur_bands(bands: np.ndarray, sigma: float) -> np.ndarray:
    """对一批 (n, h, w, 3) 的裁切做高斯低通；sigma<=0 或没有 cv2 时原样返回。"""

    if sigma <= 0 or cv2 is None or bands.size == 0:
        return bands.reshape(bands.shape[0], -1)
    height, width = BAND_SIZE[1], BAND_SIZE[0]
    flat = bands.reshape(bands.shape[0], height, width, 3)
    out = np.empty((bands.shape[0], height * width * 3), dtype=np.float32)
    for index in range(bands.shape[0]):
        out[index] = cv2.GaussianBlur(flat[index], (0, 0), sigma).reshape(-1)
    return out


def query_bands(
    image: Image.Image,
    boxes: Sequence[Sequence[float]],
    *,
    sigma: float = QUERY_BLUR,
) -> np.ndarray:
    """把若干裁切转成（已归一化的）查询矩阵。"""

    bands = np.asarray([_cut(image, box) for box in boxes])
    return _normalize(_blur_bands(bands, sigma))


def refine_crops(box: Sequence[float]) -> list[tuple[float, float, float, float]]:
    """以某个粗裁切为中心做 ±1 步的局部细化。"""

    xi0, top0, _xr0, bottom0 = box
    out: list[tuple[float, float, float, float]] = []
    for dxi in (-REFINE_STEP_X, 0.0, REFINE_STEP_X):
        for dtop in (-REFINE_STEP_Y, 0.0, REFINE_STEP_Y):
            for dbottom in (-REFINE_STEP_Y, 0.0, REFINE_STEP_Y):
                xi = min(max(0.0, xi0 + dxi), 0.32)
                top = min(max(0.0, top0 + dtop), 0.40)
                bottom = min(max(0.50, bottom0 + dbottom), 0.95)
                out.append((xi, top, 1.0 - xi, bottom))
    return out


def _char_id_of(filename: str) -> int:
    stem = Path(filename).stem
    if len(stem) >= 4 and stem[:4].isdigit():
        return int(stem[:4])
    return 0


class AvatarLibrary:
    """icon/unit 头像参考库。

    ``avatars_dir`` 里是 ``<4位角色id><2位稀有度>.webp`` 的 128px 方图。
    加载只做一次（773 张约 0.5 秒），之后所有识别共用同一份归一化矩阵。
    """

    def __init__(
        self,
        avatars_dir: str | Path,
        *,
        cache_path: str | Path | None = None,
        allowed_ids: Iterable[int] | None = None,
    ) -> None:
        self.avatars_dir = Path(avatars_dir)
        self.cache_path = Path(cache_path) if cache_path else None
        self.allowed_ids = {int(value) for value in allowed_ids} if allowed_ids else None
        self.filenames: list[str] = []
        self.char_ids: np.ndarray = np.zeros((0,), dtype=np.int32)
        self.features: np.ndarray | None = None      # (N, D) 已归一化
        self._paths: dict[str, Path] = {}
        self._char_rows: dict[int, list[int]] = {}
        self._loaded = False
        self._load_seconds = 0.0

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.filenames)

    @property
    def character_count(self) -> int:
        return len(self._char_rows)

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def load_seconds(self) -> float:
        return self._load_seconds

    def path_for(self, filename: str) -> Path | None:
        return self._paths.get(filename)

    def rows_for(self, char_id: int) -> list[int]:
        return self._char_rows.get(int(char_id), [])

    # ------------------------------------------------------------------
    def load(self, *, force: bool = False) -> int:
        if self._loaded and not force:
            return len(self.filenames)
        started = time.monotonic()
        features: list[np.ndarray] = []
        filenames: list[str] = []
        paths: dict[str, Path] = {}
        char_rows: dict[int, list[int]] = {}

        try:
            files = sorted(
                path
                for path in self.avatars_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            )
        except OSError:
            files = []

        for path in files:
            char_id = _char_id_of(path.name)
            if char_id <= 0:
                continue
            if self.allowed_ids is not None and char_id not in self.allowed_ids:
                continue
            try:
                with Image.open(path) as image:
                    image.load()
                    band = _cut(image, REF_CROP)
            except Exception as exc:  # noqa: BLE001 - 单张坏图不该拖垮整个库
                logger.warning("PCRBot 读取头像失败，已跳过 %s：%s", path.name, type(exc).__name__)
                continue
            char_rows.setdefault(char_id, []).append(len(filenames))
            features.append(band)
            filenames.append(path.name)
            paths[path.name] = path

        if features:
            self.features = _normalize(_blur_bands(np.asarray(features), REF_BLUR))
        else:
            self.features = None
        self.filenames = filenames
        self.char_ids = np.asarray(
            [_char_id_of(name) for name in filenames], dtype=np.int32
        )
        self._paths = paths
        self._char_rows = char_rows
        self._loaded = True
        self._load_seconds = time.monotonic() - started
        logger.info(
            "PCRBot 头像参考库已加载：%d 张，覆盖 %d 个角色，耗时 %.2f 秒",
            len(filenames),
            len(char_rows),
            self._load_seconds,
        )
        return len(filenames)

    async def load_async(self) -> int:
        import asyncio

        return await asyncio.to_thread(self.load)


class ImageRecognizer:
    """输入一张竞技场截图，按队输出角色。"""

    def __init__(
        self,
        library: AvatarLibrary,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        min_margin: float = DEFAULT_MIN_MARGIN,
        use_clip: bool = False,
        top_k: int = 3,
    ) -> None:
        self.library = library
        self.threshold = max(0.3, min(0.99, float(threshold)))
        self.min_margin = max(0.0, min(0.5, float(min_margin)))
        # use_clip 保留参数只为兼容旧配置；现在完全不用 CLIP（比 NCC 差很多）。
        self.use_clip = False
        self.top_k = max(1, min(10, int(top_k)))

    # ------------------------------------------------------------------
    def _scores_for_boxes(
        self,
        frame: Image.Image,
        boxes: Sequence[Sequence[float]],
        rows: np.ndarray,
    ) -> np.ndarray:
        """一组裁切 × 一组参考行 → (len(boxes), len(rows)) 的 NCC。"""

        assert self.library.features is not None
        query = query_bands(frame, boxes)
        return query @ self.library.features[rows].T

    def _match_frame(self, frame: Image.Image) -> tuple[list[Match], dict[str, Any]]:
        library = self.library
        assert library.features is not None
        feature_count = library.features.shape[0]

        # --- 第一遍：粗网格 -------------------------------------------------
        query = query_bands(frame, COARSE_CROPS)
        coarse = query @ library.features.T          # (n_coarse, N)
        per_icon = coarse.max(axis=0)
        best_crop = coarse.argmax(axis=0)

        order = np.argsort(-per_icon)
        shortlist: list[int] = []
        seen: set[int] = set()
        for index in order:
            char_id = int(library.char_ids[index])
            if char_id in seen:
                continue
            seen.add(char_id)
            shortlist.append(int(index))
            if len(shortlist) >= SHORTLIST:
                break

        # --- 第二遍：对候选做局部细化 ---------------------------------------
        refined: dict[int, float] = {}
        for index in shortlist:
            boxes = refine_crops(COARSE_CROPS[int(best_crop[index])])
            scores = self._scores_for_boxes(frame, boxes, np.asarray([index]))
            refined[index] = float(scores.max())

        # --- 按角色聚合 -----------------------------------------------------
        best_by_char: dict[int, tuple[float, int]] = {}
        for index, score in refined.items():
            char_id = int(library.char_ids[index])
            current = best_by_char.get(char_id)
            if current is None or score > current[0]:
                best_by_char[char_id] = (score, index)

        ranked = sorted(best_by_char.items(), key=lambda item: -item[1][0])
        matches: list[Match] = []
        for position, (char_id, (score, index)) in enumerate(ranked[: max(self.top_k, 3)]):
            runner_up_score = ranked[position + 1][1][0] if position + 1 < len(ranked) else 0.0
            runner_up_id = ranked[position + 1][0] if position + 1 < len(ranked) else 0
            margin = score - runner_up_score
            accepted = score >= self.threshold and margin >= self.min_margin
            matches.append(
                Match(
                    char_id=char_id,
                    filename=library.filenames[index],
                    score=score,
                    second_char_id=runner_up_id,
                    second_score=runner_up_score,
                    margin=margin,
                    accepted=accepted,
                )
            )
        diagnostics = {
            "icons": feature_count,
            "shortlist": len(shortlist),
            "coarse_best": float(per_icon.max()) if per_icon.size else 0.0,
        }
        return matches, diagnostics

    # ------------------------------------------------------------------
    def _coarse_best(self, frame: Image.Image) -> float:
        """只跑粗网格，返回「最像的那个 icon」的分数，用来比较不同切法。"""

        assert self.library.features is not None
        query = query_bands(frame, COARSE_CROPS)
        return float((query @ self.library.features.T).max())

    def _pick_fallback_layout(self, image: Image.Image) -> list[list[dict[str, Any]]]:
        """图里没有外框时，试 5/4/3/2/1 等分，用粗匹配分数挑最靠谱的一种。

        只裁了头像那一条的图，宽高比会被上面的标题带偏（5 格算成 4 格很常见），
        所以交给内容来判断，而不是只看比例。
        """

        best_columns = 0
        best_value: tuple[int, float] = (-1, -1.0)
        for rows in portrait_detect.fallback_layouts(image.size):
            scores = [
                self._coarse_best(image.crop((x, y, x + bw, y + bh)))
                for row in rows
                for (x, y, bw, bh, _area) in row
            ]
            if not scores:
                continue
            value = (
                sum(1 for score in scores if score >= 0.80),
                sum(scores) / len(scores),
            )
            if value > best_value:
                best_value = value
                best_columns = len(rows[0]) if rows else 0
        if not best_columns:
            return []
        # 复用 detect_portraits 的兜底分支拿统一的 dict 结构
        return portrait_detect.detect_portraits(
            image,
            allow_fallback=True,
            _forced_columns=best_columns,
        )

    # ------------------------------------------------------------------
    def recognize(self, image: Image.Image, *, max_ids: int = 5) -> Recognition:
        started = time.monotonic()
        if image is None:
            return Recognition(teams=[], library_count=len(self.library),
                               threshold=self.threshold, note="没有图片")
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self.library.features is None:
            self.library.load()

        teams_raw = portrait_detect.detect_portraits(image, allow_fallback=False)
        if not teams_raw:
            teams_raw = self._pick_fallback_layout(image)
        teams: list[TeamResult] = []
        for team_index, row in enumerate(teams_raw):
            team = TeamResult(team_index=team_index)
            for slot_index, slot in enumerate(row):
                box = tuple(slot["box"])            # type: ignore[arg-type]
                crop_box = tuple(slot["crop_box"])  # type: ignore[arg-type]
                frame = image.crop(box)
                matches, _diag = self._match_frame(frame)
                best = matches[0] if matches else None
                team.slots.append(
                    SlotMatch(
                        box=box,
                        crop_box=crop_box,
                        team_index=team_index,
                        slot_index=slot_index,
                        match=best,
                        alternatives=matches[1:],
                        accepted=bool(best and best.accepted),
                    )
                )
            teams.append(team)

        # 一队里不会有重复角色；真的撞了说明有格子认错，把重复的那个降级成「不确定」。
        for team in teams:
            seen: set[int] = set()
            for slot in team.slots:
                if not slot.accepted or slot.match is None:
                    continue
                if slot.match.char_id in seen:
                    slot.accepted = False
                    slot.match.accepted = False
                    continue
                seen.add(slot.match.char_id)

        elapsed = time.monotonic() - started
        return Recognition(
            teams=teams,
            library_count=len(self.library),
            threshold=self.threshold,
            min_margin=self.min_margin,
            elapsed=elapsed,
            image_size=image.size,
            note="" if teams else "没找到头像框",
        )


__all__ = [
    "AvatarLibrary",
    "ImageRecognizer",
    "Match",
    "Recognition",
    "SlotMatch",
    "TeamResult",
    "COARSE_CROPS",
    "BAND_SIZE",
    "REF_CROP",
    "REF_BLUR",
    "QUERY_BLUR",
    "DEFAULT_THRESHOLD",
    "DEFAULT_MIN_MARGIN",
    "detect_portraits",
]

# 方便调用方直接拿定位结果（validate_image.py / 调试用）。
detect_portraits = portrait_detect.detect_portraits
