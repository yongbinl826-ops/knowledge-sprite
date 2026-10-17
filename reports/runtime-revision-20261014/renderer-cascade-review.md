# 首请求补取与二次重放：只读复核

2026-10-14。只读生产代码及既存报告，另运行一个使用项目既有 StubRenderer/内存 HTTP 的最小复现。未联网、未启动浏览器、未修改生产源码或旧报告。

## 两个需要处理的点

### 首轮关键失败可以被第二轮成功覆盖

`backend/app/rendering.py` 的首轮分支在找到可补取的 GET `.md/.json` 后，没有确认同轮其他 fatal 是否属于不可忽略的操作。第二轮一旦 `status=rendered`，最终就返回 rendered。

本地最小复现：首轮 `blocked_requests` 包含同源 README GET/xhr，同时包含 `reason=non_get, method=POST, kind=fetch, fatal=true`；第二轮 Stub 返回 rendered。实际最终结果为 `status=rendered, passes=2`，并发生了一次内存 README 获取。首轮 POST 记录保留在 passes 中，但最终状态掩盖了关键失败。

建议：只有首轮的 fatal 全部属于已观察、可补取的同源无 query GET `.md/.json` 时才进入补取/重放。POST、导航/frame、worker/WS、未知脚本、不能安全关联的 CSP 等关键失败应阻止继续成功；普通 passive/明确 optional 非 fatal 不影响此门槛。补参数化测试：`README GET + critical` 必须保持失败，不能因第二轮 clean 而被抹去。本次真实 Docsify 首轮只有两个符合条件的文本 GET，不受此修复影响，可使用已保存响应做离线回归。

### 保存 DOM 的原始文件 hash 与 DOM 文本 hash 不同

`dynamic-cascade/dynamic-course-live.json` 的 `$.resource.render_diagnostics.dom_sha256` 为：

`81813479c8328b31d66c45e80af7e4cbed4bf6633fbd042bb2dfb785c2cd1a09`

而 `dynamic-cascade/dynamic-course-sources/rendered-dom.html` 原始文件字节 SHA-256 为：

`13422cbc694e6fc282ab0d2b7db1521863d0aaaf362369fae266199e8dce0bfa`

文件含 293 个 CRLF；读取为文本并规范化换行后 UTF-8 hash 与 diagnostics 完全一致。原因是 `scripts/verify_dynamic_course.py:141` 使用 Windows `write_text`，而 renderer 在内存 DOM 字符串的 UTF-8 bytes 上计算 hash。不是章节文本不一致，但不可宣称该文件 raw hash 已匹配。

建议保留现有记录，新增说明明确 `dom_utf8_text_sha256` 与 `saved_file_sha256` 的区别；未来用 `write_bytes(result.html.encode('utf-8'))` 保存新的 DOM 文件。无需改写旧报告或再次联网。

## 此次已确认的正确边界

- `range(2)` 固定最多两轮。仅首轮第一个符合规则的实际请求被预取；后续请求保存在 `deferred_observed_dependencies`。第二轮依然缺少关键依赖时返回 `render_incomplete`，没有第三轮或再次补取。
- 请求、DoH、响应字节使用同一 result 和观察钩子，跨轮不重置。外层 `asyncio.timeout` 覆盖准备、预取、启动和两轮；清理宽限独立，不能称为包含清理的严格总耗时上限。
- `max_observed_data_resources` 为安全上限；当前策略实际只取 1 个（设 0 则不取），没有超出配置为 1 或 2 时的上限。
- 延后不等于确认无用：`/_404.md` 仍保存在首轮 fatal 与 deferred 记录；最终第二轮它没有再次请求。不能把它称为已成功抓取，也不能据其消失推断整个来源永不需要该页。
- `dynamic-cascade-offline.json` 明确标注保存公共字节的离线回放，零外部 HTTP；没有冒充新 live 验收。

## 现有新 live 报告与逐章证据

`dynamic-cascade/dynamic-course-live.json` 已完成，`source_unchanged=true`、`preserved_reports_unchanged=true`：

- 6 次 target HTTP、12 次 DoH；完整 target 响应字节 256469。renderer 额外请求为 4 target/8 DoH；入口及入口 robots 在 renderer 前读取，因此两者不是相互矛盾的计数。
- manifest 字节总量 256411；与完整响应总量相差 58，恰为 CDN robots 400 响应字节，不是遗漏课程正文。DoH 字节不混算为 target 正文字节。
- 两轮状态分别为 `render_dependency_blocked` 和 `rendered`。首轮 README 与 `/_404.md` 被阻止；只补取 README。第二轮没有 fatal 记录，图片等仍被动阻止。
- 28/28 目录的 `evidence_id` 指向对应 `field=chapters.N`；证据 JSON 的 title/url 与章字段一致，均带 `acquisition=offline_rendered_dom`，source/manifest/DOM hash 与 render diagnostics 一致。
- 这是**同一门课程的 28 个学习目录链接**。原表数字行 0–25 共 26 行，07/08 各含两个学习链接；不得改称 28 门课程或 28 个已核验视频。`resource_type=course`、`video_evidence_status=none`、playback 未测试，口径正确。
- 原 HTML 文件 raw hash 与 source_sha256 匹配。DOM 保存文件的换行/hash 差异单独见上文，不影响已核对的逐项文本绑定结论。

截至本次只读快照，除上述关键失败覆盖与 DOM 文件序列化证据边界外，未发现本次“先补主请求再重放”的预算/两轮上限错误。
