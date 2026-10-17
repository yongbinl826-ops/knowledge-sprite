# FETCH_DEADLINE_AT 与超时构造分支只读复核

2026-10-14，以下行号对应本次读取时源码。生产由 root 唯一修改；本次仅阅读源码和执行一次纯内存 httpx.MockTransport 复现，没有外网、SQLite 写入或生产编辑。

## 隔离与 reset：当前正确部分

- `backend/app/service.py:148`：worker 为每任务建立独立 asyncio Task。
- `service.py:172`：run 在执行前设置 FETCH_DEADLINE_AT；TaskGroup/详情子任务继承这个上下文值。
- `service.py:192`：最内层 finally 在诊断保存成功、失败或取消后 reset token，恢复调用者上下文，不把本任务 deadline 留给后续任务。
- `backend/app/fetcher.py:29`：独立 ContextVar，不会被官方搜索安装 NETWORK_OBSERVER 覆盖。PinnedHTTPClient 只读取此变量，没有自行 set，无需另行 reset。

## 需补足的实际边界

**过期 deadline 尚不能阻止请求发出。** `fetcher.py:254` 的首响应 timer 未裁剪 Djob；`:501` DNS timeout、`:536–537` HTTP 外层 wait_for 仍分别只使用配置值。`:279` 直到 headers 后才读取 job deadline。JobService 的外层任务 timeout 一般会取消它们，但独立 ContextVar 的约束并未贯穿所有阶段。

已复现：设置 FETCH_DEADLINE_AT 为 loop.time()-1，调用带 phase=True 的 `_request`；离线 DNS 与 HTTP handler 均被调用，HTTPX 内存 1 字节响应返回成功。原因是把 timer reschedule 到过去只安排下一 event-loop tick 取消，立即完成的 await 序列可能在取消回调执行前退出。必须先同步检查剩余期限非正即抛停止，不依赖 reschedule 单独兜底。

最小建议：在等待网络槽/节流后、DNS 前及 HTTP 前同步检查；DNS/首响应/外围 HTTP 的等待均取配置与 Djob 剩余值最小值。PinnedHTTPClient 直接入口也检查过期，并将首响应 timer 改为 absolute min(t0+H,Djob)。headers 后如计算期限已到立即停止，不进入正文迭代。

`service.py:198` 又从进入 _run_job 的时刻创建相对 timeout，与 :172 的绝对 deadline 存在保存耗时差。建议整个任务使用同一个绝对 deadline 的 timeout_at；如果调用者已有更短 FETCH_DEADLINE_AT，则取 min，避免内部延长期限。当前生产串行 worker 的常规调用者没有旧 job 值，reset 逻辑本身未发现泄漏。

`fetcher.py:224` elapsed 使用 time.monotonic，而 `:276–278` 将 started 与 loop.time 混作绝对 deadline。当前标准 asyncio 时钟一致，但建议 t0_deadline 单独使用 loop.time，time.monotonic 只作耗时，便于替代 event-loop 或假时钟测试不出现偏移。

## 配置构造分支清单

| 位置 | 当前状态 | 最小建议 |
| --- | --- | --- |
| `service.py:35–42` | Settings → FetcherConfig 的 phased_timeouts、body_idle_timeout_seconds、body_min_bytes_per_second、body_timeout_cap_seconds 均已完整传入 | 保留；新增字段将来在此同步 |
| `official_sitemap.py:100–104` | 不注入 fetcher 时的独立构造漏上述四字段，默认为 phased=False | 补同样四项，维持 max_retries=0；新增 direct build_provider(settings) 回归 |
| `providers.py:325` | build_provider 可不传 fetcher，从而进入上述独立构造 | 无需单独再建配置，修 provider 构造即可 |
| `service.py:53` | fallback 注入同一个 self.fetcher | 已共享正确配置，无重复构造问题 |
| `fetcher.py:417–421` | 无 config 的通用 Fetcher() 使用明确默认值 | 合理；这不是 Settings 转换分支 |
| `scripts/live_acceptance.py:105–108` | 历史脚本从 Settings 只抄初始 timeout/DNS，未抄新 phase 字段 | 不为本轮改写历史实验；若将来作为新入口复用，须同步四字段并清楚声明安全配置 |
| `scripts/verify_mit_transport_revision.py:81–90` | 历史 runner 的显式 Fetcher 为 phase=True/bodycap10；其 Settings 仍默认False/bodycap20 | 真实传输取 FetcherConfig，但 capabilities/page cache 的 transport profile 取 Settings（service.py:569–574）。旧报告保留，新的 runner 应从同一 scope 同步填 Settings 和 FetcherConfig，避免实际与声明不一致 |
| `scripts/verify_dynamic_course.py:123–130` | 显式 Settings/Fetcher 均启用 phase、bodycap10，idle5/minrate32768 均用相同默认值 | 当前一致；新的不同速率 scope 应显式同步填写 |
| `scripts/verify_official_discovery.py:155–161` 及旧 probe/compare 脚本 | 旧实验明确使用当时未分阶段或固定采集配置 | 保留历史，不自动“修正”旧脚本后声称原实验运行过新配置 |

当前 `_transport_profile()` 依据 Settings；若产品允许调用者注入任意不同配置的真实 Fetcher，应考虑从其实际 config 生成 profile，或校验配置一致。对于本轮新验证，显式使两端一致即可避免扩大生产接口。

建议定向回归包括：过期 Djob 时 DNS/HTTP 计数均为 0；更短父 deadline 不被延长；headers/DNS/body 均裁剪；异常/取消/诊断保存异常后 token 恢复；两个并发隔离内存任务不串值；官方独立构造与 JobService 构造的四字段相同。本复核未新增这些测试文件。
