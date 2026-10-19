# Web v3 / Arduino v2 独立真实来源审核

真实结果仍未达到核心生产覆盖：Web 7 单元只有 1 张标题级卡，Arduino 6 单元、13 技能为 0 卡。原数组访问→渲染、泛事件→具体按钮两条假阳性已撤回；不能因此宣称任务验收通过。

本轮仅有已授权本地 GET（8 次成功，最初错误路由 6 次404另存）和 SQLite query_only 读取；0 新上游、0 模型、0 数据库写、0 主/运行源码修改。

显示卡 BV1pE4m1R7JE 的 own title、媒体 identity、quote/hash 均可核对。只接受“原生 JS 按钮点击绑定”主题线索，不声称正文深度、disabled、渲染或项目完成；页面中文不代表音频中文，登录/收费未知。

确认的 P2：同 BV 分 P catalog 被 URL exact gate 排除；首8观察槽位继续挡住后课；招聘列表教学题材误受招聘/新闻扣分；Arduino 20送审仅10有效判定；PWM引脚明确主题被漏判；精准 analogWrite 资料被通用/跨板 PWM 候选挤出4槽。各原始证据和反事实互相分开。

独立 same-BV/观察槽位候选已冻结，40新增+235既有回归通过。它只修召回与绑定，不产生新教学声明；现存真实结果仍按旧运行结果计。

| 单元/技能 | 主因 | 已存具体依据与未知范围 |
|---|---|---|
| k1/skill_1: 阅读 Arduino 官方板卡引脚图确定模拟输入与 PWM 引脚 | own_scope_incomplete | Own UNO/analog/digital/PWM title is a board/pin overview, not explicit instruction to consult an official pin diagram. No same-demo or exact pin-number requirement added. |
| k1/skill_2: 按极性正确连接 LED 与限流电阻 | own_scope_incomplete | LED/resistor title and generic correct-use description establish subject relevance; polarity and actual wiring procedure are not explicitly stated. Do not substitute resistor-value arithmetic for polarity wiring. |
| k1/skill_3: 断电接线并检查共地的安全操作步骤 | own_scope_incomplete | No retained own teaching passage states power-off wiring plus common-ground checks. General LED family is insufficient; not evidence of internet unavailability. |
| k2/skill_1: Arduino analogRead 读取模拟量，并初始化串口打印原始读数 | catalog_binding_and_slot_loss | Actual own p30 declares analogRead; currently discarded by part-URL guard then first8 observations. Exact source does not explicitly prove serial initialization plus raw-value print in the same skill, so full composite remains unknown. Patched selection admits this source as fourth candidate. |
| k2/skill_2: 通过旋转两端与中间判断读数范围是否合理 | own_scope_incomplete | Own p29 potentiometer/p31 potentiometer-controlled LED are useful topics; endpoints/midpoint range-validity checking method is not stated in retained metadata. |
| k3/skill_1: Arduino millis 时间戳差值实现周期任务 | detail_admission_gap | Actual discovered title 通过millis来实现时间中断 remains search-only. Cannot use snippet as support. Fetched generic timer/LCD and Arduino overview do not prove millis timestamp-difference scheduling. |
| k3/skill_2: 用非阻塞方式替换 delay 保持循环响应 | query_and_evidence_gap | Secondary queries omit Arduino and return epoll/Simulink/Spring/system-delay subjects. Fetched timer/LCD title does not prove replacing blocking delay with responsive looping. |
| k4/skill_1: Arduino map 线性映射与整数截断处理 | query_and_evidence_gap | Own title/description teach numerical mapping as a topic; no literal map API plus integer-truncation handling. Mixly graphical course is not C++ map API instruction; generic linear-algebra results cannot count. |
| k4/skill_2: 用 constrain 或 min/max 限制输出在有效范围 | query_and_evidence_gap | No retained fetched source explicitly teaches constrain/min-max clipping. Min-max normalization and generic mapping are different operations. Compact declared Arduino+literal API recall is a bounded test suggestion, not proven improved recall. |
| k5/skill_1: Arduino analogWrite 占空比控制输出 | candidate_selection | Actual fetched beginner analogWrite lesson excluded from top4 in favor of generic PWM/ESP32/Buck sources. Same-course p26 analogWrite/p27 PWM also lost. A specific analogWrite title is a topic pointer; do not automatically fill duty-cycle parameters or full method. Even catalog patch alone leaves this single lesson outside4. |
| k5/skill_2: 识别并选用支持 PWM 的数字引脚 | semantic_under_recall | Actual own title explicitly teaches Arduino PWM-output pin usage, selected and saved empty. Manual title-topic gold and structural-only counterfactual saved separately; analogWrite and exact Uno pins still unknown. |
| k6/skill_1: Arduino 串口多值输出的标签与行格式设计 | own_scope_incomplete | Own serial communication/output-function topics do not explicitly teach labeled multi-variable line formatting. Do not insist on identical potentiometer values; the missing facet is formatting multiple values. |
| k6/skill_2: 在非阻塞周期节拍内打印多个变量 | own_scope_incomplete | Own basic serial/temperature-monitor description does not show multi-variable printing inside a nonblocking periodic cycle. Timer and serial families cannot be spliced across sources into this whole skill. |

具体反事实及字段证据见同目录 audit.json、web-reviewed-title-rank-drop.json、arduino-pwm-pin-counterfactual.json、arduino-selection-replay.json。不得把反事实当新 live、把目录话题当完整方法，或把当前不足说成互联网无课。
