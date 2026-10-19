# Arduino potLED v3：真实新来源独立审核

6单元13技能，实际4张去重卡；6是送复核claim数，4是accepted，不能重复平台分栏计卡。来源身份/quote/hash均可核，但3张完整技能声明超出own证据，不能验收通过。

| 视频 | 证据层 | 独立结论 |
|---|---|---|
| 【电子基础-双语自翻】8# 关于LED与限流电阻 ( GreatScott! / Electronic Basics ) | description | reject_full_skill_claim: Own source says only correct LED use. It never explicitly states polarity or connecting a current-limiting resistor; the title names LED/resistors as a family. This cannot establish the full declared skill. |
| 05 模拟输入｜数值映射与串口监视器｜mixly图形化编程｜Arduino 轻松学 | description | reject_full_skill_claim: Own source teaches numerical mapping in Mixly graphical programming. No literal Arduino map API or integer truncation instruction. Different demo is acceptable; missing programming method/facets are not. |
| 第六课Arduino系列课程~模拟输入、数值映射与串口监视器 | description | reject_full_skill_claim: Own source declares numerical mapping only. No map API or integer-truncation teaching in its own title/description/part. Parent technology cannot donate those methods. |
| 【太极创客】零基础入门学用Arduino 第一部分 合辑 | catalog | accept_scoped_catalog_topic_only: Observed own part26 explicitly declares Arduino analogWrite analog-output lesson. Useful direct catalog topic pointer. It does not prove observed body instruction, exact duty-cycle parameters, PWM pins or student mastery; do not count it as watched/body-verified complete implementation. |

真实关闭：同BV的analogWrite第26P已进入结果并保留实际链接；单pair校验失败未吞整批其它结果。

仍阻塞：泛LED正确使用没有极性/限流电阻接线证据；两条数值映射没有map API与整数截断依据，其中一条明确为Mixly图形化。章节标题只证明课程列出analogWrite课题，不证明已观察视频正文或完整实现。

4次只读本地GET；0上游/模型/DB写/源码改动。语言、登录、付费、播放状态均保留未知边界。
