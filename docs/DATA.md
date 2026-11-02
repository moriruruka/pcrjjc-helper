# 数据与头像

## 角色表 `characters.json`

随包发布，位于 `astrbot_plugin_pcrjjc/pcrjjc/data/characters.json`，353 个角色 / 约 150 KB。

结构：

```json
{
  "updated_at": "2026-11-01 21:34:01",
  "source": "https://pcrdfans.com/units",
  "stats": { "total": 353, "cn": 320, "ja_only": 2, "us": 113 },
  "characters": [
    {
      "id": 107101,
      "uid4": 1071,
      "name": "克莉丝提娜",
      "name_jp": "クリスティーナ",
      "name_lang": "zh",
      "aliases": ["克总", "克里斯提娜"],
      "servers": ["cn", "us"]
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `id` | 6 位角色 id（`uid4 * 100 + 1` 是“基础形态”） |
| `uid4` | 4 位角色 id，作业网接口用的是这个维度 |
| `name` | 展示名；只有日文名时以 `*` 结尾（`display_name` 会加星号） |
| `name_lang` | `zh` / `ja` / `en` |
| `aliases` | 别称（黑话、错译、旧译），解析时与原名同权 |
| `servers` | 该角色在哪些服可用（`cn` / `us`） |

数据来源：`https://pcrdfans.com/units`（权威单位表）+ `https://wiki.biligame.com/pcr/`（中文名）+ 仓库内的人工别称表 `aliases_extra.json`。

## 头像

- **不入库**。773 张 webp，约 15 MB，来源是第三方 CDN（默认 `https://redive.estertion.win/icon/unit/`）。
- 命名必须是 `<6 位 id>.webp`（或 `.png` / `.jpg`），否则识别库扫不到。
- 三种获取方式：

```bash
# 1) 从 CDN 直接下（默认）
pcrjjc avatars

# 2) 只下指定角色
pcrjjc avatars --only 布丁,克总

# 3) 从 Release 的 avatars-v1.zip 解压到 <data>/avatars
```

- 缺少头像时仍可使用：卡片以占位块代替头像，识别功能会关闭并给出提示。
- `pcrjjc avatars --dry-run` 可以先看缺多少张，不真的下载。

## 数据目录

按优先级：

1. 环境变量 `PCRJJC_DATA_DIR`
2. 包内 `pcrjjc/data/`（源码运行时；也方便 `git diff` 看到数据更新）
3. 系统用户目录：
   - Windows `%LOCALAPPDATA%\pcrjjc`
   - macOS `~/Library/Application Support/pcrjjc`
   - Linux `$XDG_DATA_HOME/pcrjjc`（默认 `~/.local/share/pcrjjc`）

AstrBot 插件里优先用 AstrBot 的插件数据目录（`data/plugin_data/pcrjjc`）。

## 运行时产生的文件

| 文件 | 用途 | 要入库吗 |
| --- | --- | --- |
| `characters.json` | 角色表 | ✅（随包发布） |
| `aliases_extra.json` | 人工补充的别称 | ✅ |
| `aliases_remove.json` | 要删掉的错误别称 | ✅ |
| `avatars/` | 头像 | ❌ |
| `arena_cache.json` | 作业查询缓存 | ❌ |
| `units_site.json` | 抓下来的单位表缓存 | ❌ |
| `meta.json` / `stats.json` | 更新时间、使用统计 | ❌ |
| `avatar_prints.json` | 头像特征缓存（加速识别） | ❌ |

上述“不入库”的文件都已写进 `.gitignore`。

## 更新角色表

有两种路径，按使用场景选择。

### 1. 插件运行期自动更新（默认）

插件内 `auto_update_days`（默认 7 天）到期后自行抓取 `/units`、合并 wiki 中文名并按需补头像。
这是插件自身的行为，与仓库无关。

### 2. 本地手动更新（仓库数据发布前使用）

```bash
python scripts/update_dataset.py                  # 只刷新，写入 characters.json
python scripts/update_dataset.py --commit         # 刷新并提交
python scripts/update_dataset.py --commit --push  # 刷新、提交并推送
python scripts/update_dataset.py --avatars        # 顺带下载头像到数据目录
```

提交的作者与提交者固定为 `Aria_Luna <80839392+moriruruka@users.noreply.github.com>`，
不受本机 `git config` 影响。

仓库不设自动写数据的 CI：所有 `characters.json` 变更都由上述命令在本地完成，
以保证提交归属与内容审阅。

### 手工命令

```bash
pcrjjc refresh            # 抓 pcrdfans /units，重建 characters.json
pcrjjc refresh --url ...  # 换镜像/代理
```

刷新会保留 `aliases_extra.json` 里的补充别称。AstrBot 插件里对应 `pcr 更新`。

## 数据来源与致谢

| 数据 | 来源 | 说明 |
| --- | --- | --- |
| 单位表 / 作业数据 | [pcrdfans.com](https://pcrdfans.com) | 作者 Peter Li，[@peterli110](https://github.com/peterli110)；前端源码开源于 [peterli110/pcrdfans.com](https://github.com/peterli110/pcrdfans.com) |
| 中文名与别称 | [biligame wiki](https://wiki.biligame.com/pcr/) | 由 `pcr_wiki` 抓取，只补中文名，不覆盖已有译名 |
| 头像 | `https://redive.estertion.win/icon/unit/` | 由 [esterTion](https://github.com/esterTion/redive_master_db_diff) 维护 |
| 解包的游戏数据 | [esterTion/redive_master_db_diff](https://github.com/esterTion/redive_master_db_diff) | 头像 id 与角色 id 的映射依据 |

本项目只调用上述服务的公开页面与接口，不打包其数据以外的任何代码；
角色名与立绘版权归 Cygames, Inc. 所有。
