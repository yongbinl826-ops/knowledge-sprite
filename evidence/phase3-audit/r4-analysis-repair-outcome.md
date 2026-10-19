# r4 独立3.3分析修正试验

结论：**quality失败，没有产出获批学习路线，尚未证明稳定生产生成/修正能力。** 346项离线测试不能替代本次真实结果。

新项目 `7c66b822-b8bf-4741-aa96-cd53fd00d629` v1 使用 `project-analysis-v3.3-method-traceability`，其完整合成输入与原Pomodoro v8逐字段、canonical SHA一致；它是独立新试验，不加入或改写原8例通过率。

实际调用严格为两轮生成及语义复核：**4 calls，30,704 tokens（prompt24,012；completion6,692）**。生成2次18,892tokens，复核2次11,812tokens；全部有usage，HTTP200/stop/json_returned只表示返回JSON，不表示语义合格。共享观察器中其他搜课调用已排除。客户端意图到首次保留终态约36.523秒，含轮询；实际effective operator timeout没有另查环境/接口，仅源码硬边界2gen+2review得到核实。

失败保留完整输入、`error.code=quality`和两轮安全attempt摘要；`analysis=null`、`confirmation=null`、`batches=[]`且未开始搜课。首轮摘要只报告numeric_boundary，位置为unknown；次轮模型复核报告k2练习观察先修不足及方法到技能追溯不足。**拒绝草稿没有保存，不能独立认定这些诊断全部正确，也不能补写首轮具体数字错误或还原草稿原因。** 这些是保存的复核指控，不是独立精读草稿的结论。

原Pomodoro v8在前置保留快照中的获批分析SHA与冻结r3一致；本次失败没有获批内容可覆盖旧路线。本复核未重新GET原项目/读DB，故只声明保留证据一致，不把它冒称新的在线状态检查。

本次复核0外呼、0模型、0DB写、0产品源变更、0人工修正/重跑。完整证据、call IDs、usage、输入/源码/运行manifest SHA及限制见 [r4-analysis-repair-outcome.json](r4-analysis-repair-outcome.json)，原始快照在同名目录。r3矩阵和3.3独立失败分别保留。
