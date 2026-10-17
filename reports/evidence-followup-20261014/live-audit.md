# 五题原始 live 请求与结果审计

本报告只分析 `live/` 中 D06、D13、H06、H09、H16 的原始执行记录。后续离线重评与隔离 UI 模拟数据不在本报告内。输入 SHA-256 和逐请求账本保存在 [live-audit.json](live-audit.json)。五题均已作为开发使用，不能称独立留出验收。

## 实际请求与预算

25 条逻辑查询（23 completed、2 failed）；44 次应用→SearXNG HTTP、4 次来源 HTTP、8 次 DoH HTTP，共 56 条请求账本记录，全部为 HTTP 200。SearXNG 响应体仍报告 4 次上游故障（D06：timeout 2、unknown 2）。**SearXNG 后端物理上游请求次数 unknown**；不得把请求组数、原始结果数或 HTTP 200 当成上游成功证明。

| 项目 | 实际 | 冻结上限 / 解释 |
|---|---:|---|
| SearXNG HTTP | 44 | 60 |
| 来源 HTTP | 4 | 20；2 robots、1 MIT sitemap、1 Douyin详情 |
| DoH HTTP | 8 | 40；与来源 HTTP 分开 |
| 详情处理任务 | 8 | 每题最多2；7次策略停止、1次实际详情 |
| 目录页跟随 | 0 | 未取得自动目录；不能称目录联网验收通过 |
| 播放测试 | 0 | 未执行 |

进度 `search_requests` 合计46，包含44次SearXNG和2次官方发现请求（MIT robots+sitemap），不能写成46次SearXNG。`details_completed=8`不是8次页面HTTP：D13两次YouTube、H06两次B站、H09一次B站、H16两次YouTube均为策略处理后停止；只有H09的Douyin详情实际请求。B站/MOOC没有详情或robots直连。

账本所有类别合并的请求起始最小间隔 **2.001166 秒**，观察到的并发峰值 **1**；半开滚动窗口 `[t,t+60s)` 内峰值 **23** 次。SearXNG单类最小间隔 2.001905 秒，60秒峰值 21 次。第4至第5题间等待 60.008678 秒。所有记录的请求/任务预算均未超限，单题完成均不足90秒。这里是应用账本边界，不是抓包，也不证明SearX内部并发或全机流量。

## 每题查询、结果和时延

下表“支持/部分/待核”按 default 与所有平台分区合并、每题 resource_id 去重；这是原始API的证据分类，不是完整教学质量人工验收。

| 题目 | 逻辑查询 | SearX HTTP | 来源/DoH | 支持/部分/待核 | 首证据/完成秒 |
|---|---:|---:|---|---|---|
| D06 CSS Flexbox 对齐 | 5 | 10 | 2/4 | 0/0/0 | 未返回/48.702 |
| D13 JavaScript closures | 5 | 8 | 0/0 | 5/0/0 | 4.797/24.976 |
| H06 JavaScript Promise 并发与错误处理 | 5 | 10 | 0/0 | 0/2/0 | 3.836/25.951 |
| H09 地理坐标与投影坐标转换 | 5 | 8 | 2/4 | 4/0/0 | 3.992/43.783 |
| H16 quaternion rotations | 5 | 8 | 0/0 | 4/0/1 | 2.809/15.895 |

默认分区合计支持9、部分2、待核1；合并平台结果后共16个资源记录（支持13、部分2、待核1）。不是16门独立课程。全部5题原始任务状态为partial。普通搜索与详情缓存命中为0；MIT官方发现索引随后有缓存复用，不能合称整个运行完全无缓存。

## B站与MOOC是否实际查询

每题各执行1条B站和1条MOOC定向逻辑查询。合计B站5条逻辑查询对应7次SearX HTTP；MOOC5条对应10次SearX HTTP。这些是独立搜索服务的站点限定查询，不是直接请求平台网页。原始候选数量包含上游返回与客户端域筛选，不能当相关课程数量。

| 题目 | B站：HTTP / DDG原始 / 最终入任务候选 / 分区支持-部分-待核 | MOOC：HTTP / DDG原始 / 最终入任务候选 / 展示 |
|---|---|---|
| D06 | 2 / 0 / 0 / 0/0/0 | 2 / 0 / 0 / 0/0/0 |
| D13 | 1 / 51 / 6 / 2/0/0 | 2 / 0 / 0 / 0/0/0 |
| H06 | 2 / 60 / 6 / 0/2/0 | 2 / 24 / 6 / 0/0/0 |
| H09 | 1 / 60 / 6 / 3/0/0 | 2 / 6 / 6 / 0/0/0 |
| H16 | 1 / 56 / 6 / 1/0/1 | 2 / 0 / 0 / 0/0/0 |

MOOC五题均无展示：D06为上游unknown加Bing域不匹配；D13、H16为DDG返回0且Bing结果均域不匹配；H06返回24条、选入6条但未通过该复合知识点依据；H09返回6条、选入6条但主题信号0。不能归结为“MOOC没有课程”或“平台访问限制”。

## H06：两条都只支持并发，错误处理仍未知

- `res_a2b7b4ba2aab174e86be731c`：[ TS 异步系列 EP.7 | Promise 并发详解：all / race / allSettled / any 一次讲清 ](https://www.bilibili.com/video/BV1N4L36EEJi/?uid=4256314E344C333645454A69)。原分类partial；并发有自身搜索证据，错误处理unknown，页面not_fetched。支持ID：`ev_1251d8a1-8bce-4d7a-b47f-59d73e80a236`、`ev_2f0609b2-baf6-4600-a660-b8d640309460`。
- `res_8969a927b90ef5ca21be4f79`：[ 42-Node.js教程-使用Promise.all方法执行并发操作 ](https://www.bilibili.com/video/BV1DM4y1P7s6/?uid=425631444D34793150377336)。原分类partial；并发有自身搜索证据，错误处理unknown，页面not_fetched。支持ID：`ev_cc0bad6e-36d6-427f-bc68-a1a580f672d9`。

两条集合仍然是 **1/2子项有依据**；不是一条并发加一条错误处理，也不是完整复合主题命中。JS/Promise共同上下文由已保存的标准Promise API规则标注；原题与来源标题（TS、Node.js）如实保留。不能把allSettled等API名自动当作已核验错误处理教学。

## D06：零返回的具体边界

10次SearXNG HTTP均200，但DDG在两个通用查询报告timeout，在B站/MOOC两个定向查询报告unknown。Bing通用查询留下的6个唯一资源为CSS Profile、MDN CSS、Wikipedia CSS、GeeksforGeeks CSS Tutorial、W3Schools CSS及HTML Styles CSS，均无课程/视频类型依据，也不足以证明CSS Flexbox对齐。站点限定查询的Bing结果均domain_mismatch。MIT官方发现成功读取robots和含2588位置的sitemap索引，匹配子索引0、候选0，没有把宽泛课程塞入结果。

D06的零结果是该次受上游故障及证据范围约束的零返回，不能声称排除了相关课程存在，也不能把unknown上游原因写成403、限流或验证码。

## partial、目录和未验证范围

- **D06**：2个逻辑平台查询失败；DDG两次timeout、两次unknown；Bing返回泛CSS/域不匹配；MIT sitemap索引无匹配子索引。零返回不能证明平台无课。
- **D13**：5个逻辑查询completed，HTTP均200；保存no_topic_signal及详情预算文案，2次详情处理均site_policy_blocked且未发目标HTTP。通用未完成警告不等于HTTP故障。
- **H06**：5个逻辑查询completed，HTTP均200；完整复合点信号为0，但2条partial仅支持并发，错误处理仍unknown；2次详情处理为策略停止。
- **H09**：5个逻辑查询completed，HTTP均200；1次B站策略停止，1次Douyin详情HTTP200后javascript_required；JS未启用，目录未取得。
- **H16**：5个逻辑查询completed，HTTP均200；2次YouTube详情处理为策略停止；1条四元数泛外链线索保留needs_review，未计入明确支持。

H09 Douyin robots与详情均200；详情结果是javascript_required，并非页面完整教学核验。本批JS渲染关闭，catalog_pages_attempted/completed均0。搜索trace有合计462条观察因截断未保存，不能用可见trace断言所有上游结果内容。

所有来源证据只支持其记录层面的标题/摘要、页面信息或状态；完整教学覆盖、访问条件和播放仍按原记录unknown。目录缺失不阻塞真实相关链接的返回。本报告未发任何网络请求，未改原始live文件、SQLite或源码。

## 输入证据

- [冻结范围](live/frozen-scope.json)
- [执行完成记录](live/finished.json)
- [已终结请求账本](live/checkpoint.json)
- [逐题完成清单](live/coverage.json)
- [D06.json](live/D06.json)
- [D13.json](live/D13.json)
- [H06.json](live/H06.json)
- [H09.json](live/H09.json)
- [H16.json](live/H16.json)
