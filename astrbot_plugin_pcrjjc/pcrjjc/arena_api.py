"""pcrdfans 作业网查询客户端与本地缓存。

只依赖标准库 + aiohttp。所有网络 / 授权 / 风控错误都会转换成可以直接
回复给群友的中文句子，不向上抛裸异常。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://api.pcrdfans.com/x/v1/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REGION_NAMES = {
    0: "全部",
    1: "国服",
    2: "国际服",
    3: "日服",
}

AUTH_HELP = (
    "pcrdfans 作业网需要授权 key 才能查作业。\n"
    "获取方法：浏览器登录 pcrdfans.com → 按 F12 打开开发者工具 → "
    "切到 Network（网络）→ 随便查一次 → 找到发往 "
    "api.pcrdfans.com/x/v1/search 的请求 → 复制请求头里的 "
    "authorization 值，填到插件配置的 auth_key。\n"
    "没配置时仍可使用 /pcr 角色、/pcr 状态、/pcr 更新；"
    "以前查过的同一组防守会从本地缓存返回。"
)


class ArenaError(Exception):
    """作业网查询失败的基类，message 是给人看的中文。"""

    def __init__(self, message: str, *, code: int | None = None, kind: str = "api"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.kind = kind

    def __str__(self) -> str:
        return self.message


class ArenaAuthError(ArenaError):
    def __init__(
        self,
        message: str = AUTH_HELP,
        *,
        configured: bool = False,
        code: int = 103,
    ):
        super().__init__(message, code=code, kind="auth")
        self.configured = configured


class ArenaNetworkError(ArenaError):
    def __init__(self, message: str):
        super().__init__(message, kind="network")


class ArenaRateLimitError(ArenaError):
    def __init__(self, message: str):
        super().__init__(message, kind="rate_limit")


class ArenaResponseError(ArenaError):
    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message, code=code, kind="response")


@dataclass(slots=True)
class CacheHit:
    entries: list[dict[str, Any]]
    timestamp: float

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.timestamp)

    @property
    def age_days(self) -> float:
        return self.age_seconds / 86400.0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unit_id(raw_id: Any) -> int:
    """pcrdfans 的 6 位头像 id → 6 位角色 id。"""

    value = _as_int(raw_id, 0)
    if value >= 100000:
        return value
    return value * 100 + 1


def _normalize_members(raw_members: Any) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    if not isinstance(raw_members, list):
        return members
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            continue
        char_id = _unit_id(raw.get("id"))
        if char_id <= 0:
            continue
        members.append(
            {
                "id": char_id,
                "star": max(0, min(6, _as_int(raw.get("star"), 0))),
                "equip": bool(raw.get("equip", False)),
            }
        )
    return members


def normalize_result(data: Any) -> list[dict[str, Any]]:
    """把作业网 data.result 整理成稳定结构，保留接口顺序。"""

    if not isinstance(data, Mapping):
        return []
    raw_result = data.get("result")
    if not isinstance(raw_result, list):
        return []

    entries: list[dict[str, Any]] = []
    for raw in raw_result:
        if not isinstance(raw, Mapping):
            continue
        atk = _normalize_members(raw.get("atk"))
        if not atk:
            continue
        entries.append(
            {
                "id": str(raw.get("id") or ""),
                "atk": atk,
                "def": _normalize_members(raw.get("def")),
                "up": max(0, _as_int(raw.get("up"), 0)),
                "down": max(0, _as_int(raw.get("down"), 0)),
                # 接口不一定给时间；保留原始值，排序时再解析。
                "ts": raw.get("ts"),
            }
        )

    # 保留接口顺序（通常新→旧），排序交给 main / card_render，避免
    # time / relevance 模式拿到已经被按赞数排过的数据。
    return entries


class ArenaClient:
    """一次查询一个防守队伍；不做自动重试，避免风控。"""

    def __init__(
        self,
        auth_key: str = "",
        region: int = 1,
        timeout: float = 15.0,
        api_url: str = API_URL,
        browser_endpoint: str = "",
    ) -> None:
        self.auth_key = str(auth_key or "").strip()
        self.browser_endpoint = str(browser_endpoint or "").strip()
        self.region = region if region in (1, 2, 3) else 1
        self.timeout = max(3.0, min(120.0, float(timeout)))
        self.api_url = api_url

    @property
    def has_auth(self) -> bool:
        return bool(self.auth_key)

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "user-agent": USER_AGENT,
            "accept": "application/json, text/plain, */*",
            "origin": "https://pcrdfans.com",
            "referer": "https://pcrdfans.com/",
        }
        # 空 key 也要带上这个 header：这样 selftest 能真实验证 code=103。
        headers["authorization"] = self.auth_key
        return headers

    def _payload(self, def_ids: Sequence[int], page: int, sort: int) -> dict[str, Any]:
        query_ids: list[int] = []
        for char_id in def_ids:
            value = int(char_id)
            uid4 = value // 100 if value >= 100000 else value
            query_ids.append(uid4 * 100 + 1)
        return {
            "_sign": "a",
            "def": query_ids,
            "nonce": "a",
            "page": max(1, int(page)),
            "sort": int(sort),
            "ts": int(time.time()),
            "region": self.region,
        }

    @staticmethod
    def _human_http_error(status: int, body: str) -> ArenaError:
        text = (body or "").lower()
        if status == 429 or "1010" in text or "cloudflare" in text:
            return ArenaRateLimitError(
                "作业网现在触发了限流 / 风控（HTTP %s）。"
                "等几分钟再查，别连续猛点；也可以先去 pcrdfans.com 手动查。"
                % status
            )
        if status in (401, 403):
            return ArenaAuthError(
                "作业网拒绝了这次请求（HTTP %s），可能是授权失效或触发风控。"
                "请重新登录 pcrdfans.com 获取 auth_key；如果 key 没问题，"
                "等几分钟再试。" % status,
                configured=True,
            )
        if status >= 500:
            return ArenaNetworkError(
                "作业网服务器暂时出问题了（HTTP %s），过一会儿再试。" % status
            )
        return ArenaResponseError(
            "作业网返回了异常状态（HTTP %s），请稍后再试。" % status,
            code=status,
        )

    async def search_via_browser(self, def_ids: Sequence[int]) -> list[dict[str, Any]]:
        """没 key 时走本机浏览器服务（真实 Edge 打开作业网、由页面自己签名）。"""
        query_ids: list[int] = []
        for char_id in def_ids:
            value = int(char_id)
            uid4 = value // 100 if value >= 100000 else value
            query_ids.append(uid4 * 100 + 1)
        timeout = aiohttp.ClientTimeout(total=max(60.0, self.timeout * 4))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                endpoint = self.browser_endpoint.rstrip("/")
                if not endpoint.endswith("/search"):
                    endpoint += "/search"
                async with session.post(
                    endpoint,
                    json={"def": query_ids, "region": self.region},
                ) as response:
                    body = await response.text()
                    status = response.status
        except asyncio.TimeoutError as exc:
            raise ArenaNetworkError(
                "本机浏览器查询超时了（可能 Edge 没起来或作业网很慢），稍后再试。"
            ) from exc
        except aiohttp.ClientError as exc:
            raise ArenaNetworkError(
                "连不上本机浏览器查询服务（%s）。确认启动器里「作业网浏览器」在跑。"
                % type(exc).__name__
            ) from exc

        try:
            wrapper = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise ArenaResponseError("本机查询服务返回了非 JSON（HTTP %s）" % status) from exc

        if not wrapper.get("ok"):
            raise ArenaNetworkError(str(wrapper.get("error") or "本机查询服务出错了")[:200])

        payload = wrapper.get("data") or {}
        code = payload.get("code")
        if code not in (0, None):
            if code in (103, 601):
                raise ArenaAuthError(
                    "作业网说没登录/没授权（code=%s）。请在启动器里重新打开一次作业网登录窗口，"
                    "登录后关掉，再试。" % code,
                    configured=True,
                )
            raise ArenaResponseError(
                "作业网返回 code=%s" % code, code=int(code) if isinstance(code, int) else None
            )

        raw = (payload.get("data") or {}).get("result") or []
        return normalize_result({"result": raw})

    async def search(
        self,
        def_ids: Sequence[int],
        *,
        page: int = 1,
        sort: int = 1,
        allow_missing_auth: bool = False,
        session: aiohttp.ClientSession | None = None,
    ) -> list[dict[str, Any]]:
        """查询防守队伍。

        allow_missing_auth 仅供 selftest / 诊断使用：没有 key 也真的发一次请求，
        以便验证作业网返回 code=103。正常查询没 key 会直接在本地报错。
        """

        def_ids = [int(value) for value in def_ids]
        if not def_ids:
            raise ArenaResponseError("没有可查询的防守角色。")
        if not self.auth_key and not allow_missing_auth:
            if self.browser_endpoint:
                return await self.search_via_browser(def_ids)
            raise ArenaAuthError(AUTH_HELP, configured=False)

        own_session = session is None
        if own_session:
            timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=min(10.0, self.timeout),
                sock_read=self.timeout,
            )
            session = aiohttp.ClientSession(timeout=timeout)

        try:
            assert session is not None
            async with session.post(
                self.api_url,
                json=self._payload(def_ids, page, sort),
                headers=self._headers(),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    raise self._human_http_error(response.status, body)
        except asyncio.TimeoutError as exc:
            raise ArenaNetworkError(
                "连接作业网超时了。检查服务器网络 / 代理，或稍后再试。"
            ) from exc
        except aiohttp.ClientError as exc:
            logger.warning("pcrdfans network error: %s", type(exc).__name__)
            raise ArenaNetworkError(
                "连不上作业网（%s）。检查服务器网络 / 代理，或稍后再试。"
                % type(exc).__name__
            ) from exc
        finally:
            if own_session and session is not None:
                await session.close()

        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            snippet = (body or "").strip().replace("\n", " ")[:80]
            logger.warning("pcrdfans non-json response: %s", snippet)
            raise ArenaResponseError(
                "作业网返回的不是正常 JSON，可能被风控页面拦截了。"
                "等几分钟再试；频繁查询容易触发限制。"
            ) from exc

        if not isinstance(payload, Mapping):
            raise ArenaResponseError("作业网返回的数据格式不对，请稍后再试。")

        code = _as_int(payload.get("code"), 0)
        if code == 0:
            return normalize_result(payload.get("data"))

        if code in (103, 601):
            if self.auth_key:
                message = (
                    f"pcrdfans 不认这个 auth_key（code={code}），可能已经过期，"
                    "或者当前 IP 触发了风控。\n"
                    "请重新登录 pcrdfans.com，从网络请求的 authorization 请求头"
                    "复制最新的 key，填到插件配置 auth_key。"
                )
            else:
                message = AUTH_HELP
                if code == 601:
                    message = (
                        "作业网当前要求授权或触发了风控（code=601）。\n" + message
                    )
            raise ArenaAuthError(
                message,
                configured=self.has_auth,
                code=code,
            )

        if code in (117, -429, 429):
            raise ArenaRateLimitError(
                "作业网高峰期限流了（code=%s）。等一会儿再查，"
                "或者先去 pcrdfans.com 手动查。" % code
            )

        logger.warning("pcrdfans api code=%s message=%s", code, payload.get("message"))
        raise ArenaResponseError(
            "作业网查询失败（code=%s）。如果反复出现，稍后再试或去 "
            "pcrdfans.com 手动查询。" % code,
            code=code,
        )


class ArenaCache:
    """成功查询结果的本地缓存，用于没配 auth_key 时的“本地库模式”。"""

    def __init__(
        self,
        path: str | Path,
        *,
        ttl_days: float = 30.0,
        max_entries: int = 300,
    ) -> None:
        self.path = Path(path)
        self.ttl_days = max(0.0, float(ttl_days))
        self.max_entries = max(10, int(max_entries))
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        entries = payload.get("entries") if isinstance(payload, Mapping) else None
        if isinstance(entries, dict):
            self._entries = {
                str(key): value
                for key, value in entries.items()
                if isinstance(value, Mapping) and isinstance(value.get("result"), list)
            }

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "entries": self._entries}
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError:
            logger.warning("failed to save arena cache: %s", self.path)

    @staticmethod
    def key(region: int, def_ids: Sequence[int]) -> str:
        return "r%s:%s" % (
            int(region),
            "-".join(str(int(value)) for value in def_ids),
        )

    def get(self, region: int, def_ids: Sequence[int]) -> CacheHit | None:
        item = self._entries.get(self.key(region, def_ids))
        if not item:
            return None
        try:
            timestamp = float(item.get("ts") or 0)
            entries = item.get("result")
            if not isinstance(entries, list):
                return None
        except (TypeError, ValueError):
            return None
        return CacheHit(entries=entries, timestamp=timestamp)

    def put(self, region: int, def_ids: Sequence[int], entries: list[dict[str, Any]]) -> None:
        self._entries[self.key(region, def_ids)] = {
            "ts": time.time(),
            "result": entries,
        }
        if len(self._entries) > self.max_entries:
            ordered = sorted(
                self._entries.items(),
                key=lambda pair: float(pair[1].get("ts") or 0),
                reverse=True,
            )
            self._entries = dict(ordered[: self.max_entries])
        self._save()
