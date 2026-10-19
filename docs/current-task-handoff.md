# 当前工作交付定位（2026-10-19）

当前实际工程为 `D:\项目制知识引导小精灵`，GitHub `yongbinl826-ops/knowledge-sprite`，HEAD `d4beb5df724d57f7b6e9dde2bb088e7a71f26fc6`；本机预览 `http://127.0.0.1:8001`。最新进程身份、受保护文件及17张SQLite表全部行/schema核验，见 `evidence/mooc-discovery-focused-20261019/local-update/{started,verified}.json`。不要依据旧PID或旧8000进程判断当前版本。

用户当前范围保持：左侧为可选择/编辑/排序的专业知识点名称，右侧只显示可跳转的视频/课程封面；用户已经取消强制任务/技能/练习拆解和critic。分析提示为 `project-analysis-v4.1-coherent-professional-terms`，检索模式 `professional_terms_v1`，全局并发2，B站/MOOC并行。指定设计实际素材在 `design/imagegen/2026-10-18-three-screens-v2/`；本轮没有修改前端或构建产物。

**可本地使用和复核，但双平台核心不能宣称已可生产：当前MOOC自动召回未恢复。** 本轮两个真实专业点的实际JobService作业中，B站4次HTTP正常，保留13条去重发现卡（5页详情成功、1页过大、7页未抓取）；MOOC首请求报告验证码，其后3个槽均暂停、未发HTTP，最终0条。一次成功的搜索、课程大纲回放或健康200均不代替完整验收。

本轮继续完成合法免费路径调查：独立DDG公开HTML搜索两次实际成功，动态发现9个不同真实MOOC课程；后续验证码后停止。Brave首次限流后停止。百度robots通配禁止全站，未执行搜索。公开MIT许可CSdiy全文索引能读到，但原生MOOC仅1门HITOS且不相关；官网真实声明的新一流课程入口HTTP200却没有课程链接。未绕过验证码/限流/robots、猜私有接口、创建凭据、购买服务或新增付费模型调用。具体服务条件及证据见 `docs/mooc-discovery-status-20261019.md`；不能将有限调查扩大成“全网没有免费合法来源”。

已关闭的本地缺陷：官方课程实际使用另一种结构化大纲表示，旧解析会漏掉本课大纲。本次只改 `backend/app/source_adapters/icourse163.py`，保留courseId/tid绑定、旧结构优先、大小/条目上限和不执行JS；新增38项测试、7份最小真实fixture。三份实际页面回放107/34/43条大纲，非视频数、免费或播放证明。独立45/45检查通过，完整离线主回归3813、适配器145通过。实际8001只读Edge桌面/平板/手机3项通过，截图见 `evidence/mooc-discovery-focused-20261019/actual-8001-browser/`。这些离线、接口和浏览器证据分开统计。

本轮最小集成源为 `tmp/mooc-discovery-focused-stage/`；C工作区根backend/frontend保留历史源码，不要反向覆盖D。新增包 `artifacts/knowledge-sprite-focused-discovery-20261019.zip` 是1生产后端+8测试/fixture+2文档增量，非完整仓库。SHA见 `evidence/mooc-discovery-focused-20261019/delivery.json`。原包 `knowledge-sprite-current-user-patch.zip` SHA `222faf29e0a45cbb87476234637fd3bec7873f64c76e9724a3fc52ff4203c9dc`、前轮包 `knowledge-sprite-mooc-followup-20261019.zip` SHA `fb65689faff16fd74e7eb9e10b82ba2bb2836ecf87fd206d3d7fb9d34c535364` 均保持不变。私有备份位置由本轮 `local-update/prepared.json` 记录，只在本机Temp，严禁打包或覆盖到隔离测试数据。

既有验收属于历史证据：此前四案真实Flash单次生成37知识点；早期真实公开发现24个B站来源；前端Node120、模拟API Edge72、此前只读实际Edge3；详见 `docs/current-user-acceptance.md` 与 `evidence/user-current/`。不将既有计数当成本轮生产通过数。

生产前置仍包括：稳定且获准的相关课程发现来源及连续真实验收、各类学生先修和项目覆盖、真实部署环境认证/TLS/容量与恢复演练及部署授权。可考虑修复现有通用搜索、另一明确获准的免费公开目录/搜索，或用户已有学校云授权范围；学校云需要appId和签名，可能只覆盖被授权高校课程。本轮无Git推送、外网部署或权限扩大。隔离18781/18782已清理，原18780不变。
