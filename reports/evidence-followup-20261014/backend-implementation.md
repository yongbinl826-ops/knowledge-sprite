# v7 后端证据分区与互补覆盖实现

状态：2026-10-14 最后离线修正后源码冻结。修改范围为 `backend/app/ranking.py`、`models.py`、`service.py`、新增 `tests/test_evidence_followup.py`，以及平台限额隔离测试的过时 mock。未增加依赖、来源、权限；未操作 8000 服务；本代理未执行外网请求。历史报告与原始证据未改写。

## 稳定 API

每个 `match` 增加：

- `topic_evidence_status`: `supported` / `partial` / `needs_review`，界面对应直接支持、部分覆盖、待核。
- `topic_evidence_reasons`: `{code,message,evidence_ids}` 数组。待核理由 ID 指向造成疑问的自身观察，不表示支持整个知识点。
- `supporting_evidence_ids`: 本资源真正支持主题或已支持子项的证据 ID；待核资源为空。
- `subtopic_coverage`: `{id,text,status,evidence_ids,reason}` 数组，状态为 `supported` / `unknown`。
- 原 `matched_evidence_ids` 保留，并纳入语境等价后的真实支持 ID；等价规则记录在 `topic_match_rules`。

每个结果组：

- `items` / `platform_items` 只含直接支持。
- `partial_items` / `partial_platform_items` 与 `review_items` / `review_platform_items` 分别独立展示。
- `total_matches`、`total_partial_matches`、`total_review_matches` 是各分类限额前数量；`section_limit` 表示**每分类**最多展示的数量。默认 3 时不是所有分类合计最多 3。
- `collection_coverage`、`platform_collection_coverage` 只按各自限额后实际展示、按资源 ID 去重的直接支持及部分覆盖资源计算，待核不参与。每子项提供资源 ID 与证据 ID；`single_resource_full_coverage` 独立于集合状态。
- 类型筛选、平台筛选后的前端会基于当时可见卡片再次计算集合，并校验证据 ID 属于该卡及其支持 ID 集。

## 判定边界

1. 比较其他方案时才出现目标术语、匿名函数被直接称作闭包且没有捕获/词法作用域依据、明确预约/预告而没有回放依据、目标术语只出现在外部引用 URL 中，分别给出具体待核原因。保留明确比较教学、实授应用例和明确回放。规则不依赖案例 ID 或资源 URL。
2. 搜索标题/摘要可以直接支持主题；页面未取、平台停采、播放未知本身不会使主题变待核。直接支持不表示完整教学或播放已核验。
3. 每条搜索观察先隔离明确相关推荐尾部，再从评分副本移除外部 URL。原始证据不改写；不同知识点的标题不互借。
4. 复合知识点仅在可明确拆分的技术前缀与 2–4 个显式并列子项上启用。无法可靠拆分的任意自然语言保持未知，不生成假课程大纲。
5. 共同技术上下文与每个子项必须在同一自身观察中成立。标准 Promise API 名称可说明 JavaScript/Promise 归属；它本身不自动说明视频讲了并发或错误处理。错误处理与异常处理按完整概念等价，单独“错误”不等价。
6. 子项与上下文只从实授文本副本判断，不能从先修说明借词，否定先修说明也不自动证明教学。各子项分别在不同观察出现时标为部分覆盖，并说明缺少同一观察的完整支持。
7. `Normalization` 与 `1NF` / `2NF` / `3NF` / `4NF` / `5NF` / `BCNF` 同观察可提供明确数据库范式语境，记录 `database_standard_normal_forms_context`；泛 normalization、UE5 动画归一化、只有外链中的四元数旋转文字不由此升级。
8. 读取旧任务时重新评估其已有候选，恢复有据部分覆盖并计算新状态，不写 SQLite、不修改证据。默认与平台分区共用一次判定。LLM 重排只作用于直接支持资源，不能跨状态晋级。

搜索缓存 `provider_version` 从 10 增至 11，避免沿用旧候选优先级语义。

## 验证与时间界限

- 首版整合 236 项通过；随后增加边界后 243 项通过，分别保留 `backend-evidence-initial.xml`、`backend-evidence-final.xml`。
- 保存 40 题证据的首次回放发现 H05 “文件的读写”及 H15 标准范式标题被保守误降；监督复核发现子项可借先修文字。运行中的 5 题真实验证期间后端源码保持冻结，待全部终态才实施这三处修正。原始联网结果不改写、不追加联网；最终仅用原证据离线重评。
- 最后定向测试 **51 项通过**（新增证据测试 50 项，加平台限额隔离测试 1 项）。
- 最后关联整合测试 **255 项通过，5.25 秒**：`backend-evidence-final-corrections.xml`。包含 core、identity、completion repairs、link trial、lifecycle、official sitemap 与独立边界测试。只有既有 Starlette/httpx 弃用提醒。
- 完整后端套件、最终 40 题回放及 5 题原证据重评由 root 独立执行，本报告不将本地 fixture 当作实网成功率或独立留出泛化结果。

## 最终 SHA-256

| 文件 | SHA-256 |
|---|---|
| backend/app/ranking.py | `33af5b21869b20c179e23a34f1d7810698e5961fe153da53980c303b9c7b1f66` |
| backend/app/models.py | `1d138e7cf4a7a330bc589d01f0e1f13db9bb3af4fe398a5cbe0a999ca63a5052` |
| backend/app/service.py | `1062545be94ce97977b0e8f6bcdfe52801d620bb80a96588c7e4b84fe42aaba2` |
| tests/test_evidence_followup.py | `358c6a5b91ed9481a00e6dee761f52cccebe4a76d55c885c5e426493ab34ac9d` |
| tests/test_platform_results.py | `086a186ca02531578fbb96bb25e93c98e37004173848c749a2d27a24d0f65be7` |

同目录 `backend-source-final.json` 提供上述最终修正后的机器可读 SHA-256。
