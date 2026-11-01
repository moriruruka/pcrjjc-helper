#!/usr/bin/env python3
"""本地更新角色表，并按维护者身份提交。

适用场景：不想依赖 GitHub Actions 的定时任务，或想在提交前人工核对改动。

用法：
    python scripts/update_dataset.py                 # 只刷新角色表，不提交
    python scripts/update_dataset.py --commit        # 刷新并提交（作者/提交者固定为维护者）
    python scripts/update_dataset.py --commit --push # 刷新、提交并推送
    python scripts/update_dataset.py --avatars       # 顺带下载头像到数据目录（不入库）

提交身份固定为：
    Aria_Luna <80839392+moriruruka@users.noreply.github.com>

这样无论用哪个 git 客户端执行，提交都会正确归属到仓库维护者。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "astrbot_plugin_pcrjjc"
DATA = PLUGIN / "pcrjjc" / "data"

sys.path.insert(0, str(PLUGIN))

from pcrjjc import pcr_data, pcr_wiki  # noqa: E402

AUTHOR_NAME = "Aria_Luna"
AUTHOR_EMAIL = "80839392+moriruruka@users.noreply.github.com"
COMMIT_MESSAGE = "chore(data): 更新角色表（{date}）"
TRACKED_FILES = (
    "astrbot_plugin_pcrjjc/pcrjjc/data/characters.json",
    "astrbot_plugin_pcrjjc/pcrjjc/data/wiki_names.json",
)


def _git(*args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def refresh() -> dict:
    """抓 /units，合并 wiki 中文名与旧版中文名，写回 characters.json。"""

    previous = pcr_data.load_characters(DATA / "characters.json")
    print("抓取 https://pcrdfans.com/units …")
    units = pcr_data.fetch_units_page(DATA / "units_site.json", timeout=30)
    payload = pcr_data.build_characters_from_units(
        units,
        aliases_extra=pcr_data.load_aliases_extra(DATA / "aliases_extra.json"),
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    wiki = asyncio.run(pcr_wiki.fetch_names(force=False, cache_path=DATA / "wiki_names.json"))
    chars = payload.get("characters") or []
    changed = pcr_wiki.merge_into(chars, wiki) if wiki else 0
    print(f"  biligame 补名：{changed} 个")

    restored = pcr_data.merge_previous_names(payload, previous)
    if restored:
        print(f"  保留旧版中文名：{restored} 个")

    pcr_data.save_characters(DATA / "characters.json", payload)
    total = len(chars)
    zh = sum(1 for item in chars if item.get("name_lang") == "zh")
    print(f"写入 characters.json：{total} 个角色，其中中文名 {zh} 个")
    return payload


def download_avatars() -> None:
    preset = os.environ.get("PYTHON", sys.executable)
    proc = subprocess.run(
        [preset, "-m", "pcrjjc", "avatars", "--data-dir", str(DATA)],
        cwd=PLUGIN,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print("下载头像失败，可用 `pcrjjc avatars` 重试")


def commit_and_push(push: bool) -> int:
    code, diff = _git("status", "--porcelain", "--", *TRACKED_FILES)
    if code != 0:
        print(diff)
        return 1
    if not diff:
        print("角色表没有变化，跳过提交")
        return 0

    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME=AUTHOR_NAME,
        GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
        GIT_COMMITTER_NAME=AUTHOR_NAME,
        GIT_COMMITTER_EMAIL=AUTHOR_EMAIL,
    )
    code, out = _git("add", "--", *TRACKED_FILES, env=env)
    if code != 0:
        print(out)
        return 1

    message = COMMIT_MESSAGE.format(date=time.strftime("%Y-%m-%d"))
    code, out = _git("commit", "-m", message, env=env)
    print(out)
    if code != 0:
        return 1

    if push:
        code, out = _git("push", "origin", "HEAD", env=env)
        print(out)
        if code != 0:
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地更新角色表并提交")
    parser.add_argument("--commit", action="store_true", help="刷新后自动提交")
    parser.add_argument("--push", action="store_true", help="提交后推送到 origin")
    parser.add_argument("--avatars", action="store_true", help="顺带下载头像到数据目录")
    parser.add_argument("--dry-run", action="store_true", help="只抓取并打印统计，不写文件")
    args = parser.parse_args(argv)

    if args.push and not args.commit:
        parser.error("--push 需要同时指定 --commit")

    if args.dry_run:
        units = pcr_data.fetch_units_page(DATA / "units_site.json", timeout=30)
        payload = pcr_data.build_characters_from_units(units)
        chars = payload["characters"]
        print(f"dry-run：{len(chars)} 个角色，中文名 {sum(1 for c in chars if c.get('name_lang') == 'zh')} 个")
        return 0

    refresh()
    if args.avatars:
        download_avatars()
    if args.commit:
        return commit_and_push(args.push)
    print("未提交（需要提交请加 --commit）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
