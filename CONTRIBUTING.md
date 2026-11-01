# 参与开发

## 本地跑起来

```bash
git clone https://github.com/moriruruka/pcrjjc-helper.git
cd pcrjjc-helper
python -m venv .venv
```

激活虚拟环境：Windows 用 `.venv/Scripts/activate.bat`，macOS/Linux 用 `source .venv/bin/activate`。

```bash
pip install -e ".[full,dev]"
pytest -q
pcrjjc selftest
```

## 代码约定

- 核心库 `astrbot_plugin_pcrjjc/pcrjjc/` **不引入任何 bot 框架**；平台相关的东西放进适配器。
- 新增依赖要克制：能只用 Pillow 就别引 numpy，能用标准库就别引三方库。
- 对外文案用中文，变量名与日志用英文。
- 提交前 `ruff check .` 与 `pytest -q` 必须全绿（CI 会跑同样的东西）。

## 目录速查

| 路径 | 作用 |
| --- | --- |
| `astrbot_plugin_pcrjjc/pcrjjc/` | 核心库（可单独 pip 安装） |
| `astrbot_plugin_pcrjjc/main.py` | AstrBot 适配器 |
| `astrbot_plugin_pcrjjc/pcrjjc/data/` | 角色表等种子数据 |
| `scripts/` | 头像下载、数据刷新、测试素材生成 |
| `tests/` | pytest 用例（离线、不联网） |

## 提交信息

`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:` + 一句话说明，例如：

```
feat: 支持「排除一个角色」后再查一次
```
