# 来源身份、课程准入和知识点匹配复核

日期：2026-10-13。此文记录本轮源码与**隔离 fixture 离线验证**；没有新增外网请求，不能据此宣称真实平台目录或播放通过。测试时间 `2026-10-13T00:00:00+00:00` 是固定离线时钟，不是实际抓取时间。

## 实际缺口及修正

1. 旧准入要求视频证据，或 MOOC/学堂课程搜索入口，导致普通来源的可靠 JSON-LD `Course` 也被排除。现在独立接受可绑定到已抓取页面的课程结构；`video_evidence_status` 保持 `none`，`playback_verified` 不变。标题包含“课程”、普通文章目录、技术先修要求仍不足以推荐。
2. 旧通用目录逻辑会把“课程”标题加 `.course-outline` / `.curriculum` / `.chapter-list` 升为课程。现已删除该推断：先有 JSON-LD 或来源适配器的类型依据，才能提取这类目录。`html.visible_course_outline` 仅是目录来源，不再是课程类型证据。
3. 同 URL 的后续查询标题保存在搜索证据中，但旧规则只评分全局首次标题。现在标题、摘要评分按知识点范围使用搜索证据；页面字段可共享。类型准入可经 `eligibility_evidence` 接受全资源类型凭据，避免第二知识点无法找到首知识点类型证据 ID。已覆盖空摘要和查询顺序交换。
4. 原模型没有同来源课程归属、版本和讲次关系。新纯函数派生分组，保留原始资源 URL、canonical URL、resource ID、搜索来源及 B站分 P 身份。分组不是对资源记录做破坏性合并。

## 字段与证据契约

`Resource` 新增可选 `resolved_url`、`parent_course_url` 和 `course_identity`。`resolved_url` 由既有抓取器的实际响应目标保留，不采用 HTML canonical 作为重定向证据。身份函数仅在抓取成功且有对应页面证据时采用该目标；安全 HTTP → HTTPS 重定向下的普通 Course 不再被误排。

`course_identity` 字段：

- `status`: `identified` / `partial` / `unknown`。
- `family_id`、`offering_id`、`lesson_id`：不同层级分别可空；ID 为来源 URL 的稳定散列。
- `family_url`、`offering_url`、`source_url`：归属锚与依据来源。原资源 `url` 不变。
- `role`: `course` / `catalog` / `lesson` / `video` / `unknown`。
- `basis`: `recognized_url` / `page_course` / `page_is_part_of` / `unknown`。
- `evidence_ids`：绑定现有观察，不新造搜索结果；`unknown_reason` 保留不能确认的层级与跨站边界。

`recognized_url` 需要当前 URL 的实际 `search` / `page` / `page_link` 记录；`page_course` 绑定 `kind=page, field=resource_type`，来源为当前接受的 `jsonld.@type`（实际值 Course）或 `html.mit_ocw.course_home`。记录 URL 必须是原始资源或实际抓取响应 URL。元信息、类型和视频状态独立。

新提取的 `parent_course_url` 仅来自主 JSON-LD 对象的显式 `isPartOf`、其对象类型为 Course、真实 HTTP(S) URL 与当前页同 origin。对应独立 `kind=page, field=parent_course_url, source=jsonld.isPartOf.Course` 证据，文本为 JSON `{ "@type": "Course", "url": "…" }`。名称、跨来源 URL、多个冲突父节点不推断归属，不跟随请求。身份函数还支持相同严格契约的 `html.explicit_course_parent`，当前未新增此 DOM 提取器。

## 已识别与 unknown 的边界

| 来源/结构 | 可识别范围 | 仍为 unknown |
| --- | --- | --- |
| MIT `/courses/<完整 slug>/…` | 同 slug 首页、目录、讲次归入同来源课程；已证实视频的 `/resources/…` 可记讲次 | 不按标题合并不同 slug；不同年份仍独立。版本只在完整 slug 有明确季节/年份时标识 |
| MOOC `/course/<token>`、`/learn/<token>` | 同一完整 course token 的课程入口 | 不把 `tid` 自动当学期证据；开课版本 unknown；不猜机构前缀别名 |
| 学堂 `/course/<token>` | 包含实际形式 `THU02041000368` 的课程入口 | 学期、跨来源同课 unknown |
| B站 BV/av 及 `p` | 已有资源身份与分 P 保留；视频事实按原凭据显示 | BV 本身不是课程族证明，也不将每 P 算成独立课程 |
| 普通真实 Course | 绑定页面 Course 结构的同来源 URL 锚 | 未出现可靠父关系的同名 Course 不自动合并；视频和可播放性独立 |
| 同源显式 `isPartOf: Course` | 父课程归属；有视频证据的子页可记讲次 | 未知学期、不明确讲次层级单列 |
| Archive SICP 等视频列表 | 视频列表结构和章节仍按原证据显示 | 不因 SICP 同名或已知人工镜像关系自动归到 MIT 课程族 |

历史评估的 **4 份文档、41 次章节观察** 没有变成新增独立课程。历史报告的人工可知 SICP 关联与当前程序按可绑定来源字段识别的结果不同：当前不能确认跨站镜像归属时，仍报告 unknown。

## 结果选择和计数

`diversify(items, limit)` 先选各已知课程族的第一条，再按原顺序补同课程条目；unknown 资源彼此独立。它不改排序分数，不删除存储中的候选，也不按标题相似度合并。默认结果和平台筛选分别应用分组后取前 N。

`identity_summary` 的统计单位是实际返回的默认及平台结果的 resource ID 去重集合：

- `resource_records`：资源记录数，不是课程数。
- `identified_course_families` / `identified_course_offerings` / `identified_lessons`：各已识别 ID 的去重数。
- `unknown_course_family_resources`：没有课程族 ID 的资源记录数，包括仅有视频依据的 partial 记录。
- `unknown_offering_resources`：已识别课程族但没有开课版本的记录数。
- `unknown_identity_resources`：整体状态为 unknown 的记录数；不包含 partial。
- `scope=observed_source_scoped_identities_not_global_course_deduplication`：只称已识别的同来源身份；不是全课程或跨站去重率。

## 验证与改动范围

最终相关命令：

```text
.venv\Scripts\python.exe -m pytest tests/test_course_identity.py tests/test_core.py tests/test_resource_identity.py backend/tests/test_fetcher.py backend/tests/test_source_adapters.py -q
172 passed, 26 subtests passed in 14.12s
```

一个既有 Starlette/httpx 弃用警告；没有新外网、浏览器播放或真实目录验收。真实联网结论由其他独立报告提供，不能将本轮隔离 fixture 作为其替代。

本子任务修改：`backend/app/models.py`、`ranking.py`、`extractor.py`，新增 `resource_identity.py` 和 `tests/test_course_identity.py`。既有 `backend/tests/test_fetcher.py` 的目录正例补上明确 Course 结构，以保留目录及隐藏/危险链接过滤的原测试目的。服务、前端与端到端验收由相应负责人接线和验证。

本轮源码冻结：身份/准入/提取及上述测试已完成；本报告之后未再扩大来源或身份推断范围。
