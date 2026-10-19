# 沿用真实分析的独立搜课复验

本工具仅适用于隔离的本轮验收数据库。先由主任务使用 `scripts/serve_project_acceptance.py` 启动 fresh runner（端口 18120），确认新库已经初始化且尚无任何请求创建项目、任务、结果或缓存。然后运行：

```powershell
.venv\Scripts\python.exe scripts/validate_project_search_revision.py --source reports/project-deepseek-live-20261017/project-results.json --database reports/project-search-diagnosis-20261018/live/live.sqlite3 --output reports/project-search-diagnosis-20261018/retained-analysis-import.json --service-url http://127.0.0.1:18120 --expected-points 10
```

脚本不启动服务、不调用模型、不执行 HTTP、不自动确认或搜课；只通过现有 `ProjectStore` 写入一个新项目的未确认版本 1。已有项目、任务、资源、证据、映射或缓存均使导入拒绝，重复运行也拒绝。知识点 ID 保留原分析的版本内身份，但属于新的 `project_id`，不会继承旧任务或资源映射。

输入与分析重新经过当前 Pydantic 校验，且必须与来源确认快照、选择映射和版本一致。记录来源文件 SHA256、结构化分析 SHA256、原项目/版本、原模型/提示词版本、`origin=retained_analysis`、`new_model_analysis_performed=false`。导入后的 `confirmation` 为空、批次为空、搜索时间为空；正常确认端点会生成本轮的新确认快照。

输出显示新 `project_id`、服务地址和项目读取地址。主任务接着通过正常接口读取并核对，再提交：

- `POST /api/projects/{new_project_id}/confirm`，JSON：`{"version":1,"acknowledged_skipped_prerequisites":[]}`。
- `POST /api/projects/{new_project_id}/search`，JSON：`{"version":1}`。
- 使用正常项目/任务结果端点与现有 live-audit 收集本轮全新检索证据。

报告必须称为“沿用上一轮真实分析的搜课复验”。本轮没有重新执行项目分析模型，不得将旧分析计入本轮新增模型调用；后续搜索中的关键词扩展或重排调用若真实发生，应按各自用途单独计数。旧搜索结果和缓存完全未导入，旧审计证据保持原样。
