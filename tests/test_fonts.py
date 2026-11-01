"""字体查找：至少能拿到一个可用字体，且支持环境变量覆盖。"""

from __future__ import annotations

from pathlib import Path

from pcrjjc import fonts


def test_load_returns_font():
    font = fonts.load(20)
    assert hasattr(font, "getbbox")


def test_load_cached_same_object():
    assert fonts.load(18) is fonts.load(18)


def test_bold_falls_back_gracefully():
    font = fonts.load(16, bold=True)
    assert hasattr(font, "getbbox")


def test_describe_reports_path_or_none():
    info = fonts.describe()
    assert "font" in info
    assert info["font"] is None or Path(str(info["font"])).is_file()


def test_env_override(tmp_path, monkeypatch, seed_dir):
    # 随便指一个不存在的路径：应该忽略它并继续用系统字体，而不是崩
    monkeypatch.setenv(fonts.ENV_FONT, str(tmp_path / "missing.ttf"))
    assert hasattr(fonts.load(14), "getbbox")
