"""作业接口解析：真实响应形状、id 归一化、请求体签名、错误分级。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcrjjc import arena_api

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "arena_payload.json"


def test_normalize_real_payload():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entries = arena_api.normalize_result(payload["data"]["data"])
    assert len(entries) == 2
    first = entries[0]
    assert first["up"] == 12 and first["down"] == 3
    assert [m["id"] for m in first["def"]] == [100201, 110501, 102301, 100101, 114701]
    assert [m["id"] for m in first["atk"]] == [100701, 107101, 100501, 100901, 101001]
    assert entries[1]["up"] == 0 and entries[1]["down"] == 8


def test_normalize_skips_rows_without_attack_team():
    payload = {"result": [{"id": "x", "def": [{"id": 100201}], "up": 1, "down": 0}]}
    assert arena_api.normalize_result(payload) == []


def test_normalize_handles_junk():
    assert arena_api.normalize_result(None) == []
    assert arena_api.normalize_result({"result": "nope"}) == []


def test_payload_uses_uid4_star_one_ids():
    client = arena_api.ArenaClient(auth_key="", region=2)
    body = client._payload([100201, 110501, 114701], page=2, sort=3)
    assert body["def"] == [100201, 110501, 114701]
    assert body["region"] == 2
    assert body["page"] == 2
    assert body["sort"] == 3
    assert isinstance(body["ts"], int)


def test_payload_strips_star_variants():
    client = arena_api.ArenaClient(region=1)
    # 6 位 id 的十位是星级/皮肤位，请求时要归到 uid4*100+1
    assert client._payload([100231], page=1, sort=1)["def"] == [100201]


def test_headers_never_include_empty_auth():
    client = arena_api.ArenaClient(auth_key="")
    headers = client._headers()
    assert headers["authorization"] == ""
    assert headers["referer"].startswith("https://pcrdfans.com")


def test_has_auth_flag():
    assert not arena_api.ArenaClient().has_auth
    assert arena_api.ArenaClient(auth_key="k").has_auth


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, "1010", arena_api.ArenaRateLimitError),
        (403, "cloudflare", arena_api.ArenaRateLimitError),
        (401, "", arena_api.ArenaAuthError),
        (500, "boom", arena_api.ArenaError),
    ],
)
def test_http_error_mapping(status, body, expected):
    err = arena_api.ArenaClient._human_http_error(status, body)
    assert isinstance(err, expected)


def test_auth_error_mentions_configuration():
    err = arena_api.ArenaAuthError(configured=False)
    assert "browser_endpoint" in str(err) or "auth" in str(err).lower()
