"""下载角色头像（对 `pcrjjc avatars` 的薄包装，方便直接 `python scripts/fetch_avatars.py`）。

例：
    python scripts/fetch_avatars.py                      # 下全部
    python scripts/fetch_avatars.py --only 布丁,克总      # 只下这几个
    python scripts/fetch_avatars.py --dry-run            # 只看缺多少
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "astrbot_plugin_pcrjjc"))

from pcrjjc.cli import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    raise SystemExit(main(["avatars", *args]))
