# Phase 2：学习单元的视频覆盖与下一步

本轮验证流程：打开指定项目版本的推荐视频 → 查看单元学习路线 → 切换课程平台 → 核对当前视频可支持与仍缺的子技能 → 打开有依据的视频并按项目练习检验。

## 交付与结果

FCC/TWT 两种明确来源绑定、Pandas 短链接和稳定 whole_topic 契约已完成验证。最终完整回归76项通过；之后仅修正两处测试类型和“检索完成”文案，并分别完成2项与11项受影响回归及最终构建。原69项报告保留为修复前基线。

每个学习单元现在显示“本单元学习路线”：当前视频可支持的具体子技能、仍需补充的子技能、下一步和项目练习。资料不足时显示待确认，并提示核对视频简介或目录。全部已列子技能均有依据时，仍明确保留教学深度、完整性和实践检验的边界。

| 验证 | 结果 | 记录 |
| --- | --- | --- |
| 最终完整浏览器回归 | **76 passed，0 failed/flaky，88.9 秒**；覆盖展示20 + 原项目23 + 手动33 | `evidence/browser/phase2/e2e-two-source-final-results.json` |
| 76项后的测试类型修正 | 受影响TWT2项再次通过；生产代码未改 | `evidence/browser/phase2/twt-types-incremental-results.json` |
| 76项后的检索终态文案 | 现有三步/历史/来源/整单元11项增量通过，21.4秒 | `evidence/browser/phase2/search-status-wording-incremental-results.json` |
| 原新覆盖展示独立浏览器回归 | 13 passed，0 failed/flaky | `evidence/browser/phase2/coverage-corrected-title-results.json` |
| 摘要分支修复前的完整浏览器基线 | **69 passed，0 failed/flaky，75.5 秒**；新覆盖 13 + 原项目 23 + 手动检索 33 | `evidence/browser/phase2/e2e-full-results.json` |
| Node 证据、章节和图片策略测试 | **45 passed，0 failed**，本轮重新运行 | `evidence/browser/phase2/node-final-tests.tap.txt` |
| TypeScript 与 Vite 生产构建 | 通过 | `evidence/browser/phase2/frontend-final-build.log` |
| 新路线文字对比度 | 三尺寸各 13 项采样，最低 **5.33283:1**，0 失败 | `evidence/browser/phase2/coverage-{desktop,tablet,mobile}.json` |
| 原流程三步骤文字对比度 | 9 组通过，最低 5.15989:1 | `evidence/browser/phase2/contrast-*.json` |

完整回归中的 3 项 opt-in 真实只读测试按配置跳过；本轮没有访问、启动或停止 8000 服务。此前真实服务报告与 52、23、56 项阶段报告均保留。本轮使用隔离响应，不能证明真实检索质量、来源可用性、视频完整教学或学生已完成实践。

## 证据边界

展示层复用现有 `collection_coverage.subtopics`、资源自身 `subtopic_coverage`、`supporting_evidence_ids` 和 `collectionCoverageRows`。不新增 API 汇总字段，也不照搬 `all_subtopics_supported`、`single_resource_full_coverage` 或平台的全量汇总断言。

计入“有内容依据”须同时满足：

- 资源实际位于当前版本、当前平台和每栏展示上限内，类型为已有课程/视频展示范围。
- 卡片不处于 `needs_review`；匹配中的知识点和资源编号与当前结果、自身资源一致。
- 子技能的编号与文字均与当前单元的分解一致；支持 ID 同时存在于自身匹配和自身证据中。
- 证据记录唯一，并属于资源自身 URL、canonical URL 或 resolved URL；标题和搜索摘要不参与此清单。
- 正文证据必须是 `page/description`，并与资源 description、field provenance 的 ID 和来源完全绑定。
- 目录证据必须是 `catalog/chapters.N`，与对应章节 ID、标题、链接、时间字段一致，链接与时间值有效；篡改或交叉引用不计入。

这里的“有内容依据”表示来源自身简介或目录支持该子技能，仍不等于实际播放、完整教学或学习效果已核验。截断而不能精确绑定的正文、未支持来源的特殊摘要字段和仅搜索发现的线索会保守地留在待确认状态；原卡片的部分匹配、待核实和未知语言说明保持原样。


### 明确来源的视频摘要分支

修复后的展示只接受两种明确来源协议，均不会因存在 video_topic_summary 字段就泛信该内容。此前69项基线没有验证这些分支。

- freeCodeCamp：HTTPS公告页；精确 summary/video 来源；同页唯一证据和provenance；自身摘要等于证据正文；公告及课程标题一致；watch链接和iframe指向相同11位视频ID；另允许已观察的HTTPS精确youtu.be/<11位ID>短链接，拒绝伪域、转跳路径、HTTP及不一致ID。正文首段须与保留公告一致。损坏时不回退到文章description或目录。
- Tech With Tim：HTTPS三层课页；精确 title/video/summary 三条来源和同页唯一证据；lesson_title、embed_title、lesson_url和显式“video above”教学声明一致；同ID iframe；浏览器原生WebCrypto核对完整UTF-8摘要SHA-256。核对期间标记待确认，失败保守未知；结果按当前摘要key应用并在effect清理后忽略过期回写。不回退到侧栏、Full Code、通用文章描述或搜索摘要。

三份API-shaped JSON（FCC Python、TWT、FCC Pandas）均由仓库已保留的真实公开HTML经当前extractor、Resource模型和ranking离线生成，原HTML与原公开来源SHA留存。Tech With Tim重放明确设置已观察HTTP200对应fetched/page状态，不重新请求页面或播放器。测试不手工制造合法资源的supported/partial状态；对JSON的损坏或污染修改仅用于负例。TWT字体渲染支持与矩形碰撞未支持由后端严格数据流规则产生；前端保留partial和原语言说明，不根据页面域名或中文UI推断中文授课。

## 覆盖矩阵

| 情形 | 预期与实测 |
| --- | --- |
| 正文支持读取 + 目录支持统计 | 合并为 2/3；导出仍需补充 |
| 同时存在“导出”的搜索摘要和待核实视频 | 不把其纳入内容依据；原卡片仍可供核对 |
| 只有待核实视频 | 0/3，全部子技能仍需补充，无“有依据的视频”入口 |
| 切换 B站、其他网站、全部平台 | 支持列表和缺项实时重算；不借隐藏平台的视频补齐 |
| 视频位于每栏展示上限以外 | 不计入当前覆盖 |
| 所有子技能分别有依据 | 3/3；仍展示完整性提醒和独立项目练习，不标记已掌握 |
| 新稳定whole_topic行 | 未能拆分时，唯一whole_topic且文字等于当前result.text才可按同一有效自身证据显示；错文本不伪造子技能 |
| FCC Python和Pandas实际HTML重放 | 合法绑定摘要2/2；Pandas null/duplicate来自项目教学段落，合法短watch链接仍须与iframe同ID |
| TWT实际HTML重放 | 字体渲染1/2；矩形碰撞仍缺，FullCode/侧栏不补足；hash损坏或WebCrypto不可用时保守未知 |
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
| 新后端稳定whole_topic行保留not_applicable/unknown，旧展示工具仅接受applied | 在展示组件支持唯一且文字绑定当前result.text的真实整单元行，不伪造拆分 | whole_topic正例与错文本负例 |
| 原视频结果缺少单元层面补充任务与实践落点 | 显示缺项、明确下一步和原分析中的 practice_check/project_task/learning_goal | 最终20项覆盖展示回归及三尺寸截图通过 |
| 结果终态“已完成”容易被理解为学习或项目完成 | 只将completed中文文案改为“检索完成”，保留原后端值与实践边界 | 76项后的11项现有状态/历史/三尺寸增量通过，最终截图已打开 |
| 新测试有DOM变量遮蔽和nullable赋值两处TS错误 | 仅改为globalThis.document和明确的string赋值 | 首次日志保留frontend-typecheck-before-fix.log；受影响TWT2与最终build/Node45通过 |
| 初轮新测试 helper 使用了过时页面标题 | 仅修正测试到现有 `index.html` 标题，未修改产品标题 | 初轮 11 项 setup 失败保留为 `coverage-targeted-results.json`；修正后13项、69项基线及最终76项通过 |
| 空态提示曾假设必有 B站搜索入口 | 改为不依赖平台偏好的“调整单元目标与工具后重新检索”建议 | 最终完整回归的 empty 与原无结果/平台入口测试通过 |

已实际打开桌面入口、平板详情、手机详情截图，检查排版、留白、文字、细线和响应式。保留原设计的暖白、石墨与蓝色，不新增动效；手机使用单列支持/补充清单，避免两列挤压。新路线通过采样对比度验证。没有发现本轮范围内未解决的明显高/中优先级问题；不声称获得设计奖项或完整无障碍认证。

## 文件与环境

生产文件修改 `frontend/src/components/ProjectVideos.tsx`、`frontend/src/styles.css` 的 `unit-coverage` 限定块及 `frontend/src/types.ts` 的可选摘要字段，并新增 `frontend/src/components/LearningCoverage.tsx`。另在76项后按集成复核将 `frontend/src/projectTypes.ts` 的completed文案改为“检索完成”，后端状态未改；11项增量通过。`ResourceCard.tsx`（含 CourseCover）及除此列明文件外的既有生产源码SHA与上一阶段一致。测试新增 `project-coverage.spec.ts`；原 project/search 测试只增加可选 `QA_EVIDENCE_ROOT`，让本轮截图和 JSON 写入独立目录。

Browser plugin / browser skill 不可用，因此采用现有仓库 `@playwright/test` 与已安装 Edge；未安装依赖。Windows 沙箱无法启动浏览器/访问 loopback，使用已授权本地执行环境。隐藏 Vite 为 `http://127.0.0.1:5175`，PID **24548**，身份及日志记录于 `phase2/vite-process.json`；保留给集成负责人，未使用 Ctrl+C 或全局进程终止。

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\frontend'
$env:PLAYWRIGHT_CHANNEL = 'msedge'
$env:PLAYWRIGHT_EXTERNAL_SERVER = '1'
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:5175'
$env:QA_EVIDENCE_ROOT = '../evidence/browser/phase2'
$env:PLAYWRIGHT_JSON_OUTPUT = '../evidence/browser/phase2/e2e-full-results.json'
$env:PLAYWRIGHT_OUTPUT_DIR = '../evidence/browser/phase2/full-artifacts'
npm run test:e2e -- --workers=1
npm run build
node --test --test-reporter=tap tests/chapter-recommendations.test.mjs tests/partial-chapter-evidence.test.mjs tests/topic-evidence.test.mjs tests/course-images.test.mjs
```

最终源码、测试、配置和 dist 共 42 个文件的 SHA 在 `evidence/browser/phase2/tested-frontend-manifest.json`；新生产文件及改动前 SHA 单独列出。机器可读汇总为同目录 `qa-summary.json`。未测试 Firefox/Safari 或实际屏幕阅读器会话；真实模型与课程服务的验收由集成负责人另行进行。

截图位于 `evidence/browser/phase2/screenshots/`：

- `coverage-desktop-entry.png`、`coverage-tablet-detail.png`、`coverage-mobile-detail.png`：新路线的三尺寸实拍。
- `coverage-keyboard-reduced-motion.png`：键盘焦点与减少动态偏好。
- `mock-{desktop,tablet,mobile}-01-input.png`、`-02-selection.png`、`-03-results.png`：最终完整回归的三步骤。
- 同目录保留 loading、empty、error、search-loading 等关键状态，未覆盖上一阶段截图。

最终fixture生产者ranking文件因后端相关修复更新后，三份数据重新经真实提取/模型/ranking生成；对point、item和collection整个API payload逐一SHA比较完全相同，仅producer provenance改变，记录于fixture-producer-refresh-verification.json，因此没有重复未受影响的全套浏览器回归。

实际HTML重放截图还包括 coverage-fcc-bound-summary.png、coverage-fcc-pandas-short-url.png 和 coverage-twt-{desktop,tablet,mobile}-bound.png；最后一组三尺寸均已实际打开，新的“检索完成”顶栏也已复核。
