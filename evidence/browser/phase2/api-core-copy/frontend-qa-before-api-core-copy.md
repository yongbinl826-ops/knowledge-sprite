# Phase 2：学习单元的视频覆盖与下一步

本轮验证流程：打开指定项目版本的推荐视频 → 查看单元学习路线 → 切换课程平台 → 核对当前视频可支持与仍缺的子技能 → 打开有依据的视频并按项目练习检验。

## 交付与结果

最新检索范围失配状态已集成并冻结：完整浏览器87项通过（覆盖展示30＋项目24＋手动33），58项Node与最终TypeScript/Vite构建通过。新87构建在r8 PID20748已完成五例真实终态三宽、三步骤、键盘及Dashboard历史v1选择性隐藏与来源质量提示复核。此前r7b／84构建证据独立保留。真实来源身份与教学覆盖仍未通过，不把界面通过、mock或部分材料视为生产验收。原85／84／83／79／76／69项及首轮失败报告均保留。冻结回归位于`scope-mismatch/`，最新实际观察位于`runtime-r8/`。

每个学习单元现在显示“本单元学习路线”：当前视频可支持的具体子技能、仍需补充的子技能、下一步和项目练习。资料不足时显示待确认，并提示核对视频简介或目录。全部已列子技能均有依据时，仍明确保留教学深度、完整性和实践检验的边界。

| 验证 | 结果 | 记录 |
| --- | --- | --- |
| r8当前87构建实际只读 | 五例终态三宽／三步／键盘完成；0写/console/runtime/平台跳转、job与批次身份不变；历史v1仅隐藏失配组并保留正确卡片 | `evidence/browser/phase2/runtime-r8/observation-summary.json` |
| 检索范围失配后完整回归 | **87 passed，3 opt-in skipped，0 failed/flaky，97.45秒**；覆盖展示30 + 项目24 + 手动33 | `evidence/browser/phase2/scope-mismatch/e2e-full-results.json` |
| 检索范围失配定向 | 2项通过：实际保存结果的只读投影、旧卡/平台/覆盖屏蔽、文本安全、重试创建新版、历史只读 | `evidence/browser/phase2/scope-mismatch/targeted-results.json` |
| 当前冻结Node与构建 | **58/58通过**（原53＋新5）；TypeScript与Vite通过 | `evidence/browser/phase2/scope-mismatch/node-tests.tap.txt`、`frontend-build.log` |
| 失配提示三尺寸 | 1440／768／390无横溢，提示文字最低对比度5.72614:1，三张图已实际打开 | `evidence/browser/phase2/scope-mismatch/scope-mismatch-observations.json`、`screenshots/scope-mismatch-*.png` |
| 精确同文展示分组后完整回归 | **85 passed，3 opt-in skipped，0 failed/flaky，97.66秒**；覆盖展示29 + 项目23 + 手动33 | `evidence/browser/phase2/exact-text-display/e2e-full-results.json` |
| 同文分组定向 | 1项通过：跨类同文只列一次，全部目标ID保留，隐藏来源或任一unknown不能借支持，计数与清单一致 | `evidence/browser/phase2/exact-text-display/targeted-results.json` |
| 同文展示阶段Node与构建 | **53/53通过**（原45＋新8）；TypeScript与Vite通过 | `evidence/browser/phase2/exact-text-display/node-tests.tap.txt`、`frontend-build.log` |
| 新同文分组三尺寸 | 1440／768／390无横溢，最低对比度5.33283:1，三张图已实际打开 | `evidence/browser/phase2/exact-text-display/exact-text-observations.json`、`screenshots/coverage-exact-text-*.png` |
| r7b旧84构建实际五例只读 | 5/5完成三宽、三步、键盘；0写/console/runtime、job ID不变；31单元24张按单元计实际卡片，各项目仍partial | `runtime-r7b/terminal-summary.json`、`terminal-visual-review.md` |
| 单元终态修复后的完整回归 | **84 passed，0 failed/flaky，99.3秒**；覆盖展示28 + 原项目23 + 手动33 | `evidence/browser/phase2/mixed-unit-state/e2e-full-results.json` |
| 单元混合状态定向 | 1项通过，涵盖terminal0卡不等待、四种排队/运行状态等待、terminalpartial有卡仍学习 | `evidence/browser/phase2/mixed-unit-state/targeted-results.json` |
| 单元终态修复阶段Node与构建 | 45/45通过；TypeScript与Vite通过 | `evidence/browser/phase2/mixed-unit-state/node-tests.tap.txt`、`frontend-build.log` |
| 旧runtime实际只读与超时记录 | 修复前7单元9卡、三宽无溢出、0写/console/runtime、job ID不变；随后GET超时保留；已由r7b新runtime五例复核解决 | `real-data-final/report.json`、`mixed-unit-state/get-probe.json` |
| TWT DOM v2后的完整浏览器回归 | **83 passed，0 failed/flaky，92.7秒**；覆盖展示27 + 原项目23 + 手动33 | `evidence/browser/phase2/twt-dom-v2/e2e-full-results.json` |
| 测试分析说明校正后增量 | Movement与Snake2项通过，3.2秒；只改mock任务/练习以匹配窄目标，生产/API数据不变 | `evidence/browser/phase2/twt-dom-v2/mock-context-incremental-results.json` |
| 新DOM v2定向验证 | 4项通过，包括26种结构损坏/降级/界限及shell待核实说明 | `evidence/browser/phase2/twt-dom-v2/targeted-results.json` |
| DOM v2后Node与最终构建 | 45/45通过；TypeScript与Vite通过 | `evidence/browser/phase2/twt-dom-v2/node-tests.tap.txt`、`frontend-final-build.log` |
| 确认概念追加后的完整浏览器回归 | **79 passed，0 failed/flaky，81.8秒**；覆盖展示23 + 原项目23 + 手动33 | `evidence/browser/phase2/concept-targets/e2e-full-results.json` |
| 确认概念追加前的完整浏览器回归 | **76 passed，0 failed/flaky，88.9 秒**；覆盖展示20 + 原项目23 + 手动33 | `evidence/browser/phase2/e2e-two-source-final-results.json` |
| 76项后的测试类型修正 | 受影响TWT2项再次通过；生产代码未改 | `evidence/browser/phase2/twt-types-incremental-results.json` |
| 76项后的检索终态文案 | 现有三步/历史/来源/整单元11项增量通过，21.4秒 | `evidence/browser/phase2/search-status-wording-incremental-results.json` |
| 原新覆盖展示独立浏览器回归 | 13 passed，0 failed/flaky | `evidence/browser/phase2/coverage-corrected-title-results.json` |
| 摘要分支修复前的完整浏览器基线 | **69 passed，0 failed/flaky，75.5 秒**；新覆盖 13 + 原项目 23 + 手动检索 33 | `evidence/browser/phase2/e2e-full-results.json` |
| Node 证据、章节和图片策略测试 | **45 passed，0 failed**，本轮重新运行 | `evidence/browser/phase2/node-final-tests.tap.txt` |
| TypeScript 与 Vite 生产构建 | 通过 | `evidence/browser/phase2/frontend-final-build.log` |
| 新路线文字对比度 | 三尺寸各 13 项采样，最低 **5.33283:1**，0 失败 | `evidence/browser/phase2/coverage-{desktop,tablet,mobile}.json` |
| 原流程三步骤文字对比度 | 9 组通过，最低 5.15989:1 | `evidence/browser/phase2/contrast-*.json` |
| 新确认概念缺项的三尺寸复核 | 1440／768／390无横溢，每尺寸13个文字样本最低5.33283:1；已实际打开截图 | `evidence/browser/phase2/concept-targets/confirmed-concepts-widths.json` |
| 确认概念追加后的Node与构建 | 新跑45/45通过；TypeScript与Vite通过 | `evidence/browser/phase2/concept-targets/node-tests.tap.txt`、`frontend-build.log` |

完整回归中的3项opt-in真实只读测试按配置跳过；87项使用隔离响应，不访问8000。r7b五例实际GET与浏览器只读观察另列，未启动或停止服务，未创建版本或检索。此前52、23、56项阶段报告均保留。浏览器回归和只读UI观察均不能证明完整教学、播放可用或学生已完成实践。

## 证据边界

展示层复用现有 `collection_coverage.subtopics`、资源自身 `subtopic_coverage`、`supporting_evidence_ids` 和 `collectionCoverageRows`。不新增 API 汇总字段，也不照搬 `all_subtopics_supported`、`single_resource_full_coverage` 或平台的全量汇总断言。

计入“有内容依据”须同时满足：

- 资源实际位于当前版本、当前平台和每栏展示上限内，类型为已有课程/视频展示范围。
- 卡片不处于 `needs_review`；匹配中的知识点和资源编号与当前结果、自身资源一致。
- 子技能的编号与文字均与当前单元的分解一致；支持 ID 同时存在于自身匹配和自身证据中。
- `learning_target_1` 至 `learning_target_8` 另须与当前已确认 concepts 的序号和原文一致，三个分解状态均保留目标行；整单元标题支持不能回填目标支持。旧结果未返回目标行时，确认概念仍列为缺项，不能借用未汇总的资源目标行。已拆分的同文具体技能不重复补入旧结果的本地缺项。
- 证据记录唯一，并属于资源自身 URL、canonical URL 或 resolved URL；标题和搜索摘要不参与此清单。
- 正文证据必须是 `page/description`，并与资源 description、field provenance 的 ID 和来源完全绑定。
- 目录证据必须是 `catalog/chapters.N`，与对应章节 ID、标题、链接、时间字段一致，链接与时间值有效；篡改或交叉引用不计入。

这里的“有内容依据”表示来源自身简介或目录支持该子技能，仍不等于实际播放、完整教学或学习效果已核验。截断而不能精确绑定的正文、未支持来源的特殊摘要字段和仅搜索发现的线索会保守地留在待确认状态；原卡片的部分匹配、待核实和未知语言说明保持原样。


### 明确来源的视频摘要分支

修复后的展示只接受两种明确来源协议，均不会因存在 video_topic_summary 字段就泛信该内容。此前69项基线没有验证这些分支。

- freeCodeCamp：HTTPS公告页；精确 summary/video 来源；同页唯一证据和provenance；自身摘要等于证据正文；公告及课程标题一致；watch链接和iframe指向相同11位视频ID；另允许已观察的HTTPS精确youtu.be/<11位ID>短链接，拒绝伪域、转跳路径、HTTP及不一致ID。正文首段须与保留公告一致。损坏时不回退到文章description或目录。
- Tech With Tim：HTTPS三层课页；精确 title/video/summary 三条来源和同页唯一证据；lesson_title、实际h1与embed_title、lesson_url及同ID iframe均须一致；浏览器原生WebCrypto核对完整UTF-8摘要SHA-256，TWT摘要上限6000个Unicode码点。无version/kind/witness的旧proof仍须有显式“video above”声明。新DOM v2另须精确版本、kind和结构说明，5项唯一容器/标题/正文/iframe计数均为1，可见标志为true，独立标题记录与witness标题一致，notes哈希等于原生摘要哈希，字符数一致，教学段落数为2至200的安全整数。未知或损坏v2不回退旧phrase。核对期间标记待确认，失败保守未知；不回退到侧栏、Full Code、通用文章描述或搜索摘要。

五份API-shaped JSON（FCC Python、TWT Scoring、FCC Pandas、新TWT Movement与Snake）均由仓库已保留的真实公开HTML经当前extractor、Resource模型和ranking离线生成，原HTML与原公开来源SHA留存。Tech With Tim重放明确设置已观察HTTP200对应fetched/page状态，不重新请求页面或播放器。测试不手工制造合法资源的supported/partial状态；对JSON的损坏或污染修改仅用于负例。TWT字体渲染支持与矩形碰撞未支持由后端严格数据流规则产生。新Movement的2628字正文验证main-loop，Snake的1674字正文验证Drawing the Grid，仍保留实际标题“Basic Movement & Key Presses”和“Tutorial #1”；这两条窄目标验证不代表真实迷宫项目目标已被覆盖。前端保留partial和原语言说明，不根据域名或中文UI推断中文授课。

## 覆盖矩阵

| 情形 | 预期与实测 |
| --- | --- |
| 正文支持读取 + 目录支持统计 | 合并为 2/3；导出仍需补充 |
| 同时存在“导出”的搜索摘要和待核实视频 | 不把其纳入内容依据；原卡片仍可供核对 |
| 只有待核实视频 | 0/3，全部子技能仍需补充，无“有依据的视频”入口 |
| 切换 B站、其他网站、全部平台 | 支持列表和缺项实时重算；不借隐藏平台的视频补齐 |
| 视频位于每栏展示上限以外 | 不计入当前覆盖 |
| 所有子技能分别有依据 | 3/3；仍展示完整性提醒和独立项目练习，不标记已掌握 |
| 新稳定whole_topic与确认目标 | whole_topic文字等于当前result.text才可按同一有效自身证据显示；另有learning_target行时仍保留，标题支持不覆盖目标缺项 |
| 旧标题结果、三种分解状态、目标错原文、隐藏平台和待核实目标 | 确认概念原文保留；无目标自身有效证据保持unknown；同ID换文字不能借用支持 |
| FCC Python和Pandas实际HTML重放 | 合法绑定摘要2/2；Pandas null/duplicate来自项目教学段落，合法短watch链接仍须与iframe同ID |
| TWT实际HTML重放 | 字体渲染1/2；矩形碰撞仍缺，FullCode/侧栏不补足；hash损坏或WebCrypto不可用时保守未知 |
| TWT无固定phrase的实际Movement与Snake | 合法DOM v2能显示当前窄目标正文依据；保留实际标题；26类损坏/降级/超过6000界限均不补齐目标 |
| 仅壳元数据的课程 | 既有access_notice原样可见，仍为待核实线索，不计入内容覆盖 |
| 部分单元结束但整个项目仍运行 | 终态0卡单元提示调整目标；排队/运行单元继续等待；已有部分依据时可先学习，不以全项目running替代单元状态 |
| 检索范围与声明技术不一致 | 显示“检索范围需重试”、原因、正确范围与下一步；旧三类卡、平台和覆盖均隐藏，历史页不出现写操作 |
| 缺少 aggregate 或无课程 | 显示待核对的既有 concepts 和可执行下一步，无伪造覆盖 |
| 历史与最新版本切换 | 只依据所选版本；历史结果不出现重新检索操作 |
| 缺失 ID、错知识点/资源、标题字段、重复记录、外部课程 URL、未绑定正文、错子技能文字、目录篡改 | 9 类均不能成为支持依据 |
| 键盘与减少动态 | Tab 可从平台选择进入视频入口；链接有新窗口提示；静态路线无新增动画 |
| 桌面/平板/手机 | 1440×1000、768×1024、390×844；无文档横向溢出，标题与控制保留原三步设计 |

## 发现、改动与复核

| 发现 | 改动 | 复测证据 |
| --- | --- | --- |
| 既有汇总工具允许存在的 search ID 参与支持，直接展示会混淆搜索相关性与内容依据 | 新纯展示组件收紧正文/逐行目录绑定，且仅计算实际可见资源 | 合并、待核实、搜索摘要、平台、展示上限及 9 类异常证据测试通过 |
| 首次收紧只允许description/catalog，会漏合法的FCC/TWT绑定摘要 | 按两种精确来源协议核对自身summary/provenance、同页视频proof；TWT另核对原生SHA | 三份实际HTML衍生API数据和损坏/污染/短域/累计代码反例；不扩大为通用摘要信任 |
| 新后端稳定whole_topic行保留not_applicable/unknown，旧展示工具仅接受applied | 在展示组件支持文字绑定当前result.text的真实整单元行，不伪造拆分，并保留追加的明确目标 | whole_topic正例与错文本负例、concept三种分解状态回归 |
| 短标题可能遗漏已确认concepts，追加目标又会被旧单行whole分支丢失 | 各分解状态接收严格ID＋原文目标；历史结果的未评估概念保留缺项，整单元支持不自动借给目标 | 新增3项契约反例，全量23项覆盖、79项完整回归通过；三尺寸截图已打开 |
| 只认固定phrase会漏真实Movement/Snake课页；1800字上限会漏Movement完整own段 | 仅新增明确TWT DOM v2绑定分支及6000码点上限，不扩大通用正文信任 | 真实HTML衍生的2个正例、26个损坏反例、83项全量回归；六张三尺寸截图已打开 |
| 新source-replay测试分析沿用了Scoring的文字/碰撞任务 | 仅将两份mock分析改为主循环/网格线练习，生产/API数据不变 | 原六图保留screenshots-before-context-correction；两项增量及最终TS/build通过 |
| 真实项目仍running时，已terminal partial且0卡的单元仍提示等待返回 | 仅按本单元pending/queued/submitted/running传递searching，不修改API或后端 | 新定向1项与完整84项、45Node/build通过；新构建实际复拍因GET超时待完成 |
| 新concept用例把边界文案多写一个“个” | 仅修正测试到原有“整单元教学完整”文案，未改产品边界 | 首轮2通过1失败保留concept-targets/targeted-results.json；修正后23项、最终79项通过 |
| 原视频结果缺少单元层面补充任务与实践落点 | 显示缺项、明确下一步和原分析中的 practice_check/project_task/learning_goal | 最终23项覆盖展示回归及三尺寸截图通过 |
| 结果终态“已完成”容易被理解为学习或项目完成 | 只将completed中文文案改为“检索完成”，保留原后端值与实践边界 | 76项后的11项现有状态/历史/三尺寸增量通过，最终截图已打开 |
| 新测试有DOM变量遮蔽和nullable赋值两处TS错误 | 仅改为globalThis.document和明确的string赋值 | 首次日志保留frontend-typecheck-before-fix.log；受影响TWT2与最终build/Node45通过 |
| 初轮新测试 helper 使用了过时页面标题 | 仅修正测试到现有 `index.html` 标题，未修改产品标题 | 初轮 11 项 setup 失败保留为 `coverage-targeted-results.json`；修正后13项、69项基线及最终76项通过 |
| 空态提示曾假设必有 B站搜索入口 | 改为不依赖平台偏好的“调整单元目标与工具后重新检索”建议 | 最终完整回归的 empty 与原无结果/平台入口测试通过 |

已实际打开桌面入口、平板详情、手机详情截图，检查排版、留白、文字、细线和响应式。保留原设计的暖白、石墨与蓝色，不新增动效；手机使用单列支持/补充清单，避免两列挤压。新路线通过采样对比度验证。没有发现本轮范围内未解决的明显高/中优先级问题；不声称获得设计奖项或完整无障碍认证。

## 文件与环境

生产文件修改 `frontend/src/components/ProjectVideos.tsx`、`frontend/src/styles.css` 的 `unit-coverage` 限定块及 `frontend/src/types.ts` 的可选摘要字段，并新增 `frontend/src/components/LearningCoverage.tsx`。另在76项后将`frontend/src/projectTypes.ts`的completed文案改为“检索完成”。85阶段新增有类型的`coverageDisplay.ts`并修改LearningCoverage最终展示层，保留原版本／可见来源／ID原文／正文绑定验证。87阶段仅改ProjectVideos、projectTypes与types消费后端失配标记及中文状态；不改API实现、后端、设计或依赖。`ResourceCard.tsx`（含CourseCover）、CSS、同文helper与LearningCoverage在87阶段均未改。测试增加`project-scope.test.mjs`五项和两项浏览器场景；实际API-shaped派生fixture独立保存，未使用隐藏日志或真实POST。

Browser plugin / browser skill 不可用，因此采用现有仓库 `@playwright/test` 与已安装 Edge；未安装依赖。Windows 沙箱无法启动浏览器/访问 loopback，使用已授权本地执行环境。隐藏 Vite 为 `http://127.0.0.1:5175`，PID **24548**，身份及日志记录于 `phase2/vite-process.json`；保留给集成负责人，未使用 Ctrl+C 或全局进程终止。

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\frontend'
$env:PLAYWRIGHT_CHANNEL = 'msedge'
$env:PLAYWRIGHT_EXTERNAL_SERVER = '1'
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:5175'
$env:QA_EVIDENCE_ROOT = '../evidence/browser/phase2/scope-mismatch'
$env:PLAYWRIGHT_JSON_OUTPUT = '../evidence/browser/phase2/scope-mismatch/e2e-full-results.json'
$env:PLAYWRIGHT_OUTPUT_DIR = '../evidence/browser/phase2/scope-mismatch/full-artifacts'
npm run test:e2e -- --workers=1
npm run build
node --test --test-reporter=tap tests/chapter-recommendations.test.mjs tests/partial-chapter-evidence.test.mjs tests/topic-evidence.test.mjs tests/course-images.test.mjs tests/coverage-display.test.mjs tests/project-scope.test.mjs
```

最新源码、测试、配置和dist共48文件SHA在`evidence/browser/phase2/tested-frontend-manifest.json`，与`scope-mismatch/`副本相同；原46文件／85项基线、QA和文档快照保留于`scope-mismatch/*-before-scope.*`，原44文件／84项也仍保留。新源文件与改动前SHA单列，机器汇总为同目录`qa-summary.json`。未测试Firefox/Safari或实际屏幕阅读器会话；真实模型与课程质量验收由集成负责人另行进行。

截图位于 `evidence/browser/phase2/screenshots/`：

- `coverage-desktop-entry.png`、`coverage-tablet-detail.png`、`coverage-mobile-detail.png`：新路线的三尺寸实拍。
- `coverage-keyboard-reduced-motion.png`：键盘焦点与减少动态偏好。
- `mock-{desktop,tablet,mobile}-01-input.png`、`-02-selection.png`、`-03-results.png`：最终完整回归的三步骤。
- 同目录保留 loading、empty、error、search-loading 等关键状态，未覆盖上一阶段截图。

最终fixture生产者ranking文件因后端相关修复更新后，三份数据重新经真实提取/模型/ranking生成；对point、item和collection整个API payload逐一SHA比较完全相同，仅producer provenance改变，记录于fixture-producer-refresh-verification.json，因此没有重复未受影响的全套浏览器回归。

实际HTML重放截图还包括 coverage-fcc-bound-summary.png、coverage-fcc-pandas-short-url.png 和 coverage-twt-{desktop,tablet,mobile}-bound.png；最后一组三尺寸均已实际打开，新的“检索完成”顶栏也已复核。

确认概念追加后的全部新截图位于 `evidence/browser/phase2/concept-targets/screenshots/`，包括 `coverage-confirmed-concepts-{desktop,tablet,mobile}.png`，清晰显示标题已有支持而具体目标仍待补充。原76项源码清单、汇总和本文快照分别保留为 `tested-frontend-manifest-before-concepts.json`、`qa-summary-before-concepts.json`、`frontend-qa-before-concepts.md`；不把原结果改记为79项。

此前79项阶段的ranking SHA为 `e1e0205b06b8540018783dae40468278bc23f63c3c3cbfd0b182854d60f5efda`，对应三份fixture的metadata比较仍保留于 `concept-targets/fixture-final-ranking-verification.json`；较早c06候选在替换前检测到ranking已变化并中止，未覆盖已验收fixture。

本轮TWT DOM v2 adapter SHA为 `6fdecd8e255b60bf9b20988baab877cec56b5e15bf2d6f6f51b7461b0a58baf0`。原三份fixture重导后完整业务JSON仍完全相同（只排除producer_sha256），核对生成器SHA一致后才更新元数据；Scoring仍走旧phrase且保留1271字正文，FCC两份内容不变，见 `twt-dom-v2/fixture-final-comparison.json`。新增两份fixture来自实际新课页，正文和DOM v2结构协议构成新增观测范围，没有强行沿用旧摘要或支持状态。

最终六张实拍位于 `evidence/browser/phase2/twt-dom-v2/screenshots/coverage-twt-dom-v2-{movement,snake}-{desktop,tablet,mobile}.png`，均已实际打开；三宽无横溢，最低文字对比度5.33283:1。原79阶段文档、清单、汇总和三份API数据均保留于 `twt-dom-v2/*-before-twt-dom-v2.*`。本轮不访问或启停8000，不验证实际播放器或实际迷宫覆盖。

最终生成器再次对齐ranking冻结版本 `455451288fcbd4b8e4bbfb6e2ea0516c79b93a29e2d98589b471ad6d035e350b`：五份fixture均先生成独立候选，完整业务JSON比较全部相同后才更新producer元数据，记录于 `twt-dom-v2/five-fixture-final-producer-comparison.json`；因此不重复生产源码未变的83项回归。

最新真实只读发现、原始三宽图、外链标题与状态、键盘记录见 `real-data-final/review.md`。修复前bundle为`index-CSndD1CO.js`，修复后构建为`index-hGmLMzcm.js`（SHA `1ab294a8203868e60bb0f66ba6aa42df3c8bfe696a28ff6c6f21128cc4287501`）；两个独立GET均10秒超时，不能声称8000已实际观察到新bundle。原tablet卡片截图的一次绘制空白仍待复拍判定，未据此修改CSS。父任务正在排查同步排名性能；本分支停止重复探测，未启停服务。

## r7b重载后的只读验收准备与进度观察

`evidence/browser/phase2/runtime-r7b/verify-existing-cases.mjs`已通过语法与本地准备检查，未访问HTTP或启动浏览器。44个已测文件SHA全部一致，当前84构建仍为`index-hGmLMzcm.js`。计划绑定父任务给定的新检索版本：data／maze v5，web／Arduino v4，Streamlit看板v1；看板项目ID来自已有本地分析审核。它们在准备记录中仅标为计划，未称搜索已启动或完成。

默认执行只生成`preparation.json`。实际运行必须在父任务明确通知重载后，由调用者提供`--run-after-reload --runtime-label <label> --expected-pid <newPID>`；旧26048、PID不符、runtime manifest的源码／dist哈希不符，均在任何HTTP前拒绝。可用`--case <case_id>`只验收已启动的单例；不创建版本、不分析、不确认、不重试或启动搜索。

实际模式逐例串行只读GET、核对真实静态bundle SHA，浏览器阻断全部写方法；1440／768／390下记录三个步骤、当前结果、覆盖缺口、终态0卡及键盘返回，核对job ID不变。没有在真实窗口观察到的加载／错误／有卡状态会保留为“未观察到”，不注入HTTP错误或延迟来伪装。原84回归的加载、空态、错误、有卡截图路径作为fixture证据独立列入准备记录，不能替代新runtime实际截图，也不代表完整教学或项目实践通过。

父任务明确通知重载后，于19:31:10至19:31:18Z仅观察data v5单页；runtime PID16148，manifest SHA `f7c4c1e8eb6cd9ab54b7c78bcd5d37f0593e60c781a037e6fe248694149a2ad2`，真实HTTP bundle完整SHA等于84构建的`1ab294…`。Desktop8卡、tablet/mobile11卡，均为项目running；三宽文档宽度等于视口宽度，0控制台/运行时错误、0写请求、job ID未变。两个job为`716c1174-0492-4c5a-aa92-875fb7dc0c36`与`bbf806fa-dbcc-428b-ac8f-b8442390c42d`。终态partial且0卡的时间解析单元在全局running时，三宽均正确提示返回调整，不再等待；实际终态空图和平板课程图已打开复核，旧绘制空白未复现，未改CSS。

证据保存在 `runtime-r7b/progress-data-v5/bicycle_csv_advanced/`；此窗口未出现实际错误提示，也未执行最终键盘验收或访问其他尚未检索版本。后续使用独立`--phase terminal-five`目录，保留本次真实加载与渐进原图；等待父任务另行通知五例终态。

### r7b实际终态复核（data v5、maze v5）

父任务逐例确认终态后，分别在19:33:32–19:33:46Z、19:35:11–19:35:24Z完成只读复核。两例均绑定PID16148、runtime manifest `f7c4c1e8…`和真实HTTP bundle完整SHA `1ab294…`，此前GET超时及旧bundle未实证的记录属于旧runtime，现已得到新runtime证据。冻结44文件再次核对0变化，未重新执行或改记84项回归。

| 实际项目与版本 | 观察结果 | 三宽／三个步骤／键盘 | 证据 |
| --- | --- | --- | --- |
| 共享单车CSV分析 v5 | partial，7单元13卡；2单元0卡，缺口与确认概念保留，空单元提示返回调整，不等待 | 1440／768／390无横溢；本地01→02→03可达；Enter返回审阅与结果，8个Tab停点均显示焦点 | `runtime-r7b/terminal-data-v5/bicycle_csv_advanced/report.json` |
| pygame迷宫 v5 | partial，6单元0卡；无加载／骨架；每单元保留未知技能、具体项目练习、调整建议及明确的平台搜索入口 | 同上，0卡不会使键盘或三步导航失效 | `runtime-r7b/terminal-maze-v5/pygame_maze_intermediate/report.json` |

两次浏览器均0写请求、0控制台信息、0运行时错误，初末job ID完全一致。data两个job为`716c1174-0492-4c5a-aa92-875fb7dc0c36`、`bbf806fa-dbcc-428b-ac8f-b8442390c42d`；maze为`8eefa50c-5640-4e9f-bf41-80bb1019110f`、`d686b7c4-5250-4a2b-8932-9f636054ced6`。未启动或重试检索，未访问外链播放。

已亲自打开data桌面结果与输入、平板实际卡与审阅、手机输入／结果／空单元及键盘审阅截图；maze桌面结果、平板与手机终态空单元图也已打开。文字、留白、卡片标题、部分匹配说明、下一步与缺口均可读，旧平板一次空白绘制未复现，未修改CSS。实际页面仅证明当前返回材料能如实展示：data并未覆盖全部确认技能，maze没有可展示课程，均不能作为课程生产覆盖通过。实际错误状态本窗口未出现，仍仅有单独标注的mock错误证据。

汇总`runtime-r7b/terminal-summary.json`和主`qa-summary.json`记录已观察2/5例；web v4、Arduino v4与Streamlit v1继续等待父任务确认终态，未把准备或渐进观察当作最终五例通过。

### r7b五例只读UI复核完成

父任务随后分别确认剩余三例终态；当前五例均完成，仍绑定PID16148、上述manifest和84构建，不代表后续r8 runtime已验收。

| 项目版本 | 实际终态UI | 观察窗口UTC | 独立证据目录 |
| --- | --- | --- | --- |
| web v4 | 7单元4张部分卡片，其余单元明确缺口 | 19:37:46–19:37:52；卡片补拍19:38:46–19:39:02 | `runtime-r7b/terminal-web-v4/`、`terminal-web-v4-cards/` |
| Arduino v4 | 5单元1张部分卡片，串口调试与其他未知技能区分 | 19:39:16–19:39:22 | `runtime-r7b/terminal-arduino-v4/` |
| Streamlit v1 | 6单元6张部分卡片，上传支持与重运行／校验／聚合等缺项区分 | 19:41:33–19:41:39 | `runtime-r7b/terminal-streamlit-v1/` |

三例均三尺寸无文档横向溢出、三步骤可达、8个Tab停点焦点可见、Enter可返回审阅和结果；0写请求、0控制台/运行时错误，job ID不变，终态0卡不显示等待。已实际打开web三宽课程卡、手机空单元及平板审阅；Arduino桌面课程卡、平板缺口及手机空单元；Streamlit桌面结果、平板和手机课程卡及手机空单元图。首轮web脚本选了无卡的首个缺口单元，因此卡片特写缺失；仅调整evidence脚本独立选择实际有卡单元，在新目录补拍，原始记录保留，未修改产品或掩盖缺陷。

五例整体显示31个学习单元、24张按单元计的实际卡片；所有项目均partial，UI渲染通过与教学覆盖失败分开记录。没有观察到真实错误提示；错误场景仍仅属于84项mock回归。`runtime-r7b/terminal-summary.json`现为5/5只读UI观察完成，主QA和44文件manifest同步，文件SHA仍0变化。

发现一项低优先级可读性问题：web“状态对象”在标题拆分行与确认目标行同文但ID不同，路线重复显示并计为2/5；Streamlit缺项“脚本重运行”也同文重复。API原始行保留不同目标身份，不能仅按一个支持行自动补另一行。独立`tmp/coverage-display-proposal/`提供未集成的精确同文分组方案和8/8 Node试验：仅跨拆分/确认行分组，保留全部ID，任一unknown或缺当前有效来源即整个展示组unknown，计数与清单使用同一组，不合并同义或不同措辞。主源码、主测试、依赖、锁及84bundle均未改变；该试验不并入45项Node结果，是否集成由主任务决定。

### 已批准并集成的精确同文展示分组（85项冻结）

主任务审查上述PoC并明确批准后，新增有类型的`coverageDisplay.ts`，仅在LearningCoverage完成原有所有来源校验后对最终显示行分组。仅拆分／整单元行与确认目标行的完全相同原文跨类合并，不trim、不猜同义、不合并不同措辞；保留原`members`和全部`memberIds`，界面列表的`data-requirement-ids`可追溯。合并组任一成员为unknown或没有当前有效来源，则显示为仍需补充，不借用同文支持链接。未合并行保持原有已校验来源判断；计数、清单与下一步均使用同一组。API与后端教学结论不改。

首轮完整回归84通过、1失败：旧历史whole_topic测试仍预期将同文支持行与unknown概念分列1/4；新行为正确保守合并为0/3，概念仍缺项。经主任务确认，只更新该断言，并增加全部底层ID及无支持链接验证，没有再次修改生产代码。首轮`e2e-first-results.json`、`e2e-first.log`及`full-artifacts/`保留；最终完整重跑85通过、3opt-in跳过、0失败/flaky，97.659872秒。53项Node（原45＋新8）和最终TS/build通过，定向1项通过。冻结文件仅LearningCoverage、新helper、两份测试、dist/index及新JS发生变化，清单由44增加至46；CSS、其余生产源与依赖未变。

三张新路线截图`exact-text-display/screenshots/coverage-exact-text-{desktop,tablet,mobile}.png`均已亲自打开，无横溢，最低文字对比度5.3328300964134785:1。新增浏览器测试证明全量平台可得1/3、隐藏目标来源后为0/3、显式unknown后仍0/3，全部目标ID保留，不借已有来源，也不宣称教学或实践完成。

新构建为`index-CSx7LjzL.js`，完整SHA `0ec4763c7230ac742ff9b219308209762cc2fdab14f38b46b639854be2f1ff4d`；LearningCoverage SHA `5081ab44ceea4468d93dc922b7fd8df4a8bcd99c654aa2652e2a03d67e735fc6`，helper SHA `2a831f9d1f6c51744af2bd9ff0c00a20fdcb3f760616bb1cc0b996d025a3424c`。旧r7b五例实际截图绑定的是84bundle `1ab294…`，不能替代新85bundle实际观察；新版本等待主任务r8重载后只读验收，不新发分析或搜索。

### 检索范围失配的明确恢复路径（87项冻结）

实际Dashboard v1曾将Excel GROUPBY材料用于Streamlit单元，后端只读投影新增外层`scope_mismatch`与group的`scope_status='mismatch'`、`scope_notice`、`expected_search_text`。前端仅消费该明确合同，不从标题或工具名自行猜失配；任一标记存在就不展示这一单元的旧卡片、平台选项或覆盖结论。界面标为“检索范围需重试”，显示原因和正确学习范围，当前版本引导使用既有“重新检索这些知识点”创建新版本；历史版本只引导从“我的项目”返回最新版本。不会把这一状态写成无结果或单元仍加载，不改变其他单元结果。

`frontend/tests/fixtures/project-scope-mismatch.json`来自实际保存的Dashboard v1经后端stage纯读投影，SHA `09ad8aecf65917409956edda81bba62b409f792756ef9e85193df928b76e8a01`。producer SHA `8481d17548151c311584db6eee014b8008118e5008c0185fe636d18f4f957cf0`，输入／后端源SHA见`scope-mismatch/fixture-provenance.json`；无新HTTP、数据库写或模型调用。后端revision2提供相同输出，已逐字节SHA比较一致，只更新producer源元数据，r1记录也保留，没有重复未受影响的测试。浏览器fixture的图片请求隔离为占位像素，不作为实际封面、播放或新检索证据。

新增Node五项覆盖两种标记、普通状态／标题不误判、保存数据不被修改。两项浏览器用例覆盖上述真实派生API形状、即使旧三类列表和覆盖误留也不能显示、旧平台不进入筛选、服务端提示按纯文本渲染、键盘选中该单元、三宽与对比度；另验证点击既有重试创建并确认v2、只检索v2，返回v1后无写入口且旧job身份保持。首轮一项新测试用了严格单元素locator匹配三单元，产生1通过1失败；只修测试检查所有单元，生产未改，`targeted-first-results.json`与trace保留，随后定向2通过、完整87通过。58项Node与最终构建通过。

最终bundle `index-CNRwT4ew.js`，SHA `d42a9edc94206fbf94db656f998b87aa2b41765e8a0ec7e0eb28b48b00b07cc0`。48文件清单、QA、日志和截图均在`scope-mismatch/`及主清单同步；三张失配图已实际打开，0横溢，最低提示文字对比度5.726136387959927:1。前端源、测试、dist和本文现已冻结；该新版实际运行态仍等待主任务r8重载通知，未发真实POST，不把r7b旧bundle五例截图作为当前版本的实际验收。

### r8当前构建实际只读收尾

父任务明确通知r8后，绑定实际PID20748、`evidence/phase2/runtime-r8-manifest.json`（SHA `5695977b0584231601d72125c96824a1f482b220d905834f6855da6fbe2c04c7`）及实际HTTP返回的CNRwT4ew完整SHA `d42a9edc…`，逐例串行只读观察。默认脚本只做本地准备、0网络/0浏览器；实际模式在HTTP前核对48文件及runtime全部源／dist SHA，并拒绝旧16148／26048。未启动检索、分析或重试，未点击平台外链。

| 实际版本 | 单元／材料卡 | 终态窗口UTC | 证据目录（`runtime-r8/`下） |
| --- | --- | --- | --- |
| data v6 | 7／13 | 20:16:37–20:16:46 | `terminal-data-v6/bicycle_csv_advanced/` |
| maze v6 | 6／1 | 20:18:21–20:18:29 | `terminal-maze-v6/pygame_maze_intermediate/` |
| web v5 | 7／6 | 20:20:53–20:21:00 | `terminal-web-v5/web_pomodoro_beginner/` |
| Arduino v5 | 5／1 | 20:22:03–20:22:09 | `terminal-arduino-v5/arduino_reaction_beginner/` |
| Dashboard v2 | 6／3 | 20:23:40–20:23:47 | `terminal-dashboard-v2/study_room_streamlit_intermediate/` |

五例均1440／768／390文档宽度等于视口，三步骤可达，桌面Enter可在结果与审阅间切换，8个Tab停点焦点可见；0写请求、0控制台／运行时错误、0平台document跳转，初末已分配job与批次对应身份完全不变。每例桌面结果或课程特写、平板缺口或课程图、手机终态空单元均已实际打开，没有发现新的明显高／中优先级前端呈现或导航缺陷。实际错误状态未出现，仍只引用另列的mock错误证据。31单元／24材料卡是API当前展示数量（23partial＋1review），不是24条已验证视频或教学覆盖通过。

web“状态对象”实际只列一次，1/4，三项缺口未丢；maze保留实际标题`Tutorial #1`及授课语言尚未确认说明，不改成具体迷宫教程。Dashboard v2的k5实际检索为`Streamlit groupby 汇总与 Streamlit 条形图`，只返回`python streamlit 创建柱状图`（B站BV19T411t71G），无Excel；界面1/6仅`st.bar_chart`有依据，groupby等仍缺，见该例`new-owner-scope-observation.json`。内容真实性与深度由独立来源审查负责，未以标题命中替代教学证明。

历史Dashboard v1另在20:15:50–20:15:56观察：current v2、selected v1，k5明确scope_mismatch、三类卡及平台清空、覆盖全unknown；正确k1卡`res_34ac36880ba839f666df09e8`初末仍实际可见。三宽无卡／覆盖／加载，提示回最新，无历史重试按钮；旧job与选中v1身份不变。`dashboard-history-v1/`含完整初末实际API与三宽图。20:20:17–20:20:21在`dashboard-history-v1-card/`补拍实际卡、推荐理由和本课依据，均已打开：UI确有作者自述音频问题、当前未验证播放，以及后续完整版未核实发布的提醒；本课路线仍1/5。

API时间边界明确保留：历史两轮与Dashboard v2直接保存真实完整初末响应；前四例原脚本保存的是完整初末投影摘要，没有早期完整body。随后复制父任务原完整终态body并核对其与原initial摘要一致，每例仅补一次较晚GET完整body并核对与原final摘要一致，分别保存`parent-terminal-full-response.json`、`closeout-response.json`、`api-preservation-proof.json`。`api-preservation-summary.json`明确较晚时间与未倒填，原report、父任务raw及manifest未替换，补件不能冒称先前未保存的原始body。

首次data进度窗口保留于`progress-data-v6/`：实际三宽8卡／running、0写／console/runtime，但旧证据guard因后台为既有pending第2批赋新job而失败；原job未换，这次不记通过。按父任务批准，仅修改evidence进度guard允许同版本／同批次集合的原空job赋值，禁止原非空job替换和重复job；终态继续严格不变。未改生产源或测试，也未重跑／改记87和58基线。数据已终态，故以独立终态窗口完成严格验收，未倒改首轮失败。

已知来源身份边界：web的Tuts资源`res_3edb2cd182f41415c02bd469`，URL `https://webdesign.tutsplus.com/css-pseudo-class-focus-visible--cms-37211t`，当前API为`resource_type=video`但`video_evidence_status=search_discovered`。其视频身份待独立核查，分类／卡片与正文支持不等于已验证视频或播放。`observation-summary.json`和主QA明确`sourceQualityAcceptance=false`／`productionAcceptance=false`；后续r9隔离方案不是本r8成果。48个冻结源／测试／dist SHA仍0变化。
