"""pcrjjc：公主连结竞技场作业查询核心库。

这个包不含任何 bot 框架依赖，只负责：

* 角色表与别称解析（``pcr_data``）
* 从 pcrdfans / biligame 抓取与更新数据（``pcr_wiki``）
* 截图里的头像框检测（``portrait_detect``，需要 OpenCV）
* 头像 88×54 脸带比对（``recognize`` / ``image_match``，需要 numpy）
* 作业查询与降级（``arena_api``）
* 作业卡片渲染（``card_render``，只需要 Pillow）
* 查不到作业时的追问状态机（``dialog``，纯逻辑）

上层适配器（AstrBot 插件、命令行）只负责收发消息与存状态。
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
