"""``pcrjjc`` 命令行：不装 bot 也能查作业、认头像、拉头像、刷数据。

用法示例::

    pcrjjc arena --names 布丁,克总,真琴,纺希,莉莎
    pcrjjc recognize --image shot.png --avatars D:\\pcrjjc\\avatars
    pcrjjc avatars --data-dir D:\\pcrjjc --jobs 8
    pcrjjc refresh --data-dir D:\\pcrjjc
    pcrjjc selftest --offline

之所以提供命令行，是因为它同时是 CI 的验收工具：任何一次提交都要能在这里
跑通，才说明核心库没有退化。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, fonts, pcr_data

DEFAULT_ICON_SOURCE = "https://redive.estertion.win/icon/unit/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# 公共
# --------------------------------------------------------------------------- #
def _data_dir(explicit: str | None) -> Path:
    from .paths import resolve_data_dir, seed_missing

    target = Path(explicit).expanduser().resolve() if explicit else resolve_data_dir()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / "characters.json").is_file():
        seed_missing(target)
    return target


def _index(data_dir: Path) -> pcr_data.CharacterIndex:
    path = data_dir / "characters.json"
    payload = pcr_data.load_characters(path)
    if payload is None:
        raise SystemExit(
            f"找不到角色表：{path}\n"
            "先跑 `pcrjjc refresh` 生成，或从仓库 data/ 目录复制一份 characters.json。"
        )
    return pcr_data.CharacterIndex(payload)


def _split_names(raw: str) -> list[str]:
    out: list[str] = []
    for chunk in raw.replace("，", ",").replace("、", ",").split(","):
        out.extend(part for part in chunk.split() if part)
    return out


def _resolve_team(index: pcr_data.CharacterIndex, names: list[str]) -> tuple[list[int], list[str]]:
    ids: list[int] = []
    missing: list[str] = []
    for name in names:
        char_id = index.resolve_token(name)
        if char_id is None:
            missing.append(name)
        elif char_id not in ids:
            ids.append(char_id)
    return ids, missing


def _entry_line(index: pcr_data.CharacterIndex, entry: dict, limit: int = 5) -> str:
    members = entry.get("defense") or entry.get("def") or []
    names = []
    for item in members[:limit]:
        raw = item.get("id") if isinstance(item, dict) else item
        try:
            char = index.by_id.get(int(raw))
        except (TypeError, ValueError):
            char = None
        names.append(char.display_name if char else str(raw))
    ratio = ""
    up, down = entry.get("up"), entry.get("down")
    if isinstance(up, int) and isinstance(down, int):
        ratio = f" {up}/{down}"
    views = entry.get("views")
    tail = f" 浏览{views}" if isinstance(views, int) else ""
    return f"{' '.join(names)}{ratio}{tail}"


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_arena(args: argparse.Namespace) -> int:
    data_dir = _data_dir(args.data_dir)
    index = _index(data_dir)
    if args.ids:
        ids = [int(x) for x in _split_names(args.ids)]
    else:
        ids, missing = _resolve_team(index, _split_names(args.names or ""))
        if missing:
            print(f"没认出来的角色：{', '.join(missing)}", file=sys.stderr)
        if not ids:
            print("没有可查询的角色", file=sys.stderr)
            return 2

    from .arena_api import ArenaClient, ArenaError

    client = ArenaClient(
        auth_key=os.environ.get("PCRJJC_AUTH_KEY", ""),
        region=int(os.environ.get("PCRJJC_REGION", args.region)),
        timeout=float(os.environ.get("PCRJJC_TIMEOUT", args.timeout)),
        browser_endpoint=os.environ.get("PCRJJC_BROWSER_ENDPOINT", args.browser or ""),
    )

    async def run() -> list[dict]:
        entries = await client.search(ids, allow_missing_auth=True)
        return entries

    started = time.monotonic()
    try:
        entries = asyncio.run(run())
    except ArenaError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("没查到作业（可能是冷门阵容，或作业网限流）")
        return 1
    print(f"共 {len(entries)} 支队伍，用时 {time.monotonic() - started:.1f}s")
    for i, entry in enumerate(entries[: args.limit], 1):
        print(f"  {i}. {_entry_line(index, entry)}")
    return 0


def cmd_recognize(args: argparse.Namespace) -> int:
    from PIL import Image

    from .image_match import AvatarLibrary, ImageRecognizer

    data_dir = _data_dir(args.data_dir)
    avatars = Path(args.avatars) if args.avatars else data_dir / "avatars"
    if not avatars.is_dir():
        print(f"头像目录不存在：{avatars}（先跑 `pcrjjc avatars`）", file=sys.stderr)
        return 2
    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"图片不存在：{image_path}", file=sys.stderr)
        return 2

    library = AvatarLibrary(avatars)
    recognizer = ImageRecognizer(library, threshold=args.threshold)
    image = Image.open(image_path)
    result = recognizer.recognize(image, max_ids=args.max_ids)

    index = _index(data_dir)
    if args.json:
        payload = [
            {
                "team": team.team_no,
                "slots": [
                    {"slot": s.index + 1, "id": s.char_id, "score": round(s.score, 4)}
                    for s in team.slots
                ],
            }
            for team in result.teams
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not result.teams:
        print(f"没找到头像框（库里 {result.library_count} 张头像）：{result.note}")
        return 1
    for team in result.teams:
        names = []
        for slot in team.slots:
            char = index.by_id.get(slot.char_id) if slot.char_id else None
            label = char.display_name if char else "?"
            names.append(f"{label}({slot.score:.2f})")
        print(f"第 {team.team_no} 队：{'  '.join(names)}")
    return 0


def cmd_avatars(args: argparse.Namespace) -> int:
    data_dir = _data_dir(args.data_dir)
    target = Path(args.dest) if args.dest else data_dir / "avatars"
    target.mkdir(parents=True, exist_ok=True)
    index = _index(data_dir)

    ids: list[int] = []
    if args.only:
        ids, missing = _resolve_team(index, _split_names(args.only))
        if missing:
            print(f"没认出来的角色：{', '.join(missing)}", file=sys.stderr)
    if not ids:
        ids = [char.id for char in index.characters]

    pending = [cid for cid in ids if not _avatar_exists(target, cid)]
    print(f"目标目录 {target}：共 {len(ids)} 个角色，缺 {len(pending)} 张")
    if args.dry_run or not pending:
        return 0

    import aiohttp

    source = args.source or os.environ.get("PCRJJC_ICON_SOURCE", DEFAULT_ICON_SOURCE)
    if not source.endswith("/"):
        source += "/"
    timeout = aiohttp.ClientTimeout(total=float(args.timeout))

    async def one(session: aiohttp.ClientSession, sem: asyncio.Semaphore, char_id: int) -> bool:
        async with sem:
            for ext in (".webp", ".png"):
                url = f"{source}{char_id}{ext}"
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.read()
                        if len(data) < 512:
                            continue
                        (target / f"{char_id}{ext}").write_bytes(data)
                        return True
                except Exception:  # noqa: BLE001 - 单张失败不影响整体
                    continue
            return False

    async def run() -> tuple[int, int]:
        headers = {"User-Agent": USER_AGENT}
        sem = asyncio.Semaphore(max(1, args.jobs))
        ok = bad = 0
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for i, char_id in enumerate(pending, 1):
                success = await one(session, sem, char_id)
                ok += 1 if success else 0
                bad += 0 if success else 1
                if i % 25 == 0 or i == len(pending):
                    print(f"  进度 {i}/{len(pending)}（成功 {ok}）")
        return ok, bad

    ok, bad = asyncio.run(run())
    print(f"完成：下载 {ok}，失败 {bad}")
    return 0 if bad == 0 else 1


def _avatar_exists(folder: Path, char_id: int) -> bool:
    return any((folder / f"{char_id}{ext}").is_file() for ext in (".webp", ".png", ".jpg", ".jpeg"))


def cmd_refresh(args: argparse.Namespace) -> int:
    data_dir = _data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    chars_path = data_dir / "characters.json"
    units_path = data_dir / "units_site.json"
    print(f"抓取 {pcr_data.UNITS_URL if not args.url else args.url} …")
    try:
        units = pcr_data.fetch_units_page(units_path, timeout=args.timeout, url=args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"抓取失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    unit_object = units.get("unitObject") or {}
    print(f"  units: {len(unit_object)} 个（cache_used={units.get('cache_used')}）")
    payload = pcr_data.write_characters_from_units(
        chars_path,
        units,
        aliases_extra=pcr_data.load_aliases_extra(data_dir / "aliases_extra.json"),
    )
    chars = payload.get("characters", [])
    cn = sum(1 for c in chars if any("\u4e00" <= ch <= "\u9fff" for ch in (c.get("cn") or c.get("name") or "")))
    print(f"写入 {chars_path}：{len(chars)} 个角色（中文名 {cn}）")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from PIL import Image

    from . import dialog

    checks: list[tuple[str, bool, str]] = []

    data_dir = _data_dir(args.data_dir)

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    payload = pcr_data.load_characters(data_dir / "characters.json")
    chars = (payload or {}).get("characters") or []
    check("角色表可读", bool(chars), f"{len(chars)} 个角色")
    ids = [c.get("id") for c in chars]
    check("角色 id 唯一", len(set(ids)) == len(ids), f"{len(set(ids))}/{len(ids)}")
    check("id 都是 6 位", all(isinstance(i, int) and 100000 <= i <= 999999 for i in ids))

    index = pcr_data.CharacterIndex(payload) if payload else None
    if index is not None:
        for alias, _expect in (("布丁", 100701), ("克总", 107101), ("真琴", 100501)):
            got = index.resolve_token(alias)
            check(f"别称 {alias}", got is not None, f"-> {got}")
        check("宫子变体", index.resolve_token("宫子") is not None)

    team = [100701, 107101, 100501, 100901, 101001]
    check("位置编号：最右是前卫", dialog.position_of(len(team), 0) == len(team))
    check("位置转下标", dialog.index_of_position(len(team), len(team)) == 0)
    check("选 1/2 解析", dialog.parse_choice("2") == "2" and dialog.parse_choice("1") == "1")
    check("排除：位置号", dialog.parse_exclude("3号位").position == 3)
    check("排除：角色名", dialog.parse_exclude("排除布丁").name != "")
    check("取消词", dialog.is_cancel("算了"))

    info = fonts.describe()
    check("中文字体", info["font"] is not None, str(info["font"]))

    try:
        from .card_render import render_job_card

        entries = [
            {
                "id": 1,
                "def": [{"id": i} for i in team],
                "up": 12,
                "down": 3,
                "views": 345,
                "updated": int(time.time()),
                "likes": 12,
            }
        ]
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = render_job_card(
                def_ids=team,
                entries=entries,
                out_dir=tmp,
                avatars_dir=data_dir / "avatars",
                name_for=lambda cid, fallback: (index.by_id[cid].display_name if index and cid in index.by_id else fallback),
                official_name_for=lambda cid: (index.by_id[cid].display_name if index and cid in index.by_id else str(cid)),
                show_names="slang",
            )
            img = Image.open(out)
            img.load()
            check("卡片渲染", out.is_file() and img.width > 100, f"{img.width}x{img.height}")
    except Exception as exc:  # noqa: BLE001
        check("卡片渲染", False, f"{type(exc).__name__}: {exc}")

    font = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"{mark} {name}" + (f"  {detail}" if detail else ""))
    print(f"\n{font}/{len(checks)} 通过")
    return 0 if font == len(checks) else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    data_dir = _data_dir(args.data_dir)
    print(f"pcrjjc {__version__}")
    print(f"数据目录  {data_dir}")
    print(f"字体      {fonts.describe()['font']}")
    for name, mod in (("numpy", "numpy"), ("Pillow", "PIL"), ("OpenCV", "cv2"), ("aiohttp", "aiohttp")):
        try:
            __import__(mod)
            print(f"{name:9} 已安装")
        except Exception:  # noqa: BLE001
            print(f"{name:9} 缺失")
    chars_path = data_dir / "characters.json"
    if chars_path.is_file():
        payload = pcr_data.load_characters(chars_path) or {}
        print(f"角色表    {len(payload.get('characters') or [])} 个")
    else:
        print("角色表    缺失（跑 `pcrjjc refresh`）")
    avatars = data_dir / "avatars"
    if avatars.is_dir():
        print(f"头像      {len([p for p in avatars.iterdir() if p.is_file()])} 张")
    else:
        print("头像      未下载（跑 `pcrjjc avatars`）")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcrjjc", description="公主连结竞技场作业查询（命令行）")
    parser.add_argument("--data-dir", help="数据目录（默认取 PCRJJC_DATA_DIR 或包内 data）")
    parser.add_argument("--version", action="version", version=f"pcrjjc {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("arena", help="按角色名查作业")
    p.add_argument("--names", "-n", default="", help="逗号/空格分隔的角色名，如 布丁,克总")
    p.add_argument("--ids", default="", help="直接给 6 位 id（逗号分隔）")
    p.add_argument("--region", default=os.environ.get("PCRJJC_REGION", "1"), help="1=日服 2=台服 3=国服")
    p.add_argument("--timeout", default=os.environ.get("PCRJJC_TIMEOUT", "15"), help="请求超时（秒）")
    p.add_argument("--browser", default="", help="浏览器服务地址，如 http://127.0.0.1:6191")
    p.add_argument("--limit", type=int, default=10, help="最多打印几支队伍")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_arena)

    p = sub.add_parser("recognize", help="从截图识别防守阵容")
    p.add_argument("--image", "-i", required=True)
    p.add_argument("--avatars", help="头像目录（默认 <data>/avatars）")
    p.add_argument("--threshold", type=float, default=0.70)
    p.add_argument("--max-ids", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recognize)

    p = sub.add_parser("avatars", help="批量下载角色头像")
    p.add_argument("--dest", help="目标目录（默认 <data>/avatars）")
    p.add_argument("--only", help="只下这些角色（名字或 id，逗号分隔）")
    p.add_argument("--jobs", type=int, default=6)
    p.add_argument("--timeout", default="20")
    p.add_argument("--source", help="图标源地址")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_avatars)

    p = sub.add_parser("refresh", help="从 pcrdfans 刷新角色表")
    p.add_argument("--timeout", default="25")
    p.add_argument("--url", default="")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("selftest", help="离线自检（CI 用）")
    p.add_argument("--offline", action="store_true", help="不联网（当前实现本来就离线）")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("doctor", help="看环境：依赖、字体、数据")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
