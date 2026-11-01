"""数据目录解析与种子数据补齐。"""

from __future__ import annotations

from pathlib import Path

from pcrjjc import paths


def test_env_override_wins(tmp_path: Path, monkeypatch):
    target = tmp_path / "custom"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    assert paths.resolve_data_dir() == target.resolve()


def test_falls_back_to_seed_without_env(monkeypatch):
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    resolved = paths.resolve_data_dir()
    assert (resolved / "characters.json").is_file()
    # 仓库内运行时应当是源码目录（pyproject.toml 在仓库根）
    assert paths.is_source_checkout() is True


def test_seed_missing_copies_only_absent(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    target = tmp_path / "data"
    target.mkdir()
    (target / "characters.json").write_text("{}", encoding="utf-8")
    copied = paths.seed_missing(target)
    assert "characters.json" not in copied
    assert "aliases_extra.json" in copied
    assert (target / "characters.json").read_text(encoding="utf-8") == "{}"


def test_user_data_dir_is_per_platform(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    folder = paths.user_data_dir("pcrjjc")
    assert folder.name == "pcrjjc"
