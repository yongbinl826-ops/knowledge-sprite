# 一轮有界真实公开检索

已通过 reviewed exec 执行唯一任务 `8aa44e3b-bc97-4149-b488-381cda2e1681`，109.377 秒终态 partial。首次准备命令因 JSON tuple/list 比较退出，确认没有 marker、数据库或提交后才修正比较；实际只创建一个 job，没有重提不确定任务。

使用既有 SearXNG / Bing / DuckDuckGo videos 公开检索配置；只提交四个公共合成术语，B站与 MOOC 两个平台偏好。隔离 GLOBAL_CONCURRENCY 从原配置 1 覆盖为 2；配置搜索 cap30 不变，平台计划只用16次，12次详情、240秒期限。NoLLM 显式哨兵且模型 provider/key/endpoint 清空，teaching false、renderer false。没有模型扩展、重排或 judge，也没有浏览器、原 D 数据库读取/复制或 D 写入。

| 合成术语 | 平台发现 | 已取页面 | 代表来源与范围 |
|---|---:|---:|---|
| pygame 矩形碰撞检测 | 6 | 3 | [Pygame中简单的碰撞检测](https://www.bilibili.com/video/BV1MK4y1g77P/)：碰撞主题相关，当前标题/简介不能定位到矩形算法。 |
| pandas 分组聚合 | 6 | 3 | [16 pandas分组聚合统计](https://www.bilibili.com/video/BV1CU4y1V7CD/)：自有简介列明 groupby 聚合；明确演示版本1.1.5，不保证当前API完全一致。 |
| JavaScript localStorage | 6 | 3 | [现代JavaScript教程 Episode20](https://www.bilibili.com/video/BV1rY4y177CZ/)：自有标题为本地存储；系列后续节，不能假定零基础无前提。 |
| Arduino 按钮去抖 | 6 | 3 | [arduino教程(10) debounce](https://www.bilibili.com/video/BV1Qa4y1t7UJ/)：自有标题/简介相关；标题说“官网教程”不代表本视频由官方发布。 |

24个均为格式正确、同平台的 B站原生视频 URL，12个详情返回 fetched/page_verified，另12个仍为 search_discovered/not_fetched。24个有缩略图 URL，其中已取详情的12个为B站封面，另12个为搜索预览；未请求图片或媒体，不能声称已验证所有封面加载、视频可播或免费。

MOOC 8个查询均未返回可接受候选。保留 trace 显示：首轮上游 timeout/unknown；后续三次 Bing 查询返回合计30个错误域名结果，严格域过滤全部剔除。不是将其它文档伪装成 MOOC，也不能据此说互联网没有相应课程。job.partial 和上游警告如实保留，16个网关响应不等于16个有效查课结果。

真实并行观测：B站首请求 06:18:41.215 开始、约06:18:44.010结束；MOOC首请求 06:18:42.220 开始、约06:18:50.617结束，区间重叠。MOOC首次仍在等待时，B站首轮4个请求都已启动，支持两 lane 独立执行。首批 B站查询没有候选，首个资源在16.335秒才被监测到；没有运行UI，不能声称实际看到“快平台视频在慢平台响应前显示”。

人工相关性逐项见 `independent-review.json`：pandas/localStorage/去抖均有具体主题来源；pygame 候选属于碰撞相关，矩形限定仍未从已取本视频材料确定。有一页简介列出全课程“矩形碰撞21:32”，但本页实际仅601秒单视频，不能把整课目录归给该视频或制造时间戳。Mixly/Wokwi与实物去抖演示有学习价值，但不自动变成 Arduino C++ 实现课；面试比较、图书宣讲也未被当作保证初学者适合的操作教程。

已取页面语言仅来自 html.lang=zh-Hans，不能当作音轨语种验证。登录/付费/选课字段仍 unknown，未因这些状态将任何链接标为 invalid。本轮没有播放器验证，也不要求它作为跳转平台的门槛。

证据：`plan.json`、`submission.json`、`job.json`、`results.json`、`source-pool.json`、`progress.json`、`summary.json`，所有 SHA 与逐来源指针见独立 JSON。运行期间 backend/app 全部源 SHA 无变化。剩余限制是当前公开索引的 MOOC 召回、部分主题的粒度/阶段信息以及未取的12个详情；不是旧强制教学覆盖率门槛。
