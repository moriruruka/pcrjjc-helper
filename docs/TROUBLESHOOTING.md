# 排障

先跑这两条，多数问题能直接定位：

```bash
pcrjjc doctor
pcrjjc selftest
```

## 常见现象

| 现象 | 先看哪里 | 常见原因 |
| --- | --- | --- |
| 回「没查到作业」 | 换个时间段再试；`pcrjjc arena -n ... --json` 看返回 | 冷门阵容真的没人打；或作业网限流（`103 / 601`） |
| 回「作业网触发了限流」 | 等 5–10 分钟 | 连续查太多、同 IP 多账号、Cloudflare 判定 |
| 卡片上中文变方块 | `pcrjjc doctor` 的「字体」一行 | 系统没有中文字体：装 Noto Sans CJK，或 `PCRJJC_FONT=/path/font.ttc` |
| 发图后回「没装 numpy / opencv」 | `pcrjjc doctor` | 装 `pip install "pcrjjc-helper[full]"` |
| 发图后回「本地还没有头像文件」 | `pcrjjc avatars --dry-run` | 先下载头像（约 15 MB） |
| 识别出的角色不对 | `pcrjjc recognize -i xx.png --json` 看分数 | 截图被裁过 / 缩放太小；调 `image_threshold`（0.6 宽松、0.8 严格） |
| 卡片位置标错 | `pcrjjc selftest` 的位置编号两条 | 位置从右往左数，1 号位是最右边（前卫） |
| 追问没反应 | 面板 `dialog_timeout_min` 是否为 0 | 0 表示关闭追问；另外只有**发起者本人**能回答 |
| 主动触发不响应 | `dialog_active_minutes` | 0 表示关闭；或上一次对话并不是在查作业 |
| 重启后追问状态没了 | —— | 状态只在内存里，属预期行为 |
| `characters.json` 解析失败 | `pcrjjc refresh` | 文件被手动改坏了，重新生成即可 |

## 作业网返回码

| code | 含义 | 处理 |
| --- | --- | --- |
| `0` | 正常 | —— |
| `103` | 未登录 / 无权限 | 配 `PCRJJC_AUTH_KEY`，或自备浏览器转发服务 |
| `601` | 触发风控 | 等一会儿；不要连续请求 |
| HTTP 429 / Cloudflare 页面 | 限流 | 同上 |

## 数据目录被写坏

```bash
# 角色表坏了：重新抓
pcrjjc refresh

# 头像缺失：重新下
pcrjjc avatars

# 缓存类文件可以直接删，会自动重建
rm <data>/arena_cache.json <data>/avatar_prints.json <data>/meta.json
```

## AstrBot 里不响应

1. 面板看插件是否加载成功（日志里找 `pcrjjc` / `astrbot_plugin_pcrjjc`）；
2. 群里是否被 `allow_group=false` 挡掉；
3. 关键词是否被 `keywords` 覆盖（默认 `["作业"]`）；
4. 配置里的 `enable_image` 关了不影响文字查询，反之亦然。

日志里出现 `pcrjjc：没装 numpy/opencv-python` 属正常降级，不是错误。
