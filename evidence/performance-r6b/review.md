# 结果读取性能独立复核（仅暂存）

已定位到重复纯排名与观察构造，而非已证实的单个灾难正则：maze 单 job 原始 cProfile 9.04 秒、2748 万调用，97 次排名反复为每个概念重建目录观察；normalize_url 约6.3万次。TWT实际最长摘要2628字符，最大Bili目录104/99章节。

单次排名 ContextVar 纯字符串缓存减少约半数 CPU，但 maze 无 profile 仍约1.63–2.15秒，不能单独收尾。新增仅 results 读取使用的实例 LRU：完整 point/resource/observed/eligibility/request/require_type 的 canonical SHA key，256条及8MiB输出JSON上限、输入>1MiB旁路、None可缓存、deepcopy入出，异常不存。无DNS/robots/权限/HTTP事实缓存；writer排名未改。

同一只读副本完整 resource/evidence/coverage/ranking JSON 字节不变。maze cold1.642秒，warm0.050/0.052秒；data cold0.394秒，warm0.040/0.040秒。20项隔离边界测试通过。主源未修改，补丁与新模块在 tmp/phase2-ranking-performance，等待root与其他暂存差异合并。

首次多轮benchmark的未打补丁baseline在watchdog栈打印期间发生原生access violation；原始栈/已完成两次baseline均保留，未归因补丁。修正为每次调用独立计时后，缺少的after与LRU验证完成，无超时/额外上游。

冷读仍可能短暂阻塞，256条跨多作业会淘汰，源码合并后还需真实HTTP/health/事件环验证。另 project_service.results→view→terminal refresh 与随后results可对同batch重复计算；应复用请求内结果。不能直接把共享Store连接放进线程。
