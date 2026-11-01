# 架构

## 分层

```
┌──────────────────────────────────────────────┐
│ 适配器：负责收发消息与会话状态                 │
│  astrbot_plugin_pcrjjc/main.py  ·  CLI        │
└───────────────────┬──────────────────────────┘
                    │ 调用
┌───────────────────▼──────────────────────────┐
│ 核心库 pcrjjc                                 │
│  pcr_data   角色索引 / 别称 / 相似度           │
│  pcr_wiki   数据抓取（pcrdfans / biligame）    │
│  portrait_detect  头像框检测（OpenCV）         │
│  recognize  脸带归一化互相关（numpy）          │
│  image_match  头像库与识别器                   │
│  arena_api  作业查询 / 响应解析 / 错误分类     │
│  card_render  卡片渲染（Pillow）               │
│  dialog     追问状态机                         │
│  fonts / paths / images / cli                  │
└──────────────────────────────────────────────┘
```

核心库不引入任何 bot 框架。接入其它框架时，只需把「收消息」换成对应的事件处理器，把事件拆成 `(会话标识, 文本, 图片)` 三个参数即可。

## 截图识别

识别流程由几何检测与模板匹配组成，不依赖深度学习模型：

1. **定位头像框**（`portrait_detect.py`）
   - 灰度化后使用 `cv2.Canny(40, 120)` 提取边缘，膨胀后 `findContours`；
   - 依据「近似正方形、面积占比、边框内部填充率」过滤；
   - 第一遍阈值偏严以减少误检，未命中时以 `Canny(30, 90)` 复核，降低漏检；
   - 按行聚类并按尺寸排序，每行补齐至 5 个（截图边缘常被裁切）。
2. **识别角色**（`recognize.py`）
   - 每个框只取中间 88×54 的「脸带」，规避边框、UI 遮挡与缩放差异；
   - 归一化后与本地头像库做归一化互相关，取最高分与次高分间距（margin）；
   - `score ≥ threshold` 且 `margin ≥ 0.05` 判定为确定，否则标记为不确定。
3. **同队去重**：同一队伍不会出现重复角色；若出现重复，将分数较低者降级为不确定。

该方案针对同一画风、同一批头像的比对场景，单张耗时低于 0.3 秒，CPU 即可完成，无需显存。若需接入 CLIP 类模型，`ImageRecognizer(use_clip=True)` 预留了入口。

## 作业查询

`ArenaClient.search()` 的流程：

1. 将 6 位角色 id 归一化为 `uid4 * 100 + 1`（接口只接受基础形态）；
2. 向 `https://pcrdfans.com/api/v1/search` 发送 `def / region / page / sort / ts / _sign`；
3. 解析为稳定结构 `{id, atk[], def[], up, down, ts}`，保留接口顺序，排序交由上层处理；
4. 错误分为四类：`ArenaAuthError`（103/601/401）、`ArenaRateLimitError`（429/Cloudflare）、`ArenaNetworkError`、`ArenaResponseError`，分别对应不同的用户提示。

未配置 API key 时可设置 `browser_endpoint`，由 `search_via_browser()` 转发到本机浏览器服务；签名与 Cookie 由浏览器页面自行处理。

## 追问状态机

`dialog.Dialog` 为纯数据对象：

| 字段 | 作用 |
| --- | --- |
| `stage` | `choose`（等待 1/2）、`exclude`（等待排除对象）、`replace`（等待替换目标） |
| `team` | 当前阵容，按截图从左到右存储（左为后卫） |
| `deadline` | 本轮截止时间，由 `touch()` 刷新 |
| `rounds` | 已追问轮数，受 `dialog_max_rounds` 限制 |
| `excluded` / `replaced` | 记录已执行的操作，用于结束时的汇总 |

位置编号只由 `position_of()` 与 `index_of_position()` 计算：最右侧为前卫，即 1 号位。展示与解析共用这两个函数，避免多处重复实现。

会话隔离使用 `unified_msg_origin`；在核心库中它只是一个字符串键。

## 数据与素材的划分

- 角色表约 150 KB、纯文本，纳入版本管理，便于通过 diff 审阅名称变更；
- 头像约 15 MB、二进制，版权归 Cygames，因此不纳入仓库，改为按需下载或通过 Release 分发。

## 降级运行

`numpy` 与 `opencv` 仅用于截图识别：

- 适配器对视觉模块采用懒加载（`_vision()`），导入失败时将 `vision_available` 置为 `False`；
- 自动识图的过滤器直接返回 `False`，不再占用消息；
- 用户发送图片时返回提示，说明可安装 `pcrjjc-helper[full]`，或直接使用文字查询。

因此在只安装基础依赖（约 5 MB）的环境中，文字查询与卡片渲染仍可正常工作。
