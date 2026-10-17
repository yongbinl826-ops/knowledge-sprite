"""Build the final human-readable report from completed, reviewed evidence."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone
from xml.etree import ElementTree

out=Path(sys.argv[1]);load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
s=load(out/'summary.json');rows=load(out/'coverage-detailed.json');queue=load(out/'review-queue.json');review=load(out/'review-decisions.json');state=load(out/'live/checkpoint.json')
assert s['terminal_cases']==40 and all(r['state']=='terminal' for r in rows)
assert set(review['reviewed_cases'])=={r['id'] for r in rows}
assert all(review['case_evidence_hashes'][r['id']]==r['evidence_sha256'] for r in rows)
exceptions={(e['case_id'],e['resource_id']):e for e in review['exceptions']}
applications={(e['case_id'],e['resource_id']) for e in review.get('applications',[])}
review_counts=Counter()
for item in queue:
    key=(item['case_id'],item['resource_id'])
    item['evidence_review']=('off_topic' if exceptions[key]['decision']=='off_topic' else 'neighboring_or_insufficient') if key in exceptions else 'application' if key in applications else 'direct_topic'
    item['evidence_review_note']=exceptions.get(key,{}).get('reason','Saved title/snippet supports topic; page and teaching quality remain unverified.')
    review_counts[item['evidence_review']]+=1
(out/'reviewed-links.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2),encoding='utf-8')
def label(value):return str(value).replace('|','／').replace('[','（').replace(']','）')
lines=['# 已保存来源的课程与视频链接','','以下分类是助手对搜索标题／摘要的证据复核，不是页面或播放验收。邻近／证据不足条目另列；数量是链接观察，不能当独立课程数。','']
for row in rows:
    lines += [f"## {row['id']} · {row['point']}",'']
    items=[i for i in queue if i['case_id']==row['id']]
    if not items:lines += ['本轮没有符合规则的链接；实际查询和原因见覆盖矩阵。',''];continue
    for item in items:
        category={'direct_topic':'直接主题','application':'应用相关','neighboring_or_insufficient':'邻近／证据不足','off_topic':'明确错配'}[item['evidence_review']]
        lines.append(f"- [{label(item['title'])}]({item['url']}) · {item['platform']} · {category}")
    lines.append('')
(out/'links.md').write_text('\n'.join(lines),encoding='utf-8')
b=s['platforms']['bilibili'];m=s['platforms']['icourse163'];total_http=sum(s['transport_counts_including_probe_and_recheck'].values())
attempts=sum(1+len(r.get('previous_attempts',[])) for r in rows)
live_frozen=load(out/'live'/state.get('frozen_file','frozen-scope.json'))
app_hashes={p:h for p,h in live_frozen['source_hashes'].items() if p.startswith('backend')}
case_counts=Counter(r['status'] for r in rows)
probe=load(out/'live/epoch-1-checkpoint.json')
first_link=[r['first_link_seconds'] for r in rows if r.get('first_link_seconds') is not None]
restrictions=json.dumps(s['restrictions'],ensure_ascii=False)
suite=ElementTree.parse(out/'epoch4-backend-tests.xml').getroot().find('testsuite')
backend_tests=len(suite.findall('testcase')); subtests=int(suite.attrib['tests'])-backend_tests
before_repair=load(out/'pre-repair-40/summary.json')
report=f'''# 40 主题真实联网验收与当前边界

日期：2026-10-14。此前只跑少量样本、又把接口接入和目录能力混作完整验收，不能证明 B站、MOOC 已覆盖。本轮逐主题执行真实搜索，保存空结果、故障、修复前结果和复验；没有预置预期 URL。

## 当前结论

- 原定 **40 个主题全部有实际执行结果**，共 {attempts} 次任务（含 D02、D18、H14、H15 的有界复验）。38 个正常主题中 {s['positive_topic_hits']} 个返回链接；两个不存在主题作为负例单列，不加入正例命中分母。首次40题原始结果为 {before_repair['positive_topic_hits']}/38，已独立保存在 [修复前40题快照](pre-repair-40/summary.json)。
- B站定向查询 {b['queries_executed']}／40 个主题，平台分栏有链接的主题 {b['cases_with_links']} 个。MOOC 定向查询 {m['queries_executed']}／40 个主题，平台分栏有链接的主题 {m['cases_with_links']} 个。不能仅看默认前3项就称 MOOC 零返回。
- 默认视图共 {s['default_link_count']} 条；合并默认／平台分栏后共 {s['visible_unique_case_resource_pairs']} 个“主题＋资源记录”观察。不是独立课程数、教学质量或完整覆盖率。
- 目录资源数：{sum(r['catalog_resources'] for r in rows)}。目录为可选补充；本轮没有测试播放，也没有登录、购买或扩大自动采集权限。B站／MOOC 的页面、学期、免费与播放状态仍按实际证据标 unknown。
- 任务终态：{dict(case_counts)}。partial 包含页面采集政策、来源故障等限制，不能改写成全部平台完整成功。

## 平台覆盖口径

以下仅统计每主题最后一次结果；D02／D18／H14／H15 原结果保留，不重复算成独立主题。

| 平台 | 定向查询主题 | 该查询下SearXNG端点HTTP | 原始条目观察 | 选入候选观察 | 默认视图 | 平台分栏 | 有平台链接的主题 |
|---|---:|---:|---:|---:|---:|---:|---:|
| B站 | {b['queries_executed']} | {b['endpoint_http']} | {b['raw_candidates']} | {b['selected_observations']} | {b['default_displayed']} | {b['displayed']} | {b['cases_with_links']} |
| MOOC | {m['queries_executed']} | {m['endpoint_http']} | {m['raw_candidates']} | {m['selected_observations']} | {m['default_displayed']} | {m['displayed']} | {m['cases_with_links']} |

默认视图与平台分栏有重合，不能相加。平台链接也可能来自通用搜索；定向查询原始条目有域不符、内容不符和重复，不能当相关课程数。D10 的三条 MOOC 摘要明确列出正则表达式教学内容，属相关课程线索；课程页面和开课版本未核验。详情见 [40行覆盖矩阵](coverage.md)、[结构化逐项指标](coverage-detailed.json)、[真实链接及证据分类](links.md)。

## 修复与冻结阶段

1. 第一阶段 D01–D04 真实探测保留在 live 根目录。D01／D03 从旧轮空结果变为返回链接，同时伴随 DDG 上游恢复返回结果，不能只归功于代码。
2. D02 首次为0，但实际搜索包含 HTML 表单校验／验证视频。修复中文跨词二元组过严的问题，要求同一观察覆盖完整核心概念，允许长度至少2字的完整词段；缺少并列项、跨观察拼词和仅先修仍拒绝。HTML5 对无版本 HTML 的归属及表单“校验／验证”映射有明确范围，未加入结果 URL 白名单。真实复验返回3条，首条3.432秒。
3. epoch 2 起冻结上述应用版本；epoch 3 仅修复 Windows 原子替换遇临时读占用的本地重试。D18 原终态和最新临时断点与 SQLite 独立核对后恢复，计数未回退、限制未清除；恢复证据见 [本地保存故障记录](live/local-save-failure-20261014/recovery.json)。
4. 按最后结果，源码阶段分布为 {s['source_epochs']}。不同阶段不冒充同一版本实网；epoch 2 与3应用代码一致。H01–H04已被旧轮修复使用。H05–H20首先按冻结版本执行，随后H14／H15因明确错配被消费为开发样本，其复验不能继续计作未见留出。
5. epoch 4修复：搜索摘要中的明确“相关视频／相关推荐”尾部仅在判定副本中排除，原证据保留；明确Pose Database＋Motion Matching／Normalization set而无关系模型证据的观察，不再支持数据库范式主题。未按URL、案例ID特判，也未整体禁止UE5。两个修复主题单独复验，沿用原预算、缓存和限制账本。最终代码对首次40题保存证据回放，恰好移除两条已确认错配，其余原展示资源保留；回放不算新增实网样本，见 [离线40题对照](offline-epoch4-final-40/summary.json)。
6. 实网复验的H14唯一展示由6条变为3条，除旧错配移除、加入新Collector视频外，也未再展示旧3条相关YouTube结果。离线回放保留了这3条，说明不能把新实网集合变化全归于过滤规则；搜索召回与候选选取会变化。H15唯一展示仍6条。两个新增条目标题支持主题但摘要为空，教学细节未知。

版本号解析修复 Python3.13 贪婪切分与数字紧邻汉字的边界，保留 D3.js 名称约束；中文“和弦／与门”不再拆成单字；否定先修的局部范围修正。诊断保留有界标题摘要、过滤原因和未知错误指纹，认证、Cookie、URL查询等敏感模式脱敏。

表单术语依据：[MDN表单数据校验](https://developer.mozilla.org/zh-CN/docs/Learn_web_development/Extensions/Forms/Form_validation)、[MDN表单验证](https://developer.mozilla.org/zh-CN/docs/Learn_web_development/Core/Structuring_content/HTML_forms)。其他既有术语规则依据保留在 [上一轮参考记录](../link-trial-20261014/references.md)。

## 实际请求、预算与限制

本轮包括探测和复验的应用可见委派：{s['transport_counts_including_probe_and_recheck']}，合计 {total_http}。搜索计数是应用到自托管 SearXNG 端点，不是 SearXNG 内部物理上游请求数；后者 unknown。官方目标请求已计入 target，不能再把 job.progress.search_requests 加一遍。

每例发现预算12、详情槽2、90秒；搜索和页面重试0；并发1、每次可见委派至少2秒；每4主题间隔60秒。全 campaign 硬上限：search480／target240／DoH480。无JS补全、无模型调用，新SQLite隔离并跨阶段保留缓存，复验缓存逐项记录。

保留现有 Bing／DuckDuckGo videos 组；没有重启或更换 SearXNG 去绕过限制，也没有增开此前受限来源。明确拒绝／验证码持久锁定；限流保存 UTC 到期，重启恢复剩余时间，到期只在正常排定、有预算请求中尝试。unknown／timeout 不伪标429。最终限制账本：`{restrictions}`。空账本不证明所有平台不限制，只表示本轮这些请求没有登记此类明确限制；详情采集政策仍生效。

实际案例终态耗时中位 {s['median_case_seconds']:.3f} 秒，最长 {s['max_case_seconds']:.3f} 秒。分语言、开发／留出及负例统计见 [summary.json](summary.json)。H06请求成功但完整主题证据不足，原始0结果保留，见 [空结果诊断](empty-result-analysis.md)。未使用独立人工金标准，未报告 P@3、nDCG 或总体泛化准确率。

## 搜索证据复核

助手逐项检查保存标题／摘要，分类为：{dict(review_counts)}。这是搜索线索证据审查，不是独立人工金标准，不证明页面内容或教学质量。

明确错配与邻近／不足条目如下；全部原始结果仍保存，没有按URL偷偷删改评测：
'''
for e in review['exceptions']:report+=f"\n- {e['case_id']} / `{e['resource_id']}`：{e['reason']}\n"
report+='\n已修复且原始失败保留的条目：\n'
for e in review.get('resolved_exceptions',[]):report+=f"\n- {e['case_id']} / `{e['resource_id']}`：{e['reason']} 原结果保留；最终复验与离线回放均未再展示该错配。\n"
report+='''
宣传摘要、频道套话等质量限制另见 [review-decisions.json](review-decisions.json)。因此“有链接”的原始命中数不能直接当准确率；这些不足仍属于当前推荐质量边界。

## 本机验证与交付

- 应用最终版本完整后端套件__BACKEND_TESTS__项及__SUBTESTS__项子测试通过，1条警告；应用及runner定向回归58项通过。之后runner仅补充新DNS记录的顶层完成时间，9项runner检查通过；历史DNS完成时间从原有trace.finished_at读取，未补写历史。此前Windows恢复8项及中间测试记录保留，没有重复累加成实跑总数。
- 旧8例、100个已保存候选离线回归，已知串题移除、合法术语样本保留；这不是新增联网样本。新旧阶段的每条结果都有原始证据文件。
- 原有本地队列负载/取消恢复测试复用：并发请求只作用于本地fixture，外部HTTP为0，队列上限20；不重复向第三方压测，不声称生产容量。见 [既有负载证据](../link-trial-20261014/local-load-v1)。
- 主应用已重启至epoch 4应用源码，仍仅 localhost:8000、单worker。健康和真实页面检查见 [main-health.json](main-health.json)、[可见卡片](main-visible-cards.json)、[页面截图](main-epoch4-ui.png)、[浏览器日志](main-epoch4-ui-checks.json)；浏览器控制台无警告／错误。
- 主页面检查使用既有“二分查找”任务；本轮40主题通过实际API路由＋真实外部传输执行，驱动是进程内ASGI，不冒称40次浏览器端到端提交。

所有历史 v1/v2/v3 报告和失败保留。哈希、状态和计数机器核对见 final-validation.json；主应用滚动日志不纳入静态哈希。当前交付为本机试用与有来源链接发现，不等于所有平台目录、播放或生产部署验收。
'''
report=report.replace('__BACKEND_TESTS__',str(backend_tests)).replace('__SUBTESTS__',str(subtests))
(out/'final-report.md').write_text(report,encoding='utf-8')
print(json.dumps({'review_counts':dict(review_counts),'tasks_including_rechecks':attempts,'application_hashes':app_hashes},ensure_ascii=False))
