# 合法公开课程发现与大纲修复（2026-10-19）

本轮继续调查了独立搜索来源、官方公开目录、合法开源课程索引，并修复一个经真实页面证明的大纲解析遗漏。**两项专业点可以从真实搜索结果定位到真实官方课程内容；应用实时自动MOOC召回仍未通过。** 不把一次检索成功、离线解析成功或健康检查 200 当作可生产验收。

## 实际搜索与来源条件

| 路径 | 已完成动作与结果 | 决定与边界 |
|---|---|---|
| 原 SearXNG/Bing 链 | 上轮已经抓取 q 与响应 query 逐字一致的原始 JSON；仍返回10条外域结果，严格域过滤正确 | 已安装公开适配源码的请求构造也保留 q；未捕获容器真实出站请求，不能归因到 Bing 本体。没有证据支持继续修改空格或放宽域过滤 |
| 独立 DuckDuckGo general | 用现有固定官方镜像在隔离18781端口仅新增公开 HTML/no-JS 首屏表单引擎；`Python 列表 字典`、`pandas 分组 聚合`两查询各 raw10/接受5，回显一致、无警告 | 真实观察共10条记录、9个不同 MOOC URL，来自动态搜索，不是种子。无 API key、无账户、无分页/VQD请求；无需 key 不等于许可或稳定担保 |
| DuckDuckGo 应用联调 | 实际 JobService 用两个专业点与 B 站并行；第一条 MOOC 请求的 HTTP200 信封包含明确 CAPTCHA；其后3个 MOOC 逻辑槽均 suspended，0 HTTP | 停止该 general 来源，没有换域、locale、headers、cookie、VQD、浏览器或重启清暂停来重试；不能将最初两次成功推广为稳定修复。原8001和18780未受隔离服务影响 |
| B 站并行行为 | 同一真实作业4个 B 站 HTTP 全成功；13个去重发现卡保留，Python7/pandas6；初轮屏障后才补搜 | 5页详情成功、1页过大，另7未抓取。13是发现卡数，不是13个教学适配/播放验收。MOOC失败没有占用或丢掉 B 站已返结果 |
| 独立 Brave | 只启用公开 HTML 搜索引擎，第一条 SearXNG 请求报告 `too many requests`/rate_limited，第二查询未执行 | 已停止来源，不换入口或身份。没有 API key/私有搜索 API；限流信息是网关的引擎观察，不冒充已捕获直接上游 HTTP 状态 |
| 百度 | 只读官方 robots 与免责声明，未发搜索 | 通配组 `Disallow: /` 覆盖 `/s`，按本项目策略不探测。`tn=json` 不应无据称为私有账户接口，但无 key 也不代表自动化获准；未换 URL、主机或身份 |
| MOOC 学校云公开文档 | 已读取官方课程列表文档，未调用接口 | 文档要求学校云赋权、appId 与签名，不能当匿名通用目录；没有创建凭据或扩大权限 |
| 官网匿名浏览器 | 分类页热榜有10个公开 href，主列表空；搜索页没有可用搜索控件。新“计算机”筛选调查在导航等待阶段超时，0点击，两个CDN脚本连接关闭 | 不把热榜视作知识点匹配，也不把导航超时说成拒绝或全站不可用；没有猜参数、重放内部RPC或伪造这轮DOM/截图 |

## 开源索引和官方公开目录的实际覆盖

CS自学指南的主仓库为 `PKUFlyingPig/cs-self-learning`，贡献者自有内容采用MIT许可；外部课程、图书和视频保留各作者权利。其公开站点 `https://csdiy.wiki/` 的真实页面声明了搜索worker和主bundle。只读检查主bundle中实际声明的 `search/search_index.json` 后，通过原生安全Fetcher读取 `https://csdiy.wiki/search/search_index.json`：HTTP200、1,019,553字节、1,051条片段记录、270个不同文档。六次target HTTP、12次DoH、0重试，robots404按既有策略处理，没有执行JS、注入robots缓存或调用私有接口。

索引正文没有 `<a href>`；含原生MOOC的只有HITOS中英两个重复记录、**1个不同课程URL**。HITOS描述的是操作系统、C语言先修，不匹配本次Python列表/字典或pandas分组聚合。CS50P页面的HTML另有课程网站/B站外链，但搜索索引正文只保留“2022”等锚文本，不能据此恢复其目的URL；该页面也没有原生MOOC课程。没有加入单门已知课程种子，也没有把这个有限目录做成通用召回通过证据。

另从本轮实际官方课程HTML中观察到“一流课程/了解更多”的公开链接 `https://www.icourse163.org/channel/2001.htm`，在新的robots404预检后正常读取：HTTP200、69,981字节、0个原生课程href、0个课程URL字面量、未声明sitemap。只得到已调查的 `/category/all`、`/search.htm` 路由，没有探测猜测接口或内部RPC。这次调查为2个target HTTP、4次DoH、0重试。结果表示该响应未提供可解析目录，**不是官网拒绝访问或全站不可用的证明**。

上述结果没有证明广泛、持续的原生MOOC专业点召回。它们也不证明全网不存在免费合法路径。课程页自身访问正常，不能把搜索限制、目录空壳、登录/付费/地域条件混称为无效课程链接。


## 两专业点的真实内容证据与修复

最初成功搜索得到的真实 URL 被独立安全 Fetcher 读取，3页均 HTTP200，4个目标HTTP（含robots）+8个DoH；没有再次访问被挑战的搜索来源。URL选择按实际题名/摘要中的技术词排序并去重，不在生产代码写入课程编号。

| 专业点 | 真实官方课程与本课证据 | 学生阶段与限制 |
|---|---|---|
| Python 列表与字典 | `https://www.icourse163.org/course/HIT-9003` 本课34条大纲包含6.1列表、7.1字典；`CUPK-1474026162`也有对应章节 | HIT预备知识“无”；CUPK面向零基础，但后续章节仍有课程内先修路径 |
| pandas 分组聚合 | `https://www.icourse163.org/course/NJCIT-1469574161` 本课项目6明确“使用pandas进行数据分组与聚合”，任务含分组聚合、apply和transform；CUPK本课9.8明确Pandas分组聚合 | NJCIT明确需要Python或其他语言基础，不能宣称零先修即可学。课程里的遥测localStorage不算本地存储教学 |

公开页另一种 `termDto.outLineDto.outLineStructureDtos` 表示此前未被读取：旧 `outLine` 字符串为空，并不意味着无大纲。本轮只修改 `source_adapters/icourse163.py`，保留本课 courseId/tid 绑定、旧大纲优先及500条总项上限；按原顺序读取 name/plan，goals 不充当章节。拒绝不支持或超限的整体结构，过滤脚本/隐藏元素/远程推荐/遥测，不执行 JavaScript。

三份原始页回放：CUPK **0→107**、HIT **34→34**、NJCIT **0→43** 个大纲条目。条目不等于视频数，未推断时间戳、片段URL、免费状态或播放能力。公开大纲可作为具体知识点相关性证据，用户只需跳转平台，不要求本任务验证播放。

## 验证与本地交付

修复前保留红测16个失败；最终定向112项通过（38新、74既有，原测试未改），独立审核45/45检查及事前16/16准则通过，3原始页/最小fixture目录逐项一致。独立首轮因空格规范化差异误报的评审脚本记录、测试环境临时目录错误均保留并解释，没有覆盖失败证据。

完整主回归 **3813通过，0失败/错误/跳过**；适配器 **145通过，0失败/错误/跳过**。两轮均冻结并复核源码SHA。它们是离线回归；真实搜索、课程HTTP与浏览器证据另存，不混算。测试期间仅复用本机已安装依赖，未下载或升级库。

解析修复已按SHA保护计划安全集成至 `D:\项目制知识引导小精灵`，只修改1个生产适配器、1份新测试与7份最小真实大纲fixture、2份说明；没有修改前端、`.env`、原SearXNG配置或Git，也没有替换用户数据库。更新前备份位于本机Temp，未收入交付包。

最新运行、健康、17张SQLite表的全部行/schema摘要与受保护文件核验，以 `evidence/mooc-discovery-focused-20261019/local-update/{started,verified}.json` 为准。仍用回环单worker的 `http://127.0.0.1:8001`；`/health/ready` 200只表示配置/既有观察层面就绪，不能代表MOOC实时检索可用。

实际8001生产构建进行桌面/平板/手机三种宽度只读Edge回归，结果与截图在 `actual-8001-browser/`；该验证不提交项目、不触发模型或课程搜索，不能替代核心检索验收。前端继续保持专业知识点列表与右侧可跳转封面，未恢复用户取消的教学拆解/critic。

本轮自行创建的18781/18782两个隔离检索容器，已按精确ID、镜像和回环端口核验后停止并移除；原18780容器ID与启动时间不变。见 `isolated-services-cleanup.json`。没有为恢复被拒绝来源而重启或更换身份。

新增交付包为 `artifacts/knowledge-sprite-focused-discovery-20261019.zip`，SHA与公开文件清单见 `delivery.json`、包内 `PACKAGE_MANIFEST.json`；它是追加增量，不是完整仓库。两个历史包保持原SHA。公开包不含私有配置、数据库、备份/日志、凭据、完整第三方HTML/JS或node_modules。


## 仍需处理的边界

两专业点“实际查询→观察到的课程URL→真实官方页→具体本课内容”的分步证据成立，但新的完整 JobService 实时作业中 MOOC 为0，不能回填以前成功的发现来声称该作业通过。NJCIT的先修适配、全部项目类型和学生阶段、持续稳定的通用MOOC发现仍未完成生产验收。现有实际作业MOOC零结果属于明确未通过，不是待验证的成功。

若需要采用学校云课程接口，需用户已有相应高校/平台赋权、appId与签名凭据，并确认授权课程范围；它不一定覆盖全平台。另一方案是明确获准自动检索且有适当额度的搜索服务，需确认服务及现有授权。本轮不创建/索取到公开记录中的凭据，不购买接口，不扩大访问权限，不推送Git或部署外网。公开索引路径的实际可用性及覆盖范围按上文如实列出，不将有限调查扩大成“全网不存在免费合法路径”。

证据在本任务 `evidence/mooc-discovery-focused-20261019/`：`isolated-search/`、`live-professional-chain/`、`isolated-brave-search/`、`baidu-public-conditions/`、`native-open-index/`、`csdiy-public-index/`、`discovered-course-content/`、`independent-quality/`、`full-backend-outline/`、`adapters-outline/`、`official-public-entry-audit/`、`actual-8001-browser/`、`local-update/`。原失败证据与旧交付包保持原状。
