# 测试

## 本地怎么跑

```bash
pip install -e ".[full,dev]"
pytest -q
ruff check .
pcrjjc selftest
```

三条都应该全绿。CI 跑的是同样的东西。

## 分层

| 层 | 覆盖什么 | 在哪 |
| --- | --- | --- |
| 单元测试 | 角色索引、别称解析、追问状态机、作业响应解析、卡片渲染、字体、路径 | `tests/test_*.py` |
| 合成端到端 | 现场生成 5 张头像 + 一张“截图”，验证「找框 → 脸带比对」返回 5 个格子 | `tests/test_recognize.py` |
| 命令行自检 | `pcrjjc selftest`：数据完整性、位置编号、字体、卡片能否生成 | `pcrjjc/cli.py` |
| CI | 3 个 Python 版本 × Windows/Linux、lint、数据校验、构建、离线 e2e | `.github/workflows/ci.yml` |

## 为什么不用真实截图做测试素材

- 真实截图里有玩家的角色、等级、公会信息，不适合进公开仓库；
- 合成图能精确控制变量（缩放、边框、遮挡），回归时更容易定位是哪一步退化。

`scripts/make_fixtures.py` 能现场生成这套素材，想看效果：

```bash
python scripts/make_fixtures.py --out /tmp/pcr-fixtures
# 输出 avatars/100701.webp … 与 screenshot.png
pcrjjc recognize -i /tmp/pcr-fixtures/screenshot.png --avatars /tmp/pcr-fixtures/avatars
```

## 识别回归怎么判断有没有退化

`tests/test_recognize.py` 断言的是：

1. 5 个格子全部找到（`len(team.slots) == 5`）；
2. 每个格子的 `char_id` 都在预期集合里；
3. 最高分 ≥ 0.9（合成图几乎是原图，分数应该很高）。

如果哪天改了检测参数导致找不到框，第 1 条会直接红；改了归一化导致分数掉，第 3 条会红。

## CI 矩阵

```yaml
python: ["3.10", "3.11", "3.12", "3.13"]
os: [ubuntu-latest, windows-latest]
```

另外两个独立 job：

- `data`：校验 `characters.json` 的 id 唯一、6 位、每个角色至少一个名字；
- `offline-e2e`：装 wheel → `pcrjjc selftest` → `pcrjjc arena --ids ...`（用假后端，不联网）。

`nightly-live` 每周跑一次真实网络（pcrdfans / estertion），失败只发通知，不阻塞 PR。

## 加测试的约定

- 只测公开行为，不测私有函数名；
- 需要网络的用例必须打 `@pytest.mark.network` 并从默认运行里排除；
- 任何 `except Exception: pass` 的地方都要有一个用例覆盖“失败时用户看到什么”。
