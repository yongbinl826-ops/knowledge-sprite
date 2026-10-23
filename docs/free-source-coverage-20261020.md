# 免费来源补全与中英文参考匹配（2026-10-20）

本轮是 `related-reference-policy-20261020.md` 之后的有界免费来源补全；旧文中的2/20是当时的历史状态。本轮最终结果以实际 JobService 与 create_app GET 响应为准：**20个知识点中15个有至少一条可展示相关参考，共29条逐点参考、15个不同URL**。这表示相关材料可展示，不代表完整讲授、播放验证、学生学会或全项目生产验收通过。

学生仍自己勾选知识点；不增加已会知识记录或顺序要求。两份分析沿用此前真实模型输出，本轮没有重新调用模型、扩点或重排。此处只复核小游戏和数据看板两案，不外推网站、APP或硬件项目的验收。没有向真实学生库或共享课程库注入测试记录。

## 已修复

真实英语视频页面包含 game loop、key presses、DataFrame、font.render 等内容时，旧中文词面规则可能漏掉相关视频。中文“读取csv格式文件”与“CSV 文件读取”的词序变化也会导致漏召回。新增通用中英文概念/API及CSV读取语序提示，只从选定知识点及绑定的实际来源内容取词，并要求技术语境；不按项目名、站点URL或固定答案放行。显式“not covered / not taught”的内容不得成为正面依据；CSV导出不得充当CSV读取。

仍保留安全URL、真实视频类型、明显错技术栈、广告和来源绑定检查。推荐标为 `exact_teaching_verified=false`，解释依据和访问条件；没有编造章节、时间戳或播放能力。

## 真实免费采集与边界

- 本机既有 SearXNG 的 duckduckgo videos 两次不同查询均返回上游 timeout；HTTP200不等于正常空结果。连续两次后停止该来源，未重试、未绕过访问限制，也未把剩余查询描述为“没有视频”。
- 已有匿名允许来源的 Bilibili 视频页、Tech With Tim Pygame 目录、freeCodeCamp Pandas 页面新读取HTTP200。目录调用沿用现有 Fetcher 的 robots、公开DNS与来源校验。所有素材均区分本轮新取和此前归档，不把归档回放说成新在线验证。
- 3次共享目录逻辑查询（Pygame、Streamlit、Python）共取得7个详情页。原Python补充用于随机数/状态机的第二次不同查询；泛泛 Variables & Data Types 和 Basic Operators & Input 不计为这两点的相关推荐。每个相关点最多2次不同逻辑查询，目录中的逐页读取另计。
- 新取Streamlit文本页面及 Creating the game 的资源类型为unknown，未算作视频。付费/登录/地区提示不等于链接无效；未执行媒体播放。
- 目录采集累计55次真实传输尝试（含公开DNS等元数据请求），预算上限60；初始来源探测累计21次，SearXNG查询2次/4次本机传输。这些是分组统计，不能当作模型或付费调用数。首轮两处诊断守卫在发送前误拦，已保留原失败和证明未发送的修正记录；未对被站点拒绝的请求改路绕行。

## 逐点实际API验收

4个RAM隔离任务，每个最多5点，以正常结果处理和真实ASGI GET输出，使用公开真实来源的保留元数据。局部resource/evidence ID仅为正常数据库主键隔离，原eID、原文本哈希、原观察时间和局部映射均保存于 `api-replay/evidence-lineage.json`。无外部、详情、模型请求，无真实学生数据，GET零写。

首轮仅纳入四份已选资源导出，实际12/20；定位到另一份完整旧公开诊断导出中的CSV/日期资源及真实eID后纳入最终池。首轮历史与修正来源清单保留，未把未保存的检索条目或无依据线索补成课程。

|项目|知识点|实际参考数|实际链接|
|---|---|---:|---|
|pygame|游戏主循环|5|[Jumping & Boundaries](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/jumping>)；[Character Animation & Sprites](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-animation>)；[Basic Movement & Key Presses](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-tutorial-movement>)；[Scoring & Health Bars](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars>)；[Tutorial #1](<https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-1>)|
|pygame|矩形区域表示|3|[Jumping & Boundaries](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/jumping>)；[Basic Movement & Key Presses](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-tutorial-movement>)；[Scoring & Health Bars](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars>)|
|pygame|键盘输入处理|2|[Jumping & Boundaries](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/jumping>)；[Basic Movement & Key Presses](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-tutorial-movement>)|
|pygame|边界限制|1|[Jumping & Boundaries](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/jumping>)|
|pygame|随机数生成|0|当前来源池无可展示的相关视频|
|pygame|矩形碰撞检测|3|[Pygame碰撞检测](<https://www.bilibili.com/video/BV1Ct4y127He/>)；[Pygame 自定义碰撞检测区域和函数，改善不精确的 Sprite 精灵碰撞检测｜Python 游戏开发教程](<https://www.bilibili.com/video/BV1UoyKBCECZ/>)；[中文编程pygame游戏教程5_检测碰撞](<https://www.bilibili.com/video/BV1P8411X71Q/>)|
|pygame|列表增删遍历|1|[Tutorial #1](<https://www.techwithtim.net/tutorials/game-development-with-python/snake-pygame/snake-tutorial-1>)|
|pygame|有限状态机|0|当前来源池无可展示的相关视频|
|pygame|文本渲染|1|[Scoring & Health Bars](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars>)|
|pygame|游戏计数变量|1|[Scoring & Health Bars](<https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars>)|
|dashboard|DataFrame 数据结构|2|[Python-第三方库Pandas系列教程之 27-python-pandas-时间数据处理 @数据分析](<https://www.bilibili.com/video/BV14T2cB8EXT/>)；[Learn Pandas & Python for Data Analysis [Full Course]](<https://www.freecodecamp.org/news/learn-pandas-for-data-science/>)|
|dashboard|CSV 文件读取|3|[Python-第三方库Pandas系列教程之 27-python-pandas-时间数据处理 @数据分析](<https://www.bilibili.com/video/BV14T2cB8EXT/>)；[利用pandas读取csv格式文件](<https://www.bilibili.com/video/BV1dK411M7oM/>)；[使用pandas库读取csv文件并筛选行和列数据](<https://www.bilibili.com/video/BV1gZ421i7Fy/>)|
|dashboard|数据类型转换|1|[Python-第三方库Pandas系列教程之 27-python-pandas-时间数据处理 @数据分析](<https://www.bilibili.com/video/BV14T2cB8EXT/>)|
|dashboard|缺失值处理|1|[Learn Pandas & Python for Data Analysis [Full Course]](<https://www.freecodecamp.org/news/learn-pandas-for-data-science/>)|
|dashboard|日期时间属性|1|[Python-第三方库Pandas系列教程之 27-python-pandas-时间数据处理 @数据分析](<https://www.bilibili.com/video/BV14T2cB8EXT/>)|
|dashboard|分组聚合|3|[2020最新python pandas数据分析案例之数据的合并与分组聚合](<https://www.bilibili.com/video/BV19J411n7iN/>)；[105集Pandas分组聚合操作](<https://www.bilibili.com/video/BV1WKH7zZEEw/>)；[8.Pandas教程_分组与聚合-数据分析与探索-[Python]](<https://www.bilibili.com/video/BV1n7YLepEx6/>)|
|dashboard|布尔索引过滤|1|[Learn Pandas & Python for Data Analysis [Full Course]](<https://www.freecodecamp.org/news/learn-pandas-for-data-science/>)|
|dashboard|Streamlit 交互控件|0|当前来源池无可展示的相关视频|
|dashboard|Streamlit 图表展示|0|当前来源池无可展示的相关视频|
|dashboard|CSV 文件导出与下载|0|当前来源池无可展示的相关视频|

覆盖以 `api-replay/summary.json` 和 `point-coverage.json` 为准；同一真实课程可用于多个确实相关点，课程跨点复用不等于独立视频数量，也不应重复计算同一点的URL。

## 验证与交付程度

- 后端冻结源码59文件，全量离线/mock回归：5834 passed、26 subtests passed、1条既有Starlette/httpx弃用提示；源码前后一致，外部传输尝试0。见 `backend-final-r2/receipt.json` 和 `results.xml`。旧5831绿色及新修复前的实际观察均保留。这不是供应商实网全点验收。
- 独立固定真实来源判例87/87通过（90组合中3个邻近背景例明确不计分）；原32项边界、3项否定表达、4项新增页面正反控制、5项CSV/日期/类型恢复及导出负例通过。保留原失败记录。测试夹具来自实际公开来源，不注入生产课程库。
- 前端源码和普通Web构建保持此前冻结的98项输入；本轮只对当前真实API载荷进行三宽、键盘、相关卡链接/原因、去重计数及缺口/来源失败的有限浏览器回放。准确观察与截图见任务证据目录的前端最终回执；这是保留来源载荷的本机回放，不是新实时检索。
- 本地预览 `http://127.0.0.1:8928`，API `http://127.0.0.1:8017`；重启后GET健康检查与源码绑定另存 `runtime.json`、`source-verified.json` 和 `installed-preview/receipt.json`。自动MOOC刷新关闭，不提交新的分析或检索请求。

**尚不能宣称“每点都有视频”或生产内容验收通过。** 未覆盖点见上表；当前明确边界是免费检索引擎连续超时，以及有界允许目录内未取得可展示视频，不代表互联网上不存在这些视频。需要恢复允许免费检索源或补充实际课程材料后再做全点验收；本轮不会调用付费服务或新增模型来补数。

## 预算、安装和回滚

本轮新增模型/付费调用0；累计物理模型账本仍12次，原账本SHA256 `3743f6c5c6a6c6ede4f56b079136f53f45d4e42152f6ec4a98ac50cbafe91063`，未重置或改写。未执行打包、安装工具、创建凭据、扩权、外网部署、Git推送或Library重试。

只集成6个明确公开文件，先验证此前163项D公开文件哈希和HEAD，再备份原件并CAS安装；不读取/复制/修改真实.env、学生库或隐藏日志。正常应用启动按现有配置运行。任务工作区的 `tmp/install_free_coverage.py rollback` 可回滚这次6文件变更；目标有后续改动时拒绝覆盖。前后哈希与原件在 `evidence/free-point-coverage-20261020/source-install/`。回滚源码后需按实际空闲进程身份重新启动本机API，不能复用旧PID执行重启。
