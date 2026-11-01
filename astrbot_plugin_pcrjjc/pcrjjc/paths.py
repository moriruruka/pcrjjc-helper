"""数据目录解析：环境变量 > 包内置种子数据 > 用户目录。

优先级刻意做成这样，是为了同时满足三种用法：

1. 测试/CI：``PCRJJC_DATA_DIR`` 指到临时目录，不污染真实数据。
2. 源码运行（``python -m pcrjjc``）：直接用包里的 ``data/``，开箱即用。
3. 装在 AstrBot / 服务器里：包目录只读，写入落到用户数据目录。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ENV_DATA_DIR = "PCRJJC_DATA_DIR"

SEED_FILES = (
    "characters.json",
    "aliases_extra.json",
    "aliases_remove.json",
    "ai_names.json",
    "wiki_names.json",
)


def env_data_dir() -> Path | None:
    """读 ``PCRJJC_DATA_DIR``；没设置就返回 None。"""

    raw = (os.environ.get(ENV_DATA_DIR) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def seed_data_dir() -> Path:
    """包内自带的种子数据目录（角色表等，只读）。"""

    return Path(__file__).resolve().parent / "data"


def user_data_dir(name: str = "pcrjjc") -> Path:
    """平台惯例的用户数据目录。"""

    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / name


def is_source_checkout() -> bool:
    """判断是不是“从仓库直接跑”（而不是 pip 装在 site-packages 里）。"""

    # pcrjjc/ -> astrbot_plugin_pcrjjc/ -> 仓库根
    repo = seed_data_dir().parents[1]
    return (repo / "pyproject.toml").is_file() or (repo.parent / "pyproject.toml").is_file()


def resolve_data_dir(name: str = "pcrjjc") -> Path:
    """选一个可写的数据目录（不会自动创建，调用方自己 mkdir）。"""

    override = env_data_dir()
    if override is not None:
        return override
    if is_source_checkout():
        # 源码运行：直接读写包里的 data（开发期改数据方便，git 也能看到 diff）
        return seed_data_dir()
    # pip 安装：site-packages 通常只读，落到用户数据目录，首次使用再拷种子数据
    return user_data_dir(name)


def seed_missing(target: str | Path) -> list[str]:
    """把包内种子文件补进 ``target``，返回补了哪些。已存在的不覆盖。"""

    dest = Path(target)
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    seed = seed_data_dir()
    for name in SEED_FILES:
        src = seed / name
        if not src.is_file():
            continue
        out = dest / name
        if out.exists():
            continue
        shutil.copy2(src, out)
        copied.append(name)
    return copied


def avatars_dir(data_dir: str | Path) -> Path:
    """头像目录（不在种子数据里，首次按需下载）。"""

    return Path(data_dir) / "avatars"


def meta_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "meta.json"
