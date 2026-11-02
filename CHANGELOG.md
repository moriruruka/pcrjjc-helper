# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

### Added

- README、插件 README 与 `docs/DATA.md` 补充上游致谢：pcrdfans.com（作业数据与查询服务）、
  esterTion（头像 CDN 与解包数据）、AstrBot（机器人框架）。

### Changed

- 角色表更新改为本地命令 `scripts/update_dataset.py`，仓库不再保留自动写数据的 CI。

## [0.1.0] - 2026-11-02

### Added

- 核心库 `pcrjjc`：角色索引、截图识别、作业查询、卡片渲染、追问状态机，**不依赖任何 bot 框架**。
- AstrBot 适配器 `astrbot_plugin_pcrjjc`：`/作业` 指令、关键词触发、自动识图、查不到作业时追问 1/2。
- 命令行 `pcrjjc`：`arena` / `recognize` / `avatars` / `refresh` / `selftest` / `doctor`。
- 跨平台字体查找（Windows / macOS / Linux），支持 `PCRJJC_FONT` 指定字体文件。
- 数据目录解析：`PCRJJC_DATA_DIR` > 包内种子数据 > 系统用户目录。
- 纯文字降级：没装 numpy / opencv 时自动关闭截图入口，文字查询不受影响。
- GitHub Actions：lint、跨平台跨版本单测、数据校验、构建、离线端到端。

### Notes

- 头像不入库：用 `pcrjjc avatars` 从 CDN 下载，或从 Release 的 `avatars-v1.zip` 导入。
- 不包含任何账号、密码、Cookie、代理配置；`browser_endpoint` 只接受你自己搭的服务地址。
