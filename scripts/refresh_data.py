"""刷新角色表（对 `pcrjjc refresh` 的薄包装）。CI 的周更任务也走这个入口。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "astrbot_plugin_pcrjjc"))

from pcrjjc.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["refresh", *sys.argv[1:]]))
