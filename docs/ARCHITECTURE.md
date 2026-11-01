# 架构

## 分层

```
┌──────────────────────────────────────────────┐
│ 适配器（只负责收发消息、存会话状态）          │
│  astrbot_plugin_pcrjjc/main.py  ·  CLI       │
└───────────────────┬──────────────────────────┘
                    │ 调用
┌───────────────────▼──────────────────────────┐
│ 核心库 pcrjjc                                 │
│  pcr_data   角色索引 / 别称 / 相似度          │
│  pcr_wiki   数据抓取（pcrdfans / biligame）   │
│  portrait_detect  头像框检测（OpenCV）        │
│  recognize  脸带归一化互相关（numpy）         │
│  image_match  头像库 + 识别器门面             │
│  arena_api  作业查询 / 解析 / 错误分类        │
│  card_render  卡片渲染（Pillow）              │
│  dialog     追问状态机（纯逻辑）              │
│  fonts / paths / cli  跨平台字体、数据目录    │
└──────────────────────────────────────────────┘
```

原则：**核心库不 import 任何 bot 框架**。想在 NoneBot2 里用，只需要把「收消息」换成它的 handler，把 `event` 拆成 `(session_key, text, images)` 三个参数即可。

## 截图识别怎么做的

不做 OCR、不用深度学习模型，纯几何 + 相关：

1. **找头像框**（`portrait_detect.py`）
   - 灰度 → `cv2.Canny(40, 120)` 边缘 → 膨胀 → `findContours`
   - 按「近似正方形 + 面积占比 + 边框内部填充率」过滤
   - 第一遍偏严（防误检），一把没找到再放宽到 `Canny(30, 90)` 重跑一遍（防漏检）
   - 按行聚类、按尺寸排序，每行补齐到 5 个（截图边缘常被裁掉半张）
2. **认脸**（`recognize.py`）
   - 每个框只取中间一条 **88×54** 的“脸带”，四周的边框、UI 遮挡、缩放差异都被排除
   - 归一化后与本地头像库做**归一化互相关**，取最高分 + 与第二名的间距（margin）
   - `score ≥ threshold` 且 `margin ≥ 0.05` 才算“确定”，否则标成“不确定”
3. **队伍去重**：同一队不会出现重复角色，撞了就说明有格子认错，把分低的那个降级为不确定。

为什么不用 CLIP/视觉大模型：这一步是「同一套画风、同一批头像」的模板匹配，互相关又快又稳（单张 <0.3 秒），也不需要 2 GB 显存。真要用大模型，`ImageRecognizer(use_clip=True)` 留了钩子。

## 作业查询

`ArenaClient.search()`：

1. 把 6 位 id 归一成 `uid4 * 100 + 1`（作业网只认基础形态）；
2. POST `https://pcrdfans.com/api/v1/search`，带 `def / region / page / sort / ts / _sign`；
3. 解析成稳定结构：`{id, atk[], def[], up, down, ts}`，保留接口顺序（排序交给上层）；
4. 错误分四类：`ArenaAuthError`（103/601/401）、`ArenaRateLimitError`（429/Cloudflare）、`ArenaNetworkError`、`ArenaResponseError`——每一类都有不同的用户提示。

没有 API key 时可以配 `browser_endpoint`，走「真实浏览器转发」这条路（由页面自己签名，最不容易被风控）。

## 追问状态机

`dialog.Dialog` 是一个纯数据对象：

| 字段 | 作用 |
| --- | --- |
| `stage` | `choose`（等 1/2）/ `exclude`（等排除谁）/ `replace`（等替换谁） |
| `team` | 当前阵容，按截图从左到右存（左 = 后卫） |
| `deadline` | 本轮截止时间（`touch()` 刷新） |
| `rounds` | 已追问轮数，受 `dialog_max_rounds` 限制 |
| `excluded` / `replaced` | 记录做过什么，用于结束时的总结 |

位置编号规则集中在两个函数里：`position_of(team_len, index)` 与 `index_of_position(team_len, position)`——**最右边是前卫 = 1 号位**。所有展示、解析都从这里取，避免各处各算一套。

会话隔离用 `unified_msg_origin`（AstrBot 的概念）；核心库里它只是一个字符串 key。

## 为什么头像和角色表分开

- 角色表 150 KB、纯文本、可以走 git 历史做 diff（谁的名字改过一目了然）；
- 头像 15 MB、二进制、版权归 Cygames，放进 git 会让仓库变重也说不清授权。

所以：角色表入库，头像按需下载 / Release 分发。

## 纯文字降级

`numpy` 与 `opencv` 只在「发截图」这条路上需要，所以：

- 适配器里视觉模块是**懒加载**（`_vision()`），导入失败就把 `vision_available` 置 False；
- 自动识图的 filter 直接返回 False，不抢消息；
- 用户发图时回一句「这台机器没装 numpy/opencv，可以 pip install "pcrjjc-helper[full]"，也可以直接发 /作业 布丁 克总」。

这样 `pip install ".[lite]"` 的部署只有 5 MB，照样能查作业、出卡片。
