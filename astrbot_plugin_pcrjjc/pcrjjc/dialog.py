"""查不到作业时的追问状态机：排除角色法 / 替换角色法。

只做「解析用户这句话是什么意思」，不碰网络、不碰 AstrBot，方便单测。
调用方（main.py）负责维护 `Dialog` 实例、查作业、发消息。

位置编号约定（用户明确过的，别改）：
    截图从左到右是「后卫 → 前卫」；1 号位 = 最右边 = 前卫，5 号位 = 最左边 = 后卫。
    所以 team 列表按截图从左到右存（index 0 最左），位置号 = len(team) - index。
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

# 对话阶段
CHOOSE = "choose"      # 等用户回 1 / 2
EXCLUDE = "exclude"    # 等用户说排除谁（文字或截图）
REPLACE = "replace"    # 等用户说把谁换成谁（只接受文字）

CANONICAL_TEAM_SIZE = 5

# 主动触发：用户看完作业不满意，可以再喊一声进入排除/替换追问。
# 只在「上一次对话确实在查作业」时才生效（main.py 里做时间窗校验）。
ACTIVE_EXCLUDE_WORDS = ("竞技场阵容排除", "阵容排除", "竞技场排除")
ACTIVE_REPLACE_WORDS = ("竞技场阵容替换", "阵容替换", "竞技场替换")

CANCEL_WORDS = (
    "取消", "算了", "不查了", "不用了", "不查", "退出", "结束", "停下", "停",
    "不要了", "放弃", "没事了", "走了", "散了",
)

_PUNCT = " \t\r\n，。、；：！？…~～·,.;:!?()（）[]【】<>《》\"'“”‘’"
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}

_REPLACE_VERBS = ("替换成", "替换为", "代替为", "换成", "换为", "改成", "改为", "→", "->", "=>", "＝>")
_EXCLUDE_VERBS = ("排除掉", "排除", "剔除", "去掉", "剔掉", "拿掉", "ban掉", "ban")
_POS_TOKEN = r"(?P<pos>[1-5一二两三四五])\s*号?\s*位?"
_POS_TOKEN_MATCH = re.compile(_POS_TOKEN)
_REPLACE_RE = re.compile(
    r"^(?:请|麻烦|帮我)?\s*(?:把|将)?\s*(?P<who>.+?)\s*(?:"
    + "|".join(re.escape(verb) for verb in _REPLACE_VERBS)
    + r")\s*(?P<new>.+)$"
)


def _squash(text: object) -> str:
    """去掉所有空白和标点，保留内容用于比对；顺带把全角数字/字母转半角。"""

    value = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(ch for ch in value if ch not in _PUNCT)


def _display(text: object) -> str:
    """去掉首尾标点/空白，保留中间内容用于角色名。"""

    value = unicodedata.normalize("NFKC", str(text or ""))
    return value.strip().strip(_PUNCT).strip()


def _num(token: str) -> int | None:
    token = _squash(token)
    if not token:
        return None
    if token.isdigit():
        try:
            return int(token)
        except ValueError:
            return None
    return _CN_NUM.get(token)


# ----------------------------------------------------------------------
# 位置换算
# ----------------------------------------------------------------------
def position_of(team_len: int, index: int) -> int:
    """截图从左到右的下标 → 用户说的位置号（1 = 最右 = 前卫）。"""

    return max(1, int(team_len) - int(index))


def index_of_position(team_len: int, position: int) -> int | None:
    """位置号 → 截图从左到右的下标；越界返回 None。"""

    if not 1 <= int(position) <= int(team_len):
        return None
    return int(team_len) - int(position)


def positions_line(names: Sequence[str]) -> str:
    """「① 克总（前卫）② … 」这种给用户看的位置对照。"""

    icon = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"]
    parts: list[str] = []
    for index, name in enumerate(names):
        mark = icon[index] if index < len(icon) else f"{index + 1}."
        parts.append(f"{mark}{name}")
    return " ".join(parts)


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def is_cancel(text: object) -> bool:
    value = _squash(text)
    if not value:
        return False
    if value in CANCEL_WORDS:
        return True
    return any(value == _squash(word) for word in CANCEL_WORDS)


def parse_choice(text: object) -> str | None:
    """解析「1/2」选择，认不出返回 None。"""

    raw = _display(text)
    value = _squash(raw)
    if not value:
        return None
    if value in {"1", "1号", "一", "选1", "选一", "方案1", "第一个", "1方案", "第一个方案"}:
        return "1"
    if value in {"2", "2号", "二", "两", "选2", "选二", "方案2", "第二个", "2方案", "第二个方案"}:
        return "2"
    # 「排除吧」「用替换」这类口语
    if any(word in value for word in ("排除", "剔掉", "剔除", "去掉一个")) and not any(
        word in value for word in ("换", "替换")
    ):
        return "1"
    if any(word in value for word in ("替换", "换一个", "换人")) and "排除" not in value:
        return "2"
    return None


def active_trigger(text: object) -> str | None:
    """识别主动触发词，返回要直接进入的阶段（EXCLUDE / REPLACE）。"""

    value = _squash(text)
    if not value:
        return None
    for word in ACTIVE_EXCLUDE_WORDS:
        token = _squash(word)
        if value == token or value.startswith(token):
            return EXCLUDE
    for word in ACTIVE_REPLACE_WORDS:
        token = _squash(word)
        if value == token or value.startswith(token):
            return REPLACE
    return None


@dataclass(slots=True)
class ExcludeRequest:
    """用户要排除的对象：角色名或者位置号（二选一）。"""

    name: str = ""
    position: int | None = None

    @property
    def empty(self) -> bool:
        return not self.name and self.position is None


def parse_exclude(text: object) -> ExcludeRequest:
    raw = _display(text)
    if not raw:
        return ExcludeRequest()
    value = _squash(raw)
    # 位置号：「3」「3号位」「三号」
    direct = _POS_TOKEN_MATCH.fullmatch(value)
    if direct:
        position = _num(direct.group("pos"))
        if position:
            return ExcludeRequest(position=position)
    # 去掉「排除/去掉」这类动词后剩下角色名
    stripped = raw
    for verb in _EXCLUDE_VERBS:
        if stripped.startswith(verb):
            stripped = stripped[len(verb):]
            break
    stripped = _display(stripped)
    # 「排除3号位」
    pos = _POS_TOKEN_MATCH.fullmatch(_squash(stripped))
    if pos:
        position = _num(pos.group("pos"))
        if position:
            return ExcludeRequest(position=position)
    return ExcludeRequest(name=stripped)


@dataclass(slots=True)
class ReplaceRequest:
    """「把 A 换成 B」/「3 号位换成 B」。"""

    who: str = ""
    position: int | None = None
    new: str = ""

    @property
    def empty(self) -> bool:
        return not self.new


def parse_replace(text: object) -> ReplaceRequest:
    raw = _display(text)
    if not raw:
        return ReplaceRequest()
    match = _REPLACE_RE.match(raw)
    if not match:
        return ReplaceRequest()
    who = _display(match.group("who"))
    new = _display(match.group("new"))
    if not new:
        return ReplaceRequest()
    pos = _POS_TOKEN_MATCH.fullmatch(_squash(who))
    if pos:
        position = _num(pos.group("pos"))
        return ReplaceRequest(who="", position=position, new=new)
    # 「把1号位换成xx」里 who 可能带「位置」字样
    cleaned = _squash(who).replace("号位", "").replace("位", "")
    if cleaned in {"1", "2", "3", "4", "5"}:
        return ReplaceRequest(who="", position=int(cleaned), new=new)
    return ReplaceRequest(who=who, new=new)


# ----------------------------------------------------------------------
# 会话状态
# ----------------------------------------------------------------------
@dataclass(slots=True)
class Dialog:
    """一次追问的上下文。team 按截图从左到右存（左=后卫）。"""

    session: str
    sender: str
    stage: str = CHOOSE
    team: list[int] = field(default_factory=list)
    label: str = ""
    rounds: int = 0
    timeout_sec: float = 120.0
    deadline: float = 0.0
    token: int = 0
    notes: list[str] = field(default_factory=list)
    excluded: list[int] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.deadline = time.monotonic() + max(0.0, self.timeout_sec)

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) >= self.deadline

    def left_sec(self, now: float | None = None) -> int:
        remain = self.deadline - (now if now is not None else time.monotonic())
        return max(0, math.ceil(remain))

    def left_text(self, now: float | None = None) -> str:
        remain = self.left_sec(now)
        if remain >= 60:
            return f"{remain // 60} 分 {remain % 60} 秒"
        return f"{remain} 秒"

    def positions(self) -> list[tuple[int, int]]:
        """[(位置号, team 下标)]，从 1 号位（最右）开始。"""

        total = len(self.team)
        return [(position_of(total, index), index) for index in range(total)]


def team_after_exclude(team: Sequence[int], target: int) -> list[int]:
    return [char for char in team if char != target]


def team_after_replace(team: Sequence[int], index: int, new_id: int) -> list[int]:
    result = list(team)
    if 0 <= index < len(result):
        result[index] = int(new_id)
    return result
