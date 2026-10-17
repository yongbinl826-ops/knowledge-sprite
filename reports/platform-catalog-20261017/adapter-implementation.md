# 平台目录适配实现与验证

2026-10-17。本报告描述真实浏览器保存 DOM 的离线提取结果；不代表服务器采集策略已开放、HTTP 状态已验证或视频播放通过。原始捕获未修改。

## 实际观察与输出

| 来源 | 提取结果 | 时间和链接 | 验证边界 |
| --- | --- | --- | --- |
| B 站 BV1VZ4y1G7YB | 15 个有序分 P，`catalog_kind=video_parts` | 15 个页面明示的独立时长；15 个条目 URL 均为 null；start/end 均为 null | 页面有视频选集结构，`video_evidence_status=page_verified`；未请求媒体、未验证播放 |
| MOOC PKU-1003479006 | 84 个文本大纲项，`catalog_kind=course_outline` | 41 项有明确括号 min 时长，其余 unknown；所有条目 URL 和 start/end 为 null | 9 章标题、57 个编号课程、2 个补充视频教程、16 个测验/作业；不是 84 个已验证视频 |
| 同一 MOOC 页的学期按钮 | `access_notice=老师已关闭该学期，无法查看` | 逐字段页面证据与原 URL 绑定 | 保留可读公开大纲，不把整页改成 access_denied；不推断登录、付费、报名或播放条件 |

MOOC 的初期口头观察发生在异步大纲加载之前；保存的 `mooc-dom.html` 已含完整大纲，随后真实浏览器展开核对。测试明确将该片段与同 URL 的 `mooc-term-dom.html` 组合，未将组合文件伪称原始 HTTP 响应。浏览器捕获记录的 HTTP 状态仍为 unknown。离线解析输出中的 `fetch_status=fetched` 仅表示解析给定 DOM 成功，不是后端联网验收。

每个条目均有独立 `kind=catalog`、`field=chapters.N` 证据；JSON 保留 title、url、source_url、start_seconds、end_seconds、duration_seconds。列表顺序及 `chapters.N` 表达观察顺序。未从 data-key、编号或数组下标猜造 `?p=`、课时或播放地址；未把独立时长累加成时间轴或课程总时长。MOOC 的章标题时长和下属课时时长也未相加。

## 最小源码变更

- `backend/app/source_adapters/bilibili.py`：限定 bilibili.com / www.bilibili.com 的合法视频路径；仅采 `.video-pod` 内标题为“视频选集”的 `.video-pod__list.multip` 直接条目。推荐列表不进入目录，缺标题跳过，缺时长保留 unknown。来源为 `html.bilibili.video_pod.multip`。
- `backend/app/source_adapters/icourse163.py`：限定 icourse163.org / www.icourse163.org 的课程路径及真实课程介绍/大纲容器；按 `#j-course-outline .f-richEditorText p` 提取文本。课程类型来源为 `html.icourse163.course_structure`；访问提示仅从确切报名按钮容器的明确关闭学期文本提取，来源 `html.icourse163.enrollment_notice`。
- `backend/app/source_adapters/__init__.py`：显式注册两适配器。
- `backend/app/extractor.py`：修正既有 `VideoObject.hasPart` 将任意具名 Article、VideoObject 或无类型附件误标成 Clip 时间章节的问题；现在仅明确 Clip 可生成 `video_chapters`。Course 的普通大纲路径保持可用。未扩展 JSON-LD primary 绑定策略。
- `backend/app/models.py`：新增可空 `access_notice`，不改访问或播放字段语义。
- `tests/test_platform_catalog_adapters.py`：真实保存 DOM 重放及明确标记的合成边界变体；旧 registry 测试仅同步显式注册名。

## 离线验证

最终定向回归：**173 passed，26 subtests passed，12.41 秒**。范围为新平台适配测试、既有 source adapters、fetcher 和严格章节证据验收测试。结果保存于 `adapter-tests-final.xml`；首次结果另存 `adapter-tests-initial.xml`，未覆盖。

覆盖另一域名/仿冒域名/错误路径、推荐视频污染、缺失标题、无效或缺失时长、隐藏条目、空 MOOC 目录、无课程介绍、旁侧推荐文字、明确关闭学期与可读目录并存、无关/隐藏/非关闭按钮不生成访问提示、模型保留访问提示，以及非 Clip 附件不再冒充时间章节。

全量提取结果、逐条证据、输入及源码 SHA256 位于 `adapter-extraction.json`。这些是保存页面的解析回归，不能替代另一个页面或一次新的平台联网验收。

## 原捕获校验

- `bilibili-dom.html`：`bb146089cf493d9691223e436a9088b8f01b425e45a761af51c00696b303d58f`
- `mooc-dom.html`：`369d4b630f1d6e37ced51c8eaf5f58d8893b0cbc94005fbe345cd61f9a12e374`
- `mooc-term-dom.html`：`f6cda65c32614de79ebcb2edbd7572cb4123bb4d17a0451894f08193e89091a8`

后端适配源码已冻结。未修改 fetcher 平台策略，未使用登录、Cookie、私有 API、下载媒体或新增网络请求；未改历史报告或原始捕获。父任务负责前端目录类型文案、课程来源准入及缓存版本接线；其他代理负责下游身份/排序集成回归。
