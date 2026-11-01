"""命令行：selftest 必须离线通过，doctor 不崩，arena 在没服务时给清晰错误。"""

from __future__ import annotations

from pathlib import Path

from pcrjjc import cli


def test_selftest_passes_offline(data_dir: Path, capsys):
    rc = cli.main(["--data-dir", str(data_dir), "selftest", "--offline"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "通过" in out


def test_doctor_reports_environment(data_dir: Path, capsys):
    rc = cli.main(["--data-dir", str(data_dir), "doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "数据目录" in out
    assert "角色表" in out


def test_arena_without_backend_fails_cleanly(data_dir: Path, capsys, monkeypatch):
    monkeypatch.delenv("PCRJJC_BROWSER_ENDPOINT", raising=False)
    monkeypatch.setenv("PCRJJC_AUTH_KEY", "")
    rc = cli.main(["--data-dir", str(data_dir), "arena", "--names", "布丁,克总", "--timeout", "3"])
    captured = capsys.readouterr()
    assert rc in (1, 3)
    assert "布丁" not in captured.err or "作业" in captured.out + captured.err


def test_arena_unknown_names_exits_2(data_dir: Path, capsys):
    rc = cli.main(["--data-dir", str(data_dir), "arena", "--names", "完全不存在的角色"])
    assert rc == 2


def test_avatars_dry_run_lists_work(data_dir: Path, capsys):
    rc = cli.main(["--data-dir", str(data_dir), "avatars", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "缺" in out


def test_version_flag(capsys):
    try:
        cli.main(["--version"])
    except SystemExit as exc:  # argparse 正常退出
        assert exc.code == 0
    assert "pcrjjc" in capsys.readouterr().out
