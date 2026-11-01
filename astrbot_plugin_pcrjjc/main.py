"""PCRBot：公主连结 Re:Dive 竞技场作业查询。

文字：/作业 布丁 克总
图片：/作业 + 竞技场截图，或直接发图（image_auto）
数据：角色/别称来自内置数据，头像来自 redive.estertion.win，作业来自 pcrdfans。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image as AstrImage
from astrbot.api.message_components import Node, Nodes, Reply
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from PIL import Image, ImageOps

from .pcrjjc import dialog as pcr_dialog
from .pcrjjc import images as pcr_images
from .pcrjjc import pcr_data
from .pcrjjc.arena_api import (
    AUTH_HELP,
    REGION_NAMES,
    ArenaAuthError,
    ArenaCache,
    ArenaClient,
    ArenaError,
    ArenaNetworkError,
)
from .pcrjjc.card_render import pick_display_name, render_job_card, sort_entries
from .pcrjjc.paths import resolve_data_dir, seed_missing

PLUGIN_NAME = "astrbot_plugin_pcrjjc"
DATA_DIR_NAME = "pcrjjc"
PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = resolve_data_dir(DATA_DIR_NAME)
DEFAULT_ICON_SOURCE = "https://redive.estertion.win/icon/unit/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
MAX_QUERY_IDS = 5
UPDATE_CONCURRENCY = 8
TEMP_PREFIX = "pcrbot_"
MAX_CARD_ITEMS = 8

DEFAULT_CONFIG: dict[str, Any] = {
    "auth_key": "",
    "region": 1,
    "max_results": 5,
    "sort_mode": "ratio",
    "show_names": "slang",
    "enable_image": True,
    "image_auto": True,
    "image_threshold": 0.70,
    "use_clip": False,
    "keywords": ["作业"],
    "text_mode": False,
    "card_max_items": 8,
    "icon_source": DEFAULT_ICON_SOURCE,
    "auto_update_days": 7,
    "request_timeout": 15,
    "allow_group": True,
    "show_likes": True,
    "show_time": True,
    "use_ai_names": True,
    "browser_endpoint": "",
    "dialog_timeout_min": 2,
    "dialog_step_timeout_min": 2,
    "dialog_max_rounds": 6,
    "dialog_active_minutes": 10,
}

VALID_SORT_MODES = {"ratio", "time", "relevance"}
VALID_SHOW_NAMES = {"none", "official", "slang"}


@dataclass(slots=True)
class QueryOutcome:
    """一次查询的中间结果，供文字兜底和图片卡片共用。"""

    def_ids: list[int] = field(default_factory=list)
    entries: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cache_note: str = ""
    error: str = ""
    title: str = "作业查询"

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(slots=True)
class ImageResult:
    """一张截图的识图结果：可能有多队，每队一条 QueryOutcome。"""

    outcomes: list[QueryOutcome] = field(default_factory=list)
    recognition: Any = None
    team_summary: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.outcomes)


def _iter_images(
    components: Iterable[Any] | None,
    *,
    include_reply: bool = False,
    _seen: set[int] | None = None,
) -> Iterator[AstrImage]:
    """遍历消息链中的图片；可选递归引用消息。"""

    if not components:
        return
    chain = getattr(components, "chain", components)
    if _seen is None:
        _seen = set()
    for component in chain:
        marker = id(component)
        if marker in _seen:
            continue
        _seen.add(marker)
        if isinstance(component, AstrImage):
            if component.url or component.file or getattr(component, "path", None):
                yield component
        elif include_reply and isinstance(component, Reply):
            yield from _iter_images(
                getattr(component, "chain", None),
                include_reply=True,
                _seen=_seen,
            )
        elif isinstance(component, Node):
            yield from _iter_images(
                getattr(component, "content", None),
                include_reply=include_reply,
                _seen=_seen,
            )
        elif isinstance(component, Nodes):
            for node in getattr(component, "nodes", None) or []:
                yield from _iter_images(
                    getattr(node, "content", None),
                    include_reply=include_reply,
                    _seen=_seen,
                )


class HasImageFilter(filter.CustomFilter):
    """只让带图片的消息进入自动识图 handler（没装视觉依赖时整条路径关闭）。"""

    vision_ok: Any = None

    def filter(self, event: AstrMessageEvent, cfg: Any) -> bool:
        if not getattr(type(self), "vision_ok", lambda: True)():
            return False
        try:
            return any(_iter_images(event.get_messages(), include_reply=False))
        except Exception:
            return False


class HasKeywordFilter(filter.CustomFilter):
    """只让包含触发关键词的消息进入自然语言 handler。"""

    keywords_provider: Any = None

    def filter(self, event: AstrMessageEvent, cfg: Any) -> bool:
        provider = type(self).keywords_provider
        if provider is None:
            return False
        try:
            text = event.get_message_str().casefold()
            keywords = provider() or []
            return any(str(keyword).casefold() in text for keyword in keywords)
        except Exception:
            return False


class HasDialogFilter(filter.CustomFilter):
    """有未结束的追问会话时才进入 dialog_reply（含图也能接，用来指定角色）。"""

    dialog_provider: Any = None

    def filter(self, event: AstrMessageEvent, cfg: Any) -> bool:
        provider = type(self).dialog_provider
        if provider is None:
            return False
        try:
            return provider(event) is not None
        except Exception:
            return False


class HasActiveTriggerFilter(filter.CustomFilter):
    """主动触发「阵容排除 / 阵容替换」——只有刚查过作业时才放行。"""

    trigger_provider: Any = None

    def filter(self, event: AstrMessageEvent, cfg: Any) -> bool:
        provider = type(self).trigger_provider
        if provider is None:
            return False
        try:
            return provider(event) is not None
        except Exception:
            return False


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _short(text: Any, limit: int = 160) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


@register(
    PLUGIN_NAME,
    "公主连结竞技场作业自助查询",
    "公主连结竞技场作业查询：文字 / 图片 → 作业队伍，支持别称与本地缓存。",
    "v0.1.0",
)
class PCRBot(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.config: dict[str, Any] = dict(config or {})
        self.data_dir: Path = DEFAULT_DATA_DIR
        self.characters_path: Path = self.data_dir / "characters.json"
        self.avatars_dir: Path = self.data_dir / "avatars"
        self.tmp_dir: Path = self.data_dir / "tmp"
        self.meta_path: Path = self.data_dir / "meta.json"
        self.cache_path: Path = self.data_dir / "arena_cache.json"
        self.stats_path: Path = self.data_dir / "stats.json"
        self.prints_cache_path: Path = self.data_dir / "avatar_prints.json"
        self.units_path: Path = self.data_dir / "units_site.json"
        self.aliases_extra_path: Path = self.data_dir / "aliases_extra.json"

        self.index: pcr_data.CharacterIndex | None = None
        self.vision_available = True  # 装不上 numpy/opencv 时降级为纯文字
        self.library = None
        self.arena_cache: ArenaCache | None = None
        self._meta: dict[str, Any] = {}
        self._stats: dict[str, Any] = {}
        self._update_lock = asyncio.Lock()
        self._library_lock = asyncio.Lock()
        self._auto_task: asyncio.Task[None] | None = None
        self._initialized = False
        self._keyword_conflicts: list[str] = []
        self._vision_mods: dict[str, Any] | None = None
        HasImageFilter.vision_ok = lambda: bool(self._vision() is not None)
        HasKeywordFilter.keywords_provider = self._keywords
        # 查不到作业时的追问会话（按 unified_msg_origin 隔离）
        self._dialogs: dict[str, pcr_dialog.Dialog] = {}
        self._dialog_tasks: dict[str, asyncio.Task[None]] = {}
        # 触发追问的那条消息自己不能被当成「回答」（同一句 /作业 会被
        # dialog_reply 再看到一次，记住 message_id 直接跳过）。
        self._dialog_ignore: dict[str, Any] = {}
        self._dialog_seq = 0
        # 上一次查过哪个防守队：主动触发（竞技场阵容排除/替换）时用来确认
        # 「刚才确实在查作业」，免得在闲聊里被误触。
        self._last_team: dict[str, tuple[float, list[int], str]] = {}
        HasDialogFilter.dialog_provider = self._active_dialog
        HasActiveTriggerFilter.trigger_provider = self._active_trigger_mode

    # ------------------------------------------------------------------
    # 生命周期 / 配置
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        try:
            try:
                data_dir = Path(StarTools.get_data_dir(DATA_DIR_NAME))
            except Exception:
                data_dir = DEFAULT_DATA_DIR
            self.data_dir = data_dir
            self.characters_path = data_dir / "characters.json"
            self.avatars_dir = data_dir / "avatars"
            self.tmp_dir = data_dir / "tmp"
            self.meta_path = data_dir / "meta.json"
            self.cache_path = data_dir / "arena_cache.json"
            self.stats_path = data_dir / "stats.json"
            self.prints_cache_path = data_dir / "avatar_prints.json"
            self.units_path = data_dir / "units_site.json"
            self.aliases_extra_path = data_dir / "aliases_extra.json"
            self.avatars_dir.mkdir(parents=True, exist_ok=True)
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            # 第一次跑时把包内的角色表/别称表补进数据目录（不覆盖已有文件）
            copied = seed_missing(data_dir)
            if copied:
                logger.info("pcrjjc：已初始化数据文件 %s", ", ".join(copied))
            self._load_meta()
            self._load_stats()
            self._reload_characters(seed=True)
            self.arena_cache = ArenaCache(self.cache_path)
            self.library = self._new_library(
                self.avatars_dir,
                cache_path=self.prints_cache_path,
                allowed_ids=set(self.index.by_uid4) if self.index else None,
            )
            self._initialized = True
            self._check_keyword_conflicts()
            logger.info(
                f"PCRBot 已加载：角色 {len(self.index) if self.index else 0} 个，"
                f"头像目录 {self.avatars_dir}"
            )
            # 始终起后台巡检；开机不急着重型更新，先等 5 秒让 AstrBot 启动完。
            self._auto_task = asyncio.create_task(self._auto_update_loop())
        except Exception as exc:  # noqa: BLE001
            logger.error(f"PCRBot 初始化失败：{type(exc).__name__}: {exc}")
            # 初始化失败也不抛出，避免影响 AstrBot 启动。

    def _vision(self) -> dict[str, Any] | None:
        """按需导入视觉相关模块；缺 numpy/opencv 时返回 None（纯文字模式）。"""

        if self._vision_mods is not None:
            return self._vision_mods or None
        try:
            from .pcrjjc.image_match import AvatarLibrary, ImageRecognizer

            self._vision_mods = {"lib": AvatarLibrary, "rec": ImageRecognizer}
            self.vision_available = True
        except Exception as exc:  # noqa: BLE001 - ImportError / DLL 缺失都算
            logger.warning(
                "pcrjjc：没装 numpy/opencv-python，截图识别不可用（文字查询不受影响）：%s",
                exc,
            )
            self._vision_mods = {}
            self.vision_available = False
        return self._vision_mods or None

    def _new_library(self, *args: Any, **kwargs: Any) -> Any:
        mods = self._vision()
        if not mods:
            return None
        return mods["lib"](*args, **kwargs)

    def _new_recognizer(self, *args: Any, **kwargs: Any) -> Any:
        mods = self._vision()
        if not mods:
            return None
        return mods["rec"](*args, **kwargs)

    async def terminate(self) -> None:
        if self._auto_task is not None:
            self._auto_task.cancel()
            try:
                await self._auto_task
            except (asyncio.CancelledError, Exception):
                pass
        for key in list(self._dialogs):
            self._drop_dialog(key)
        logger.info("PCRBot 已停止。")

    def _cfg(self, key: str) -> Any:
        try:
            value = self.config.get(key, DEFAULT_CONFIG.get(key))
        except Exception:
            return DEFAULT_CONFIG.get(key)
        return DEFAULT_CONFIG.get(key) if value is None else value

    def _cfg_str(self, key: str, default: str = "") -> str:
        value = self._cfg(key)
        text = str(value).strip()
        return text if text else default

    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        value = self._cfg(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on", "y", "是", "开"}:
                return True
            if text in {"0", "false", "no", "off", "n", "否", "关"}:
                return False
        return default

    def _cfg_int(self, key: str, low: int, high: int, default: int) -> int:
        try:
            value = int(float(str(self._cfg(key)).strip()))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _cfg_float(self, key: str, low: float, high: float, default: float) -> float:
        try:
            value = float(str(self._cfg(key)).strip())
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _region(self) -> int:
        value = self._cfg_int("region", 0, 9, 1)
        return value if value in (0, 1, 2, 3) else 0

    def _api_region(self) -> int:
        # /units 只有 cn/us；region=0 的「全部」落到国服查询；region=3
        # 仍尝试日服接口，虽然角色表只能按全部展示。
        region = self._region()
        if region in (1, 2, 3):
            return region
        return 1

    def _max_results(self) -> int:
        return self._cfg_int("max_results", 1, 10, 5)

    def _request_timeout(self) -> float:
        return self._cfg_float("request_timeout", 5.0, 60.0, 15.0)

    def _image_threshold(self) -> float:
        return self._cfg_float("image_threshold", 0.5, 0.98, 0.70)

    def _sort_mode(self) -> str:
        value = str(self._cfg("sort_mode") or "ratio").strip().lower()
        return value if value in VALID_SORT_MODES else "ratio"

    def _show_names(self) -> str:
        value = str(self._cfg("show_names") or "slang").strip().lower()
        return value if value in VALID_SHOW_NAMES else "slang"

    def _card_max_items(self) -> int:
        return self._cfg_int("card_max_items", 1, MAX_CARD_ITEMS, MAX_CARD_ITEMS)

    def _text_mode(self) -> bool:
        return self._cfg_bool("text_mode", False)

    def _keywords(self) -> list[str]:
        value = self._cfg("keywords")
        raw: list[str] = []
        if isinstance(value, str):
            raw = re.split(r"[\s,，、]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw = [str(item) for item in value]
        keywords: list[str] = []
        for item in raw:
            keyword = str(item or "").strip().lstrip("/\\").strip()
            if keyword and keyword not in keywords:
                keywords.append(keyword)
        return keywords[:10] or ["作业"]

    def _has_keyword(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        return any(keyword.casefold() in lowered for keyword in self._keywords())

    def _strip_keywords(self, text: str) -> str:
        value = str(text or "")
        for keyword in sorted(self._keywords(), key=len, reverse=True):
            value = re.sub(re.escape(keyword), " ", value, flags=re.IGNORECASE)
        return re.sub(r"[\s,，、+＋:：]+", " ", value).strip()

    def _name_for(self, char_id: int, mode: str) -> str:
        if self.index is None:
            return str(char_id)
        character = self.index.character(char_id)
        if character is None:
            return str(char_id)
        if mode == "none":
            return ""
        if mode == "official":
            if not self._cfg_bool("use_ai_names", True):
                jp = self._ja_name_for(character)
                if jp:
                    return jp
            return self._official_name_for(char_id)
        picked = pick_display_name(character.name, character.aliases, "slang")
        if picked and picked != character.name:
            return picked
        return self._official_name_for(char_id)

    @staticmethod
    def _ja_name_for(character: Any) -> str:
        """从别称里挑一个含假名的名字（AI 补名前的日文原名）。"""
        for alias in [character.name, *(character.aliases or [])]:
            text = str(alias or "")
            if any("\u3040" <= ch <= "\u30ff" for ch in text):
                return text
        return ""

    def _official_name_for(self, char_id: int) -> str:
        if self.index is None:
            return str(char_id)
        character = self.index.character(char_id)
        if character is None:
            return str(char_id)
        if not self._cfg_bool("use_ai_names", True):
            jp = self._ja_name_for(character)
            if jp:
                return jp
        return character.display_name

    def _icon_source(self) -> str:
        source = self._cfg_str("icon_source", DEFAULT_ICON_SOURCE)
        if not source:
            source = DEFAULT_ICON_SOURCE
        if not source.startswith(("http://", "https://")):
            source = DEFAULT_ICON_SOURCE
        return source if source.endswith("/") else source + "/"

    def _allow_group(self, event: AstrMessageEvent) -> bool:
        try:
            if event.is_private_chat():
                return True
            return self._cfg_bool("allow_group", True)
        except Exception:
            return True

    def _check_keyword_conflicts(self) -> None:
        """检查同目录插件是否也注册了 作业 / pcr / 自定义关键词。

        只读扫描，不修改其他插件；冲突时写警告日志，并在 README 给出建议。
        """

        keywords = set(self._keywords()) | {"作业", "pcr"}
        command_re = re.compile(r"filter\.command\(\s*[\"']([^\"']+)[\"']")
        alias_re = re.compile(r"alias\s*=\s*\{([^}]*)\}")
        quote_re = re.compile(r"[\"']([^\"']+)[\"']")
        conflicts: list[str] = []
        try:
            siblings = [
                path
                for path in PLUGIN_DIR.parent.iterdir()
                if path.is_dir() and path.name != PLUGIN_NAME
            ]
        except OSError:
            siblings = []

        for plugin_dir in siblings:
            main_file = plugin_dir / "main.py"
            if not main_file.is_file():
                continue
            try:
                source = main_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            registered: set[str] = set(command_re.findall(source))
            for alias_block in alias_re.findall(source):
                registered.update(quote_re.findall(alias_block))
            # metadata 的 name 也算占用（有些插件用 metadata 注册指令名）。
            meta_file = plugin_dir / "metadata.yaml"
            if meta_file.is_file():
                try:
                    for line in meta_file.read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines():
                        match = re.match(r"\s*name\s*:\s*[\"']?([^\"'\s]+)", line)
                        if match:
                            registered.add(match.group(1))
                except OSError:
                    pass
            for keyword in sorted(keywords):
                if keyword in registered:
                    conflicts.append(f"{plugin_dir.name}: {keyword}")

        self._keyword_conflicts = conflicts
        if conflicts:
            logger.warning(
                "PCRBot 关键词冲突："
                + "；".join(conflicts)
                + "。建议在 PCRBot 配置里改 keywords，避免和这些插件抢指令。"
            )
        else:
            logger.info("PCRBot 关键词检查：同目录未发现 作业 / pcr 冲突。")

    # ------------------------------------------------------------------
    # 本地数据
    # ------------------------------------------------------------------
    def _load_meta(self) -> None:
        try:
            payload = json.loads(self.meta_path.read_text(encoding="utf-8"))
            self._meta = payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            self._meta = {}

    def _load_stats(self) -> None:
        self._stats = {"date": _today_text(), "count": 0}
        try:
            payload = json.loads(self.stats_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("date") == _today_text():
                self._stats["count"] = max(0, int(payload.get("count") or 0))
        except (OSError, ValueError, TypeError):
            pass

    def _save_stats(self) -> None:
        try:
            _atomic_write_json(self.stats_path, self._stats)
        except OSError as exc:
            logger.warning(f"PCRBot 保存查询计数失败：{type(exc).__name__}")

    def _bump_query_count(self) -> None:
        today = _today_text()
        if self._stats.get("date") != today:
            self._stats = {"date": today, "count": 0}
        self._stats["count"] = int(self._stats.get("count") or 0) + 1
        self._save_stats()

    @staticmethod
    def _characters_current(payload: Mapping[str, Any] | None) -> bool:
        if not isinstance(payload, Mapping):
            return False
        try:
            if int(payload.get("schema") or 1) < 2:
                return False
            chars = payload.get("characters")
            if not isinstance(chars, list) or len(chars) < 300:
                return False
            sample = chars[0]
            return isinstance(sample, Mapping) and "uid4" in sample
        except (TypeError, ValueError):
            return False

    def _reload_characters(self, *, seed: bool = False) -> None:
        payload = pcr_data.load_characters(self.characters_path)
        units = pcr_data.load_units_cache(self.units_path)
        if units is not None and not self._characters_current(payload):
            previous_payload = payload
            payload = pcr_data.build_characters_from_units(
                units,
                aliases_extra=pcr_data.load_aliases_extra(self.aliases_extra_path),
                updated_at=_now_text(),
            )
            if previous_payload:
                restored = pcr_data.merge_previous_names(payload, previous_payload)
                if restored:
                    logger.info("PCRBot 初始化时保留了 %d 个旧版中文名", restored)
            pcr_data.save_characters(self.characters_path, payload)
        elif payload is None:
            if seed:
                payload = pcr_data.write_characters(self.characters_path, _now_text())
            else:
                payload = pcr_data.ensure_characters(
                    self.characters_path,
                    _now_text(),
                    units_cache_path=self.units_path,
                    aliases_extra_path=self.aliases_extra_path,
                )
        assert payload is not None
        self.index = pcr_data.CharacterIndex(payload)
        if self.library is not None:
            self.library = self._new_library(
                self.avatars_dir,
                cache_path=self.prints_cache_path,
                allowed_ids=set(self.index.by_uid4),
            )

    def _avatar_files(self) -> list[Path]:
        try:
            return [
                path
                for path in self.avatars_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".webp", ".png", ".jpg", ".jpeg"}
            ]
        except OSError:
            return []

    def _avatar_stats(self) -> tuple[int, int]:
        files = self._avatar_files()
        covered = {path.stem[:4] for path in files if path.stem[:4].isdigit()}
        return len(files), len(covered)

    def _last_success_ts(self) -> float:
        try:
            value = float(self._meta.get("last_success_ts") or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
        try:
            return self.characters_path.stat().st_mtime
        except OSError:
            return 0.0

    def _last_success_text(self) -> str:
        text = str(self._meta.get("last_success") or "").strip()
        if text:
            return text
        try:
            return datetime.fromtimestamp(self.characters_path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except OSError:
            return "从未更新"

    def _auto_update_due(self) -> bool:
        days = self._cfg_int("auto_update_days", 0, 365, 7)
        if days <= 0:
            return False
        if not self._characters_current(
            pcr_data.load_characters(self.characters_path)
        ):
            return True
        if pcr_data.load_units_cache(self.units_path) is None:
            return True
        if not self._avatar_files():
            return True
        last = self._last_success_ts()
        if last <= 0:
            return True
        return (time.time() - last) > days * 86400

    async def _auto_update_loop(self) -> None:
        # 等 AstrBot 启动完成，避免和别的插件抢磁盘 / 网络。
        try:
            await asyncio.sleep(5)
            while True:
                try:
                    if self._auto_update_due():
                        result = await self._run_update(manual=False)
                        logger.info(f"PCRBot 自动更新完成：{_short(result, 300)}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"PCRBot 自动更新失败（已忽略）：{type(exc).__name__}: {_short(exc)}"
                    )
                await asyncio.sleep(6 * 3600)
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------
    async def _fetch_icon_names(self, session: aiohttp.ClientSession) -> set[str]:
        source = self._icon_source()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                headers = {
                    "user-agent": USER_AGENT,
                    "accept": "text/html,application/xhtml+xml",
                    "referer": "https://redive.estertion.win/",
                }
                async with session.get(source, headers=headers) as response:
                    if response.status != 200:
                        raise ArenaNetworkError(
                            f"头像 CDN 目录返回 HTTP {response.status}，可能被风控或改版了。"
                        )
                    text = await response.text(errors="replace")
                names = set(re.findall(r"(?<!\d)(\d{6})\.webp", text))
                if not names:
                    raise ArenaNetworkError(
                        "头像 CDN 目录里没找到 6 位 .webp 文件名，页面可能改版或被拦截。"
                    )
                return names
            except (asyncio.TimeoutError, aiohttp.ClientError, ArenaNetworkError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1.5)
        if isinstance(last_error, ArenaNetworkError):
            raise last_error
        raise ArenaNetworkError(
            f"获取头像 CDN 目录失败：{type(last_error).__name__ if last_error else '未知错误'}"
        )

    @staticmethod
    def _pick_icon_names(
        char_ids: Iterable[int],
        all_names: Iterable[str],
    ) -> list[str]:
        by_prefix: dict[str, list[str]] = {}
        for name in all_names:
            if len(name) == 6 and name.isdigit():
                by_prefix.setdefault(name[:4], []).append(name)

        def variant_key(name: str) -> tuple[int, str]:
            suffix = name[4:6]
            preference = {"61": 0, "31": 1, "11": 2}
            return preference.get(suffix, 3), name

        selected: list[str] = []
        for char_id in char_ids:
            candidates = sorted(by_prefix.get(f"{int(char_id):04d}", []), key=variant_key)
            selected.extend(candidates[:3])
        return selected

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    async def _download_icons(
        self,
        session: aiohttp.ClientSession,
        names: Sequence[str],
    ) -> tuple[int, int, int, list[str]]:
        semaphore = asyncio.Semaphore(UPDATE_CONCURRENCY)
        downloaded = skipped = failed = 0
        failures: list[str] = []
        source = self._icon_source()
        lock = asyncio.Lock()

        async def one(name: str) -> None:
            nonlocal downloaded, skipped, failed
            target = self.avatars_dir / f"{name}.webp"
            try:
                if target.exists() and target.stat().st_size > 64:
                    async with lock:
                        skipped += 1
                    return
            except OSError:
                pass

            last_error = ""
            for attempt in range(2):
                try:
                    async with semaphore:
                        async with session.get(
                            source + name + ".webp",
                            headers={
                                "user-agent": USER_AGENT,
                                "accept": "image/webp,image/*,*/*",
                                "referer": "https://redive.estertion.win/",
                            },
                        ) as response:
                            if response.status == 404:
                                last_error = "404"
                                break
                            if response.status != 200:
                                last_error = f"HTTP {response.status}"
                                if attempt == 0:
                                    await asyncio.sleep(0.5)
                                continue
                            data = await response.read()
                    if len(data) < 64 or not data.startswith(b"RIFF"):
                        last_error = "不是有效的 webp"
                        if attempt == 0:
                            await asyncio.sleep(0.5)
                        continue
                    await asyncio.to_thread(self._write_bytes, target, data)
                    async with lock:
                        downloaded += 1
                    return
                except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
                    last_error = type(exc).__name__
                    if attempt == 0:
                        await asyncio.sleep(0.5)
            async with lock:
                failed += 1
                if len(failures) < 12:
                    failures.append(f"{name}({_short(last_error, 40)})")

        await asyncio.gather(*(one(name) for name in names))
        return downloaded, skipped, failed, failures

    def _prune_icons(self, allowed: set[str]) -> int:
        removed = 0
        for path in self._avatar_files():
            if path.name in allowed:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def _save_meta(self, **changes: Any) -> None:
        self._meta.update(changes)
        try:
            _atomic_write_json(self.meta_path, self._meta)
        except OSError as exc:
            logger.warning(f"PCRBot 保存 meta.json 失败：{type(exc).__name__}")

    def _apply_alias_removals(self, characters: object) -> int:
        """按 aliases_remove.json 删掉错误别称（例如「菲欧」不该属于爱梅斯）。"""
        path = self.data_dir / "aliases_remove.json"
        if not path.exists() or not isinstance(characters, dict):
            return 0
        chars_list = characters.get("characters")
        if not isinstance(chars_list, list):
            return 0
        try:
            removals = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(removals, dict):
            return 0
        changed = 0
        for item in chars_list:
            try:
                cid = int(item.get("id", 0))
            except (TypeError, ValueError):
                continue
            for key in (str(cid), str(cid // 100)):
                for bad in removals.get(key) or []:
                    aliases = item.get("aliases") or []
                    if bad in aliases:
                        aliases.remove(bad)
                        changed += 1
                    item["aliases"] = aliases
        return changed

    def _apply_ai_names(self, characters: object) -> int:
        """给 /units 重建后仍然只有日文名的角色补上中文名（AI 翻译 + 手动别名优先）。"""
        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / "pcrbot"
        ai_path = data_dir / "ai_names.json"
        extra_path = data_dir / "aliases_extra.json"
        if not isinstance(characters, dict):
            return 0
        chars_list = characters.get("characters")
        if not isinstance(chars_list, list):
            return 0
        try:
            ai = json.loads(ai_path.read_text(encoding="utf-8")) if ai_path.exists() else {}
            extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
        except Exception:
            return 0

        def is_zh(text: str) -> bool:
            return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))

        changed = 0
        for item in chars_list:
            if item.get("name_lang") != "ja":
                continue
            ja = str(item.get("name") or "")
            zh = ""
            for key in (str(item.get("id")), str(int(item.get("id", 0)) // 100)):
                for name in extra.get(key) or []:
                    if is_zh(name):
                        zh = str(name)
                        break
                if zh:
                    break
            zh = zh or str(ai.get(ja) or "")
            if not zh:
                continue
            aliases = list(item.get("aliases") or [])
            for value in (ja, ai.get(ja), zh):
                if value and value not in aliases:
                    aliases.append(str(value))
            item["name"] = zh
            item["name_lang"] = "zh"
            item["name_source"] = "ai_translate" if zh == ai.get(ja) else "manual"
            item["aliases"] = aliases
            changed += 1
        if changed:
            stats = characters.setdefault("stats", {})
            stats["ja_only"] = sum(1 for c in chars_list if c.get("name_lang") == "ja")
            stats["zh"] = sum(1 for c in chars_list if c.get("name_lang") == "zh")
        return changed

    async def _run_update(self, *, manual: bool) -> str:
        async with self._update_lock:
            started = time.monotonic()
            self.avatars_dir.mkdir(parents=True, exist_ok=True)
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            self._save_meta(last_attempt=_now_text())

            # 1) 角色 / 别称：以 pcrdfans /units 的 351 个单位为权威数据，
            #    失败时优先使用上次缓存。
            units_error = ""
            units_note = ""
            units_payload: Mapping[str, Any] | None = None
            try:
                units_payload = await asyncio.to_thread(
                    pcr_data.fetch_units_page,
                    self.units_path,
                    self._request_timeout(),
                )
                if units_payload.get("cache_used"):
                    units_note = (
                        "pcrdfans /units 本次抓取失败，已使用本地缓存（"
                        + _short(str(units_payload.get("cache_error") or ""), 100)
                        + "）"
                    )
                previous_payload = pcr_data.load_characters(self.characters_path)
                characters = pcr_data.build_characters_from_units(
                    units_payload,
                    aliases_extra=pcr_data.load_aliases_extra(self.aliases_extra_path),
                    updated_at=_now_text(),
                )
                if previous_payload:
                    restored = pcr_data.merge_previous_names(characters, previous_payload)
                    if restored:
                        logger.info("PCRBot 更新时保留了 %d 个旧版中文名", restored)
                pcr_data.save_characters(self.characters_path, characters)
            except Exception as exc:  # noqa: BLE001
                units_error = f"角色数据更新失败：{_short(exc, 140)}"
                logger.warning(f"PCRBot {units_error}")
                existing = pcr_data.load_characters(self.characters_path)
                if self._characters_current(existing):
                    characters = existing  # type: ignore[assignment]
                else:
                    characters = pcr_data.write_characters(
                        self.characters_path,
                        _now_text(),
                    )
            wiki_note = ""
            try:
                from .pcrjjc import pcr_wiki

                try:
                    wiki_units = await pcr_wiki.fetch_names(
                        force=False, cache_path=self.data_dir / "wiki_names.json"
                    )
                except TypeError:
                    wiki_units = await pcr_wiki.fetch_names()
                chars_list = (
                    characters.get("characters") if isinstance(characters, dict) else None
                )
                if wiki_units and isinstance(chars_list, list):
                    changed = pcr_wiki.merge_into(chars_list, wiki_units)
                    try:
                        stat = characters.setdefault("stats", {})
                        stat["ja_only"] = sum(
                            1 for item in chars_list if item.get("name_lang") == "ja"
                        )
                        stat["zh"] = sum(
                            1 for item in chars_list if item.get("name_lang") == "zh"
                        )
                    except Exception:
                        pass
                    ai_filled = self._apply_ai_names(characters)
                    if ai_filled:
                        wiki_note += f"，AI 补名 {ai_filled} 个"
                    removed = self._apply_alias_removals(characters)
                    pcr_data.save_characters(self.characters_path, characters)
                    wiki_note = f"biligame 补中文名/外号 {changed} 个"
                    if removed:
                        wiki_note += f"，清理别称 {removed} 条"
                    logger.info(f"PCRBot {wiki_note}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"PCRBot biligame 补名失败（忽略）：{type(exc).__name__}: {exc}")

            self.index = pcr_data.CharacterIndex(characters)
            self._reload_characters(seed=False)
            self.index = pcr_data.CharacterIndex(characters)

            icon_error = ""
            all_names: set[str] = set()
            timeout = aiohttp.ClientTimeout(
                total=self._request_timeout(),
                connect=min(15.0, max(5.0, self._request_timeout())),
            )
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    try:
                        all_names = await self._fetch_icon_names(session)
                    except Exception as exc:  # noqa: BLE001
                        icon_error = _short(exc, 180)
                        logger.warning(f"PCRBot 获取头像索引失败：{icon_error}")

                    downloaded = skipped = failed = 0
                    failures: list[str] = []
                    allowed_names: list[str] = []
                    if all_names:
                        allowed_names = self._pick_icon_names(
                            self.index.by_uid4.keys(),
                            all_names,
                        )
                        if allowed_names:
                            try:
                                downloaded, skipped, failed, failures = await self._download_icons(
                                    session,
                                    allowed_names,
                                )
                            except Exception as exc:  # noqa: BLE001
                                icon_error = f"下载头像失败：{_short(exc, 120)}"
                                logger.warning(f"PCRBot 下载头像失败：{icon_error}")
                        else:
                            icon_error = "头像目录里没有当前角色库对应的文件。"

                if all_names and allowed_names:
                    removed = self._prune_icons(
                        {f"{name}.webp" for name in allowed_names}
                    )
                else:
                    removed = 0
            except Exception as exc:  # noqa: BLE001
                icon_error = icon_error or f"更新头像时出错：{_short(exc, 120)}"
                downloaded = skipped = failed = 0
                failures = []
                removed = 0
                logger.warning(f"PCRBot 更新头像阶段失败：{icon_error}")

            avatar_count, covered = self._avatar_stats()
            elapsed = time.monotonic() - started
            if not icon_error and failed and avatar_count == 0:
                icon_error = f"头像全部下载失败（{failed} 张）"
            success = not icon_error and not units_error
            stats = self.index.server_counts()
            meta_changes: dict[str, Any] = {
                "characters": len(self.index),
                "characters_cn": stats.get("cn", 0),
                "characters_us": stats.get("us", 0),
                "characters_ja_only": stats.get("ja_only", 0),
                "avatars": avatar_count,
                "covered_characters": covered,
                "icon_source": self._icon_source(),
                "units_fetched_at": (
                    units_payload.get("fetched_at", "")
                    if units_payload is not None
                    else ""
                ),
                "units_cache_used": bool(
                    units_payload.get("cache_used") if units_payload else False
                ),
                "last_attempt": _now_text(),
            }
            if success:
                meta_changes["last_success"] = _now_text()
                meta_changes["last_success_ts"] = time.time()
            self._save_meta(**meta_changes)

            # 头像文件变化后，下一次识图重新加载 / 复用指纹缓存。
            if self.index is not None:
                self.library = self._new_library(
                    self.avatars_dir,
                    cache_path=self.prints_cache_path,
                    allowed_ids=set(self.index.by_uid4),
                )

            lines = [
                f"更新{'完成' if success else '部分完成'}："
                f"角色 {len(self.index)} 个"
                f"（国服 {stats.get('cn', 0)} / 国际服 {stats.get('us', 0)} / "
                f"仅日文名 {stats.get('ja_only', 0)}） / "
                f"头像 {avatar_count} 张 / 耗时 {elapsed:.1f} 秒"
            ]
            if units_note:
                lines.append(units_note)
            if wiki_note:
                lines.append(wiki_note)
            if units_error:
                lines.append(units_error)
            if success:
                lines.append(
                    f"本次：新下载 {downloaded} 张，已存在 {skipped} 张，"
                    f"失败 {failed} 张"
                )
                if removed:
                    lines.append(f"清理了 {removed} 张不在当前角色库里的旧头像。")
                if failures:
                    lines.append("失败样例：" + "、".join(failures[:5]))
            else:
                if icon_error:
                    lines.append(f"头像更新未完成：{icon_error}")
                if avatar_count:
                    lines.append(f"已有 {avatar_count} 张头像仍可继续用于识图。")
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # 命令入口
    # ------------------------------------------------------------------
    @filter.command("pcr", desc="PCRBot：公主连结竞技场作业查询")
    async def pcr_command(
        self,
        event: AstrMessageEvent,
        args: GreedyStr = GreedyStr,
    ) -> AsyncIterator[Any]:
        if not self._allow_group(event):
            return
        text = "" if args is GreedyStr else str(args or "").strip()
        async for result in self._handle_pcr(event, text):
            yield result

    @filter.command("作业", alias={"竞技场作业"}, desc="按角色名或截图查询竞技场作业")
    async def arena_command(
        self,
        event: AstrMessageEvent,
        args: GreedyStr = GreedyStr,
    ) -> AsyncIterator[Any]:
        if not self._allow_group(event):
            return
        text = "" if args is GreedyStr else str(args or "").strip()
        async for result in self._handle_arena_alias(event, text):
            yield result

    async def _handle_pcr(
        self,
        event: AstrMessageEvent,
        text: str,
    ) -> AsyncIterator[Any]:
        if not text:
            images = list(_iter_images(event.get_messages(), include_reply=True))
            if images and self._cfg_bool("enable_image", True):
                result = await self._handle_image(event, images[0])
                async for item in self._deliver_image(event, result):
                    yield item
            else:
                yield event.plain_result(self._help_text())
            return

        parts = text.split(maxsplit=1)
        sub = parts[0].strip().lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub in {"帮助", "help", "?", "？", "用法"}:
            yield event.plain_result(self._help_text())
            return
        if sub in {"更新", "update", "刷新"}:
            yield event.plain_result("开始更新角色库和头像，首次会下载几百张头像，请稍等…")
            try:
                report = await self._run_update(manual=True)
                yield event.plain_result(report)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"PCRBot 手动更新失败：{type(exc).__name__}: {exc}")
                yield event.plain_result(
                    f"更新失败了：{_short(exc, 160)}\n"
                    "角色/头像库没有被破坏，已有数据仍可用；稍后再试一次。"
                )
            return
        if sub in {"状态", "status"}:
            yield event.plain_result(self._status_text())
            return
        if sub in {"角色", "查角色", "chara", "char", "别名", "别称"}:
            if not rest:
                yield event.plain_result("用法：/pcr 角色 克总\n会列出匹配的 id、中文名和别称。")
                return
            yield event.plain_result(self._character_search_text(rest))
            return
        if sub in {"作业", "查询", "查", "jjc", "竞技场"}:
            if not rest:
                images = list(_iter_images(event.get_messages(), include_reply=True))
                if images and self._cfg_bool("enable_image", True):
                    result = await self._handle_image(event, images[0])
                    async for item in self._deliver_image(event, result):
                        yield item
                else:
                    yield event.plain_result(
                        "用法：/pcr 作业 布丁 克总\n或者 /pcr 作业 + 竞技场截图。"
                    )
                return
            outcome = await self._text_query(rest)
            async for item in self._deliver(event, outcome):
                yield item
            return

        # 没写子命令时，/pcr 布丁 克总 也按作业查询处理，方便使用。
        outcome = await self._text_query(text)
        async for item in self._deliver(event, outcome):
            yield item

    async def _handle_arena_alias(
        self,
        event: AstrMessageEvent,
        text: str,
    ) -> AsyncIterator[Any]:
        images = list(_iter_images(event.get_messages(), include_reply=True))
        if images and self._cfg_bool("enable_image", True):
            # 带图时优先识图；文字只作为补充提示，不强行拼进防守队。
            result = await self._handle_image(event, images[0])
            async for item in self._deliver_image(event, result):
                yield item
            return
        if not text:
            yield event.plain_result(
                "用法：/作业 布丁 克总\n"
                "或 /作业 + 一张 5 个并排头像的竞技场截图。"
            )
            return
        outcome = await self._text_query(text)
        async for item in self._deliver(event, outcome):
            yield item

    @filter.custom_filter(HasImageFilter)
    async def auto_image(
        self,
        event: AstrMessageEvent,
    ) -> AsyncIterator[Any]:
        if not self._cfg_bool("enable_image", True):
            return
        if not self._cfg_bool("image_auto", True):
            return
        if not self._allow_group(event):
            return
        # 群里必须 @ / 唤醒机器人才自动识图，避免扫到所有聊天图片。
        try:
            if not event.is_private_chat() and not event.is_at_or_wake_command:
                return
        except Exception:
            return
        # 用户明确要求：普通图片（表情包、聊天截图）不得自动触发作业查询。
        # 识图入口只剩两条：/作业 命令 + 图片、或消息里带关键词（默认「作业」）+ 图片，
        # 这两条分别由 arena_command / keyword_query 处理，这里直接放行给它们。
        return
        images = list(_iter_images(event.get_messages(), include_reply=False))
        if not images:
            return
        try:
            result = await self._handle_image(event, images[0])
            async for item in self._deliver_image(event, result):
                yield item
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PCRBot 自动识图失败：{type(exc).__name__}: {exc}")
            return

    @filter.custom_filter(HasKeywordFilter)
    async def keyword_query(
        self,
        event: AstrMessageEvent,
    ) -> AsyncIterator[Any]:
        """自然语言关键词入口：有关键词 + 能解析角色/带图才触发。"""

        if not self._allow_group(event):
            return
        try:
            if not event.is_private_chat() and not event.is_at_or_wake_command:
                return
        except Exception:
            return
        if self._is_pcr_command(event):
            return
        text = event.get_message_str().strip()
        if not text or not self._has_keyword(text):
            return
        # 「竞技场阵容排除 / 替换」是主动追问的入口，别被当成普通作业查询。
        if pcr_dialog.active_trigger(text) is not None:
            return

        images = list(_iter_images(event.get_messages(), include_reply=False))
        if images and self._cfg_bool("enable_image", True):
            local = getattr(images[0], "path", None)
            if local and Path(local).is_file() and pcr_images.reject_reason(local):
                # 聊天里带着表情包又提了关键词：不是查作业，保持安静。
                return
            result = await self._handle_image(event, images[0])
            async for item in self._deliver_image(event, result):
                yield item
            return

        payload = self._strip_keywords(text)
        if not payload:
            return
        if self.index is None:
            self._reload_characters(seed=True)
        assert self.index is not None
        parsed = self.index.parse_text(payload, limit=MAX_QUERY_IDS)
        if not parsed.ids:
            return
        outcome = await self._text_query(payload)
        async for item in self._deliver(event, outcome):
            yield item

    @staticmethod
    def _is_pcr_command(event: AstrMessageEvent) -> bool:
        """判断这条消息是否已被 PCRBot 的 /作业 或 /pcr 指令处理器接管。"""

        try:
            parsed = event.get_extra("handlers_parsed_params", {}) or {}
        except Exception:
            return False
        return any(
            "astrbot_plugin_pcrbot" in str(name)
            and ("pcr_command" in str(name) or "arena_command" in str(name))
            for name in parsed
        )

    # ------------------------------------------------------------------
    # 查不到作业时的追问：排除角色法 / 替换角色法
    # ------------------------------------------------------------------
    def _note(self, text: str) -> MessageEventResult:
        """纯文字提示。直接用 GENERAL 结果，避免被 TTS 念成语音。"""
        return MessageEventResult().message(text)

    def _dialog_timeout_min(self) -> int:
        return self._cfg_int("dialog_timeout_min", 0, 10, 2)

    def _dialog_step_timeout_min(self) -> int:
        """「排除谁 / 换成谁」这一问等多久（分钟）。"""

        return self._cfg_int("dialog_step_timeout_min", 0, 10, 2)

    def _dialog_max_rounds(self) -> int:
        return self._cfg_int("dialog_max_rounds", 1, 20, 6)

    def _dialog_active_minutes(self) -> int:
        """多久内查过作业，才允许用「竞技场阵容排除/替换」主动接上；0 = 关掉主动触发。"""

        return self._cfg_int("dialog_active_minutes", 0, 60, 10)

    def _dialog_enabled(self) -> bool:
        return self._dialog_timeout_min() > 0

    def _stage_timeout_sec(self, stage: str) -> float:
        if stage == pcr_dialog.CHOOSE:
            minutes = self._dialog_timeout_min()
        else:
            minutes = self._dialog_step_timeout_min() or self._dialog_timeout_min()
        return float(max(1, minutes)) * 60.0

    def _apply_dialog_timeout(self, dlg: pcr_dialog.Dialog) -> None:
        """按当前阶段换一套等待时间，并重新计时。"""

        dlg.timeout_sec = self._stage_timeout_sec(dlg.stage)
        dlg.touch()

    def _wait_more(self, dlg: pcr_dialog.Dialog) -> None:
        """没听懂/有错就重新问：刷新等待时间并重置看门狗。"""

        self._apply_dialog_timeout(dlg)
        self._arm_watch(dlg)

    def _active_trigger_mode(self, event: AstrMessageEvent) -> str | None:
        """这条消息是不是主动触发词，且刚才确实在查作业。"""

        if not self._dialog_enabled():
            return None
        minutes = self._dialog_active_minutes()
        if minutes <= 0:
            return None
        try:
            text = event.get_message_str().strip()
        except Exception:
            return None
        stage = pcr_dialog.active_trigger(text)
        if stage is None:
            return None
        if text.startswith(("/", "／")):
            return None
        key = self._dialog_key(event)
        if not key:
            return None
        dialogs = getattr(self, "_dialogs", None) or {}
        if key in dialogs:
            return stage
        return stage if self._last_team_for(key) is not None else None

    def _remember_team(
        self,
        event: AstrMessageEvent,
        team: Sequence[int],
        label: str = "",
    ) -> None:
        key = self._dialog_key(event)
        if not key or len(list(team)) < 2:
            return
        try:
            self._last_team[key] = (
                time.monotonic(),
                [int(value) for value in team],
                str(label or ""),
            )
        except Exception:  # noqa: BLE001
            return

    def _last_team_for(self, key: str) -> list[int] | None:
        record = self._last_team.get(key)
        if not record:
            return None
        stamp, team, _label = record
        window = max(1, self._dialog_active_minutes()) * 60.0
        if time.monotonic() - stamp > window:
            self._last_team.pop(key, None)
            return None
        return list(team)

    @staticmethod
    def _dialog_key(event: AstrMessageEvent) -> str:
        try:
            return str(event.unified_msg_origin or "")
        except Exception:
            return ""

    @staticmethod
    def _sender_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_id() or "")
        except Exception:
            return ""

    def _active_dialog(self, event: AstrMessageEvent) -> pcr_dialog.Dialog | None:
        key = self._dialog_key(event)
        dlg = self._dialogs.get(key)
        if dlg is None:
            return None
        if dlg.expired():
            logger.info(f"PCRBot 追问超时丢弃：{key}")
            self._drop_dialog(key)
            return None
        # 群里别人插话不算回答，别把别人的话当指令。
        try:
            private = event.is_private_chat()
        except Exception:
            private = True
        sender = self._sender_id(event)
        if not private and dlg.sender and sender and sender != dlg.sender:
            return None
        return dlg

    def _drop_dialog(self, key: str, *, cancel_task: bool = True) -> None:
        self._dialogs.pop(key, None)
        self._dialog_ignore.pop(key, None)
        task = self._dialog_tasks.pop(key, None)
        if task is not None and cancel_task and not task.done():
            task.cancel()

    def _start_dialog(
        self,
        event: AstrMessageEvent,
        team: Sequence[int],
        *,
        label: str = "",
        stage: str = pcr_dialog.CHOOSE,
        notes: Sequence[str] | None = None,
    ) -> pcr_dialog.Dialog | None:
        if not self._dialog_enabled():
            return None
        key = self._dialog_key(event)
        if not key:
            return None
        self._dialog_seq += 1
        self._drop_dialog(key)
        team_ids = [int(value) for value in team]
        if self.index is not None:
            team_ids = [self.index.canonical_id(value) for value in team_ids]
        dlg = pcr_dialog.Dialog(
            session=key,
            sender=self._sender_id(event),
            stage=stage,
            team=team_ids,
            label=label,
            timeout_sec=self._stage_timeout_sec(stage),
            token=self._dialog_seq,
            notes=list(notes or []),
        )
        self._apply_dialog_timeout(dlg)
        self._dialogs[key] = dlg
        try:
            self._dialog_ignore[key] = event.message_obj.message_id
        except Exception:  # noqa: BLE001
            self._dialog_ignore.pop(key, None)
        self._arm_watch(dlg)
        return dlg

    def _arm_watch(self, dlg: pcr_dialog.Dialog) -> None:
        key = dlg.session
        old = self._dialog_tasks.pop(key, None)
        if old is not None and not old.done():
            old.cancel()
        try:
            self._dialog_tasks[key] = asyncio.create_task(self._dialog_watch(dlg))
        except RuntimeError:  # 没有事件循环（单测环境）
            self._dialog_tasks.pop(key, None)

    async def _dialog_watch(self, dlg: pcr_dialog.Dialog) -> None:
        """到点没等到回答：撤掉追问并主动说一声。"""

        try:
            remain = dlg.deadline - time.monotonic()
            if remain > 0:
                await asyncio.sleep(remain)
        except asyncio.CancelledError:
            return
        current = self._dialogs.get(dlg.session)
        if current is not dlg or not dlg.expired():
            return
        self._dialogs.pop(dlg.session, None)
        self._dialog_tasks.pop(dlg.session, None)
        minutes = max(1, int(round(dlg.timeout_sec / 60.0)))
        text = (
            f"（超过 {minutes} 分钟没回，这次追问先撤了；"
            "想继续找作业，重新发 /作业 或截图就行。）"
        )
        try:
            from astrbot.api.event import MessageChain

            await self.context.send_message(dlg.session, MessageChain().message(text))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"PCRBot 追问超时提醒发送失败：{type(exc).__name__}: {exc}"
            )

    # ---------------------- 提示文案 ----------------------
    def _positions_text(self, team: Sequence[int]) -> str:
        self._ensure_index()
        names: list[str] = []
        if self.index is not None:
            for char_id in reversed(list(team)):  # 1 号位（最右）在前
                names.append(self.index.display_name(char_id))
        else:
            names = [str(value) for value in reversed(list(team))]
        return "现在这队（1 号位=最右=前卫）：" + pcr_dialog.positions_line(names)

    def _choose_prompt(self, dlg: pcr_dialog.Dialog) -> str:
        lines = [
            f"{dlg.label}这组防守没查到作业。换个思路：",
            "1. 排除一个角色，用剩下的再查；",
            "2. 把一个角色换成另一个，再查。",
            self._positions_text(dlg.team),
            f"回我「1」或「2」；回「取消」就停。等我 {dlg.left_text()}。",
        ]
        return "\n".join(lines)

    def _exclude_prompt(self, dlg: pcr_dialog.Dialog) -> str:
        return "\n".join(
            [
                "要排除哪个角色？说名字（布丁 / 克总…），",
                "或者发一张他的头像截图，也可以说「3号位」。",
                self._positions_text(dlg.team),
                f"回「取消」就停。等我 {dlg.left_text()}。",
            ]
        )

    def _replace_prompt(self, dlg: pcr_dialog.Dialog) -> str:
        return "\n".join(
            [
                "要把谁换成谁？这个只能用文字说，比如：",
                "「布丁换成克总」或者「3号位换成克总」。",
                self._positions_text(dlg.team),
                f"回「取消」就停。等我 {dlg.left_text()}。",
            ]
        )

    def _not_found_again(self, dlg: pcr_dialog.Dialog, outcome: QueryOutcome) -> str:
        notes = self._team_notes(dlg)
        if notes:
            head = "、".join(notes) + "。这样调完还是没查到作业。"
        else:
            head = "这组还是没查到作业。"
        return "\n".join(
            [
                head,
                "可以继续：回「1」再排除一个，回「2」替换一个角色"
                f"（还能改 {max(0, self._dialog_max_rounds() - dlg.rounds)} 轮）。",
                f"回「取消」就停。等我 {dlg.left_text()}。",
            ]
        )

    def _team_notes(self, dlg: pcr_dialog.Dialog) -> list[str]:
        notes: list[str] = []
        if self.index is not None and dlg.excluded:
            notes.append(
                "已排除：" + "、".join(self.index.display_name(i) for i in dlg.excluded)
            )
        if dlg.replaced:
            notes.append("已替换：" + "，".join(dlg.replaced))
        return notes

    def _low_confidence_text(self, dlg: pcr_dialog.Dialog, team: Sequence[int]) -> str:
        assert self.index is not None
        names = " / ".join(self.index.display_name(i) for i in team)
        reasons = self._team_notes(dlg)
        head = f"只剩 {len(team)} 个角色了（{names}）。"
        warn = (
            "⚠ 防守角色不全，作业可信度有限："
            "排除/替换越多，剩下的组合越偏，作业可能对不上你真正的防守。"
        )
        tail = "下面是这组残缺防守的作业，只当参考。" if not reasons else (
            "（" + "；".join(reasons) + "）" + "下面是这组残缺防守的作业，只当参考。"
        )
        return "\n".join([head, warn, tail])

    # ---------------------- 角色解析 ----------------------
    def _ensure_index(self) -> None:
        if self.index is None:
            self._reload_characters(seed=True)

    def _resolve_char_global(self, text: str) -> int | None:
        """把用户说的角色名解析成「最匹配的一个」角色 id。"""

        self._ensure_index()
        if self.index is None:
            return None
        token = str(text or "").strip()
        if not token:
            return None
        char_id = self.index.resolve_token(token)
        if char_id:
            return char_id
        hits = self.index.search(token, limit=1)
        if hits and hits[0].score >= 0.55:
            return hits[0].character.id
        return None

    def _match_in_team(self, text: str, team: Sequence[int]) -> int | None:
        """在队伍里找人：先整串解析，再按最相似的别名兜底。"""

        self._ensure_index()
        if self.index is None:
            return None
        token = str(text or "").strip()
        if not token:
            return None
        char_id = self._resolve_char_global(token)
        if char_id is not None and char_id in team:
            return char_id
        best_id: int | None = None
        best_score = 0.0
        for cid in team:
            candidates = [self.index.display_name(cid)]
            candidates.extend(self.index.name(cid) for _ in (0,))
            candidates.extend(self.index.aliases(cid))
            for alias in candidates:
                alias = str(alias or "").strip()
                if not alias:
                    continue
                score = pcr_data.similarity(token, alias)
                if len(token) >= 2 and (token in alias or alias in token):
                    score = max(score, 0.8)
                if score > best_score:
                    best_id, best_score = cid, score
        return best_id if best_score >= 0.6 else None

    async def _locate_character(
        self,
        event: AstrMessageEvent,
        dlg: pcr_dialog.Dialog,
        text: str,
        images: Sequence[AstrImage],
    ) -> tuple[int | None, str]:
        """确定用户要排除谁：截图优先，其次名字/位置号。返回 (id, 提示)。"""

        if images:
            local = getattr(images[0], "path", None)
            if local and Path(local).is_file():
                reason = pcr_images.reject_reason(local)
                if reason:
                    return None, (
                        f"{reason}，看着不像竞技场头像。"
                        "说名字（布丁）、说位置（3号位），或发一张单个角色的头像截图。"
                    )
            recognition, error = await self._recognize_component(event, images[0])
            if error:
                return None, f"这张图没认出来：{error}\n也可以直接说角色名。"
            ids: list[int] = []
            for team in getattr(recognition, "teams", []) or []:
                for slot in getattr(team, "slots", []) or []:
                    if slot.accepted and slot.match is not None:
                        if slot.match.char_id not in ids:
                            ids.append(slot.match.char_id)
            if len(ids) == 1:
                # 识别可能给出 104311 这种「稀有度版本 id」，统一换成队里用的 6 位标准 id，
                # 否则排除/替换时跟队里的 id 对不上。
                assert self.index is not None
                return self.index.canonical_id(ids[0]), ""
            assert self.index is not None
            if not ids:
                return None, "图里没认出角色（可能不是竞技场头像）。直接说名字也行。"
            names = "、".join(self.index.display_name(i) for i in ids[:6])
            return None, f"图里认出好几个：{names}。一次只排除一个，说名字或只发他的头像。"

        request = pcr_dialog.parse_exclude(text)
        if request.position is not None:
            index = pcr_dialog.index_of_position(len(dlg.team), request.position)
            if index is None:
                return None, f"这队没有 {request.position} 号位（只有 1~{len(dlg.team)}）。"
            return dlg.team[index], ""
        if not request.name:
            return None, ""
        char_id = self._match_in_team(request.name, dlg.team)
        if char_id is not None:
            return char_id, ""
        other = self._resolve_char_global(request.name)
        assert self.index is not None
        if other is not None:
            names = " / ".join(self.index.display_name(i) for i in dlg.team)
            return None, (
                f"「{self.index.display_name(other)}」不在这队里。"
                f"队里是：{names}。"
            )
        return None, f"没认出「{request.name}」。说角色名、或「3号位」、或发他的头像截图。"

    # ---------------------- 查询 ----------------------
    async def _query_ids(
        self,
        ids: Sequence[int],
        notes: Sequence[str] | None = None,
    ) -> QueryOutcome:
        """按给定防守角色查询（追问流程用，不做文字解析）。"""

        merged: list[str] = list(notes or [])
        self._ensure_index()
        assert self.index is not None
        wanted = [int(value) for value in ids]
        region = self._region()
        filtered = self.index.filter_ids(wanted, region)
        if len(filtered) < len(wanted):
            merged.append(
                f"有 {len(wanted) - len(filtered)} 个角色不在"
                f"{REGION_NAMES.get(region, '当前')}，已跳过；可把 region 设为 0。"
            )
        if not filtered:
            return QueryOutcome(
                notes=merged,
                error=(
                    f"这些角色都不在{REGION_NAMES.get(region, '当前地区')}。"
                    "可把 region 设为 0 查全部。"
                ),
            )
        try:
            outcome = await self._query_and_render(filtered[:MAX_QUERY_IDS])
        except ArenaError as exc:
            return QueryOutcome(def_ids=filtered[:MAX_QUERY_IDS], notes=merged, error=exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"PCRBot 追问查询异常：{type(exc).__name__}: {exc}")
            return QueryOutcome(
                def_ids=filtered[:MAX_QUERY_IDS],
                notes=merged,
                error=(
                    "查询时出了点问题，已经记到日志里了。稍后再试，或去 "
                    "pcrdfans.com 手动查询。"
                ),
            )
        outcome.notes = merged + outcome.notes
        return outcome

    # ---------------------- 处理入口 ----------------------
    @filter.custom_filter(HasDialogFilter)
    async def dialog_reply(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """追问会话里的回话：1/2 选择、排除谁、把谁换成谁。"""

        dlg = self._active_dialog(event)
        if dlg is None:
            return
        try:
            same_message = self._dialog_ignore.get(dlg.session) == event.message_obj.message_id
        except Exception:  # noqa: BLE001
            same_message = False
        if same_message:
            # 就是刚刚触发追问的那条消息，别回答它自己。
            return
        text = event.get_message_str().strip()
        # 主动触发词交给 active_dialog 处理，这里别抢。
        if pcr_dialog.active_trigger(text) is not None:
            return
        # 期间发 /作业 这类指令：放弃追问，把消息交还给正常指令流程。
        if text.startswith(("/", "／")):
            self._drop_dialog(dlg.session)
            return
        images: list[AstrImage] = []
        if dlg.stage == pcr_dialog.EXCLUDE and self._cfg_bool("enable_image", True):
            images = list(_iter_images(event.get_messages(), include_reply=False))
        try:
            async for item in self._dialog_flow(event, dlg, text, images):
                yield item
        except Exception as exc:  # noqa: BLE001 - 别让追问把插件搞崩
            logger.error(f"PCRBot 追问处理失败：{type(exc).__name__}: {exc}")
            self._drop_dialog(dlg.session)
            yield event.plain_result(
                "追问的时候出了点问题，已经停掉了。重新发 /作业 就可以继续查。"
            )
        finally:
            # 放在最后：先让上面所有消息都发出去，再吃掉这条消息，
            # 免得 LLM 又跟着答一句（在开头 stop_event 会把后续消息一起吞掉）。
            event.stop_event()

    @filter.custom_filter(HasActiveTriggerFilter)
    async def active_dialog(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """主动喊「竞技场阵容排除 / 竞技场阵容替换」：接上一次查过的防守继续问。"""

        if not self._dialog_enabled():
            return
        if not self._allow_group(event):
            return
        try:
            if not event.is_private_chat() and not event.is_at_or_wake_command:
                return
        except Exception:
            return
        stage = self._active_trigger_mode(event)
        if stage is None:
            return
        key = self._dialog_key(event)
        if not key:
            return
        try:
            dlg = self._dialogs.get(key)
            if dlg is not None and dlg.expired():
                self._drop_dialog(key)
                dlg = None
            if dlg is None:
                team = self._last_team_for(key)
                if not team:
                    yield event.plain_result(
                        "刚才没在查作业，我不确定你说的是哪一队。\n"
                        "先发 /作业 或一张竞技场截图，查完再喊"
                        "「竞技场阵容排除」或「竞技场阵容替换」。"
                    )
                    return
                record = self._last_team.get(key)
                label = record[2] if record else ""
                dlg = self._start_dialog(event, team, label=label, stage=stage)
                if dlg is None:
                    return
                if stage == pcr_dialog.EXCLUDE and len(dlg.team) <= 2:
                    self._drop_dialog(key)
                    yield event.plain_result(
                        f"上次那队只剩 {len(dlg.team)} 个角色，再排除就没法查了。"
                    )
                    return
                yield event.plain_result(
                    "接着上次那队来。"
                    + (
                        self._exclude_prompt(dlg)
                        if stage == pcr_dialog.EXCLUDE
                        else self._replace_prompt(dlg)
                    )
                )
                return
            # 追问还在进行中：直接切到用户喊的那一种方式。
            dlg.stage = stage
            self._wait_more(dlg)
            yield event.plain_result(
                "换成这个方式："
                + (
                    self._exclude_prompt(dlg)
                    if stage == pcr_dialog.EXCLUDE
                    else self._replace_prompt(dlg)
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"PCRBot 主动追问失败：{type(exc).__name__}: {exc}")
            yield event.plain_result("主动追问的时候出了点问题，重新发 /作业 试试。")
        finally:
            event.stop_event()

    async def _dialog_flow(
        self,
        event: AstrMessageEvent,
        dlg: pcr_dialog.Dialog,
        text: str,
        images: Sequence[AstrImage],
    ) -> AsyncIterator[Any]:
        if pcr_dialog.is_cancel(text) and not images:
            self._drop_dialog(dlg.session)
            yield event.plain_result("好，不查了。想找作业再发 /作业 就行。")
            return
        if dlg.stage == pcr_dialog.EXCLUDE:
            async for item in self._dialog_exclude(event, dlg, text, images):
                yield item
            return
        if dlg.stage == pcr_dialog.REPLACE:
            async for item in self._dialog_replace(event, dlg, text, images):
                yield item
            return
        async for item in self._dialog_choose(event, dlg, text, images):
            yield item

    async def _dialog_choose(
        self,
        event: AstrMessageEvent,
        dlg: pcr_dialog.Dialog,
        text: str,
        images: Sequence[AstrImage],
    ) -> AsyncIterator[Any]:
        if images and not text:
            self._wait_more(dlg)
            yield event.plain_result("现在先回我「1」还是「2」（排除 / 替换）。")
            return
        choice = pcr_dialog.parse_choice(text)
        if choice is None:
            self._wait_more(dlg)
            yield event.plain_result(
                "没看懂。回「1」排除一个角色、回「2」替换一个角色，回「取消」就不查了。\n"
                + self._positions_text(dlg.team)
            )
            return
        limit = self._dialog_max_rounds()
        if dlg.rounds >= limit:
            self._drop_dialog(dlg.session)
            yield event.plain_result(
                f"这个防守已经追问到 {limit} 轮上限了，先停在这里。"
                "可以换个角色组合重新发 /作业。"
            )
            return
        if choice == "1" and len(dlg.team) <= 2:
            self._drop_dialog(dlg.session)
            yield event.plain_result(
                f"这队只剩 {len(dlg.team)} 个角色了，再排除就没法查了。想重查就发 /作业。"
            )
            return
        dlg.stage = pcr_dialog.EXCLUDE if choice == "1" else pcr_dialog.REPLACE
        dlg.rounds += 1
        self._wait_more(dlg)
        yield event.plain_result(
            self._exclude_prompt(dlg) if choice == "1" else self._replace_prompt(dlg)
        )

    async def _dialog_exclude(
        self,
        event: AstrMessageEvent,
        dlg: pcr_dialog.Dialog,
        text: str,
        images: Sequence[AstrImage],
    ) -> AsyncIterator[Any]:
        if not text and not images:
            self._wait_more(dlg)
            yield event.plain_result(self._exclude_prompt(dlg))
            return
        target, hint = await self._locate_character(event, dlg, text, images)
        if target is None:
            self._wait_more(dlg)
            yield event.plain_result(hint or self._exclude_prompt(dlg))
            return
        kept = pcr_dialog.team_after_exclude(dlg.team, target)
        if len(kept) < 2:
            self._drop_dialog(dlg.session)
            yield event.plain_result(
                "排除这个就只剩 1 个角色了，这样查不出有意义的作业，先停在这里。"
            )
            return
        assert self.index is not None
        name = self.index.display_name(target)
        dlg.team = kept
        if target not in dlg.excluded:
            dlg.excluded.append(target)
        dlg.stage = pcr_dialog.CHOOSE
        dlg.rounds += 1
        yield event.plain_result(
            f"好，排除「{name}」，用剩下的 {len(kept)} 个角色再查一次…"
        )
        outcome = await self._query_ids(kept, notes=self._team_notes(dlg))
        if not outcome.ok:
            self._drop_dialog(dlg.session)
            yield event.plain_result(self._text_outcome(outcome))
            return
        if len(kept) <= 2:
            # 只剩 2 个角色：不管查没查到，都得提醒一句「这组防守不全」。
            self._drop_dialog(dlg.session)
            yield self._note(self._low_confidence_text(dlg, kept))
            async for item in self._deliver(event, outcome, offer=False):
                yield item
            return
        if outcome.entries:
            self._drop_dialog(dlg.session)
            async for item in self._deliver(event, outcome, offer=False):
                yield item
            return
        self._wait_more(dlg)
        yield event.plain_result(self._not_found_again(dlg, outcome))

    async def _dialog_replace(
        self,
        event: AstrMessageEvent,
        dlg: pcr_dialog.Dialog,
        text: str,
        images: Sequence[AstrImage],
    ) -> AsyncIterator[Any]:
        assert self.index is not None
        if images:
            self._wait_more(dlg)
            yield event.plain_result(
                "替换只能用文字说：把谁换成谁，例如「布丁换成克总」或「3号位换成克总」。\n"
                + self._replace_prompt(dlg)
            )
            return
        request = pcr_dialog.parse_replace(text)
        if request.empty:
            self._wait_more(dlg)
            yield event.plain_result(
                "没看懂怎么换。例子：「布丁换成克总」「3号位换成克总」。\n"
                + self._replace_prompt(dlg)
            )
            return

        old_id: int | None = None
        where = ""
        if request.position is not None:
            index = pcr_dialog.index_of_position(len(dlg.team), request.position)
            if index is None:
                self._wait_more(dlg)
                yield event.plain_result(
                    f"这队没有 {request.position} 号位（只有 1~{len(dlg.team)}）。\n"
                    + self._replace_prompt(dlg)
                )
                return
            old_id = dlg.team[index]
            where = f"{request.position} 号位的"
        else:
            old_id = self._match_in_team(request.who, dlg.team)
            if old_id is None:
                self._wait_more(dlg)
                other = self._resolve_char_global(request.who)
                if other is not None:
                    yield event.plain_result(
                        f"「{self.index.display_name(other)}」不在这队里，换不了。\n"
                        + self._replace_prompt(dlg)
                    )
                else:
                    yield event.plain_result(
                        f"没认出「{request.who}」。说角色名或「3号位」。\n"
                        + self._replace_prompt(dlg)
                    )
                return
            index = dlg.team.index(old_id)
            where = ""  # 名字已经写在后面的「角色」里，别重复

        new_id = self._resolve_char_global(request.new)
        if new_id is not None:
            new_id = self.index.canonical_id(new_id)
        if new_id is None:
            self._wait_more(dlg)
            yield event.plain_result(
                f"没认出「{request.new}」这个角色。换个说法试试（官名 / 黑话都行）。\n"
                + self._replace_prompt(dlg)
            )
            return
        old_name = self.index.display_name(old_id)
        new_name = self.index.display_name(new_id)
        if new_id == old_id:
            self._wait_more(dlg)
            yield event.plain_result(
                f"「{old_name}」换成自己了，说起来还是同一个角色，换个别的吧。\n"
                + self._replace_prompt(dlg)
            )
            return
        if new_id in dlg.team:
            # 用户明确要求：换重复了就提醒并继续追问，直到不重复为止。
            self._wait_more(dlg)
            pos = pcr_dialog.position_of(len(dlg.team), dlg.team.index(new_id))
            yield event.plain_result(
                f"「{new_name}」已经在队里了（{pos} 号位），不能重复。\n"
                + self._replace_prompt(dlg)
            )
            return

        new_team = pcr_dialog.team_after_replace(dlg.team, index, new_id)
        dlg.team = new_team
        dlg.replaced.append(f"{old_name}→{new_name}")
        dlg.stage = pcr_dialog.CHOOSE
        dlg.rounds += 1
        yield event.plain_result(f"好，把{where}「{old_name}」换成「{new_name}」，再查一次…")
        outcome = await self._query_ids(new_team, notes=self._team_notes(dlg))
        if not outcome.ok:
            self._drop_dialog(dlg.session)
            yield event.plain_result(self._text_outcome(outcome))
            return
        if outcome.entries:
            self._drop_dialog(dlg.session)
            async for item in self._deliver(event, outcome, offer=False):
                yield item
            return
        self._wait_more(dlg)
        yield event.plain_result(self._not_found_again(dlg, outcome))

    def _offer_dialog(self, event: AstrMessageEvent, outcome: QueryOutcome) -> str:
        """没查到作业时挂上追问会话，返回要追加的提示；不满足条件返回空串。"""

        if not self._dialog_enabled():
            return ""
        team = [int(value) for value in outcome.def_ids]
        if len(team) < 5:
            # 只对完整 5 人防守追问；本来就不全的队，排了更没参考价值。
            return ""
        label = ""
        title = str(outcome.title or "").replace(" 作业", "").strip()
        if title and title != "作业查询":
            label = title + " "
        dlg = self._start_dialog(event, team, label=label, notes=outcome.notes)
        if dlg is None:
            return ""
        return self._choose_prompt(dlg)

    # ------------------------------------------------------------------
    # 文字查询
    # ------------------------------------------------------------------
    async def _text_query(self, text: str) -> QueryOutcome:
        if self.index is None:
            self._reload_characters(seed=True)
        assert self.index is not None
        parsed = self.index.parse_text(text, limit=MAX_QUERY_IDS)
        if not parsed.ids:
            return QueryOutcome(
                error=self._unknown_text(parsed.unknown or [text]),
            )

        notes: list[str] = []
        if parsed.unknown:
            notes.append("这几个词没认出来：" + "、".join(parsed.unknown))
        if parsed.truncated:
            notes.append(f"最多只取前 {MAX_QUERY_IDS} 个角色。")
        region = self._region()
        filtered_ids = self.index.filter_ids(parsed.ids, region)
        if len(filtered_ids) < len(parsed.ids):
            notes.append(
                f"有 {len(parsed.ids) - len(filtered_ids)} 个角色不在"
                f"{REGION_NAMES.get(region, '当前')}，已跳过；"
                "可把 region 设为 0 查全部。"
            )
        parsed_ids = filtered_ids[:MAX_QUERY_IDS]
        if not parsed_ids:
            return QueryOutcome(
                notes=notes,
                error=(
                    f"这些角色都不在{REGION_NAMES.get(region, '当前地区')}。"
                    "可把 region 设为 0 查全部。"
                ),
            )
        if len(parsed_ids) < 5:
            notes.append(
                f"只识别出 {len(parsed_ids)} 个角色；作业网按当前防守查询，"
                "人数不足时结果可能偏少。"
            )

        try:
            outcome = await self._query_and_render(parsed_ids)
        except ArenaError as exc:
            return QueryOutcome(def_ids=parsed_ids, notes=notes, error=exc.message)
        except Exception as exc:  # noqa: BLE001 - 兜底，绝不让 handler 崩
            logger.error(f"PCRBot 文字查询异常：{type(exc).__name__}: {exc}")
            return QueryOutcome(
                def_ids=parsed_ids,
                notes=notes,
                error=(
                    "查询时出了点问题，已经记到日志里了。稍后再试，或去 "
                    "pcrdfans.com 手动查询。"
                ),
            )
        outcome.notes = notes + outcome.notes
        return outcome

    def _unknown_text(self, unknown: Sequence[str]) -> str:
        assert self.index is not None
        lines = [f"没认出这些角色：{'、'.join(unknown)}"]
        for token in list(unknown)[:3]:
            hits = self.index.suggest(token, limit=3)
            if not hits:
                continue
            candidates = " / ".join(
                f"{hit.character.display_name}({hit.character.id})" for hit in hits
            )
            lines.append(f"「{token}」最接近：{candidates}")
        lines.append("可以发 /pcr 角色 关键词 确认黑话，或换用更常见的别称。")
        return "\n".join(lines)

    @staticmethod
    def _server_label(character: pcr_data.Character) -> str:
        labels = []
        if "cn" in character.servers:
            labels.append("国服")
        if "us" in character.servers:
            labels.append("国际服")
        return "/".join(labels) or "全部"

    def _character_search_text(self, keyword: str) -> str:
        if self.index is None:
            self._reload_characters(seed=True)
        assert self.index is not None
        normalized = pcr_data.normalize(keyword)
        # 纯数字优先按 id 查（4 位 uid4 / 6 位 unit id 都行）。
        if normalized.isdigit():
            character = self.index.character(int(normalized))
            if character:
                aliases = "、".join(character.aliases[:10]) or "（无）"
                return (
                    f"{character.id}  {character.display_name}\n"
                    f"uid4：{character.uid4}  服务器：{self._server_label(character)}\n"
                    f"别称：{aliases}"
                )
        hits = self.index.search(keyword, limit=5)
        if not hits:
            suggestions = self.index.suggest(keyword, limit=3)
            if not suggestions:
                return f"没找到「{keyword}」，也没有足够接近的候选。"
            lines = [f"没找到「{keyword}」，最接近："]
            for hit in suggestions:
                lines.append(
                    f"{hit.character.id}  {hit.character.display_name}  "
                    f"（匹配别称：{hit.matched_alias}）"
                )
            return "\n".join(lines)

        lines = [f"「{keyword}」的匹配结果（最多 5 条）："]
        for hit in hits:
            aliases = "、".join(hit.character.aliases[:10]) or "（无）"
            lines.append(
                f"{hit.character.id}  {hit.character.display_name}  "
                f"（{self._server_label(hit.character)}）"
            )
            lines.append(f"  别称：{aliases}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 图片查询
    # ------------------------------------------------------------------
    async def _handle_image(
        self,
        event: AstrMessageEvent,
        component: AstrImage,
    ) -> ImageResult:
        """识图 → 每队一条 QueryOutcome。

        多队（战斗结果 / 编成截图）时按队各自查作业，回复里由调用方标「第几队」。
        """

        local = getattr(component, "path", None)
        if local and Path(local).is_file():
            reason = pcr_images.reject_reason(local)
            if reason:
                return ImageResult(
                    recognition=None,
                    error=f"{reason}，没当竞技场截图处理。要查作业请发一张 5 个并排头像的截图，或直接说角色名。",
                )
        recognition, error = await self._recognize_component(event, component)
        if error:
            return ImageResult(recognition=recognition, error=error)

        outcomes: list[QueryOutcome] = []
        teams = list(recognition.teams)
        for index, team in enumerate(teams):
            if index:
                # 一图多队就是连着查好几组防守；pcrdfans 高峰期限流很敏感，
                # 队与队之间稍等一下，别把账号打到 117。
                await asyncio.sleep(1.2)
            outcomes.append(
                await self._team_outcome(team, multi=len(teams) > 1)
            )
        return ImageResult(
            outcomes=outcomes,
            recognition=recognition,
            team_summary=self._team_summary(recognition),
        )

    async def _recognize_component(
        self,
        event: AstrMessageEvent,
        component: AstrImage,
    ) -> tuple[Any, str]:
        """只识图、不查作业：返回 (recognition | None, 错误文案)。"""

        if not self._cfg_bool("enable_image", True):
            return None, "图片识别已关闭（enable_image=false）。可以改用 /作业 布丁 克总。"
        if not self.vision_available:
            return None, (
                "这台机器没装 numpy / opencv-python，截图识别不可用。"
                "装一下就能用：pip install \"pcrjjc-helper[full]\"。"
                "现在也可以直接发 /作业 布丁 克总。"
            )
        if self.library is None:
            return None, "本地头像库还没准备好，先发 /pcr 更新 试试。"
        library = self.library

        if not library.loaded:
            try:
                async with self._library_lock:
                    if not library.loaded:
                        await library.load_async()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"PCRBot 加载头像参考库失败：{type(exc).__name__}: {exc}")
                return None, "读取本地头像库失败，先发 /pcr 更新 或查看 AstrBot 日志。"
        if len(library) == 0:
            return None, "本地还没有头像文件，先发 /pcr 更新 下载头像后再识图。"

        tmp_dir = self.tmp_dir / f"{TEMP_PREFIX}{uuid.uuid4().hex}"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=False)
            path = await self._materialize_image(component, tmp_dir)
            recognizer = self._new_recognizer(
                library,
                threshold=self._image_threshold(),
            )
            recognition = await asyncio.to_thread(self._recognize_file, path, recognizer)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PCRBot 图片处理失败：{type(exc).__name__}: {exc}")
            return None, (
                "这张图没能处理成功（可能不是图片、下载失败或格式不支持）。"
                "可以重新发一张，或直接用 /作业 布丁 克总。"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if not recognition.teams:
            return recognition, (
                "没能在图里找到竞技场头像框。\n"
                "请发完整一点的截图（头像成排、别被裁掉），或者直接用 "
                "/作业 布丁 克总。"
            )
        return recognition, ""

    def _team_summary(self, recognition: Any) -> str:
        """多队时先说一句「第几队都是谁」。"""

        assert self.index is not None
        parts: list[str] = []
        for team in recognition.teams:
            names: list[str] = []
            for slot in team.slots:
                if slot.match is None:
                    names.append("?")
                    continue
                name = self.index.display_name(slot.match.char_id)
                if not slot.accepted:
                    name += "?"
                names.append(name)
            parts.append(f"第{team.team_no}队：{' / '.join(names)}")
        return "\n".join(parts)

    @staticmethod
    def _recognize_file(path: Path, recognizer: Any) -> Any:
        with Image.open(path) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            return recognizer.recognize(image, max_ids=MAX_QUERY_IDS)

    async def _materialize_image(self, component: AstrImage, tmp_dir: Path) -> Path:
        source: Path | None = None
        local = getattr(component, "path", None)
        if local and Path(local).is_file():
            source = Path(local)
        if source is None:
            try:
                source = Path(await component.convert_to_file_path())
            except Exception as exc:
                logger.warning(f"PCRBot 图片转换失败，尝试直接下载：{type(exc).__name__}")
                reference = component.url or component.file or ""
                if not str(reference).startswith(("http://", "https://")):
                    raise
                timeout = aiohttp.ClientTimeout(total=self._request_timeout())
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        str(reference),
                        headers={"user-agent": USER_AGENT},
                    ) as response:
                        if response.status != 200:
                            raise ArenaNetworkError(
                                f"下载图片失败（HTTP {response.status}）。"
                            ) from None
                        data = await response.read()
                target = tmp_dir / "input.img"
                await asyncio.to_thread(target.write_bytes, data)
                return target

        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            suffix = ".img"
        target = tmp_dir / f"input{suffix}"
        await asyncio.to_thread(shutil.copyfile, source, target)
        return target

    async def _team_outcome(self, team: Any, *, multi: bool) -> QueryOutcome:
        """一支队的识图结果 → 一次作业查询。"""

        assert self.index is not None
        label = f"第{team.team_no}队" if multi else ""
        title = f"第{team.team_no}队 作业" if multi else "作业查询"
        accepted = [
            slot for slot in team.slots if slot.accepted and slot.match is not None
        ]
        if not accepted:
            best = max(
                (slot.match.score for slot in team.slots if slot.match is not None),
                default=0.0,
            )
            return QueryOutcome(
                title=title,
                error=(
                    f"{label}没能认出角色。\n"
                    f"最高相似度 {best:.2f} 低于阈值 {self._image_threshold():.2f}；"
                    "可能截图被裁掉了头像、或者本地头像库太旧。\n"
                    "可以补一张完整的头像截图，或直接用 /作业 布丁 克总。"
                ),
            )

        notes: list[str] = []
        parts: list[str] = []
        ordered: list[tuple[int, bool]] = []   # (char_id, accepted)
        shown: set[int] = set()
        for slot in team.slots:
            if slot.match is None:
                continue
            char_id = self.index.canonical_id(slot.match.char_id)
            if char_id in shown:
                continue
            shown.add(char_id)
            ordered.append((char_id, slot.accepted))
            mark = "" if slot.accepted else "?"
            parts.append(
                f"{self.index.display_name(char_id)}{mark}（{slot.match.score:.2f}）"
            )
        notes.append(f"{label}识图：" + " / ".join(parts))

        canonical_ids = [char_id for char_id, ok in ordered if ok]
        pending_ids = [char_id for char_id, ok in ordered if not ok]
        missing = 5 - len(accepted)
        if missing > 0:
            notes.append(
                f"有 {missing} 格没认准（分数或领先幅度不够），已标 ?；"
                "可以对照一下再决定要不要手动补。"
            )
        if len(canonical_ids) < 3 and pending_ids:
            # 认出来的太少时，把「不确定」的 top1 也用上，不然没得查。
            canonical_ids = canonical_ids + pending_ids[: 5 - len(canonical_ids)]
            notes.append("可查角色太少，已把不确定的那几个也一起查了。")
        if not canonical_ids:
            return QueryOutcome(
                title=title,
                notes=notes,
                error="这支队伍没认出可信的角色，没法查作业。",
            )
        if len(canonical_ids) < 2:
            notes.append("只认出一个角色，作业参考价值有限；建议补一张完整截图。")

        region = self._region()
        query_ids = self.index.filter_ids(canonical_ids, region)
        if len(query_ids) < len(canonical_ids):
            notes.append(
                f"有 {len(canonical_ids) - len(query_ids)} 个角色不在"
                f"{REGION_NAMES.get(region, '当前')}，已跳过；"
                "可把 region 设为 0 查全部。"
            )
        if not query_ids:
            return QueryOutcome(
                title=title,
                def_ids=canonical_ids,
                notes=notes,
                error=(
                    f"认出的角色都不在{REGION_NAMES.get(region, '当前地区')}。"
                    "可把 region 设为 0 查全部。"
                ),
            )

        try:
            outcome = await self._query_and_render(query_ids)
        except ArenaError as exc:
            return QueryOutcome(
                title=title,
                def_ids=query_ids,
                notes=notes,
                error=exc.message,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"PCRBot 图片查询异常：{type(exc).__name__}: {exc}")
            return QueryOutcome(
                title=title,
                def_ids=query_ids,
                notes=notes,
                error=(
                    "识图完成了，但查作业时出了点问题；稍后再试，或直接用 "
                    "/作业 角色名 查询。"
                ),
            )
        outcome.title = title
        outcome.notes = notes + outcome.notes
        return outcome

    # ------------------------------------------------------------------
    # 作业查询 / 渲染
    # ------------------------------------------------------------------
    async def _query_and_render(self, def_ids: Sequence[int]) -> QueryOutcome:
        if self.arena_cache is None:
            self.arena_cache = ArenaCache(self.cache_path)
        api_region = self._api_region()
        def_ids = [int(value) for value in def_ids][:MAX_QUERY_IDS]
        if not def_ids:
            return QueryOutcome(error="没有可查询的防守角色。")

        self._bump_query_count()
        cache_hit = self.arena_cache.get(api_region, def_ids)
        client = ArenaClient(
            auth_key=self._cfg_str("auth_key"),
            region=api_region,
            timeout=self._request_timeout(),
            browser_endpoint=self._cfg_str("browser_endpoint"),
        )

        if not client.has_auth and not client.browser_endpoint:
            if cache_hit:
                if cache_hit.age_days <= self.arena_cache.ttl_days:
                    note = f"本地缓存（{self._cache_time(cache_hit)}）"
                else:
                    note = (
                        f"较旧的本地缓存（{self._cache_time(cache_hit)}），"
                        "配置 auth_key 后可查最新作业"
                    )
                return self._make_outcome(
                    def_ids,
                    cache_hit.entries,
                    cache_note=note,
                )
            raise ArenaAuthError(AUTH_HELP, configured=False)

        try:
            entries = await client.search(def_ids)
        except ArenaError as exc:
            if cache_hit:
                return self._make_outcome(
                    def_ids,
                    cache_hit.entries,
                    cache_note=(
                        f"作业网暂时查不了：{_short(exc.message, 100)}；"
                        f"以下为本地缓存（{self._cache_time(cache_hit)}）"
                    ),
                )
            raise

        if entries:
            self.arena_cache.put(api_region, def_ids, entries)
        return self._make_outcome(def_ids, entries)

    def _make_outcome(
        self,
        def_ids: Sequence[int],
        entries: Sequence[dict[str, Any]],
        *,
        cache_note: str = "",
    ) -> QueryOutcome:
        ordered = sort_entries(entries, self._sort_mode(), def_ids)
        limit = self._max_results()
        return QueryOutcome(
            def_ids=list(def_ids),
            entries=ordered[:limit],
            cache_note=cache_note,
        )

    @staticmethod
    def _cache_time(hit: Any) -> str:
        try:
            return datetime.fromtimestamp(hit.timestamp).strftime("%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            return "未知时间"

    def _member_text(self, member: dict[str, Any]) -> str:
        assert self.index is not None
        char_id = int(member.get("id") or 0)
        name = self.index.display_name(char_id)
        star = int(member.get("star") or 0)
        suffix = f"★{star}" if star else ""
        if member.get("equip"):
            suffix += "专"
        return f"{name}{suffix}"

    def _sort_label(self) -> str:
        return {
            "ratio": "赞踩比 + 时间衰减",
            "time": "最新",
            "relevance": "防守命中数",
        }.get(self._sort_mode(), "赞踩比 + 时间衰减")

    def _text_outcome(self, outcome: QueryOutcome) -> str:
        lines: list[str] = []
        prefix = ""
        if outcome.title and outcome.title != "作业查询":
            prefix = outcome.title.replace(" 作业", "") + " "
        if outcome.def_ids:
            assert self.index is not None
            names = " / ".join(
                self.index.display_name(char_id) for char_id in outcome.def_ids
            )
            lines.append(
                f"{prefix}防守：{names}"
                f"（{REGION_NAMES.get(self._region(), '未知服')}）"
            )
        if outcome.cache_note:
            lines.append(outcome.cache_note)
        lines.extend(outcome.notes)
        if outcome.error:
            lines.append(outcome.error)
            return "\n".join(lines)
        if not outcome.entries:
            lines.append(
                "没有查到这组防守的作业。可能太冷门，或者防守人数不足；"
                "可以去 pcrdfans.com 手动看看。"
            )
            return "\n".join(lines)

        lines.append(
            f"找到 {len(outcome.entries)} 队解法，按「{self._sort_label()}」排序："
        )
        for index, entry in enumerate(outcome.entries, 1):
            team = entry.get("atk") or []
            team_text = " + ".join(self._member_text(member) for member in team)
            up = int(entry.get("up") or 0)
            down = int(entry.get("down") or 0)
            lines.append(f"{index}. {team_text}  👍{up} / 👎{down}")
        lines.append("数据来源：pcrdfans.com")
        return "\n".join(lines)

    def _render_card(self, outcome: QueryOutcome) -> Path:
        assert self.index is not None
        notes = list(outcome.notes)
        if outcome.cache_note:
            notes.insert(0, outcome.cache_note)
        note = _short(" · ".join(notes), 180)
        return render_job_card(
            def_ids=outcome.def_ids,
            entries=outcome.entries,
            out_dir=self.tmp_dir,
            avatars_dir=self.avatars_dir,
            name_for=self._name_for,
            official_name_for=self._official_name_for,
            show_names=self._show_names(),
            max_items=self._card_max_items(),
            note=note,
            title=outcome.title or "作业查询",
            show_likes=self._cfg_bool("show_likes", True),
            show_time=self._cfg_bool("show_time", True),
        )

    async def _deliver_image(
        self,
        event: AstrMessageEvent,
        result: ImageResult,
    ) -> AsyncIterator[Any]:
        """识图结果：多队时先报「第几队都是谁」，再按队各出一张卡片。"""

        if result.error:
            yield event.plain_result(result.error)
            return
        if not result.outcomes:
            yield event.plain_result("这张图里没找到可以查的防守队伍。")
            return
        title_notes: list[str] = []
        if len(result.outcomes) > 1:
            if result.team_summary:
                title_notes.append(result.team_summary)
            title_notes.append(f"共 {len(result.outcomes)} 队，下面按队依次给作业。")
            yield event.plain_result("\n".join(title_notes))
        elif result.team_summary and not self._text_mode():
            # 单队时把不确定的格子提示出来，免得悄悄用了错角色。
            recognition = result.recognition
            uncertain = getattr(recognition, "uncertain_slots", []) or []
            if uncertain:
                yield event.plain_result(
                    result.team_summary
                    + f"\n（有 {len(uncertain)} 格没把握，已标 ?，查作业时没用它们。）"
                )
        for outcome in result.outcomes:
            async for item in self._deliver(event, outcome):
                yield item

    async def _deliver(
        self,
        event: AstrMessageEvent,
        outcome: QueryOutcome,
        *,
        offer: bool = True,
    ) -> AsyncIterator[Any]:
        """发结果：默认图片卡片；text_mode=true 或出错时退回文字。

        ``offer=True`` 时，完整 5 人队查不到作业会在文末挂上「排除 / 替换」追问。
        """

        if outcome.def_ids:
            title = str(outcome.title or "").replace(" 作业", "").strip()
            label = "" if not title or title == "作业查询" else title + " "
            self._remember_team(event, outcome.def_ids, label)
        if not outcome.ok or self._text_mode() or not outcome.entries:
            text = self._text_outcome(outcome)
            if offer and outcome.ok and not outcome.entries:
                prompt = self._offer_dialog(event, outcome)
                if prompt:
                    text = text + "\n\n" + prompt
            yield event.plain_result(text)
            return
        path: Path | None = None
        try:
            path = await asyncio.to_thread(self._render_card, outcome)
            data = await asyncio.to_thread(path.read_bytes)
            # 图片已经读进内存，tmp 文件可以立即清理；消息里不带任何文字，
            # 避免被 AstrBot 的 TTS 念出来。
            try:
                await asyncio.to_thread(path.unlink)
            except OSError:
                logger.warning(f"PCRBot 清理卡片临时文件失败：{path}")
            path = None
            encoded = base64.b64encode(data).decode("ascii")
            yield MessageEventResult().base64_image(encoded)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"PCRBot 生成作业卡片失败：{type(exc).__name__}: {exc}")
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            yield event.plain_result(
                self._text_outcome(outcome)
                + "\n\n（图片卡片生成失败，已回退文字；可把 text_mode 设为 true 或查看日志。）"
            )

    # ------------------------------------------------------------------
    # 帮助 / 状态
    # ------------------------------------------------------------------
    def _status_text(self) -> str:
        stats = self.index.server_counts() if self.index else {
            "all": 0, "cn": 0, "us": 0, "zh": 0, "ja_only": 0,
        }
        avatars, covered = self._avatar_stats()
        auth_text = "已配置" if self._cfg_str("auth_key") else "未配置（只能用本地缓存）"
        today = int(self._stats.get("count") or 0) if self._stats.get("date") == _today_text() else 0
        image_text = "开" if self._cfg_bool("enable_image", True) else "关"
        auto_text = "开" if self._cfg_bool("image_auto", True) else "关"
        text_text = "开（纯文字）" if self._text_mode() else "关（图片卡片）"
        keywords = "、".join(self._keywords())
        conflict_text = (
            "；冲突：" + "、".join(self._keyword_conflicts)
            if self._keyword_conflicts
            else "；无冲突"
        )
        timeout_min = self._dialog_timeout_min()
        step_min = self._dialog_step_timeout_min()
        active_min = self._dialog_active_minutes()
        dialog_text = (
            f"开（选 1/2 等 {timeout_min} 分钟、追问细节等 {step_min} 分钟，"
            f"最多 {self._dialog_max_rounds()} 轮；"
            f"主动触发有效期 {active_min} 分钟）"
            if timeout_min > 0
            else "关"
        )
        active_dialogs = len(self._dialogs)
        return (
            "PCRBot 状态\n"
            f"角色：全部 {stats.get('all', 0)} / 国服 {stats.get('cn', 0)} / "
            f"国际服 {stats.get('us', 0)}\n"
            f"其中 {stats.get('ja_only', 0)} 个只有日文名（显示时带 *）\n"
            f"头像：{avatars} 张（覆盖 {covered} 个角色）\n"
            f"最后更新：{self._last_success_text()}\n"
            f"auth_key：{auth_text}\n"
            f"今日查询：{today} 次\n"
            f"地区：{REGION_NAMES.get(self._region(), '全部')}；"
            f"图片识别：{image_text}（自动识图 {auto_text}，"
            f"命中阈值 {self._image_threshold():.2f}，算法 脸带 NCC）\n"
            f"结果：文字模式 {text_text}；排序 {self._sort_mode()}；"
            f"名字 {self._show_names()}\n"
            f"关键词：{keywords}{conflict_text}\n"
            f"没查到作业时追问：{dialog_text}；当前追问中 {active_dialogs} 个\n"
            f"数据目录：{self.data_dir}"
        )

    def _help_text(self) -> str:
        return (
            "PCRBot · 公主连结竞技场作业\n"
            "① 文字查作业：\n"
            "  /作业 布丁 克总\n"
            "  /pcr 作业 布丁,克总\n"
            "  （空格、逗号、顿号、+ 都行；别名/日文/英文都认）\n"
            "② 截图查作业：\n"
            "  /作业 + 竞技场截图\n"
            "  直接发图（群里需 @机器人，image_auto 默认开）\n"
            "③ 自然语言：\n"
            f"  消息里带「{self._keywords()[0]}」且能解析出角色/图片时触发；"
            "纯聊天不抢\n"
            "④ 自助：\n"
            "  /pcr 更新   更新角色库和头像\n"
            "  /pcr 状态   查看角色/头像/auth_key/今日查询\n"
            "  /pcr 角色 克总  模糊查 id、中文名、别称\n"
            "  /pcr 帮助   显示本帮助\n"
            "⑤ 查不到作业时（完整 5 人队）：\n"
            "  回「1」排除一个角色再查（可说名字 /「3号位」/ 发他的头像）\n"
            "  回「2」把一个角色换成另一个（只能打字，如「布丁换成克总」）\n"
            "  换成队里已有的角色会提醒重复，并继续问你\n"
            "  回「取消」就停；一直不回也会自己撤（时间/轮数在面板里调）\n"
            "⑥ 已经有作业但还想找别的：\n"
            "  刚查完作业后直接说「竞技场阵容排除」→ 接着排除角色再查\n"
            "  说「竞技场阵容替换」→ 接着换角色再查\n"
            "  （只有刚查过作业时才认，防止闲聊误触）\n"
            "结果默认发图片卡片；text_mode=true 时退回纯文字调试。"
        )
