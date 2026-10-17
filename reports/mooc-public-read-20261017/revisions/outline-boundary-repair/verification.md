# 修复后独立联网核验

任务 `f2930cbf-37cd-424e-8036-fb73631573f1`；核验时间：2026-10-17T05:04:45.584197+00:00。

**MOOC公开目录后台链路核验通过；整任务状态仍为 `partial`。**

- 输入“Python 语言基础”；8次搜索请求，4查询完成、0查询失败。
- 6个MOOC公开课程页真实HTTP200；5门非空大纲合计361项，独立核验全部标题、顺序、数量与新HTTP原文完全一致。
- 每项均绑定数据库目录证据；6个原始响应文件的SHA256全部匹配网络记录；0旧搜索/详情缓存命中，无预置候选或页面回放。

| 课程 | 数据库目录 | 原始大纲 | 结论 |
|---|---:|---:|---|
| [用Python学人工智能](https://www.icourse163.org/course/-1462245166) | 45 | 45 | 完整一致 |
| [零基础学Python语言CAP](https://www.icourse163.org/course/BIT-1002058035) | 16 | 16 | 完整一致 |
| [用Python玩转数据](https://www.icourse163.org/course/NJU-1001571005) | 94 | 94 | 完整一致 |
| [Python语言程序设计基础_南京邮电大学](https://www.icourse163.org/course/NJUPT-1003215002) | 0 | 0 | 公开大纲为空 |
| [Python语言基础与应用](https://www.icourse163.org/course/PKU-1003479006) | 84 | 84 | 完整一致 |
| [数据结构与算法Python版](https://www.icourse163.org/course/PKU-1206307812) | 122 | 122 | 完整一致 |

原先截断的PKU-1206307812本轮已真实重新采集并完整保存122项，逐项与新HTTP响应一致。它未出现在当前MOOC五张卡片中，是结果区每平台最多显示5条的排序/展示限制，不是采集失败；现有UI显示的其他课程目录仍有真实链路证据。

本轮partial原因：Bing的no_topic_signal警告使服务保留upstream_partial，同时详情预算12已用尽，部分搜索候选未补全。4查询均成功，没有首轮的查询超时失败。

B站继续按5.6(3)、1.5在请求前阻断，页面HTTP请求为0。MOOC请求仅为robots.txt及6个公开/course页面；其他既有发现请求为MIT的robots.txt及sitemap.xml。没有MOOC学习页、私有API、登录、报名或媒体请求。

核验失败项：无。源文件与启动哈希差异：0。

完整逐项证据ID、响应哈希与查询记录见 [verification.json](verification.json)。
