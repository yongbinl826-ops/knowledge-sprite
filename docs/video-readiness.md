# 视频推荐独立验收（2026-10-18）

这份验收针对当前工作区源码的新运行；旧检索版本、旧测试总数和成功截图不作为本次生产验收。只要求学生能跳转真实来源平台，不要求自动播放。需要登录、购买、选课或受地区限制，不等于链接无效。

## 原始复合单元压力验收门槛

| 项目 | 观察与通过条件 |
| --- | --- |
| 具体学习单元 | Pygame 事件处理与碰撞检测、pandas 分组聚合与图表绘制、JavaScript 表单校验与 fetch API 请求、Arduino 模拟传感器读取与串口输出。每个单元需要有直接来源证据；只覆盖一部分的候选必须明确标为部分覆盖。 |
| 需求覆盖 | 四个单元均有可用候选，且所有请求子项有直接证据或互补资源集合证据；没有证据的子项保持未知。找到一个部分候选不算整个单元验收通过。 |
| 粒度与相关性 | 不用“Python 基础课”“JavaScript 基础课”“Arduino 入门介绍”替代事件、碰撞、表单、聚合、传感器等具体任务；先修提及、广告、相关链接文字不升级为本课教学证据。 |
| 学生阶段 | 使用学生所选阶段。来源明确写入门、进阶或高级才用于阶段排序；未标明时显示门槛未确认。不把“not for beginners”误当适合入门。 |
| 真实来源 | 标题和 URL 只能来自真实搜索/公开页面。课程类型、视频身份、章节/分 P 和片段信息都需要独立来源证据。未知时间码不得生成。 |
| 安全 | 排序读取旧数据时再次校验原始、规范与最终 URL。危险协议、凭据 URL、私网、本机、元数据地址、非标准端口不能变成推荐链接；详情连接时仍进行 DNS 校验、固定 IP 和逐跳重定向检查。 |
| 预算与退让 | 搜索、详情、并发、截止时间保持服务器已有预算；每个学习单元第一轮保留公平份额。401/403/429 或来源暂停不可通过切换来源来绕过。文档/官网不能凭关键词变成视频。 |

## 已完成改动

- `ranking.py` 在读取/排序入口重新验证 URL，并把原学习单元与来源中的阶段信息放入推荐理由。未知门槛明说未知，阶段不匹配给予排序降权和先修提示；这些提示不增加教学覆盖证据。
- 支持“中文概念 与 English API 概念”这一显式结构。例如“JavaScript 表单校验与 fetch API 请求”可分别评估两部分；仅有 Fetch 请求证据时，表单仍为未知，候选进入部分覆盖区。
- 在用户选择 B 站时，先给包含完整原知识单元的 B 站视频入口定向查询一个公平份额；保留开放检索与其他来源查询。紧预算先保障每个单元首轮的独立备用来源空间，避免两个一请求轮次都耗在空的主来源响应上。未提高总预算，未添加固定课程 URL，也未降低最终证据门槛。

## 真实运行与失败案例

原始运行见 `evidence/video-live-20261018.json`，原始数据库在同名 `.sqlite3`。使用既有授权配置执行一个四单元任务：**12 次真实搜索、24 个候选、8 次详情，8 次详情完成**。搜索和详情均无旧缓存命中。

| 学习单元 | 原始真实运行 | 混合语言修复后保存证据回放 |
| --- | --- | --- |
| Pygame 事件/碰撞 | 0 | 0 |
| pandas 聚合/图表 | 5 个部分候选；只证实聚合 | 5 个部分候选；图表仍未知 |
| JavaScript 表单/Fetch | 0 | 3 个部分候选；只证实 Fetch 请求 |
| Arduino 传感器/串口 | 0 | 0 |

回放见 `evidence/video-replay-20261018.json`，明确标为 `saved-live-evidence-replay`、新网络请求为 0。没有把回放当作新的真实集成通过。

真实缺陷是：主视频搜索来源在首轮返回超时/未知错误，前两轮开放检索耗尽 12 次请求；Pygame/Arduino 的备用开放来源返回大量官网/文档，未通过视频类型与教学相关性门槛。pandas 聚合视频来自真实 B 站页面，不能据此声称图表也已覆盖。JavaScript 原先因混合语言显式子项不能分开评估而丢失真正相关的 Fetch 视频，此问题已精准修复。

第二轮同样 12 次搜索预算的复验见 `evidence/video-live-scheduled-20261018.json`：12 次搜索、12 次详情完成，四个单元均发现相关候选，pandas 仍缺图表。该早期报告的 `passed-discovery-gates-manual-relevance-review-required` 仅指当时的链接发现门槛，不能解释为所有子项覆盖或人工审查通过。

第三轮 `evidence/video-live-gaps-20261018.json` 加入缺口优先检索与严格子项门槛，结果为 **not-production-accepted**：12 次搜索、12 次详情，6 个查询返回候选，1 个查询上游失败。真实执行了事件处理、图表绘制定向查询；事件查询上游失败，图表查询返回长课程，但未获得具体绘图章节证据。

人工审查发现旧中文匹配曾把大纲中的“键盘事件”和另一章“图像处理”拼接成“事件处理”。已要求处理/绘制/校验这类名词动作在来源局部绑定，且否定教学声明不能证明覆盖。修复前的完整覆盖计数作废，不作为生产结论。

对第三轮真实观察的最终零网络回放在 `evidence/video-final-replay-20261018.json`：

| 单元 | 完整候选 | 部分候选 | 结论 |
| --- | --- | --- | --- |
| Pygame | 0 | 3 | 事件处理未知 |
| pandas | 0 | 5 | 图表绘制未知 |
| JavaScript | 0 | 4 | 部分候选集合互补覆盖表单与 Fetch；单条完整课未知 |
| Arduino | 1 | 1 | 请求的两个子项均有直接来源支持 |

## 执行恢复后的修复与默认预算复验

执行环境恢复后已确认最后源码和三个否定动作测试落盘，原相关套件新运行 **344 passed**，不能用旧的 341 计数代替。

进一步定位到详情准入缺陷：`_detail_queues` 仅为已有主题证据的候选抓页面，因此缺口查询返回的真实长视频课即使可能有具体章节，也没有机会获取目录。现在仅为明确缺口查询返回、视频身份有证据、标题含同一技术上下文的候选，允许每个单元最多 **2 次目录探测**；仍计入原详情预算，来源页面未证明技能时不会进入结果。新专项套件 **40 passed**，包含“查询不能证明技能、只有返回的页面事实才能补齐技能、第三条泛课程不探测”的完整流程用例。

此前 12 搜索/12 详情是既有本机配置的紧预算，不是应用默认。最后一次真实验收使用应用实际默认 **30 搜索/40 详情**，保留现有平台策略、端点及超时设置，并在报告 `configuration.budget_profile` 明确写为 `application-default`。报告路径为 `evidence/video-live-default-20261018.json`；只有报告完整结束并通过人工逐项审查后，才能采用其结果。

该默认预算运行结束：30 次真实搜索、14 个查询成功、2 个失败、13 次详情完成，事件/图表仍未证实。发现另一恢复缺陷：缺口仅在首轮之后计算；首轮失败、后续才取得部分覆盖时，不会补查缺失技能。现改为每个公平轮边界重新评估，同一缺口不重复提交。新完整流程测试覆盖“首轮空结果→下一轮仅聚合→第三轮定向图表”，相关新回归 **136 passed**。同预算修复后复验保存在 `evidence/video-live-recovery-20261018.json`，保留默认预算失败报告。

## 本地回归

新增 `tests/test_video_readiness.py` 包含具体项目正例、泛基础负例、访问条件、危险 URL、阶段排序、阶段排除措辞、无证据章节、混合语言部分覆盖、模型关键词边界和视频首轮预算公平性。

- 执行恢复、否定动作过滤及目录探测全部落盘后，最新扩大回归 **401 passed**：视频 readiness、evidence followup、project followup matching、saved relevance、identity、queries、预算、provider routing、discovery、core，以及 platform catalog adapters/integration/platform results。仅有依赖的 Starlette/httpx deprecation 提示。这是当前代码的新执行结果。
- 混合语言修复后的相关证据回归：**228 passed**（readiness、evidence followup、project followup matching、saved link relevance、resource identity、compact queries）。
- 调度修改后预算/来源/核心回归：**137 passed**，覆盖新 readiness、search budget preservation、provider routing、discovery completion 和 core。仅有依赖的 Starlette/httpx deprecation 提示。
- 上述均为本地合成或保存证据回归，不计为真实接口通过率。

Windows 当前沙箱会在创建 asyncio 事件循环时卡住。使用 `asyncio.run(asyncio.sleep(0))` 最小无网络诊断确认沙箱外正常后，真实任务和异步测试经执行审核在沙箱外运行；没有因此更改平台访问策略或放宽网络目标。

## 可复跑命令

在项目工作区执行，`--env-file` 指向已获授权的本地配置；脚本不会复制配置、记录密钥或内部检索端点。指定新的输出文件以保存先前证据。

```powershell
Set-Location -LiteralPath '<当前项目工作区>'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --env-file 'D:\项目制知识引导小精灵\.env' --output evidence\video-live-new.json
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --env-file 'D:\项目制知识引导小精灵\.env' --default-resource-budgets --output evidence\video-live-default-new.json
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --replay-from evidence\video-live-20261018.json --output evidence\video-replay-new.json
```

如果阶段信息或某个技能子项仍未知，产品应展示未知与重试/调整选择入口；不能把已有部分结果包装成“该项目所有技能已覆盖”。生产前仍需验证真实使用流量下已配置搜索来源的可用性与代表性项目召回覆盖。


## 最终产品单元验收与键盘意图修复

以上为逐轮历史，失败记录均保留。本节是当前代码与最后证据的结论，不能用前文历史测试计数或某一轮的 `passed` 字样宣称整站可生产。

原始压力集把“pandas 分组聚合与图表绘制”绑定到同一个 pandas 上下文。真实学习分析的销售看板默认选用 Streamlit；采用 pandas + Matplotlib 时，聚合和绘图应是两个学习单元。本次另建五单元产品验收：实际小游戏分析生成的 `pygame 键盘控制角色左右移动`、`pandas 分组聚合`、明确选定技术方案变体的 `matplotlib 绘图与图像保存`，加上原网站与硬件单元。Matplotlib 单元不是声称原分析选择了 Matplotlib，也不是把 Matplotlib 课程冒充 pandas 的 plot API。原复合压力集不改名、不删除，其未知项仍未知。

最终五单元真实运行 `evidence/video-product-live-20261018.json` 使用应用默认上限 **30 搜索 / 40 详情**，实际 **30 搜索 / 14 详情**，17 条查询执行，14 成功、3 失败，81 个候选、66 个资源，240 秒保存为部分完成。该报告为 **not-production-accepted**：键盘单元当时显示 0。只读数据库复核却发现 DDG 已返回三条具体键盘移动视频，问题是长中文整短语把“角色”与“小船”“游戏人物”的相同输入移动操作判成不同概念。因而这次 0 不能全部归因于索引不足。

局部修复仅覆盖明确的 Pygame 键盘/按键控制人物移动意图：要求同一来源、Pygame 技术上下文、局部绑定的键盘 → 控制对象 → 移动，或来源明确的“键盘按下状态 → 根据状态调整角色位置”数据流。它不把只介绍键盘输入的泛课、Scratch 例子、否定教学、先修要求、另一个课程大纲或仅一个 API 名称当作支持；不能丢弃地图边界等额外目标。原短视频附全课程大纲的隔离继续有效：只有 1 个真实分P、可观测时长与宣传大纲多课时长矛盾时，评分副本排除“课程大纲”尾部，原始证据完整保留。

新回归包括三种真实文本形状、错技术/错域/泛课/不教键盘等负例、额外限定项，以及原 HTML 表单教学修饰语正例和三条否定动作负例。当前相关回归 **446 passed / 1 既有 Starlette-httpx deprecation 提示**，JUnit 为 `evidence/video-intent-regression-20261018.xml`。这是离线合成与存量证据回归数，不是 446 次真实接口成功。

| 产品学习单元 | 修复后保存证据回放 | 具体人工核查 |
| --- | --- | --- |
| pygame 键盘控制角色左右移动 | 3 直接主题支持 | 三条均在随后单元真实复测取得公开页面；例子对象不同不影响键盘控制移动操作。 |
| pandas 分组聚合 | 5 直接主题支持 | [数据合并与分组聚合 P3](https://www.bilibili.com/video/BV19J411n7iN/?p=3)、P4 有真实目录证据；不宣称使用学生的销售业务字段。 |
| matplotlib 绘图与图像保存 | 1 直接支持、5 部分候选 | 最后 live 实际抓到 [P8 图像保存](https://www.bilibili.com/video/BV1PqopB1Et6/?p=8)，真实标题 `08-matplotlib绘图-图像保存`，660 秒。较早 98P 来源另有 [P92](https://www.bilibili.com/video/BV1ohzvBxEvB/?p=92) 同主题 663 秒，仅作为独立历史证据。 |
| JavaScript 表单校验与 fetch API 请求 | 4 部分候选，集合互补覆盖两项 | Fetch 视频与表单视频分别支持各自子项，未把任何一条升级为两项完整教学；表单来源此轮仅搜索发现，页面与先修未知。 |
| Arduino 模拟传感器读取与串口输出 | 1 直接支持、1 部分 | [模拟输入、映射与串口监视器](https://www.bilibili.com/video/BV1Hi4y1m7CR/) 的真实页简介明确传感器数据输入、处理、串口显示流程。 |

该回放是 `evidence/video-product-intent-replay-20261018.json`，新增网络请求 **0**；五单元主题来源门槛达到，报告仍要求人工相关性复核，没有伪装成新 live 或独立盲测。人工复核记录 `evidence/video-product-intent-manual-review-20261018.json`：五单元都有相关元信息证据；完整教学、每个学习目标、服务稳定性不在此结论内。没有明确先修的来源继续标记门槛未知，课程标题“入门”不等于后续具体分P没有先修。

修复后只对原键盘单元新跑一次受限真实复测 `evidence/video-keyboard-live-followup-20261018.json`，未注入 URL，未增大配置上限：**9 实际搜索 / 6 详情，6 查询执行，4 成功 / 2 来源失败，88.888 秒**；3 条推荐均 `fetched / page_verified`。真实复测通过发现门槛，保留来源部分失败提醒。这是针对已知缺陷的开发回归，不是独立盲测。

- [键盘事件控制小船左右移动](https://www.bilibili.com/video/BV12t4y1P73a/)：真实 P1 215 秒，支持具体键盘移动；不能据此保证连续按键 API、地图边界或整个接球项目。
- [控制角色移动的两种方式](https://www.bilibili.com/video/BV17TygBeExJ/)：真实 P1 289 秒，页面简介明确键盘按下状态与角色位置更新、实时与事件两种方式，并原文给出 **0:40 实时状态移动、2:42 事件方式移动**。这些是来源给出的片段位置，未编造结束时间或新分P，没有验证播放，也没有推断未出现的函数名。
- [使用键盘控制游戏人物移动](https://www.bilibili.com/video/BV1K44y1a7LL/)：真实 P1 458 秒，标题与简介直接支持键盘控制人物移动。

## 索引可用性的精确边界

只读 `/config` 诊断保存在 `evidence/searxng-source-config-20261018.json` 与 `evidence/searxng-video-config-20261018.json`；当前 SearXNG 只暴露 Bing general/web 与 DuckDuckGo videos，未提供额外视频索引。实际配置显式以 DDG video 为主、Bing 为允许的独立退让，不含 Bili/YouTube 直连引擎。

`evidence/video-keyboard-source-diagnosis-20261018.json` 保存最后五单元运行中四条 Pygame 查询、引擎状态及前六个标题/URL：首条 `site:bilibili.com/video` 返回 DDG upstream timeout，Bing HTTP 200 的 10 条是 pygame.org/PyPI/GitHub 等错域页，被正确拦截；下一条不带 site 的完整中文查询却由 DDG 返回 60 个视频，前六条中就有三条具体键盘移动视频。索引确有超时和忽略 site 的问题，但本轮核心漏召回是匹配器，现已修复。不能放宽域名检查或把平台文档作为视频来补数。

这些验收数据库没有 `pygame.key.get_pressed` / `arrow key movement` 英语同义查询的执行记录，不声称已经试过。后续若做查询多样化，应保持原单元评分目标、固定预算与来源约束，仅增加可审计的 API/意图查询；本轮先修实际已召回却漏抓的问题，没有无限重跑索引。

出站引擎 timeout 当前为 8 秒，应用请求 timeout 12 秒。可在独立临时实例以相同合法索引、同样查询有界比较 8 与 10 秒，不能只改应用 timeout 后推断突破引擎上限。该对照 **未执行**，也未改共享服务、D 环境或生成新凭据；首条报告 timeout 时仅耗 2.238 秒，单靠此观察不能证明增加超时会改善召回。部署前应验证允许的第三方索引在目标环境的稳定性、明确失败降级与告警；没有把新付费接口或凭据当作已具备。

复现新增路径：

```powershell
# 五单元实际默认预算；新输出名防止覆盖证据
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --suite product --env-file 'D:\项目制知识引导小精灵\.env' --default-resource-budgets --output evidence\video-product-new.json
# 只复测键盘缺口，沿用现有有限配置
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --suite product --case python-game --env-file 'D:\项目制知识引导小精灵\.env' --output evidence\video-keyboard-new.json
# 保存证据重评分，零网络
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts\accept_video_recommendations.py --suite product --replay-from evidence\video-product-live-20261018.json --output evidence\video-product-replay-new.json
```

本分支交付的是修复、可复现验收器、真实元信息来源和明确失败语义。五个产品单元的来源相关性已用最后真实观察加受限复测人工核查；不能仅凭该开发集宣称所有项目都稳定达到生产覆盖，整站发布还须集成负责人的最终项目流程、配置与可用性验收。


## 真实整项目复核新增缺口（只读，待集成负责人处理）

主流程最后模型生成的六单元中出现 `键盘长按移动挡板与边界限制`。对以上三条真实键盘来源零网络复核：未带 Pygame 名称时分解为 unknown，均未进入候选；加上 Pygame 名称虽能拆成移动/边界两项，长按动作词序仍未匹配。本次有限语法没有把它误标全覆盖，但也没有正确保留其移动核心的 partial。旧形状 `pygame 键盘控制角色左右移动与地图边界检测` 的三条则均为 partial，边界保持 unknown。该新增形状 **尚未修复**，证据 `evidence/video-keyboard-boundary-readonly-20261018.json`。

上下文流经 `project_service.py` 时，传入搜索的是学习单元 name；技术方案只进 `SearchRequest.project_context`。`service.py` 只把该字段交给模型扩展查询，确定性主题分解和排序不会继承其中的 Pygame。因而分析中明确的技术方案不能保证每条无技术名前缀的单元正确召回，新增缺口仍应纳入整项目生产验收。不能以本节之前那五个开发单元通过元信息复核，替代此次真实模型六单元联调结果。


## 长按与边界缺口的定向修复（最终）

上节为修复前只读观察，不代表当前匹配器状态。已补充严格的长按意图语法：`pygame 键盘长按移动挡板与边界限制` 仍分成两个子项；只有明确每帧/实时读取键盘状态并更新位置、按住方向键持续移动，或同一来源附近直接连贯的“键盘按下状态→角色位置”与“实时设备状态→移动角色”证据，才支持长按子项。只有 KEYDOWN/事件触发不能证明持续按下；中间出现课程大纲/另一课时、否定、先修或新技术 owner 时不组合证明。

`evidence/video-long-press-boundary-replay-20261018.json` 是已保存真实来源的零网络回放：

- BV17TygBeExJ 的真实页面描述明确上述实时状态移动关系，结果为 **partial**，`键盘长按移动挡板=supported`、`边界限制=unknown`，推荐理由直接写明尚未确认边界。
- BV12t4y1P73a、BV1K44y1a7LL 只明确键盘事件与移动，均不再用于证明长按。
- 没有一条来源标为完整覆盖；原始证据、未知项和先前失败报告保留。

本次定向测试含真实文本形状、事件与长按区分、否定/先修/跨大纲/错技术、额外目标，以及已显式添加 pygame owner 的 JobService 全流程离线测试。该集成测试证明搜索目标保留 namespace 且结果保留边界 unknown；namespace 从项目单元自身 concepts 进入搜索的 project_service 桥接改动由集成负责人负责，本分支不把 project_context 当来源证明。无新增真实网络运行，由主线程完成最终真实项目联调。


## 最终冻结快照与完整检索链路回归

长按修复最后包含真实搜索摘要的截断形状：来源先明确键盘按下状态驱动角色位置，再明确“实时获取和通过事件获取，本视频演示这两种方式”，同一来源中这段连贯方法陈述本身就是实时方式的证据，不要求先获得被搜索摘要截掉的 0:40 标签。依旧限制局部距离，排除否定、先修、另一课时和另一个技术 owner；不只因为出现“实时”两个字就匹配。

完整离线集成测试对两种已见目标分别执行 **真实文本形状的截断搜索摘要 → SearXNGProvider → JobService 候选准入 → PageFacts 详情补全 → 最终推荐**，断言每个案例实际调用一次详情补全且 `details_completed=1`：

- `pygame 键盘长按移动挡板与边界限制`：partial；长按移动 supported，边界限制 unknown。
- 最新真实模型名称加明确 namespace 后的 `pygame 键盘事件与挡板按键移动`：只评估“键盘事件”和“挡板按键移动”这两个命名子项；来源有据时可支持这两个子项，不由项目 context 或 concepts 自动添加/证明边界、计分、游戏重开等内容。

此处使用 MockTransport 和已有真实文本做可复现离线集成，不能称为新真实接口成功。最后真实来源的搜索阶段与抓页阶段分别重评分记录在 `evidence/video-pygame-final-source-replay-20261018.json`，**零网络、六项检查全 true**：BV17TygBeExJ 在真实截断搜索摘要阶段已准入，抓页后仍为长按/边界的 partial；另外两条仅键盘事件来源不证明长按。

最终相关回归 **465 passed / 1 既有 deprecation 提示**，JUnit：`evidence/video-pygame-final-regression-20261018.xml`。其中定向 readiness + completion repairs 为 104 passed。最终冻结 `ranking.py` SHA256：`1919f6827b5ceab52da1b1a1e7c58a610e2cfb9a892d33c01f50e839dfaaf85a`。本分支此后不再更改 backend；运行态应由集成负责人重载后核对该哈希及其 namespace 桥接变更，再完成真实项目 UI 复验。

## 2026-10-18 最终定向收尾：文字显示与不可见页面

本节取代前文旧冻结 hash；旧实时失败与回放证据保留。此次没有新网络查询，没有播放验证，没有改动共享服务或 D 目录。

- 对 `pygame 分数计分与屏幕文字显示` 仅做有限的 Pygame 局部同义匹配：文字/文本显示、屏幕文字显示、字体渲染，以及“显示文字”的有限倒装。仍要求同一技术 owner、局部教学依据，并保留否定、先修、相关视频尾部和其他技术隔离。真实 BV1bv4y1H76D 的“pygame教程------文字显示”现为 partial：屏幕文字显示 supported，分数计分 unknown。没有从显示文字推断计分更新。
- 初始化检查没有发现额外 rank gate 缺陷。BV1Kd7MzfE3z 与 BV1UK2xBTEDk 在现存 v7 元数据中均已经最终排为 partial；可证初始化，不能据此补齐固定帧率主循环。未对初始化扩大规则。
- 三条实际 v7 资源 BV1e5w9z8Eo9、BV1pMkLBHEdf、BV1tk6jBFEsD 抓回通用“视频去哪了呢？_哔哩哔哩_bilibili”标题和模板占位描述，旧提取器将其当正常 fetched 元信息，覆盖搜索标题并保留旧搜索视频身份。缓存没有保留完整 HTML/errorcode/可见错误面板，不能证明删除、登录、付费、地区或反爬原因。
- 新提取对该精确 Bilibili 落地标题返回 unavailable_unconfirmed。正常标题、明确同 BV 的真实 videoData 元信息不会因文中提到不可见而误分类。现有同 BV payload404+可见错误面板的强双证据规则继续 not_found；明确 login_required/captcha/access_denied 优先保留，普通付费/登录/地区限制不被称为无效链接。
- 新 fetch、旧 page cache 和历史 results 读取均应用只读投影：有可靠同一视频搜索证据则保留真实 search title，并仅从该搜索 URL 派生 search_discovered 身份；没有可靠搜索标题则使用明确的页面不可见提示。不可见来源只进入 needs_review，所有教学子项 unknown、supporting_evidence_ids 为空，附原因未确认和到平台核实提示。原始资源、证据、缓存和章节均不重写，不编造课程名、章节或删除原因。

实际 SQLite 六来源零网络回放见 `evidence/video-final-retained-source-replay-20261018.json`；全部五项检查为 true。可重放命令：

```powershell
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\evidence\video-final-readonly-replay.py'
```

完整相关回归覆盖 31 个测试文件：**1158 passed，0 failed，1 个现有 Starlette/httpx deprecation 提示**，JUnit 为 `evidence/video-final-availability-regression-20261018.xml`。包括真实文本形状的搜索准入→详情→最终 partial 集成、不可见落地新 fetch/旧缓存/历史读取、严格软404及损坏变体、否定/跨大纲/错技术、访问限制、预算退让、资源身份、缓存、平台元信息、URL 安全、渲染与 job 生命周期。以上为本地离线回归，不是新 live 成功数，也不是整项目生产覆盖验收。

另外三个空单元只读审查仍见 `evidence/video-final-project-gaps.json`：已有 Sprite/自定义碰撞、接福游戏状态更新等相关 core 候选，但不能分别证明“矩形+下落”或“状态标记+漏接结束”；重开与数据重置没有当前直接教学依据。未扩大它们的评分标准，不能宣称互联网没有相关课。现有公共索引仅 Bing general + DDG video，之前真实记录有超时和 site 约束不生效；这些源可用性/目标技能覆盖问题仍是生产前置条件。整项目生产覆盖尚未证明，需由集成负责人加载最终 hash 后做真实 UI 回归并如实报告缺口。

最终冻结清单和 SHA256：`evidence/video-final-freeze-manifest-20261018.json`。此后本分支不再自行修改 backend。

该保留数据库回放脚本位于本次工作区，依赖工作区独立的 `data/preview.sqlite3`，不面向原 D 盘学生数据库执行。最终 v8 新分析的实时发现与 UI 结果见 [本轮交付验收](delivery-acceptance.md)；原 v7 保留来源回放不能替代 v8 的新结果。

## Phase2：新公开课程来源、有限 API 等价与独立验收

最新代码冻结清单为 `evidence/phase2/video-code-freeze.json`，ranking SHA256 为 `7bc67c76a63da2a29e04d46bc952118382dd349c4ab6331f184d5f1e30196082`；前文冻结信息均作为历史记录保留。

对真实 v8 两空单元的初查见 `evidence/phase2/v8-ranking-initial-diagnosis.json`。当时碰撞点 16 来源、结束/重开点 12 来源全部未抓详情；来源题名多为泛碰撞/Sprite 或泛 pygame 课程，尚无足够的矩形、下落、结束状态或空格重开教学依据。集成负责人另修复了零覆盖单元不能进入有限目录补全的调度遗漏，但目录抓回后仍须按原单元验明内容。

本分支在现有公开元数据配置下只额外读取两个已经真实召回的碰撞视频详情，均取得实际 catalog/page_verified，却仍仅明确泛碰撞，不因此补出矩形或下落。证据：`retained-collision-public-details.json`。另两条有界英语技能查询中，DDG 超时、Bing 返回重复泛文档，失败如实保留在 `specific-skill-public-video-query.json`，没有将文档冒充视频。

有限排名修复依据官方 pygame Rect 文档：`colliderect` 测试两个矩形是否重叠。独立公共搜索索引中的两条真实视频摘要明确教学此 API，修复只支持“矩形碰撞判定”，小球下落等其他要求仍 unknown。API 列举、参考链接、先修、否定、其他技术、泛 Sprite、自定义碰撞、广告大纲和相关视频均不能据此证明矩形。实际英语教学短语“show/teach you everything you need to know”不再被误当先修要求；普通 prior knowledge/you must know 等要求继续隔离。独立搜索摘要和官方语义核对在 `independent-colliderect-source-review.json`；它不是当前应用搜索链的 live 验收，也未作为 seed 写入任务。

freeCodeCamp 新适配复用了另一分支依法取得的两份真实课程发布 HTML。仅限确切官方 `/news/<article>/`、文章正文 `section.post-content`；同时要求可见的本课程频道声明、同一视频 ID 的正文频道 watch 链接和 iframe。只保留明确说明由该课程教授的声明/覆盖列表为 `video_topic_summary`，上限1800字符确保对应 page evidence 完整保留。排名再校验同页面 provenance、evidence ID、视频 ID、课程题名和摘要全文；绑定损坏时不退回普通 Article meta、搜索摘要或导航证明教学。作者介绍、推荐区和导航不归属该视频，列表不伪造为章节或时间戳。适配不发起 iframe、YouTube、媒体或隐藏 API 请求。

原始公开 HTML 保留在 evidence 原处；便携测试使用 `tests/fixtures/freecodecamp/` 下3.9KB/4.8KB精简结构，去除执行脚本、广告、跟踪和非必要内容，保留实际课程绑定和必要 Article 数据。manifest 记录原始与精简 SHA，没有新增教学内容，测试无需复制 evidence HTML 或联网。两份原始页面的零网络提取/绑定/题目核对见 `fcc-announcement-replay.json`，五项检查全 true；这些验证只证明来源适配正确，不证明新项目全部课程覆盖已达标。

推荐理由已增加有来源证据的语言提示：`html.lang` 和 Article 元数据只说明来源页面语言，不能推断实际音轨；同一 JSON-LD 媒体/课程的 `inLanguage` 仅按来源标注说明。未知不猜成中文。与中文偏好有差别时提示先检查平台音轨/字幕，同时保留学习门槛匹配或未知说明。

最终本轮全后端离线回归 **1792 passed / 0 failed**，1个现有 Starlette/httpx deprecation；结果为 `evidence/phase2/video-final-integrated-backend-regression.xml`。前语言版1769与181定向报告独立保留。该计数不是新真实搜索成功数，也不构成生产覆盖通过。集成负责人负责重载冻结 hash 后对四个陌生项目做新分析与真实检索；本分支只读独立核对实际候选、学生背景、真实来源、支持/未知边界和失败，不以测试数替代产品验收。
