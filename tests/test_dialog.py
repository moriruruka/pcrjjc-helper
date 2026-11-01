"""追问状态机：位置编号、1/2 选择、排除 / 替换解析、超时与轮数。"""

from __future__ import annotations

import time

import pytest

from pcrjjc import dialog

TEAM = [100701, 107101, 100501, 100901, 101001]


def test_position_is_counted_from_right():
    # 最右边是前卫 = 1 号位
    assert dialog.position_of(5, 0) == 5
    assert dialog.position_of(5, 4) == 1
    assert dialog.index_of_position(5, 1) == 4
    assert dialog.index_of_position(5, 5) == 0
    assert dialog.index_of_position(5, 6) is None


def test_positions_line_lists_right_to_left():
    line = dialog.positions_line(["宫子", "克莉丝提娜"])
    assert "宫子" in line and "克莉丝提娜" in line


@pytest.mark.parametrize("text", ["1", "一", "选1", "排除", "第一个"])
def test_parse_choice_first(text):
    assert dialog.parse_choice(text) == "1"


@pytest.mark.parametrize("text", ["2", "二", "两", "选2", "替换", "换一个"])
def test_parse_choice_second(text):
    assert dialog.parse_choice(text) == "2"


@pytest.mark.parametrize("text", ["", "嗯", "？", "全部"])
def test_parse_choice_rejects_noise(text):
    assert dialog.parse_choice(text) is None


@pytest.mark.parametrize("text", ["算了", "取消", "不查了", "退出", "停"])
def test_cancel_words(text):
    assert dialog.is_cancel(text)


def test_parse_exclude_by_position():
    req = dialog.parse_exclude("排除3号位")
    assert req.position == 3
    assert req.name == ""


def test_parse_exclude_by_name():
    req = dialog.parse_exclude("把布丁去掉")
    assert req.name
    assert "布丁" in req.name


def test_parse_exclude_empty():
    assert dialog.parse_exclude("").empty


def test_parse_replace_basic():
    req = dialog.parse_replace("把布丁换成克总")
    assert "布丁" in req.who
    assert "克总" in req.new


def test_parse_replace_by_position():
    req = dialog.parse_replace("3号位换成怜")
    assert req.position == 3
    assert "怜" in req.new


def test_parse_replace_empty():
    assert dialog.parse_replace("我不换了").empty


def test_active_trigger_words():
    assert dialog.active_trigger("竞技场阵容排除") == dialog.EXCLUDE
    assert dialog.active_trigger("竞技场阵容替换") == dialog.REPLACE
    assert dialog.active_trigger("阵容排除吧") == dialog.EXCLUDE
    assert dialog.active_trigger("今天天气不错") is None


def test_team_transforms_keep_positions():
    assert dialog.team_after_exclude(TEAM, 100501) == [100701, 107101, 100901, 101001]
    assert dialog.team_after_replace(TEAM, 2, 100201) == [100701, 107101, 100201, 100901, 101001]


def _dialog(timeout: float) -> dialog.Dialog:
    dlg = dialog.Dialog(session="s", sender="u", stage=dialog.CHOOSE, team=list(TEAM), timeout_sec=timeout)
    dlg.touch()
    return dlg


def test_dialog_expires_after_timeout():
    dlg = _dialog(1)
    assert not dlg.expired()
    dlg.deadline = time.monotonic() - 1
    assert dlg.expired()
    assert dlg.left_sec() == 0


def test_dialog_touch_extends():
    dlg = _dialog(60)
    dlg.deadline = time.monotonic() + 5
    dlg.touch()
    assert dlg.left_sec() > 50
