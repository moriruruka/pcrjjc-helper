"""pytest 公共夹具：把核心包加进 sys.path，并给每个用例一份干净的数据目录。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "astrbot_plugin_pcrjjc"
DATA = PLUGIN / "pcrjjc" / "data"

if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """复制一份种子数据到临时目录，并通过环境变量指过去。"""

    target = tmp_path / "pcrdata"
    target.mkdir()
    from pcrjjc.paths import SEED_FILES

    for name in SEED_FILES:
        src = DATA / name
        if src.is_file():
            shutil.copy2(src, target / name)
    monkeypatch.setenv("PCRJJC_DATA_DIR", str(target))
    return target


@pytest.fixture(scope="session")
def seed_dir() -> Path:
    return DATA


def require_vision() -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
