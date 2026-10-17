# 2026-10-14 搜索出站链路与 B 站普通播放核验

## 结论

本次把 Microsoft 搜索失败定位到**解析前收到的搜索正文已不相关**：完整的站点限定查询到达原 Bing 引擎、原客户端及 libcurl URL 参数，返回 HTML 的搜索框也保留完整查询；但 HTML 的 10 条主结果是 artificial 的词典、电影等内容。原 Bing 解析器和原 ResultContainer 聚合后仍是相同的 10 条。未证明应用截断查询、丢失目标课程或域名过滤错误，因此没有修改生产搜索逻辑，也没有放宽过滤。

B 站唯一既有样本 `BV1VZ4y1G7YB` 的普通浏览器短片段播放已确认，页面显示 15 个分集。**完整视频播放、应用自动提取 B 站目录、MOOC 自动目录验收仍未通过。**

## 固定范围与方法

- 唯一查询：`(site:microsoft.github.io) Artificial Intelligence for Beginners course lesson`，来自之前第一组搜索的第 3 条；语言 en、页码 1、引擎 Bing。没有换词、换引擎、翻页、搜索结果替换或课程入口注入。
- 在现有官方 SearXNG 容器中启动独立 Python 进程，复用安装版本的 `bing.request → OnlineProcessor → searx.network → AsyncClient/curl_cffi → bing.response → ResultContainer`。不导入 webapp、不初始化全部引擎、不调用 fetch_traits。
- 为保持公开参数对应，读取现存实例配置到独立进程内存，仅输出白名单公开字段。与早期“禁用实例配置”的只读方案不同，实际使用 safesearch=1（中等）、TLS 验证启用、无代理/Tor、原有 chrome 客户端配置。没有新增指纹或切换传输方式。
- 最大客户端委托 1、并发 1、额外重试 0、客户端超时 20 秒；进程 alarm 40 秒、硬退出 45 秒、父层 48 秒。原引擎 `allow_redirects=false`，本次跟随跳数 0，低于授权的最多 3 跳；没有额外开启重定向。
- 这是安装组件的独立受控复现，**不是当前 Flask worker 或整个应用任务的在线验收**；无法倒推历史请求逐字网络状态。

## 真实搜索证据

开始 `2026-10-14T06:05:40.834446Z`，结束 `06:05:47.341100Z`，诊断进程耗时 6.507 秒，退出码 0。

实际交给 libcurl 的完整 URL：

```text
https://www.bing.com/search?q=%28site%3Amicrosoft.github.io%29+Artificial+Intelligence+for+Beginners+course+lesson&adlt=moderate&setlang=en
```

| 记录点 | 本次结果 |
| --- | --- |
| 原引擎准备 URL、客户端 URL、libcurl URL 的 q | 全部保留完整查询 |
| 传输返回 | HTTP 200；最终 URL 同上；Location 无；history 空；redirect_count=0 |
| 协议 | HTTP/2，curl 枚举值 3；配置允许 HTTP/3 不等于实际使用 HTTP/3 |
| 解码后的原始 HTML | 128,964 字节；完整读取，未触发超限分支 |
| HTML SHA-256 | `25f742043df42665d860fde93b7ce2f734b3a143c9d6fb0390c9f3bc59a8befb` |
| 返回页面搜索框 | 原完整查询；页面标题也包含原完整查询 |
| HTML 主结果 | 10 条，无目标课程；示例为 Merriam-Webster artificial、Wikipedia Artificial (2026 film)、IMDb |
| 原 Bing 解析器 / 原聚合 | 10 / 10；URL 顺序完全一致，也与先前该站点查询的 10 条结果一致 |
| 应用域名过滤（本次离线调用原函数） | 接受 0；10 条均为 `domain_mismatch`，行为正确 |
| 可观测调用 | engine.request、客户端委托、Curl.URL 赋值、patch_response、engine.response 各 1 |
| 物理 HTTP 次数 | **unknown**：没有抓包，不能用客户端调用数替代 libcurl 内部物理请求数 |

HTML 中出现 `microsoft.github.io` 共 22 次不能证明课程命中，因为查询自身也会重复出现在表单和页面元信息中。预期结果区 10 行的标题与解析结果才是此次结论的依据。

原始解码 HTML 仅在受限进程内存保留；落盘的是 SHA-256、页面标题、查询框和公开结果摘要，不保存整份 HTML、Cookie、认证头或完整请求/响应头。Bing 跟踪链接的未知查询参数已遮盖。没有访问任何搜索结果链接。

仍然 **unknown**：上游为什么在回显完整查询的同时返回无关结果；是否涉及上游检索、路由或缓存。不能凭此断言 Bing 内部截断了查询。当前服务 worker 的 Flask/plugins 阶段也不在此轮观测内。

## B 站普通浏览器核验

已有样本没有存留标签，因此仅新开一次已知规范入口：
`https://www.bilibili.com/video/BV1VZ4y1G7YB/`。

- 页面标题：2020年最新Python零基础教程——第5章 列表、元组和字典。
- 页面可见“视频选集（1/15）”，包括“本课目标”“为什么需要列表”“字典基本应用”等；未将这些目录复制进生产数据库。
- 页面静音自动播放，无需初始 Play。`06:06:51.436Z` 时 currentTime=8.062279；`06:07:00.104Z` 时为 16.729769，间隔约 8.668 秒、推进约 8.667 秒；两次 paused=false、readyState=4、error=null。可见课程画面与时间推进共同证明本样本短片段播放。
- 后续界面显示“登录 免费享高清视频 / 试看30秒”。未进行登录、验证码、付费、媒体下载或替代接口访问，也未判断该提示具体限制的是清晰度还是全片。
- 停止轨迹保留：首次点击视频意在暂停，但立即读取发生在异步状态更新前；随后点击播放/暂停按钮曾意外恢复播放，**偏离了原定见提示即停的观察窗口**。发现时间继续推进后再次点暂停，最终 `06:08:13.874Z` 确认 currentTime=58.630429、paused=true、readyState=4、error=null，随后关闭标签。**不宣称提示出现后立即停止，也不宣称完整 155 秒已播放。** 提示指向高清体验，且本次时间超过 30 秒，不能据此认定完整正常画质视频必须登录。
- 截图 `bilibili-playback.png` 为最后一次暂停操作后、最终 paused=true 读取前的画面；截图本身不作为暂停状态证明。

MOOC 此轮没有新增请求。此前普通页面访问不能证明课程目录自动提取，现有未知状态与 B 站/MOOC 自动目录门禁均保留。

## 诊断脚本边界修正与检查

实际执行脚本完整保留为 `capture_bing_executed_v1.py`，对应 `live.json`，不覆盖该版或历史失败。第一次准备阶段的模块路径错误也单独保留，发生在任何外部请求之前。

执行后审查确认了诊断脚本的一项真实缺陷：安装版 curl_cffi 会把正文回调返回 0 当作整块接收，不能用它中止超限下载。本次正文只有 128,964 字节，超限分支未触发，接收、patch 前后哈希一致，故本次结果不受影响；但不能据此认可旧版的一般性超限保护。

修订版 `capture_bing_once.py` 使用库支持的 `CURL_WRITEFUNC_ERROR=0xFFFFFFFF`，在成功路径进入解析前再次拒绝超限标记，并在引擎构建请求后、实际客户端委托前复查认证/Cookie 头键名。本次原 Bing 构建器仅写 URL，原版没有引擎新增认证字段的证据。

`check_capture_offline.py` 通过安装库真实 callback 包装验证 5 项离线边界：明确中止信号、超限不进入成功/解析、恰好上限可通过、敏感头拒绝、普通头允许。**新增外部请求 0**。修订脚本未再次联网。

## 退出与生产状态

- live 报告确认内存 hook 原引用逐一恢复、客户端关闭、进程完成；父层确认子进程退出码 0。磁盘源文件哈希一致不是唯一还原依据。
- 独立进程内 metrics 禁用持久存储；没有注入服务 worker，没有重启应用或 SearXNG，没有修改课程数据库。
- 41 个生产源码/配置与既有关键报告文件前后 SHA-256 均一致，包括 `.env`、SearXNG settings、后端/前端源码及旧联网报告。旧失败保留。
- 当前应用进程 PID 67496 / 68720 仍是此前实例。创建的 4 个容器 `/tmp/knowledge-sprite-*` 临时文件已逐个清除；B 站临时标签已关闭。
- 本轮只增加此目录的诊断与证据文件，未修改生产代码。未重复已通过的整套测试，也没有把组件诊断计入整应用端到端通过。

主要证据：`scope.json`、`live.json`、`execution.json`、`analysis.json`、`bilibili-playback.json`、`bilibili-playback.png`、`offline-budget-checks.json`、`preservation-before.json`、`preservation-after.json`。
