# r10 后端合同原因审计

本轮只读保留证据与纯函数反事实，没有修改主源码、测试或数据库，没有 HTTP/模型调用。r9c 保持可运行。

19 个 UI 无支持单元全部混用了可迁移技能、具体 API/参数以及项目验收目标；这属于目标层设计问题，不代表这些参数应被视频泛泛覆盖。3 个已有局部材料但 UI 正文/目录仍为零，16 个无卡。所有19已有至少一种已确认视频身份的候选，但媒体身份并不证明内容相关。

83 次有界纯函数反事实保留原媒体与全部证据：9 个较窄技能/技能族有阳性（3 个原已局部显示、6 个原无卡）；其中输入控件族仍需独立判定。3 个阳性只是相邻/先修，不能当恢复成功；7 个在抽样中未得阳性，原因未定。没有一例能证明合法来源确实不可得。

| 项目/单元 | 现象与可证实主因 |
|---|---|
| bicycle_csv_advanced / k3 | 真实to_datetime用法已展示为API核心；pd别名/errors、无效集合和end<start是不同层，不应让解析技能消失，也不能宣称这些项目规则已教。 |
| bicycle_csv_advanced / k4 | 已存主要是时间序列预测/通用Pandas课程；抽样未见Timedelta/total_seconds教学，不可用预测课程填时间差。 |
| bicycle_csv_advanced / k7 | 已裁定标题partial与正文目录两层；当前搜索ID支持，own标题同文但英文目录未获有限解析器支持，不硬换ID。 |
| pygame_maze_intermediate / k1 | 有地图生成视频和其他工具Tilemap视频；地图生成并不自动教二维列表渲染，Unity/u2d不能借Pygame标签。 |
| pygame_maze_intermediate / k2 | Pong玩家移动范围限制是可迁移边界检查材料；不证明(col,row)、0..7、墙格查询与target验证。 |
| pygame_maze_intermediate / k3 | 已有键盘事件/Basic Movement等媒体，原KEYDOWN单次与get_pressed区别无充分源声明；抽样改词仍无阳性，不能确定是未取细节还是词法。 |
| pygame_maze_intermediate / k5 | 已有键盘事件和主循环文字，但R/Esc、胜利不退出、按状态限键均是项目应用；本轮核心反事实未成功，不能据此断定无可迁移课。 |
| web_pomodoro_beginner / k1 | HTML语义化own视频可教可迁移页面结构；番茄钟文本占位/原生button/可读标签不能由相关视频尾巴补入。 |
| web_pomodoro_beginner / k4 | 普通倒计时可命中，但没有Date.now绝对截止/后台准确性源证；普通倒计时仅先修，不作为修复成功。 |
| web_pomodoro_beginner / k5 | 已有JS秒表开始暂停继续重置own标题/简介；同控制机制可迁移，不能因此声称恢复截止时间、后台精度和项目状态策略。 |
| web_pomodoro_beginner / k6 | 阶段切换/专注计数是应用条件；已存多为JS基础课，没有逐条证明阶段状态迁移。不能拿泛基础课替代组件课程。 |
| arduino_reaction_beginner / k1 | 现有共阴阳数码管/通用Arduino媒体未明示全部LED极性、电阻、共地和断电检查；安全内容不能靠标题推断。 |
| arduino_reaction_beginner / k3 | 真实debounce算法课程可教去抖主题；稳定窗口、millis非阻塞、下降沿与长按单次各须保留未知或独立取证。 |
| arduino_reaction_beginner / k4 | random函数已有API核心partial；2000..5001、非阻塞与millis差值不能从随机数课推断。 |
| arduino_reaction_beginner / k5 | ArControl图形化状态机并非原生C++ switch-case；单灯切换也不等于反应游戏FSM。本轮样本无合适核心阳性。 |
| study_room_streamlit_intermediate / k2 | occupied<=capacity*open_minutes是本数据验收式；通用过滤可迁移但不能删掉不去重/列规则。现抽样未获布尔索引核心阳性。 |
| study_room_streamlit_intermediate / k3 | 已存own目录用户输入控件能命中较宽技能族；不能据此认date_input/multiselect、闭区间/空选语义已教，需独立审适用性。 |
| study_room_streamlit_intermediate / k4 | Pandas分组与聚合own课程可教汇总；加权比率、过滤口径、百分比格式与该业务公式不能整体赠予。 |
| study_room_streamlit_intermediate / k6 | st.dataframe显示课是正常表格展示先修，不能证明空结果判断、除零防护或info/error分支。 |

通用最小方案是新增可编辑 learning_skills，保留 project_task、practice_check 和原 concepts/约束。对教学技能做来源绑定、精确引文和指纹校验；项目字段、数值、验收表达式留在应用验证层。源只教通用技能时可显示可迁移材料，不能给原参数/行为打勾。标题线索和正文/目录教学继续分层。

支持 root 提议的每 job 最多两次有限语义调用、只输入技能与已绑定 own 字段、返回已知 IDs 与逐字 quote；GET 只重验持久化指纹，不调用模型。应拒绝泛基础课替代具体技能、错工具、仅先修/未来/TODO/否定/演示和跨课拼接。

详细逐例证据、函数行号、实验反事实和边界见 backend-contract-audit.json、pure-counterfactuals.json、retained-candidate-sample.json。以上实验不计作新增覆盖或生产内容通过。
