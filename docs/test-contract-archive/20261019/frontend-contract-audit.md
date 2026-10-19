# 当前UI测试合同维护

旧测试原文归档在 before/tests/。逐条处置如下；底层证据测试保留，不恢复用户撤销的UI。

| 文件:行 | 旧用例 | 处置 | 理由/替代 |
| --- | --- | --- | --- |
| cover-only.spec.ts:8 | cover-only right pane has no visible text, only safe clickable images;3width and keyboard unit mapping | 保留 | 现有合同仍有效 |
| cover-only.spec.ts:9 | cover-only loading and empty states remain icon-only and accessible with reduced motion | 保留 | 现有合同仍有效 |
| cover-only.spec.ts:10 | broken cover has no visible alternate/title text while shared default cards retain their original copy | 保留 | 现有合同仍有效 |
| learning-support.spec.ts:66 | phase3 两轴：内容、标题线索和项目实践分别表达，项目参数不进入技能行 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:85 | phase3 平台筛选只统计可见来源；同一项目练习不被隐去或自动完成 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:95 | phase3 损坏哈希或跨技能借用引文不能展示为内容依据 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:104 | phase3 历史实际APIcore只显示局部标题线索，不造新技能；旧明细折叠且不可编辑 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:120 | phase3 新技能可编辑保存，原concepts/任务/检查原样保留；6条上限明确失败可恢复 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:140 | phase3 空材料仍保留技能、练习和明确重试方向，不凭重分类变成功 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| learning-support.spec.ts:151 | phase3 三尺寸、键盘与减少动态：技能依据可展开、练习不被标成已完成 | 归档旧UI，保留Node与原字段透传 | 用户撤销昨日强制技能/项目实践双轴、技能编辑和右栏文字；simple-review验证历史字段逐值透传。 |
| live-smoke.spec.ts:9 | ${viewport.name} 真实 capabilities、项目列表、入口和布局 | 保留opt-in | 3个真实只读用例需单独授权启用；离线mock不计通过。 |
| project-coverage.spec.ts:106 | phase2 API 使用核心：真实来源离线回放保留部分材料，原学习目标仍为 0/8 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:164 | phase2 检索范围失配：实际保存结果的只读投影明确重试，旧Excel与旧覆盖不能继续展示 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:231 | phase2 精确同文：拆分与确认目标只显示一次，未知成员和隐藏来源不借用已有支持 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:276 | phase2 单元状态：项目仍运行时已结束空单元不再等待，排队单元等待，已有部分依据仍可学习 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:346 | phase2 TWT DOM v2：真实${lesson.key}自身正文与视频绑定保留实际标题及窄目标 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:380 | phase2 TWT DOM v2：结构旗标、版本降级、标题或摘要破坏不能替代真实自身绑定 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:421 | phase2：仅页面壳元数据的待核实课程保留access_notice且不能补齐学习目标 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:434 | phase2 TWT：真实课页摘要经同标题视频和SHA核对可支持子技能，FullCode与侧栏不能补齐 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:473 | phase2 TWT：同课视频绑定损坏、摘要hash不符或WebCrypto不可用时保守待确认 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:508 | phase2 FCC Pandas：真实课页的HTTPS youtu.be同ID短链接可支持子技能，伪域与转跳不采信 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:536 | phase2 FCC：真实保留HTML经后端提取的绑定视频摘要可支持子技能，不虚构播放器或章节 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:554 | phase2 FCC：标题、meta描述、脚本和旁侧Article污染不能补足绑定摘要之外的子技能 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:572 | phase2 FCC：缺失、改写或损坏的视频与页面绑定拒绝全部覆盖，不回退为泛文章正文 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:606 | phase2：可见视频的正文与目录支持可互补，摘要和待核实项不能补齐覆盖 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:620 | phase2：切换平台重新计算子技能，不借隐藏视频或服务端全量汇总补足 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:635 | phase2：只有待核实视频时所有子项仍需补充 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:644 | phase2：每栏展示上限以外的视频不能计入当前覆盖 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:652 | phase2：未拆分单元的合法whole_topic行显示自身依据，错文本不能伪造新子技能 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:670 | phase2 concepts：整单元已支持不能隐藏确认概念，三种分解状态都保留目标缺项 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:700 | phase2 concepts：目标只接收同ID同原文的自身证据，隐藏平台与错配目标不能补齐 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:725 | phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:742 | phase2：全部子项有依据仍保留练习与完整性边界，不宣称已掌握 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:755 | phase2：错配ID、标题字段、重复记录、目录篡改及跨资源引用不能成为内容依据 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:793 | phase2：切换版本只显示该版本可见资源的依据 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:819 | phase2：${viewport.name} 学习路线可读、无横溢并保留三步设计 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project-coverage.spec.ts:834 | phase2：键盘可从平台筛选到视频入口，减少动态偏好保持静态路线 | 归档旧coverage UI，替换安全/范围/媒体/版本边界 | 当前不展示覆盖分母、正文依据、标题原因或平台下拉。109 Node保留同来源/ID/整文hash/学习状态判断；scope错配不出旧封面、媒体过滤和历史隔离改验gallery。 |
| project.spec.ts:96 | phase3 历史缺省技能不算用户修改：直接确认保留版本，不制造空技能或调用edit | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:109 | 离线 Mock：真实入口结构、原始输入、共享勾选与只搜索勾选项 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:137 | 离线 Mock：未勾选前置必须明确确认；刷新恢复、超过五点分批与取消 | 更新到简单审阅与封面DOM | 强制先修ack明确撤销；保留一次检索、分批、刷新与取消，确认传[]。取消入口缺陷需r3修复后回归。 |
| project.spec.ts:159 | 离线 Mock：全部取消勾选只保存选择，不创建空检索 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:168 | 离线 Mock：旧版掌握仅在草稿转换，明确保存才建新版且历史不变 | 更新到简单审阅与封面DOM | 反向维护：mastered不得隐式转skip，只有明确操作才改变，历史保持不变。 |
| project.spec.ts:199 | 离线 Mock：增删改与方案编辑生成新版本，删除前置需先处理引用 | 归档已撤销编辑器 | 仅名称、选择和顺序可编辑，不恢复增删映射、技术方案或technology等编辑；隐藏原字段仍透传。 |
| project.spec.ts:219 | 离线 Mock：保存编辑后确认失败仍恢复新版本，重试不重复编辑 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:231 | 离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读 | 归档已撤销编辑器 | 仅名称、选择和顺序可编辑，不恢复增删映射、技术方案或technology等编辑；隐藏原字段仍透传。 |
| project.spec.ts:276 | 离线 Mock：预算超限保留全部知识点，需求修改后阻止旧分析确认 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:290 | 离线 Mock：模型未配置仍保存原始输入，保留直接搜索入口 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:305 | 离线 Mock：历史结果保留版本，新版本不混入旧课程；手机布局无溢出 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:328 | 离线 Mock：部分完成仅有文字资源时显示明确空态，不假示仍在检索 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:351 | 离线 Mock：平台筛选无匹配区别于本次无结果，切回全部恢复课程 | 更新到简单审阅与封面DOM | 右栏筛选被撤销，替换左侧知识点筛选与按URL去重/原单元归属。 |
| project.spec.ts:382 | 离线 Mock：轮询自动恢复清除读取错误，同时保留确认预算失败 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:469 | 离线 Mock：${viewport.name} 三步流程、共享项去重与关键截图 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:515 | 离线 Mock：键盘可跳过页头、填写需求、提交并将焦点移至新步骤标题 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:551 | 离线 Mock：默认按先修学习顺序排列，切换项目任务仍单列并保留选择 | 更新到简单审阅与封面DOM | 任务分组/拓扑强制撤销，改验证手动order和同序稳定（r2真实DOM断言）。 |
| project.spec.ts:572 | 离线 Mock：输入草稿与学习单元草稿刷新恢复，不隐式创建项目或新版本 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:596 | 离线 Mock：分析失败保留输入，修改后重试复用已保存项目 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| project.spec.ts:612 | 离线 Mock：无结果重试创建并确认新版本，旧结果可回看且不重复同版检索 | 更新到简单审阅与封面DOM | 文字卡片/coverage撤销，保留无结果、scope保护、重试新版本和历史只读；重试入口缺陷需r3修复。 |
| project.spec.ts:631 | 离线 Mock：检索范围失配明确重试建新版，历史仍只读且旧卡片不可用 | 更新到简单审阅与封面DOM | 文字卡片/coverage撤销，保留无结果、scope保护、重试新版本和历史只读；重试入口缺陷需r3修复。 |
| project.spec.ts:657 | 离线 Mock：无结果的平台搜索固定HTTPS来源并编码原单元词，明确区别推荐视频 | 归档文字搜索入口，保留URL/XSS安全替代 | 右侧只封面，不能恢复额外文字入口；链接校验由cover-only及pointer变异验证。 |
| project.spec.ts:684 | 离线 Mock：分析加载可刷新恢复，减少动态偏好停用所有动画与过渡 | 更新到简单审阅与封面DOM | 输入/加载/选择/保存/错误/恢复/预算/历史/键盘保留，ack=[]。 |
| search.spec.ts:64 | 平台筛选能显示全平台前五名之外的课程 | 保留 | 现有合同仍有效 |
| search.spec.ts:78 | 未配置状态、必填和知识点预算校验；无假结果 | 保留 | 现有合同仍有效 |
| search.spec.ts:96 | 多知识点提交、分组筛选、简洁占位封面与安全原平台外链 | 保留 | 现有合同仍有效 |
| search.spec.ts:133 | 正常无结果区别于服务失败 | 保留 | 现有合同仍有效 |
| search.spec.ts:140 | 全部服务失败不会降级为预设课程 | 保留 | 现有合同仍有效 |
| search.spec.ts:150 | 部分失败保留结果、任务中断如实显示 | 保留 | 现有合同仍有效 |
| search.spec.ts:161 | 移动端无横向溢出，表单可用 | 保留 | 现有合同仍有效 |
| search.spec.ts:173 | 请求出错明确显示错误 | 保留 | 现有合同仍有效 |
| search.spec.ts:184 | 封面按来源图片展示，加载失败回退；点击入口保留原平台地址 | 保留 | 现有合同仍有效 |
| search.spec.ts:210 | 封面请求一直挂起时十秒回退，课程入口仍可在新窗口打开 | 保留 | 现有合同仍有效 |
| search.spec.ts:254 | 成功加载的封面在十秒等待窗口后仍显示，不被误判超时 | 保留 | 现有合同仍有效 |
| search.spec.ts:280 | 离屏延迟加载封面不会提前超时，进入视口后才计入十秒等待 | 保留 | 现有合同仍有效 |
| search.spec.ts:319 | HTTPS图片CSP下仅已观察B站CDN封面升级，未知HTTP不请求且失败封面如实占位 | 保留 | 现有合同仍有效 |
| search.spec.ts:364 | 目录仅用于最多两条知识点匹配章节，标题转义且不展示播放器或完整目录 | 保留 | 现有合同仍有效 |
| search.spec.ts:401 | 同课程在不同知识点分组只能展示当前组匹配章节 | 保留 | 现有合同仍有效 |
| search.spec.ts:414 | 目录逐行身份和数值校验拒绝交叉引用、篡改与非法时长 | 保留 | 现有合同仍有效 |
| search.spec.ts:463 | 缺少目录证据保持章节待定位，未知资源不进入课程视频推荐 | 保留 | 现有合同仍有效 |
| search.spec.ts:475 | 推荐区只列课程视频，平台筛选不会把文字资料与未知类型当成课程 | 保留 | 现有合同仍有效 |
| search.spec.ts:490 | 采集失败不伪造章节，异常说明折叠保留且搜索候选仍可去原平台 | 保留 | 现有合同仍有效 |
| search.spec.ts:506 | 取消执行中的任务只发一次请求，保留结果并停止轮询 | 保留 | 现有合同仍有效 |
| search.spec.ts:535 | 重复提交锁与后端复用原任务提示 | 保留 | 现有合同仍有效 |
| search.spec.ts:557 | 创建超时重试沿用幂等key，明确重新检索使用新key | 保留 | 现有合同仍有效 |
| search.spec.ts:589 | 取消后新任务不会被迟到的旧轮询覆盖 | 保留 | 现有合同仍有效 |
| search.spec.ts:619 | 轮询任一请求失败会及时取消同轮兄弟请求 | 保留 | 现有合同仍有效 |
| search.spec.ts:653 | 取消请求失败保持未确认状态，不假装取消成功 | 保留 | 现有合同仍有效 |
| search.spec.ts:665 | 任务已自然结束时取消返回原终态，不覆盖为cancelled | 保留 | 现有合同仍有效 |
| search.spec.ts:679 | 来源说明折叠保留平台条款，不展示内部采集配置或宣称播放已验证 | 保留 | 现有合同仍有效 |
| search.spec.ts:703 | 取得的目录证据可参与章节定位，内部渲染诊断不进入课程卡片 | 保留 | 现有合同仍有效 |
| search.spec.ts:723 | 创建响应丢失后刷新可按原幂等key恢复已结束任务，确认后清除tab存储 | 保留 | 现有合同仍有效 |
| search.spec.ts:763 | 刷新后的不同需求不会使用旧幂等key，清除入口不会请求取消 | 保留 | 现有合同仍有效 |
| search.spec.ts:803 | 弱证据保留待核标记，平台切换不能把预约或相邻概念提升为推荐 | 保留 | 现有合同仍有效 |
| search.spec.ts:859 | 复合点候选保留部分匹配，筛选去重限额有效且不展示内部覆盖报表 | 保留 | 现有合同仍有效 |
| search.spec.ts:884 | 不借其他资源的证据补足子项，缺少支持记录保持待核且隐藏内部理由 | 保留 | 现有合同仍有效 |
| simple-review.spec.ts:46 | professional-name selection and order preserve all historical fields, recover drafts, and confirm without invented prerequisite acknowledgements | 保留 | 现有合同仍有效 |
| simple-review.spec.ts:74 | confirmed left navigation follows edited priority and preserves original order for equal priorities | 保留 | 现有合同仍有效 |
| simple-review.spec.ts:90 | saving an edited term creates one version; empty selection creates no search; history remains read-only | 保留 | 现有合同仍有效 |
| topic-pointers.spec.ts:58 | zero main recommendations: actual catalog pointer opens with original p26 link and plain full-skill verification text, while0recommendations/2unknownskills stay unchanged | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:71 | platform filter hides pointer source without borrowing topic support from other visible materials | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:79 | unverified lexical fragments stay out of student copy while complete skill and actual chapter link remain | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:88 | bad hash or wrong actual part is absent, not an unknown-source clickable lead | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:92 | native Bili source cannot become a foreign same-page link after whole-context rewrite and a valid new hash | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:103 | missing pointer lane and historical absent skills cannot invent goals or display source hints | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:107 | catalog original text is React-escaped, never executable HTML or an image request | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
| topic-pointers.spec.ts:116 | three widths and reduce motion: folded/expanded pointer long source stays readable and keyboard reachable | 改为封面链接验证 | 无章节折叠文案、目标计数和平台下拉；实际p26、native part、hash/ID、foreign重写、缺字段和XSS安全仍需验证。 |
