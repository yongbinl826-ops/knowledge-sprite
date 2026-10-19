# 视频来源原因审计

范围：既有 r8 检索、r9c 只读投影与不可变 SQLite 审查快照；0 新 HTTP、0 模型调用、0 源数据库写入。
31 单元中 UI 自身正文/目录证据缺口为 19；API none 为 18，差异是 CSV 导出仅有标题/搜索层 partial。

## 已确认的软件问题

- TWT Movement 自身增量教学代码被 import/260 字符门槛整段舍弃，实际 event.get 与四方向按键示范丢失；不包含 KEYDOWN 的内容仍未知。
- API 性质纠错“不是 window 对象”被误作“不教 API”；修复只解除该错误 veto，不能补齐事件参数、暂停或截止时间算法。

## 逐单元

### bicycle_csv_advanced / k3 — pandas 时间列解析与无效行分离

主因：`specific_parameter_evidence_missing`。to_datetime 的真实视频存在；errors/isna、end < start 及相等时间边界未在本来源元数据中证实。API 名称支持不能补齐参数或业务规则。
候选 24；详情状态 {'not_fetched': 14, 'fetched': 9, 'access_denied': 1}；已执行查询 4。
建议：把日期转换技能与具体异常判定练习分开，保留 errors/isna/比较条件未知。
已存来源：[Python pandas.to_datetime函数方法的使用](https://www.bilibili.com/video/BV1eL4y1g7qY/?uid=425631654C34793167377159)（same_page_video_metadata_verified_no_playback_test）; [Learn Pandas & Python for Data Analysis [Full Course]](https://www.freecodecamp.org/news/learn-pandas-for-data-science/)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\bicycle_csv_advanced\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### bicycle_csv_advanced / k4 — pandas 时间差计算骑行分钟时长

主因：`relevant_video_recall_insufficient`。当前候选未提供 Timedelta.total_seconds 的自身教学依据；时序预测和日期格式化不等于骑行时长计算。文本文章不能作为视频。
候选 24；详情状态 {'fetched': 10, 'not_fetched': 14}；已执行查询 4。
建议：需要实际时差/总秒数课程的自身元数据；未证明合法源不存在。
已存来源：[Learn Pandas & Python for Data Analysis [Full Course]](https://www.freecodecamp.org/news/learn-pandas-for-data-science/)（same_page_video_metadata_verified_no_playback_test）; [Change datetime Format in pandas DataFrame in Python (2 Examples)](https://statisticsglobe.com/change-datetime-format-pandas-dataframe-python)（fetched_webpage_not_proven_video_excluded）
证据：`evidence\phase2-read-r9c\bicycle_csv_advanced\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### bicycle_csv_advanced / k7 — pandas 清洗结果与汇总 CSV 导出及复核日志

主因：`support_basis_layer_mismatch`。真实读写 CSV 视频存在；当前 partial 的支持指针来自搜索标题，UI 要求自身正文/目录，所以这项属于第 19 个 UI 缺口。不能把搜索依据改名为目录依据。
候选 30；详情状态 {'not_fetched': 22, 'fetched': 8}；已执行查询 6。
建议：可在显式同资源目录重评中证明 CSV 导出核心；index=False、日志计数、目录与文件名仍未知。
已存来源：[【Python Pandas教程】4-读写CSV EXCEL文件](https://www.bilibili.com/video/BV1q741157jG/?uid=425631713734313135376A47)（same_page_video_metadata_verified_no_playback_test）; [爆肝999小时的极品python数据分析课程，用pandas玩转Excel！手把手带你python基础更上一层楼！](https://www.bilibili.com/video/BV1D34y1v7iQ/?uid=425631443334793176376951)（discovered_entry_identity_or_detail_pending）; [机器学习 | Python Pandas](https://www.bilibili.com/video/BV176R4BGEiZ/?uid=42563137365234424745695A)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\bicycle_csv_advanced\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### pygame_maze_intermediate / k1 — pygame 二维列表网格地图绘制

主因：`transferable_skill_project_coupling`。Snake 本课确教 20x20 网格线，Rect 本课确教矩形；均未证明二维墙路出口地图及其 Rect 绘制关系。学生已有窗口绘图，不应重推整套基础课。
候选 22；详情状态 {'not_fetched': 5, 'fetched': 17}；已执行查询 4。
建议：可迁移网格绘制列为前置/相关材料；二维地图与墙路出口仍待直接证据。
已存来源：[Tutorial #1](https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-1)（same_page_video_metadata_verified_no_playback_test）; [pygame游戏开发教程011：强大的Rect](https://www.bilibili.com/video/BV1Us4y1B799/?uid=425631557334793142373939)（same_page_video_metadata_verified_no_playback_test）; [Python学习V：基于Python实现的迷宫游戏（Pygame）地图生成](https://www.bilibili.com/video/BV1eG411u778/?uid=425631654734313175373738)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\pygame_maze_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### pygame_maze_intermediate / k2 — 网格坐标的合法移动与阻挡判定

主因：`relevant_video_recall_insufficient`。已抓碰撞课是子弹/敌人 hit box；Pong 是挡板边界；Snake 是自身碰撞。它们不能证明目标格检查、墙阻挡及地图索引边界。
候选 24；详情状态 {'fetched': 14, 'not_fetched': 10}；已执行查询 4。
建议：先寻找通用网格寻址和越界防护的真实教学材料，不把其他游戏碰撞冒充地图碰撞。
已存来源：[Collision & Hit Boxes](https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-collision)（same_page_video_metadata_verified_no_playback_test）; [Pygame 新手入门游戏 Pong P5：玩家移动范围限制](https://www.bilibili.com/video/BV1o7411u7Rr/?uid=4256316F3734313175375272)（same_page_video_metadata_verified_no_playback_test）; [Tutorial #4](https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-4)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\pygame_maze_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### pygame_maze_intermediate / k3 — pygame 键盘输入边沿处理

主因：`confirmed_own_code_extraction_loss`。Movement 的 own markdown 在明确事件/移动教学段落后有 641/729/644 字符增量示范，包含 event.get 与四方向键；现 >260 字符/import guard 整段丢弃，造成实际教学证据缺失。KEYDOWN 不在这些代码中，仍不能证明事件沿与持续按键对比。
候选 20；详情状态 {'not_fetched': 7, 'fetched': 13}；已执行查询 4。
建议：隔离修复有界 own 增量代码抽取；FullCode/前后课/先修/侧栏继续排除。
已存来源：[Basic Movement & Key Presses](https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-tutorial-movement)（same_page_video_metadata_verified_no_playback_test）; [Tutorial #2](https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-2)（same_page_video_metadata_verified_no_playback_test）; [pygame键盘事件——控制小船左右移动](https://www.bilibili.com/video/BV12t4y1P73a/?uid=425631327434793150373361)（same_page_video_metadata_verified_no_playback_test）; [【Python 游戏开发】Pygame 事件重构 + Q 键退出 + 全屏实现](https://www.bilibili.com/video/BV15zd6B5EFX/?uid=425631357A64364235454658)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\pygame_maze_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### pygame_maze_intermediate / k5 — pygame 持续主循环与 R/Esc 键处理

主因：`transferable_skill_project_coupling`。本课已知 QUIT/Q 退出、一般循环与其他游戏 reset；没有 WIN 状态、R 重开与 Esc 分支的自身教学证据。把 READY/PLAYING/WIN 原项目实现写进学习技能过于耦合。
候选 24；详情状态 {'fetched': 14, 'not_fetched': 10}；已执行查询 4。
建议：教一般状态切换/退出/重置后，由项目练习检验具体按键与状态；未证实项保留未知。
已存来源：[【Python 游戏开发】Pygame 事件重构 + Q 键退出 + 全屏实现](https://www.bilibili.com/video/BV15zd6B5EFX/?uid=425631357A64364235454658)（same_page_video_metadata_verified_no_playback_test）; [pygame制作打砖块游戏 第四节重置游戏与碰撞音效](https://www.bilibili.com/video/BV1hN4y1H7Nq/?uid=425631684E34793148374E71)（same_page_video_metadata_verified_no_playback_test）; [Tutorial #4](https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-4)（same_page_video_metadata_verified_no_playback_test）; [Tutorial #1](https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-1)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\pygame_maze_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### web_pomodoro_beginner / k1 — 番茄钟页面结构与语义化按钮

主因：`transferable_skill_project_coupling`。语义 HTML 视频身份可靠，但标题/自身目录不足以同时证明分区、占位内容、按钮及可读标签。button 课仅搜索发现尚未补详情。
候选 22；详情状态 {'fetched': 6, 'not_fetched': 15, 'too_large': 1}；已执行查询 4。
建议：把语义结构和按钮/标签拆成可迁移技能，保持网页项目的具体标签关系未知。
已存来源：[HTML基础入门11：HTML语义化（2023）](https://www.bilibili.com/video/BV17C4y1R76B/?uid=425631374334793152373642)（same_page_video_metadata_verified_no_playback_test）; [【讲座】语义化 HTML 的重要性 | 语义化 HTML | 零基础学习 HTML | freeCodeCamp 全栈开发 编程自学入门教程](https://www.bilibili.com/video/BV1vLpkzQEkQ/?uid=425631764C706B7A51456B51)（same_page_video_metadata_verified_no_playback_test）; [【单】button标签-HTML5精讲 课时ID-6.13 【表严肃】#HTML教程 #HTML5教程 #button标](https://www.bilibili.com/video/BV1cs41147gd/?uid=425631637334313134376764)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\web_pomodoro_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### web_pomodoro_beginner / k4 — 时间戳倒计时与后台标签页准确性

主因：`specific_behavior_evidence_missing`。真实日期/倒计时课程存在，但有限元数据未证实绝对截止时间、后台节流以及 interval 仅触发刷新这一组合；另一单元抓到的整课目录确有 Date 总毫秒数及倒计时章节。
候选 24；详情状态 {'not_fetched': 15, 'fetched': 9}；已执行查询 4。
建议：目录可支持日期/时间戳子技能；抗节流截止时间算法需要自己的证据。
已存来源：[「前端小技巧」如何用JavaScript实现一个倒计时效果](https://www.bilibili.com/video/BV1Ah4y187RG/?uid=425631416834793138375247)（same_page_video_metadata_verified_no_playback_test）; [使用javascript实现倒计时的功能](https://www.bilibili.com/video/BV1GT411K77P/?uid=42563147543431314B373750)（same_page_video_metadata_verified_no_playback_test）; [5分钟学编程 · Javascript篇 #44｜日期运算：复制、加减与格式化](https://www.bilibili.com/video/BV13nN76nEU5/?uid=425631336E4E37366E455535)（same_page_video_metadata_verified_no_playback_test）; [黑马程序员最新JavaScript全套教程，零基础JavaScript入门](https://www.bilibili.com/video/BV1JT4y1z7Hn/?uid=4256314A543479317A37486E)（discovered_entry_identity_or_detail_pending）; [黑马程序员前端JavaScript入门到精通全套视频教程，javascript核心进阶ES6语法、API、js高级等基础知识和实战教程](https://www.bilibili.com/video/BV1Y84y1L7Nn/?uid=42563159383479314C374E6E)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\web_pomodoro_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### web_pomodoro_beginner / k5 — 开始暂停继续重置的状态转换

主因：`confirmed_property_negation_misveto`。真实 addEventListener 课的“不是 window 对象”性质纠错被 PARTIAL_SKILL_NONTEACHING 的“不是”误当不教 API。另一个已绑定 Rutube 视频标题和自身描述明确事件处理方法，但严格 title-action 门槛不接受。两者均不能补齐 click 参数、暂停剩余量或继续截止时间。
候选 23；详情状态 {'fetched': 12, 'not_fetched': 11}；已执行查询 4。
建议：最小修复通用性质纠错范围；保留不教/未包含/先修/未来的真正教学否定。
已存来源：[javascript进阶：网页监听函数的使用，对比使用两种获取元素属性的方法 1、addEventListener不是widnow对象 2、应用场景 3、](https://www.bilibili.com/video/BV17f421X7oC/?uid=425631376634323158376F43)（same_page_video_metadata_verified_no_playback_test）; [JavaScript addEventListener to form button](https://rutube.ru/video/e9cffc08b2cece5d9f1df32eea8d105e/)（same_page_video_metadata_verified_no_playback_test）; [JavaScript实现秒表基本功能开始、暂停、继续、重置](https://www.bilibili.com/video/BV1mZ4y1j73P/?uid=4256316D5A3479316A373350)（same_page_video_metadata_verified_no_playback_test）; [黑马程序员前端JavaScript入门到精通全套视频教程，javascript核心进阶ES6语法、API、js高级等基础知识和实战教程](https://www.bilibili.com/video/BV1Y84y1L7Nn/?uid=42563159383479314C374E6E)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\web_pomodoro_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### web_pomodoro_beginner / k6 — 阶段结束切换与专注计数

主因：`relevant_video_recall_insufficient`。阶段查询召回课程“基础阶段”等泛课；未见自身教学元数据证明阶段到零只计一次、切换后等待开始及累计完成次数。
候选 35；详情状态 {'not_fetched': 29, 'fetched': 6}；已执行查询 6。
建议：学习技能应表达条件转移/一次性计数；阶段命名、25/5 分钟与等待规则作为项目验收。
已存来源：[黑马程序员最新JavaScript全套教程，零基础JavaScript入门](https://www.bilibili.com/video/BV1JT4y1z7Hn/?uid=4256314A543479317A37486E)（discovered_entry_identity_or_detail_pending）; [黑马程序员前端JavaScript入门到精通全套视频教程，javascript核心进阶ES6语法、API、js高级等基础知识和实战教程](https://www.bilibili.com/video/BV1Y84y1L7Nn/?uid=42563159383479314C374E6E)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\web_pomodoro_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### arduino_reaction_beginner / k1 — Arduino低压电路安全接线与LED极性

主因：`detail_admission_unresolved`。明确的 Arduino 限流电阻计算课已被真实检索观察，但本轮为 not_fetched。七段数码管共阳/共阴课和过大 LED 页面不足以证明全部安全接线目标。终态 trace 不含逐点 probe 启动队列，不能断言哪一个 cap 消耗了名额。
候选 24；详情状态 {'not_fetched': 14, 'fetched': 9, 'too_large': 1}；已执行查询 4。
建议：对真实队列做离线准入重放；未抓详情不等于链接失效或源不存在。
已存来源：[【Arduino入门】2-限流电阻计算与控制多个LED](https://www.bilibili.com/video/BV19d4y1K7MF/?uid=42563139643479314B374D46)（discovered_entry_identity_or_detail_pending）; [Arduino CC++编程 第10讲 共阴极&共阳极](https://www.bilibili.com/video/BV1ho4y1p7mn/?uid=425631686F34793170376D6E)（same_page_video_metadata_verified_no_playback_test）; [Arduino Uno 基础实践：使用 digitalWrite 命令控制外接 LED 闪烁](https://www.bilibili.com/video/BV1FYtJ68Eo8/?uid=4256314659744A3638456F38)（recorded_fetch_limitation_not_assumed_dead_link）
证据：`evidence\phase2-read-r9c\arduino_reaction_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### arduino_reaction_beginner / k3 — 按钮去抖的稳定时间窗口实现

主因：`specific_behavior_evidence_missing`。Arduino 去抖视频真实存在，但自身摘要未给出 millis 稳定窗口、下降沿与按住不重复触发的具体依据。搜索关联文本链接不能充当该视频教法。
候选 23；详情状态 {'not_fetched': 13, 'fetched': 10}；已执行查询 4。
建议：可说明去抖主题相关，不能把稳定窗口与边沿实现自动标为已教。
已存来源：[arduino教程(10) 官网教程之键盘去抖动的算法（debounce）](https://www.bilibili.com/video/BV1Qa4y1t7UJ/?uid=42563151613479317437554A)（same_page_video_metadata_verified_no_playback_test）; [Arduino基础-去抖动防误触代码](https://www.bilibili.com/video/BV1fz411b7Ur/?uid=425631667A34313162375572)（same_page_video_metadata_verified_no_playback_test）; [Arduino初级第九课按键消抖动](https://www.bilibili.com/video/BV1NM4y1S7k7/?uid=4256314E4D34793153376B37)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\arduino_reaction_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### arduino_reaction_beginner / k4 — 非阻塞随机等待与millis计时

主因：`transferable_skill_project_coupling`。Arduino random 真实课程可教随机函数；未证实 random(2000,5001)、millis 差值及非阻塞等待组合。定时器串口广告描述也不能证明 millis。
候选 24；详情状态 {'not_fetched': 14, 'fetched': 10}；已执行查询 4。
建议：随机范围和非阻塞计时作为独立技能；2000/5001 保留为项目参数，不能由泛 random 标题补齐。
已存来源：[arduino函数 数学 random() 产生随机数](https://www.bilibili.com/video/BV1Lb41147Ep/?uid=4256314C6234313134374570)（same_page_video_metadata_verified_no_playback_test）; [腾讯T2手把手教你！Arduino中的定时器功能怎么使用？通过串口监视器输出递增数据说明如何实现定时功能](https://www.bilibili.com/video/BV1b54y1y7xd/?uid=425631623534793179377864)（same_page_video_metadata_verified_no_playback_test）; [Using Random Numbers with Arduino [SOLVED] [Guide + Code]](https://www.programmingelectronics.com/using-random-numbers-with-arduino/)（fetched_webpage_not_proven_video_excluded）
证据：`evidence\phase2-read-r9c\arduino_reaction_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### arduino_reaction_beginner / k5 — 反应时间游戏状态机与主循环

主因：`relevant_video_recall_insufficient`。ArControl 图形积木状态机不是 Arduino C++ Sketch；按钮切换 LED 不等于反应时间/抢按判断。FCC 已绑定 Arduino 全课但自身发布摘要太泛，未有 switch 状态与计时教学依据。
候选 24；详情状态 {'fetched': 10, 'not_fetched': 14}；已执行查询 4。
建议：保持工具 owner 隔离，不能将图形化演示提升为 C++ 状态机教学。
已存来源：[[Arduino] 2_状态机可视化编程_ArControl工具_实例"炸弹游戏"](https://www.bilibili.com/video/BV13v411v7TN/?uid=42563133763431317637544E)（same_page_video_metadata_verified_no_playback_test）; [Arduino编程，每按一次按键，小灯状态切换一次。实现方法A 4-2逻辑运算，学习时序的概念，学习逻辑表达式和逻辑运算。](https://www.bilibili.com/video/BV19h411s7in/?uid=42563139683431317337696E)（same_page_video_metadata_verified_no_playback_test）; [Arduino for Everybody](https://www.freecodecamp.org/news/arduino-for-everybody/)（same_page_video_metadata_verified_no_playback_test）; [Create Your Own Electronics With Arduino - Full Course](https://www.freecodecamp.org/news/create-your-own-electronics-with-arduino-full-course/)（same_page_video_metadata_verified_no_playback_test）
证据：`evidence\phase2-read-r9c\arduino_reaction_beginner\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### study_room_streamlit_intermediate / k2 — pandas 列校验与逐行规则验证

主因：`specific_behavior_evidence_missing`。已抓 pandas 基础方法/整课未在自身目录中证明目标 schema、格式掩码、列运算与排除计数，且项目明确不去重。泛清洗标题不能覆盖这些约束。
候选 24；详情状态 {'not_fetched': 17, 'fetched': 6, 'not_found': 1}；已执行查询 4。
建议：推荐新的验证/布尔掩码技能，而不是重推学生已会的数据读取。
已存来源：[【Pandas系列】Pandas的DataFrame的常见用法](https://www.bilibili.com/video/BV1aU411U7S3/?uid=425631615534313155375333)（same_page_video_metadata_verified_no_playback_test）; [【全 57 集】Pandas 数据分析全套教程，零基础入门到实战，全程干货无废话](https://www.bilibili.com/video/BV1ZaZFBCEZ2/?uid=4256315A615A464243455A32)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\study_room_streamlit_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### study_room_streamlit_intermediate / k3 — Streamlit 日期区间与多选控件

主因：`relevant_video_recall_insufficient`。date_input/multiselect 实际查询已执行；已绑定 Streamlit 全课仅有输入控件等目录标签，未见这两个 API 与空选语义的自身证据。另一全课 too_large 是体积限制，不是坏链接。
候选 11；详情状态 {'not_fetched': 4, 'fetched': 6, 'too_large': 1}；已执行查询 4。
建议：可标输入控件主题相关，不宣称本课必教 date_input/multiselect 或空选全部。
已存来源：[【国语】Streamlit与Python：构建与部署真实世界数据应用 教程](https://www.bilibili.com/video/BV1DoFDzjEY6/?uid=425631446F46447A6A455936)（discovered_entry_identity_or_detail_pending）; [Streamlit数据面板网页开发入门教程](https://www.bilibili.com/video/BV1m9SfYyEuw/?uid=4256316D3953665979457577)（same_page_video_metadata_verified_no_playback_test）; [Python Streamlit 完全教程](https://www.bilibili.com/video/BV1yHVhz1EUD/?uid=425631794856687A31455544)（recorded_fetch_limitation_not_assumed_dead_link）
证据：`evidence\phase2-read-r9c\study_room_streamlit_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### study_room_streamlit_intermediate / k4 — 筛选后数据的加权使用率聚合

主因：`transferable_skill_project_coupling`。pandas 分组聚合真实课存在，但学生已会该技能；自身目录未证明加权占用率、f-string 与共享过滤口径。Excel 错工具卡已撤回，不能用它填补此项。
候选 23；详情状态 {'not_found': 1, 'fetched': 7, 'not_fetched': 15}；已执行查询 4。
建议：只推荐新的分子分母聚合/格式化能力，公式和口径保留项目检验。
已存来源：[8.Pandas教程_分组与聚合-数据分析与探索-[Python]](https://www.bilibili.com/video/BV1n7YLepEx6/?uid=4256316E37594C6570457836)（same_page_video_metadata_verified_no_playback_test）; [2026年最佳（没有之一）Pandas数据分析教程，由浅入深讲解，一套搞定Pandas数据分析与可视化！](https://www.bilibili.com/video/BV15VopBwE8C/?uid=42563135566F704277453843)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\study_room_streamlit_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

### study_room_streamlit_intermediate / k6 — 空结果的安全展示

主因：`specific_behavior_evidence_missing`。st.dataframe 自身定义能支持显示表格，但没有空数据/分母为零/条件提示的证据。KNN Streamlit 成品演示不能充当保护分支教学。
候选 20；详情状态 {'not_fetched': 13, 'fetched': 7}；已执行查询 6。
建议：表格显示可以独立相关；st.info/error 与零分母防护须各自有据。
已存来源：[python streamlit 数据显示元素dataframe](https://www.bilibili.com/video/BV1o24y1N7XL/?uid=4256316F323479314E37584C)（same_page_video_metadata_verified_no_playback_test）; [streamlit-KNN分类器效果展示](https://www.bilibili.com/video/BV1Ha4y157Bz/?uid=42563148613479313537427A)（same_page_video_metadata_verified_no_playback_test）; [【国语】Streamlit与Python：构建与部署真实世界数据应用 教程](https://www.bilibili.com/video/BV1DoFDzjEY6/?uid=425631446F46447A6A455936)（discovered_entry_identity_or_detail_pending）
证据：`evidence\phase2-read-r9c\study_room_streamlit_intermediate\project-results.json`；完整字段/ID/来源/语言见 JSON source bank。

## 分布与边界

{"specific_parameter_evidence_missing": 1, "relevant_video_recall_insufficient": 5, "support_basis_layer_mismatch": 1, "transferable_skill_project_coupling": 5, "confirmed_own_code_extraction_loss": 1, "specific_behavior_evidence_missing": 4, "confirmed_property_negation_misveto": 1, "detail_admission_unresolved": 1}

没有任何单元足以证明互联网上不存在合法相关视频。未抓详情、有限目录、访问/体积限制必须分别报告。
建议将可迁移技能与项目实践校验分开；若加入语义判别，只能引用已知媒体身份、已知 ID 和逐字 own-source quote，保留全句教学范围、原参数及未知项，设置每 job 两次硬上限和失败回退。
所有来源只验证已有页面元数据和视频绑定；未验证播放。html.lang 不证明视频音频语种，显式课程门槛之外学生阶段仍未知。
