<p align="center">
  <img src="assets/logo.jpg" alt="pcrjjc-helper" width="180">
</p>

<h1 align="center">pcrjjc-helper</h1>

<p align="center">公主连结竞技场作业查询：输入角色或截图，输出作业卡片。</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10--3.13-blue">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="ci" src="https://github.com/moriruruka/pcrjjc-helper/actions/workflows/ci.yml/badge.svg">
</p>

---

## 概览

`pcrjjc-helper` 把竞技场作业查询拆成可复用的两层：

- **核心库 `pcrjjc`**：角色索引、截图识别、作业查询、卡片渲染、追问状态机，不依赖任何 bot 框架。
- **适配器**：AstrBot 插件与命令行。接入 OneBot v11、QQ 官方机器人、Telegram 或 WeCom 时，可直接调用核心库。

| 场景 | 使用方式 | 依赖 |
| --- | --- | --- |
| 在终端查作业 | `pcrjjc arena -n 布丁,克总` | Python 3.10+ |
| 接入群聊 | AstrBot 插件 | AstrBot 4.16+ |
| 二次开发 | `import pcrjjc` | 同上 |

## 快速开始

```bash
git clone https://github.com/moriruruka/pcrjjc-helper.git
cd pcrjjc-helper
pip install -e ".[full]"        # 仅文字查询可改用 .[lite]
pcrjjc selftest                 # 期望输出 15/15 通过
pcrjjc arena -n 布丁,克总
```

渲染图片卡片还需下载头像（约 15 MB，770 余张）：

```bash
pcrjjc avatars
pcrjjc arena -n 布丁,克总 --json   # 查看数据结构；卡片由适配器渲染
```

AstrBot 的安装步骤见 [docs/INSTALL.md](docs/INSTALL.md)，包含插件目录、依赖、头像与首次自检。

### 性能与加速

配置本机浏览器服务后，单次查询约 3 秒返回卡片；未配置 API key 与浏览器服务时，需要等待匿名接口超时。

```bash
pip install playwright && python -m playwright install msedge
python scripts/browser_bridge.py --login   # 首次登录作业网，仅此一次会显示窗口
python scripts/browser_bridge.py           # 之后以 headless 模式常驻，无可见窗口
```

随后在插件配置中将 `browser_endpoint` 设为 `http://127.0.0.1:6191`。完整说明见 [docs/USAGE.md](docs/USAGE.md#性能与加速)。

## 功能

- **文字查询**：支持角色原名、日文名、英文名、B 服译名与黑话别称，允许一个字的错写；也可直接输入 6 位角色 id。
- **截图识别**：在竞技场截图中定位 5 个头像框，与本地头像库比对并给出置信度。
- **作业卡片**：按赞踩比、时间或点赞数排序，支持三种名字显示模式（黑话、官译、不显示）。
- **追问流程**：未查到作业时可回复 `1` 排除一个角色，或回复 `2` 替换一个角色；含轮数上限与超时保护。
- **降级运行**：未安装 numpy 与 OpenCV 时自动关闭截图入口，文字查询不受影响。

## 平台支持

| 能力 | 命令行 | AstrBot（OneBot v11 / QQ 官方 / Telegram / Lark / WeCom） |
| --- | --- | --- |
| 文字查询 | ✅ | ✅ |
| 截图识别 | ✅（需 full 依赖） | ✅ |
| 图片卡片 | 渲染到文件 | ✅ |
| 追问流程 | —（无会话） | ✅ |
| 角色表更新 | `pcrjjc refresh` | ✅（默认每 7 天） |

## 数据与素材

- 角色表 `characters.json`（353 个角色）随包发布，不含账号信息。
- 头像不随仓库分发：可通过 `pcrjjc avatars` 从 CDN 下载，或解压 [Release](../../releases) 中的 `avatars-v1.zip` 到数据目录。
- 角色名与头像素材版权归 Cygames, Inc.；仓库仅提供工具。

详见 [docs/DATA.md](docs/DATA.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | AstrBot 插件安装、依赖、头像、首次自检 |
| [docs/USAGE.md](docs/USAGE.md) | 指令、追问流程、配置项 |
| [docs/DATA.md](docs/DATA.md) | 角色表字段、头像来源、周期刷新 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层设计、识别算法、依赖取舍 |
| [docs/TESTING.md](docs/TESTING.md) | 测试分层、合成素材、CI 矩阵 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 故障对照表 |

## 开发

```bash
pip install -e ".[full,dev]"
ruff check .
pytest -q
```

贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全说明见 [SECURITY.md](SECURITY.md)。许可：[MIT](LICENSE)。
