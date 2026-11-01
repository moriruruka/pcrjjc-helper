<p align="center">
  <img src="assets/logo.jpg" alt="pcrjjc-helper" width="180">
</p>

<h1 align="center">pcrjjc-helper</h1>

<p align="center">公主连结竞技场作业查询：发一句话或一张截图，拿回一张作业卡片。</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10--3.13-blue">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="tests" src="https://github.com/moriruruka/pcrjjc-helper/actions/workflows/ci.yml/badge.svg">
</p>

---

## 它是什么

`pcrjjc-helper` 把「查公主连结竞技场作业」拆成两层：

- **核心库 `pcrjjc`**：角色索引、截图识别、作业查询、卡片渲染、追问状态机。不依赖任何 bot 框架。
- **适配器**：目前提供 AstrBot 插件与命令行。想接 OneBot v11 / QQ 官方 / Telegram / WeCom，可以只调用核心库。

三种用法，选一个就够：

| 你是 | 怎么用 | 需要什么 |
| --- | --- | --- |
| 只想知道某个阵容怎么打 | `pcrjjc arena -n 布丁,克总` | Python 3.10+ |
| 想让它进群，发图就能查 | AstrBot 插件 | AstrBot 4.16+ |
| 想二次开发 | `import pcrjjc` | 同上 |

## 三分钟跑起来

```bash
git clone https://github.com/moriruruka/pcrjjc-helper.git
cd pcrjjc-helper
pip install -e ".[full]"        # 只要文字查询可以装 .[lite]
pcrjjc selftest                 # 应输出 15/15 通过
pcrjjc arena -n 布丁,克总
```

想要图片卡片，再补一次头像（约 15 MB，770 张左右）：

```bash
pcrjjc avatars
pcrjjc arena -n 布丁,克总 --json   # 先看数据结构，卡片由适配器渲染
```

AstrBot 用户看 [docs/INSTALL.md](docs/INSTALL.md)，里面有插件目录、依赖、头像下载与首次自检的完整步骤。

## 能做什么

- **文字查作业**：`布丁`、`克总`、`宫紫`（错字也能认）、`107101`、日文名、英文名都能解析。
- **截图识阵容**：从竞技场截图里找出 5 个头像框，逐个比对本地头像库，给出置信度。
- **作业卡片**：赞踩比 / 时间 / 命中数排序，三种名字显示模式（黑话 / 官译 / 不显示）。
- **查不到就追问**：回 `1` 排除一个角色再查，回 `2` 换一个角色再查；有轮数上限与超时保护。
- **纯文字降级**：没装 numpy / OpenCV 时自动关闭截图入口，文字查询不受影响。

## 平台支持

| 能力 | 命令行 | AstrBot（OneBot v11 / QQ 官方 / Telegram / Lark / WeCom） |
| --- | --- | --- |
| 文字查作业 | ✅ | ✅ |
| 截图识阵容 | ✅（需要 full 依赖） | ✅ |
| 图片卡片 | 渲染到文件 | ✅ |
| 追问 1/2 | 不提供（无会话） | ✅ |
| 自动更新角色表 | `pcrjjc refresh` | ✅（每 7 天） |

## 数据与素材

- 角色表 `characters.json`（353 个角色）随包发布，不含任何账号信息。
- 头像**不入库**：用 `pcrjjc avatars` 从 CDN 下载，或从 [Release](../../releases) 的 `avatars-v1.zip` 解压到数据目录。
- 角色名与头像素材版权归 Cygames, Inc.；本仓库只提供工具，不提供素材文件。

细节见 [docs/DATA.md](docs/DATA.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | AstrBot 插件安装、依赖、头像、首次自检 |
| [docs/USAGE.md](docs/USAGE.md) | 全部指令、追问流程、22 个配置项 |
| [docs/DATA.md](docs/DATA.md) | 角色表字段、头像来源、每周数据刷新 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层、识别算法、为什么不内置视觉模型 |
| [docs/TESTING.md](docs/TESTING.md) | 测试分层、怎么造合成素材、CI 矩阵 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 常见故障对照表 |

## 开发

```bash
pip install -e ".[full,dev]"
ruff check .
pytest -q
```

贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全相关见 [SECURITY.md](SECURITY.md)。许可：[MIT](LICENSE)。
