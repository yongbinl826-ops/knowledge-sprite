# r3 教学效用独立验收矩阵

本轮未达到可生产的推荐质量：8例中0例 accepted_useful，5例 failed，3例 partially_useful。后者含1例只有可用学习计划、材料效用为0的看板，不表示推荐通过。

固定范围：50单元、122技能、45关键方法组。冻结后的真实终态结果、原始输入和获批分析均已按SHA核对并复制保存；评分沿用事前25/25/25/15/10权重与0–4刻度，没有按匹配百分比自动打分。

| 案例（终态版本） | 单元/技能 | 实际卡/限定可用卡/过度声明 | 人工分/100 | 决定 |
|---|---:|---:|---:|---|
| 共享单车出行 CSV 分析报告 v8 | 7/14 | 1/0/1 | 52.5 | failed |
| pygame 单屏迷宫寻出口 v8 | 6/18 | 1/1/0 | 72.5 | partially_useful |
| 离线番茄钟学习网页 v8 | 7/16 | 2/2/0 | 76.25 | partially_useful |
| Arduino LED 按钮反应时间小游戏 v8 | 5/15 | 2/1/1 | 62.5 | failed |
| 校园自习室使用情况本地看板 v5 | 6/16 | 0/0/0 | 63.75 | partially_useful |
| 离线复习卡网页 v4 | 7/14 | 2/1/1 | 65 | failed |
| pygame 双人乒乓球 v3 | 6/16 | 0/0/0 | 60 | failed |
| Arduino 电位器调节 LED 亮度 v3 | 6/13 | 4/1/3 | 52.5 | failed |

12张实际卡按“单元+资源”去重；6张过度声明，另6张只有限定范围/主题价值，涉及5个唯一技能：二维网格边界防护、DOM选择器、具体onclick/addEventListener主题、Arduino-core数字IO主题、analogWrite目录课题。简介2张、标题3张、目录1张；同一DOM技能的两课不多算技能。它们不等于5项全步骤、学生掌握或项目完成，其他117技能未收到合格的已展示教学指针，其中明确已有的背景组件仍可复用。

45关键组中4组仅有部分方法指针，1组只有DOM元素引用短前置，40组没有合格的已展示指针；没有一组关键新方法材料达到完整适配。此处允许不同项目/数据/常量示例、多课程互补与已学先修复用，从未要求一片视频展示整项目。

## 已证问题与可用范围

- 数据报告：泛“时间日期类型处理”标题不能被写成“时间列解析与类型检查”。另一个真实日期源的决策失败哨兵不等于有效否定，不能说公网无课。advanced但首次pandas/Matplotlib，针对性库入门仍可用。
- 复习卡：具体onclick/addEventListener标题是可迁移课题；泛事件标题不能承诺button click回调。持久化、校验恢复和状态渲染等仍缺材料。
- Arduino反应：ESP32 Arduino-core输入/输出与INPUT_PULLUP主题可迁移，Uno电压/引脚仍需实际资料核对；“学习过程”泛标题不证明点灯/读取具体教学。去抖、非阻塞和抢按状态仍缺入口。
- 电位器LED：analogWrite实际目录入口可用；LED正确使用不自动证明极性+限流接线，两份数值映射简介不证明Arduino map整数截断，其中一份是Mixly。
- 迷宫：Padding边界防护为有效可迁移算法部分，不证明Python实现、查墙、离散移动、胜利状态或真实耗时。
- 番茄钟：两种DOM选择API有自己简介/标题声明；对象/render、真实时间倒计时、恢复与阶段逻辑等不能由该入门主题补齐。RUTUBE的ru元数据与标题印地语声明均不是实测音轨，字幕与适配未知。
- Pong：0卡但两处P2软件漏送已有自身教学正文：Movement循环get_pressed被1800字符观察窗口截掉；Scoring的SysFont→render Score→blit已抓却未入四候选。原指纹/候选池纯回放已复现；未展示材料不追记为本轮交付。
- 看板：6单元0卡，材料效用0。旧泛CSV视频已抓并不证明Streamlit具体上传/date_input/multiselect/重运行；反之也不能证明互联网无课。保留原0值、闭区间日期、空rooms与加权比率实践。

## 生成、修正与真实成本边界

每例首次phase3学习技能合同分析：2例独立自动通过，4例需人工修正，2例分析失败。额外Pong v2失败、Pong v3修复后通过、Pomodoro v7需人工补技能均保留。最终内容3例自动、5例人工修正；后续相同分析的搜索版本重绑不是新生成或再次人工内容修正。这8例不是3.3新prompt通过集，也不是首次全过。

独立核对r3-final搜索窗口29次模型调用：22次技能匹配+7次声明复核，全部有usage，合计185,698 tokens（prompt165,946；completion19,752）。根观察器跨前序生成/复核/搜索的累计78次、479,570 tokens另列，不能当r3-only；版本数也不能当模型次数。没有查询价格或推断货币费用。

各例“客户端提交意图→首次保留终态观察”约103.3–184.0秒，包含轮询，非精确服务执行/首张材料UI时间。首个有意义材料的实际UI延迟没有记录，保持未知；终态partial与15个job完成不等于语义验收通过。

## 证据与限制

- 完整逐单元/逐技能/逐关键组评分与12张来源原引文：[final-teaching-quality-matrix.r3.json](final-teaching-quality-matrix.r3.json)。
- 冻结原标准：[final-teaching-quality-matrix.plan.json](final-teaching-quality-matrix.plan.json)；未改权重、阈值或旧裁定。
- 最终来源独立索引：[r3-independent-source-audit-summary.json](r3-independent-source-audit-summary.json)。
- 原始结果/视图与运行账：[r3-final-matrix-sources/](r3-final-matrix-sources/)；成本安全投影：[r3-provider-usage-independent.json](r3-provider-usage-independent.json)。

本矩阵0新HTTP、0新模型、0数据库写、0产品源码变更；没有播放验证、真实硬件或学生项目代码执行。身份/原文SHA正确不等于教学语义正确；访问/音轨/步骤未知不能叫免费、失效或已教。r4修复和3.3后续试验必须单列，不能倒写r3。
