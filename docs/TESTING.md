# 测试

## 本地运行

```bash
pip install -e ".[full,dev]"
pytest -q
ruff check .
pcrjjc selftest
```

上述命令应全部通过；CI 执行的检查与此一致。

## 分层

| 层 | 覆盖内容 | 位置 |
| --- | --- | --- |
| 单元测试 | 角色索引、别称解析、追问状态机、作业响应解析、卡片渲染、字体、路径、图片可用性判断 | `tests/test_*.py` |
| 合成端到端 | 现场生成 5 张头像与一张「竞技场截图」，验证定位与比对能返回 5 个格子 | `tests/test_recognize.py` |
| 命令行自检 | `pcrjjc selftest`：数据完整性、位置编号、字体、卡片生成 | `pcrjjc/cli.py` |
| CI | Python 3.10–3.13 × Ubuntu/Windows、静态检查、数据校验、构建、安装冒烟、离线端到端 | `.github/workflows/ci.yml` |

## 测试素材

测试使用合成图像，不使用真实游戏截图：

- 真实截图包含玩家角色、等级与公会信息，不适合纳入公开仓库；
- 合成图像可精确控制缩放、边框与遮挡，便于定位回归点。

可用 `scripts/make_fixtures.py` 现场生成：

```bash
python scripts/make_fixtures.py --out /tmp/pcr-fixtures
pcrjjc recognize -i /tmp/pcr-fixtures/screenshot.png --avatars /tmp/pcr-fixtures/avatars
```

## 识别回归判定

`tests/test_recognize.py` 断言以下三点：

1. 5 个格子全部被定位（`len(team.slots) == 5`）；
2. 每个格子的 `char_id` 属于预期集合；
3. 最高分不低于 0.9（合成图接近原图，分数应处于高位）。

检测参数变化导致漏检时第 1 条失败；归一化流程变化导致分数下降时第 3 条失败。

## CI 矩阵

```yaml
python: ["3.10", "3.11", "3.12", "3.13"]
os: [ubuntu-latest, windows-latest]
```

此外包含三个独立作业：

- `data`：校验 `characters.json` 的 id 唯一性、位数与名称完整性；
- `install-smoke`：在干净虚拟环境中安装 wheel 并执行 `pcrjjc selftest`；
- `offline-e2e`：使用合成素材完成识别与卡片渲染，并用离线响应验证作业解析。

`Data refresh` 工作流每周执行一次外部接口巡检，失败不影响主分支状态。

## 编写测试的约定

- 只断言公开行为，不依赖私有函数名；
- 需要网络的用例标记 `@pytest.mark.network`，默认运行中排除；
- 凡有 `except Exception: pass` 的位置，应有一条用例覆盖失败时的用户可见行为。
