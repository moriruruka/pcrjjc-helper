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

## 刷新数据

```bash
pcrjjc refresh            # 抓 pcrdfans /units，重建 characters.json
pcrjjc refresh --url ...  # 换镜像/代理
```

刷新会保留 `aliases_extra.json` 里的补充别称。AstrBot 插件里对应 `pcr 更新`，也会按 `auto_update_days` 自动跑。

GitHub Actions 每周一执行一次 `refresh`，存在差异时创建 PR（不直接修改主分支），由维护者审阅后合并。
