"""把本地头像目录打成一个可分发的 zip（Release 资产用）。

用法：
    python scripts/pack_avatars.py --src <data>/avatars --out dist/avatars-v1.zip
    python scripts/pack_avatars.py --src <data>/avatars --out avatars-v1.zip --limit 200

zip 内结构（用户解压到 <data>/ 即可）：
    avatars/100101.webp
    avatars/...
    avatars/manifest.json
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}


def main() -> int:
    parser = argparse.ArgumentParser(description="打包头像为 Release 资产")
    parser.add_argument("--src", required=True, help="头像目录")
    parser.add_argument("--out", default="avatars-v1.zip", help="输出 zip 路径")
    parser.add_argument("--limit", type=int, default=0, help="只打前 N 张（0 = 全部）")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        raise SystemExit(f"头像目录不存在：{src}")
    files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"{src} 里没有头像文件")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "count": len(files),
        "source": "https://redive.estertion.win/icon/unit/",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "usage": "解压到 <data>/ 下，使 avatars/ 与 characters.json 同级",
    }
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            zf.write(path, f"avatars/{path.name}")
        zf.writestr("avatars/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"打包 {len(files)} 张 → {out}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
