# 参与开发

## 环境准备

```bash
git clone https://github.com/moriruruka/pcrjjc-helper.git
cd pcrjjc-helper
python -m venv .venv
```

激活虚拟环境：Windows 使用 `.venv/Scripts/activate.bat`，macOS/Linux 使用 `source .venv/bin/activate`。

```bash
pip install -e ".[full,dev]"
pytest -q
pcrjjc selftest
```

## 代码约定

- 核心库 `astrbot_plugin_pcrjjc/pcrjjc/` 不引入任何 bot 框架；平台相关内容放在适配器中。
- 新增依赖需谨慎：能用 Pillow 时不引入 numpy，能用标准库时不引入三方库。
- 面向用户的文案使用中文，变量名与日志使用英文。
- 提交前 `ruff check .` 与 `pytest -q` 必须通过，CI 执行相同检查。

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `astrbot_plugin_pcrjjc/pcrjjc/` | 核心库，可独立安装 |
| `astrbot_plugin_pcrjjc/main.py` | AstrBot 适配器 |
| `astrbot_plugin_pcrjjc/pcrjjc/data/` | 角色表等种子数据 |
| `scripts/` | 头像下载、数据刷新、测试素材生成、浏览器查询服务 |
| `tests/` | pytest 用例，离线运行 |

## 提交信息

使用 `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:` 前缀，后接一句话说明，例如：

```
feat: 支持排除一个角色后重新查询
```
