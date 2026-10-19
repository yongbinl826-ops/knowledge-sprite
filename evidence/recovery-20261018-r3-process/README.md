# SQLite 备份与恢复演练证据

结果：**passed**，真实外部服务调用 **0**。

入口：`scripts/verify_backup_restore.py --source data/preview.sqlite3 --output evidence/recovery-新名称`。

`verification.json` 是主报告；`restart-1.json` 与 `restart-2.json` 来自两个独立、自然退出的 Python 进程。源数据库使用 SQLite `mode=ro`；其余数据库都是本目录下的独立证据副本。

已验证：一致快照与还原表哈希相同；活动 WAL 的已提交行保留、未提交行排除；原有 1 个项目及 2 个历史版本能经 API 读取；历史输入、分析和确认快照保持一致；排队/运行任务及待分析状态正确恢复；项目调度重启后继续受 1 次搜索预算约束；第二次重启表指纹不变；合成旧 consumer schema 迁移添加 3 条 legacy 归属且旧表不变；各阶段完整性和外键检查通过。

数据库副本含项目历史，按与源数据相同的隐私权限管理。报告只包含哈希、计数和状态。合成故障和离线搜索夹具只用于恢复行为验证，不代表真实模型、检索平台或视频可用性。
