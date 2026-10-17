# MIT 单点分阶段验证结果

执行时间：2026-10-13 15:24:18.285419–15:24:36.986166 UTC，18.677 秒。唯一授权运行已结束，没有重试、替换主题或补跑。

**结果：FAILED / search_timeout。** 原始 `probability` 知识点未完成索引 → 子图 → 课程页证据链：0 候选、0 课程资源、0 详情、0 目录。此次诊断定位了本次失败阶段，不构成官方发现链路实网验收通过。

| 实际请求 | 结果 |
| --- | --- |
| `https://ocw.mit.edu/robots.txt` | HTTP 200，完整 64 字节；实际声明根 sitemap |
| `https://ocw.mit.edu/sitemap.xml` | HTTP 200 响应头约 1.230219 秒取得；TCP 连接约 0.004 秒、TLS 约 0.698 秒；正文读取 259803 字节后，固定 10 秒正文总期限到达 |
| 后续子地图、课程、目录 | 均未请求；run-wide stop 生效 |

sitemap 记录为 `timeout_kind=body_total`、`phase=receive_response_body`、`body_complete=false`、`partial_body=true`。该次不是首响应期限或 5 秒正文空闲期限触发。HTTP 200 只证明取得响应头，不能当作完整 XML 已读取或解析成功。部分正文仅保留字节数与 SHA-256，不进入解析、候选或成功缓存：

```text
9d5322321e223d2ca3369b6f2819378c58cc7d405e7f915f0b4214a53950f28b
```

实际为 **2 次目标 HTTP + 4 次 DoH = 6 次 HTTP**；授权上限为 6/12/18，所有预算检查通过，0 重试、并发 1。源码前后 hash 相同；旧成功探针、旧失败修复及 held-out 三份 JSON 的 hash 均不变。

旧 `official-repair-live.json` 未记录 headers/partial bytes，故其失败阶段仍为 **unknown**。不能把本次 `body_total` 回填为旧失败的原因，也不能推断更大期限一定能取得完整索引。分阶段模式增加了可审计信息，本次没有证明其改善完整发现成功率。

原始记录：[mit-transport-revision-live.json](mit-transport-revision-live.json)。任务 ID `284e342a-63ad-4736-af14-5a5b0fd5a138`，隔离数据库 `mit-transport-revision.sqlite3`；范围与方法分别见 [scope](mit-transport-revision-scope.json) 和 [离线诊断](mit-transport-diagnosis.md)。未写正式数据库，未重启服务，未执行播放或动态页面验证。外网令牌已交还根任务。
