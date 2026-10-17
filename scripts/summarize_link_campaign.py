"""Read preserved campaign evidence only; never makes network requests."""
import argparse, json, hashlib, statistics
from collections import Counter
from pathlib import Path

def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def summarize(out):
    state=load(out/'live/checkpoint.json');live=out/'live';rows=[];review=[]
    for case in state['cases']:
        row=dict(case)
        path=live/case.get('evidence_file',case['id']+'.json')
        if case['state']!='terminal' or not path.exists():rows.append(row);continue
        record=load(path);result=record['results'];groups=result['groups']
        row['point']=record['case']['request']['knowledge_points'][0]
        row['evidence_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        attempts=result['search_attempts']
        row['platforms']={}
        for platform,domain in [('bilibili','bilibili.com'),('icourse163','icourse163.org')]:
            queries=[a for a in attempts if domain in a['domain_filters']]
            requests=[r for a in queries for r in a.get('provider_requests',[]) if r.get('provider')=='searxng']
            shown=[i for g in groups for i in g.get('platform_items',{}).get(platform,[])]
            row['platforms'][platform]={'queries_executed':len(queries),'endpoint_http':len(requests),
                'query_statuses':dict(Counter(a['status'] for a in queries)),
                'query_error_codes':dict(Counter(a['error_code'] for a in queries if a.get('error_code'))),
                'raw_candidates':sum(r.get('raw_candidate_count',0) for r in requests),
                'selected_observations':sum(a.get('candidate_count',0) for a in queries),
                'topic_signals':sum(r.get('topic_signal_count',0) for r in requests),'displayed':len(shown),
                'default_displayed':sum(i['resource']['platform']==platform for g in groups for i in g['items']),
                'classification':'not_executed' if not queries else 'links_returned' if shown else 'queried_no_eligible_links'}
        unique={i['resource']['resource_id']:i for g in groups for i in [*g['items'],*(i for entries in g.get('platform_items',{}).values() for i in entries)]}
        row['visible_unique']=len(unique);row['catalog_resources']=sum(bool(i['resource'].get('chapters')) for i in unique.values())
        row['source_errors']=record['job'].get('errors',[])
        row['upstream_reasons']=dict(Counter(w.get('reason_code',w.get('code','unknown')) for a in attempts for w in a.get('upstream_warnings',[])))
        row['warning_messages']=record['job'].get('warnings',[])
        for rid,item in unique.items():
            resource=item['resource']
            review.append({'case_id':case['id'],'point':row['point'],'source_epoch':row.get('source_epoch',1),'resource_id':rid,
                'title':resource['title'],'url':resource['url'],'platform':resource['platform'],
                'metadata_evidence_level':resource['metadata_evidence_level'],'fetch_status':resource['fetch_status'],
                'chapters':resource.get('chapters',[]),'match':item['match'],
                'observations':[{k:e.get(k) for k in ('kind','title','snippet','field','text','url','evidence_id')} for e in item['evidence']],
                'manual_relevance':'pending'} )
        rows.append(row)
    terminal=[r for r in rows if r['state']=='terminal'];positive=[r for r in terminal if not r['negative_control']]
    metrics={'terminal_cases':len(terminal),'planned_cases':len(rows),'unique_topics_with_links':sum(r['returned']>0 for r in terminal),
        'positive_topic_hits':sum(r['returned']>0 for r in positive),'positive_topics_executed':len(positive),
        'negative_controls':[{'id':r['id'],'returned':r['returned']} for r in terminal if r['negative_control']],
        'default_link_count':sum(r['returned'] for r in terminal),'visible_unique_case_resource_pairs':len(review),
        'transport_counts_including_probe_and_recheck':state['counts'],'restrictions':state['restrictions'],
        'source_epochs':dict(Counter(r.get('source_epoch',1) for r in terminal)),
        'strata':{},'platforms':{},'physical_searx_upstream_requests':'unknown','playback_tests':0}
    for field in ('purpose','language','source_epoch'):
        metrics['strata'][field]={}
        for value in sorted({r.get(field,1) for r in positive},key=str):
            group=[r for r in positive if r.get(field,1)==value]
            metrics['strata'][field][str(value)]={'executed':len(group),'with_links':sum(r['returned']>0 for r in group)}
    for platform in ('bilibili','icourse163'):
        metrics['platforms'][platform]={field:sum(r['platforms'][platform][field] for r in terminal) for field in ('queries_executed','endpoint_http','raw_candidates','selected_observations','displayed','default_displayed')}
        metrics['platforms'][platform]['cases_with_links']=sum(r['platforms'][platform]['displayed']>0 for r in terminal)
    if terminal:metrics['median_case_seconds']=statistics.median(r['completed_seconds'] for r in terminal);metrics['max_case_seconds']=max(r['completed_seconds'] for r in terminal)
    save(out/'coverage-detailed.json',rows);save(out/'summary.json',metrics);save(out/'review-queue.json',review)
    lines=['# 40 主题真实联网覆盖矩阵','','仅汇总原始实际执行；目录可选，未测试播放。最终每主题结果可跨源码 epoch，详见 source_epoch。','','| ID | 知识点 | 版本 | 默认链接 | B站定向查询 / 展示 | MOOC定向查询 / 展示 | 状态 |','|---|---|---:|---:|---:|---:|---|']
    for row in rows:
        if row['state']=='terminal':
            b,m=row['platforms']['bilibili'],row['platforms']['icourse163']
            lines.append(f"| {row['id']} | {row['point']} | {row.get('source_epoch',1)} | {row['returned']} | {b['queries_executed']} / {b['displayed']} | {m['queries_executed']} / {m['displayed']} | {row['status']} |")
        else:lines.append(f"| {row['id']} | — | — | — | — | — | {row['state']} |")
    (out/'coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);summarize(Path(parser.parse_args().output))
