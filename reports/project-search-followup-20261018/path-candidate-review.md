# 文件路径候选的独立详情核验

2026-10-18。本次用户明确要求核验旧搜索发现的文件路径候选。使用生产 Fetcher、现有来源许可与安全检查，独立读取公开页面；没有把该 URL 当作新搜索种子，也没有写入下一轮项目数据库。

- 旧候选资源：`res_464422ad1a4e95dd67c47154`。
- [真实页面：Python案例技巧51：文件路径处理](https://www.bilibili.com/video/BV1ED1yY2Eo6/)。
- 实际进行了 2 次 HTTP 请求：robots 和视频公开 HTML，均为 200；新 HTML 为 829519 字节。
- 页面取得标题、简介“讲解文件路径相关的处理方法！”和 1 条实际分 P。分 P 标题与视频同名，时长 156 秒，地址为 `?p=1`。
- 来源是 `html.bilibili.__INITIAL_STATE__.videoData.pages`，目录证据 ID 为 `ev_97bdad9d2a93e429c664`。字段与本次目录观察逐项相等，六项检查通过，详见 `path-candidate-probe/verification.json`。
- 页面元数据状态为 fetched/catalog，视频页面证据为 page_verified；未验证播放，也未确认“本地”这一原始限定。因此仍只能说明相关文件路径教学，不是整个知识点完整覆盖。

执行命令：

```powershell
.venv\Scripts\python.exe scripts/probe_project_candidate.py --source reports/project-search-diagnosis-20261018/final-live/post-review-results.json --point-id k2 --resource-id res_464422ad1a4e95dd67c47154 --output reports/project-search-followup-20261018/path-candidate-probe
```

输出目录采用独占创建，重跑须改为新目录。原搜索项目、原课程证据与缓存均未修改。本独立核验不能替代下一轮真实搜索是否再次发现和抓取该候选的记录。
