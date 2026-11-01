"""从 biligame wiki 抓取公主连结角色的国服译名 / 外号。

角色页使用 `{{角色 ...}}` 模板，字段形如：

    角色ID=1007
    角色名=出云宫子
    翻译名=宫子
    日文名=出雲 宮子
    外号=布丁、幽灵

用法：
    python pcr_wiki.py            # 优先读缓存；没有缓存才抓
    python pcr_wiki.py --force    # 强制重抓并合并进 characters.json

只使用标准库 + aiohttp；批量/单页都有限速与重试，失败页会记录并继续，
不会因为一批返回 HTML 就整批放弃。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

API = "https://wiki.biligame.com/pcr/api.php"
REFERER = "https://wiki.biligame.com/pcr/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": REFERER,
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
}

PLUGIN_DIR = Path(__file__).resolve().parent
DATA_DIR = PLUGIN_DIR.parents[1] / "plugin_data" / "pcrbot"
CACHE_PATH = DATA_DIR / "wiki_names.json"
CHARACTERS_PATH = DATA_DIR / "characters.json"

BATCH = 8
BATCH_DELAY = (1.2, 1.8)
SINGLE_RETRIES = 3
SINGLE_RETRY_SLEEP = 3.0
LIST_RETRIES = 3


class WikiError(RuntimeError):
    """wiki 返回 HTML / 网关页 / 网络错误。"""


FIELD_RE = {
    "uid": re.compile(r"\|\s*角色ID\s*=\s*(\d+)"),
    "name": re.compile(r"\|\s*角色名\s*=\s*([^\n|}]+)"),
    "trans": re.compile(r"\|\s*翻译名\s*=\s*([^\n|}]+)"),
    "ja": re.compile(r"\|\s*日文名\s*=\s*([^\n|}]+)"),
    "alias": re.compile(r"\|\s*外号\s*=\s*([^\n|}]+)"),
}

LAST_REPORT: dict[str, Any] = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_value(value: str) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    value = value.replace("<br/>", " ").replace("<br>", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip().strip("|").strip()


def _split_aliases(value: str) -> list[str]:
    aliases: list[str] = []
    for part in re.split(r"[、,，/;；]+", value):
        part = _clean_value(part)
        if part and part not in aliases:
            aliases.append(part)
    return aliases


def _parse_wikitext(text: str, title: str) -> dict[str, Any] | None:
    uid = FIELD_RE["uid"].search(text)
    name = FIELD_RE["name"].search(text)
    trans = FIELD_RE["trans"].search(text)
    ja = FIELD_RE["ja"].search(text)
    kana_match = re.search(r"\|\s*(?:片假名|平假名|kana)\s*=\s*([^\n|}]+)", text)
    if not uid and not name and not trans:
        return None

    aliases: list[str] = []
    for label in ("外号", "别称", "别名"):
        match = re.search(
            r"\|\s*" + re.escape(label) + r"\s*=\s*([^\n|}]+)",
            text,
        )
        if not match:
            continue
        for part in _split_aliases(match.group(1)):
            if part not in aliases:
                aliases.append(part)

    primary = _clean_value(name.group(1)) if name else ""
    primary = primary or title
    short = _clean_value(trans.group(1)) if trans else ""
    # 翻译名偶尔带逗号/顿号列出多个候选，展示用第一个。
    if short:
        short = _split_aliases(short)[0] if _split_aliases(short) else short
    return {
        "uid": int(uid.group(1)) if uid else 0,
        "title": title,
        "name": primary,
        "short": short,
        "ja": _clean_value(ja.group(1)) if ja else "",
        "kana": _clean_value(kana_match.group(1)) if kana_match else "",
        "aliases": aliases,
    }


def _lookup_key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()


def _looks_japanese(text: str) -> bool:
    return any("\u3040" <= char <= "\u30ff" for char in str(text or ""))


async def _get_json(
    session: aiohttp.ClientSession,
    params: dict[str, Any],
    *,
    tries: int = 3,
    delay: float = 3.0,
) -> dict[str, Any]:
    """请求 MediaWiki JSON；HTML 网关页、非 JSON、异常都重试后抛 WikiError。"""

    last_error = ""
    for attempt in range(max(1, tries)):
        try:
            async with session.get(API, params=params, headers=HEADERS) as response:
                status = response.status
                content_type = response.headers.get("content-type", "")
                text = await response.text()
            if status != 200:
                raise WikiError(f"HTTP {status} ({content_type})")
            stripped = text.lstrip()
            if not stripped.startswith("{"):
                snippet = re.sub(r"\s+", " ", stripped[:80])
                raise WikiError(f"返回 HTML/非 JSON：{snippet}")
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise WikiError("JSON 顶层不是对象")
            if payload.get("error"):
                raise WikiError(f"API error：{payload['error']}")
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < tries - 1:
                await asyncio.sleep(delay)
    raise WikiError(last_error or "未知错误")


async def _get_titles(
    session: aiohttp.ClientSession,
    report: dict[str, Any],
) -> list[str]:
    titles: list[str] = []
    cont: dict[str, Any] = {}
    for _ in range(50):
        params = {
            "action": "query",
            "list": "embeddedin",
            "eititle": "Template:角色",
            "eilimit": "500",
            "format": "json",
            **cont,
        }
        try:
            payload = await _get_json(
                session,
                params,
                tries=LIST_RETRIES,
                delay=2.0,
            )
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(f"页面列表：{exc}")
            break
        embedded = (payload.get("query") or {}).get("embeddedin") or []
        titles.extend(str(item["title"]) for item in embedded if item.get("title"))
        cont = payload.get("continue") or {}
        if not cont:
            break
    # 去重，保持 wiki 顺序。
    return list(dict.fromkeys(titles))


async def _fetch_pages(
    session: aiohttp.ClientSession,
    titles: list[str],
) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "prop": "revisions",
        "rvslots": "main",
        "rvprop": "content",
        "titles": "|".join(titles),
        "format": "json",
        "formatversion": "2",
    }
    payload = await _get_json(session, params, tries=3, delay=2.0)
    return list((payload.get("query") or {}).get("pages") or [])


def _consume_pages(
    pages: list[dict[str, Any]],
    units: dict[int, dict[str, Any]],
    failed: list[str],
    unresolved: list[dict[str, Any]],
) -> int:
    parsed_count = 0
    for page in pages:
        title = str(page.get("title") or "")
        if page.get("missing"):
            failed.append(title or "<missing>")
            continue
        revisions = page.get("revisions") or []
        content = ""
        if revisions:
            slots = revisions[0].get("slots") or {}
            main = slots.get("main") or {}
            content = str(main.get("content") or "")
        parsed = _parse_wikitext(content, title) if content else None
        if not parsed:
            failed.append(title or "<no-title>")
            continue
        uid = int(parsed.get("uid") or 0)
        if uid > 0:
            units[uid] = parsed
            parsed_count += 1
        else:
            # 新角色页可能还没填 角色ID，先按标题/片假名留待后面映射。
            unresolved.append(parsed)
    return parsed_count


async def _sleep_between_requests() -> None:
    await asyncio.sleep(random.uniform(*BATCH_DELAY))


async def _fetch_chunk(
    session: aiohttp.ClientSession,
    titles: list[str],
    units: dict[int, dict[str, Any]],
    failed: list[str],
    unresolved: list[dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """抓一批；整批失败递归拆半，单页失败 3 次、每次间隔 3 秒。"""

    if not titles:
        return
    try:
        pages = await _fetch_pages(session, titles)
        _consume_pages(pages, units, failed, unresolved)
        report["batches_ok"] = int(report.get("batches_ok") or 0) + 1
        await _sleep_between_requests()
        return
    except Exception:  # noqa: BLE001
        pass

    if len(titles) == 1:
        title = titles[0]
        last_error = ""
        for attempt in range(SINGLE_RETRIES):
            try:
                pages = await _fetch_pages(session, [title])
                _consume_pages(pages, units, failed, unresolved)
                report["single_ok"] = int(report.get("single_ok") or 0) + 1
                await _sleep_between_requests()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < SINGLE_RETRIES - 1:
                    await asyncio.sleep(SINGLE_RETRY_SLEEP)
        failed.append(title)
        report.setdefault("errors", []).append(f"{title}：{last_error}")
        await asyncio.sleep(SINGLE_RETRY_SLEEP)
        return

    mid = len(titles) // 2
    await _sleep_between_requests()
    await _fetch_chunk(session, titles[:mid], units, failed, unresolved, report)
    await _fetch_chunk(session, titles[mid:], units, failed, unresolved, report)


def _load_cache(cache_path: Path) -> dict[int, dict[str, Any]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    raw_units = payload.get("units")
    if not isinstance(raw_units, dict):
        return {}
    units: dict[int, dict[str, Any]] = {}
    for key, value in raw_units.items():
        try:
            uid = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("uid"):
            units[uid] = value
    return units


def _save_cache(
    cache_path: Path,
    units: dict[int, dict[str, Any]],
    *,
    failed_pages: list[str],
    titles_total: int,
    complete: bool,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": _now(),
        "units": {str(uid): units[uid] for uid in sorted(units)},
        "failed_pages": failed_pages,
        "titles_total": titles_total,
        "complete": bool(complete),
    }
    tmp = cache_path.with_name(cache_path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, cache_path)


def _resolve_unresolved(
    units: dict[int, dict[str, Any]],
    unresolved: list[dict[str, Any]],
    failed: list[str],
    known_characters: list[dict[str, Any]] | None,
) -> None:
    """部分新角色页没填 角色ID，用 title / 片假名 / 名字对本地角色表。"""

    if not unresolved:
        return
    lookup: dict[str, int] = {}
    for char in known_characters or []:
        try:
            char_id = int(char.get("id", 0))
            uid4 = int(char.get("uid4") or (char_id // 100 if char_id >= 100000 else char_id))
        except (TypeError, ValueError):
            continue
        names = [char.get("name"), char.get("name_jp"), *(char.get("aliases") or [])]
        for name in names:
            key = _lookup_key(str(name or ""))
            if key:
                lookup.setdefault(key, uid4)
    for info in unresolved:
        keys = [
            info.get("title"),
            info.get("name"),
            info.get("short"),
            info.get("kana"),
            *(info.get("aliases") or []),
        ]
        uid4 = next(
            (lookup[key] for key in (_lookup_key(str(value or "")) for value in keys) if key in lookup),
            0,
        )
        if uid4:
            info["uid"] = uid4
            units[uid4] = info
        else:
            failed.append(str(info.get("title") or info.get("name") or "<unresolved>"))


async def fetch_names(
    *,
    force: bool = False,
    cache_path: str | Path = CACHE_PATH,
    timeout: float = 20.0,
    report: dict[str, Any] | None = None,
    known_characters: list[dict[str, Any]] | None = None,
) -> dict[int, dict[str, Any]]:
    """返回 {4 位角色 id: {"name","short","ja","aliases",...}}。

    force=False 且缓存存在时直接读缓存；否则分页拿页名、按 BATCH 小批
    抓正文，失败批次拆单页重试。失败页记录在 report 里，不会中断整批。
    """

    global LAST_REPORT
    report = report if report is not None else {}
    report.clear()
    report.update(
        {
            "cache_used": False,
            "titles": 0,
            "fetched": 0,
            "failed_pages": [],
            "complete": False,
            "errors": [],
        }
    )
    cache_path = Path(cache_path)

    if not force:
        cached = _load_cache(cache_path)
        if cached:
            report["cache_used"] = True
            report["fetched"] = len(cached)
            report["titles"] = len(cached)
            report["complete"] = True
            LAST_REPORT = dict(report)
            return cached

    timeout_obj = aiohttp.ClientTimeout(total=max(10.0, float(timeout)))
    try:
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            titles = await _get_titles(session, report)
            report["titles"] = len(titles)
            if not titles:
                report["errors"].append("没有拿到任何角色页名")
                LAST_REPORT = dict(report)
                return {}

            units: dict[int, dict[str, Any]] = {}
            failed: list[str] = []
            unresolved: list[dict[str, Any]] = []
            for start in range(0, len(titles), BATCH):
                chunk = titles[start : start + BATCH]
                await _fetch_chunk(
                    session,
                    chunk,
                    units,
                    failed,
                    unresolved,
                    report,
                )
                if (start // BATCH) % 5 == 0:
                    print(
                        f"[wiki] {min(start + BATCH, len(titles))}/{len(titles)} 页，"
                        f"解析 {len(units)}，失败 {len(failed)}",
                        flush=True,
                    )
            _resolve_unresolved(
                units,
                unresolved,
                failed,
                known_characters,
            )
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        units = {}
        failed = []
        titles = []

    # 同一 uid 可能被多个页面重复引用，保留先解析到的。
    deduped = {int(uid): value for uid, value in units.items() if uid}
    report["fetched"] = len(deduped)
    report["failed_pages"] = failed
    report["complete"] = bool(deduped) and not failed
    if deduped:
        _save_cache(
            cache_path,
            deduped,
            failed_pages=failed,
            titles_total=report.get("titles", 0),
            complete=report["complete"],
        )
    LAST_REPORT = dict(report)
    return deduped


def merge_into(characters: list[dict[str, Any]], wiki: dict[int, dict[str, Any]]) -> int:
    """把 wiki 的中文名/别称合并进角色表，返回名字被更新的角色数。

    只覆盖 name_lang != "zh" 或名字仍是日文的角色；只合并别称，不覆盖
    已有的中文好名字。
    """

    changed = 0
    for char in characters:
        try:
            char_id = int(char.get("id", 0))
            uid4 = int(char.get("uid4") or (char_id // 100 if char_id >= 100000 else char_id))
        except (TypeError, ValueError):
            continue
        info = wiki.get(uid4)
        if not info:
            continue

        short = str(info.get("short") or "").strip()
        full = str(info.get("name") or "").strip()
        display = short or full
        current_name = str(char.get("name") or "").strip()
        current_lang = str(char.get("name_lang") or "")
        can_overwrite = current_lang != "zh" or _looks_japanese(current_name)
        if display and can_overwrite:
            char["name"] = display
            char["name_lang"] = "ja" if _looks_japanese(display) else "zh"
            char["name_source"] = "biligame"
            changed += 1

        aliases = list(char.get("aliases") or [])
        for extra in (short, full, *(info.get("aliases") or [])):
            extra = str(extra or "").strip()
            if extra and extra not in aliases and extra != char.get("name"):
                aliases.append(extra)
        char["aliases"] = aliases

    return changed


def merge_payload(payload: dict[str, Any], wiki: dict[int, dict[str, Any]]) -> int:
    """合并并刷新 characters.json 的 stats / wiki_fetched_at。"""

    characters = payload.get("characters")
    if not isinstance(characters, list):
        return 0
    changed = merge_into(characters, wiki)
    payload["stats"] = {
        "cn": int((payload.get("stats") or {}).get("cn") or 0),
        "us": int((payload.get("stats") or {}).get("us") or 0),
        "zh": sum(1 for c in characters if c.get("name_lang") == "zh"),
        "ja_only": sum(1 for c in characters if c.get("name_lang") == "ja"),
    }
    payload["wiki_fetched_at"] = _now()
    return changed


async def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 biligame PCR wiki 角色名")
    parser.add_argument("--force", action="store_true", help="忽略缓存，强制重抓")
    parser.add_argument("--cache", default=str(CACHE_PATH))
    parser.add_argument("--characters", default=str(CHARACTERS_PATH))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    cache_path = Path(args.cache)
    characters_path = Path(args.characters)
    try:
        payload = json.loads(characters_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        print(f"读取 characters.json 失败：{exc}", flush=True)
        payload = {}
    known_characters = (
        payload.get("characters") if isinstance(payload.get("characters"), list) else []
    )

    report: dict[str, Any] = {}
    wiki = await fetch_names(
        force=args.force,
        cache_path=cache_path,
        timeout=args.timeout,
        report=report,
        known_characters=known_characters,
    )
    print(
        f"页面 {report.get('titles', 0)} 个，解析 {report.get('fetched', 0)} 个，"
        f"失败 {len(report.get('failed_pages') or [])} 个，"
        f"缓存 {'命中' if report.get('cache_used') else '已刷新'}",
        flush=True,
    )
    if report.get("failed_pages"):
        print("失败页：" + "、".join(report["failed_pages"][:20]), flush=True)
    for error in (report.get("errors") or [])[:10]:
        print("错误：" + str(error), flush=True)

    if not wiki:
        print("没有抓到数据，未修改 characters.json", flush=True)
        return
    if not payload:
        print("characters.json 不可用，未合并", flush=True)
        return
    before = (payload.get("stats") or {}).get("zh", 0)
    changed = merge_payload(payload, wiki)
    after = (payload.get("stats") or {}).get("zh", 0)
    ja_only = (payload.get("stats") or {}).get("ja_only", 0)
    payload["updated_at"] = _now()
    tmp = characters_path.with_name(characters_path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, characters_path)
    print(
        f"中文名：{before} → {after}；仅日文名：{ja_only}；"
        f"本次更新名字 {changed} 个；字符数 {len(payload.get('characters') or [])}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
