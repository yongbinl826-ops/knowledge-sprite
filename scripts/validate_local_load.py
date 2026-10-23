"""Finite loopback HTTP gates with synthetic data and deterministic upstream mocks.

No active configuration is read. Run against a public source tree, never a user
database. This tests this application's admission/recovery, not vendor capacity.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib
import ipaddress
import json
import math
from pathlib import Path
import socket
import sys
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch
import uuid


THRESHOLDS = {"read_p95_ms": 500, "write_p95_ms": 1000,
              "cancel_ms": 1000, "terminal_seconds": 8, "analysis_concurrency": 2,
              "search_concurrency": 2, "event_stream_capacity": 16}


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


def aggregate(observations):
    groups = {}
    for row in observations:
        groups.setdefault(row["operation"], []).append(row)
    return {key: {"requests": len(rows), "p50_ms": percentile([r["ms"] for r in rows], .5),
                  "p95_ms": percentile([r["ms"] for r in rows], .95),
                  "status_counts": {str(code): sum(r["status"] == code for r in rows)
                                    for code in sorted({r["status"] for r in rows})}}
            for key, rows in groups.items()}


class LoopbackOnly:
    """Block DNS and actual socket connects before any non-loopback transport."""
    def __init__(self):
        self.blocked = 0
        self.stack = []

    @staticmethod
    def allowed(host):
        if host in {None, "localhost", b"localhost"}:
            return True
        try:
            return ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host).is_loopback
        except (ValueError, TypeError):
            return False

    def __enter__(self):
        self.original_dns = socket.getaddrinfo
        self.original_connect = socket.socket.connect
        self.original_connect_ex = socket.socket.connect_ex
        def dns(host, *args, **kwargs):
            if not self.allowed(host):
                self.blocked += 1
                raise PermissionError("local load harness forbids external DNS")
            return self.original_dns(host, *args, **kwargs)
        def connect(sock, address):
            if isinstance(address, tuple) and not self.allowed(address[0]):
                self.blocked += 1
                raise PermissionError("local load harness forbids external connect")
            return self.original_connect(sock, address)
        def connect_ex(sock, address):
            if isinstance(address, tuple) and not self.allowed(address[0]):
                self.blocked += 1
                raise PermissionError("local load harness forbids external connect")
            return self.original_connect_ex(sock, address)
        original_sendto = socket.socket.sendto
        def sendto(sock, data, *args):
            address = args[-1]
            if isinstance(address, tuple) and not self.allowed(address[0]):
                self.blocked += 1
                raise PermissionError("local load harness forbids external datagram")
            return original_sendto(sock, data, *args)
        for target, value in [("socket.getaddrinfo", dns), ("socket.socket.connect", connect),
                              ("socket.socket.connect_ex", connect_ex), ("socket.socket.sendto", sendto)]:
            item = patch(target, value); item.start(); self.stack.append(item)
        return self

    def __exit__(self, *_):
        for item in reversed(self.stack): item.stop()


def synthetic_document():
    return {"scope": "本地合成负载验收数据处理工具", "technical_plan": "Python 本地脚本",
        "assumptions": ["所有输入仅为合成测试数据"],
        "knowledge_points": [{"name": title, "description": explanation, "technology": "Python"}
            for title, explanation in [
                ("Python 列表索引", "理解列表的位置索引，用于读取合成数据中的指定元素。"),
                ("Python 字典映射", "理解键到值的映射，用于查询合成记录的对应内容。"),
            ]]}


class MockWorld:
    def __init__(self, httpx):
        self.httpx = httpx
        self.analysis_gate = asyncio.Event(); self.analysis_gate.set()
        self.search_gate = asyncio.Event(); self.search_gate.set()
        self.analysis_entered = asyncio.Event(); self.search_entered = asyncio.Event()
        self.analysis_mode = "ok"; self.search_mode = "ok"
        self.active = {"analysis": 0, "search": 0}
        self.maximum = {"analysis": 0, "search": 0}
        self.calls = []; self.expansions = 0; self.reranks = 0

    async def respond(self, request):
        assert request.url.host in {"mock-llm.invalid", "mock-search.invalid"}, "unknown upstream mock target"
        kind = "analysis" if request.url.host == "mock-llm.invalid" else "search"
        self.calls.append({"kind": kind, "path": request.url.path, "started": time.monotonic()})
        self.active[kind] += 1; self.maximum[kind] = max(self.maximum[kind], self.active[kind])
        try:
            if kind == "analysis":
                self.analysis_entered.set(); await self.analysis_gate.wait()
                mode = self.analysis_mode
            else:
                self.search_entered.set(); await self.search_gate.wait()
                mode = self.search_mode
            if mode == "fail_once":
                if kind == "analysis": self.analysis_mode = "ok"
                else: self.search_mode = "ok"
                return self.httpx.Response(503, json={"error": "synthetic upstream unavailable"})
            if mode == "hang_once":
                if kind == "analysis": self.analysis_mode = "ok"
                else: self.search_mode = "ok"
                await asyncio.Event().wait()
            await asyncio.sleep(.04)
            if kind == "analysis":
                return self.httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                    "message": {"content": json.dumps(synthetic_document(), ensure_ascii=False)}}]})
            q = request.url.params.get("q", "")
            title = q.split(" ", 1)[-1].split(" 视频教程")[0]
            return self.httpx.Response(200, json={"results": [{"title": title + " 合成教学样本",
                "url": "https://www.bilibili.com/video/BV1TEST00001/",
                "content": "本条为本地负载测试合成元数据，不是真实课程质量证据"}], "unresponsive_engines": []})
        finally:
            self.active[kind] -= 1

    async def expand(self, *_): self.expansions += 1; return []
    async def rerank(self, *_): self.reranks += 1; return []


class SyntheticFetcher:
    async def enrich(self, _candidate, **_):
        await asyncio.sleep(.01)
        return {"fetch_status": "search_only_policy", "metadata_evidence_level": "search", "evidence": []}


class Recorder:
    def __init__(self): self.rows = []
    def stream(self, status, elapsed):
        # A streaming response is measured until headers/first event, not until
        # the deliberately held connection closes.
        self.rows.append({"operation": "SSE_open", "method": "GET", "status": status,
                          "ms": round(elapsed * 1000, 3), "code": None})
    async def request(self, client, method, path, operation, **kwargs):
        assert path.startswith("/") and not path.startswith("//")
        start = time.perf_counter()
        response = await client.request(method, path, **kwargs)
        self.rows.append({"operation": operation, "method": method, "status": response.status_code,
                          "ms": round((time.perf_counter()-start)*1000, 3),
                          "retry_after": response.headers.get("Retry-After"),
                          "code": (response.json().get("code") if response.headers.get("content-type", "").startswith("application/json") else None)})
        return response


@asynccontextmanager
async def local_server(env, database, changes=None, world=None):
    import httpx
    import uvicorn
    world = world or MockWorld(httpx)
    env.worlds.append(world)
    config = dict(database_path=str(database), searxng_url="https://mock-search.invalid",
        llm_provider="openai_compatible", llm_base_url="https://mock-llm.invalid/v1",
        llm_api_key="synthetic-not-a-secret", llm_model="synthetic-load-fixture",
        parallel_platform_search=True, bilibili_search_rounds=1, mooc_search_rounds=1,
        max_search_requests=4, max_detail_pages=1, max_knowledge_points=2,
        global_concurrency=2, deadline_seconds=2, project_deadline_seconds=20,
        project_max_search_requests=20, project_max_detail_pages=10,
        search_timeout_seconds=1, search_max_retries=0, search_min_interval_seconds=0,
        search_cache_ttl=0, page_cache_ttl=0, max_pending_jobs=4,
        max_pending_analyses=4, max_pending_project_searches=4,
        api_write_limit_per_minute=200, submission_limit_per_minute=100,
        project_analysis_timeout_seconds=1, project_analysis_total_timeout_seconds=1,
        teaching_match_enabled=False, shared_course_library_enabled=False, mooc_refresh_enabled=False,
        fetch_enabled=False, js_render_enabled=False, official_sitemap_fallback=False, public_catalog_fallback=False)
    config.update(changes or {})
    settings = env.Settings(**config).validate()
    async with httpx.AsyncClient(transport=httpx.MockTransport(world.respond), trust_env=False) as upstream:
        analyzer = env.ProjectAnalyzer(settings, upstream)
        provider = env.SearXNGProvider(settings, upstream)
        app = env.create_app(settings, provider=provider, fetcher=SyntheticFetcher(), llm=world, analyzer=analyzer)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0)); sock.listen(64); sock.setblocking(False)
        port = sock.getsockname()[1]; assert port not in {8001, 8002}
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
            log_config=None, log_level="critical", access_log=False, lifespan="on", timeout_graceful_shutdown=1))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            end = time.monotonic()+5
            while not server.started:
                if task.done(): raise RuntimeError("isolated server startup failed")
                if time.monotonic()>end: raise TimeoutError("isolated server startup deadline")
                await asyncio.sleep(.01)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                timeout=3, limits=httpx.Limits(max_connections=40,max_keepalive_connections=30)) as client:
                yield SimpleNamespace(client=client,app=app,world=world,settings=settings,port=port)
        finally:
            server.should_exit=True
            try: await asyncio.wait_for(task,5)
            except TimeoutError:
                task.cancel(); await asyncio.gather(task,return_exceptions=True)
            sock.close()


async def until(read, predicate, timeout=8):
    end=time.monotonic()+timeout
    while True:
        item=await read()
        if predicate(item): return item
        if time.monotonic()>=end: raise TimeoutError("local terminal observation deadline")
        await asyncio.sleep(.025)


class Suite:
    def __init__(self, env, out): self.env=env; self.out=out; self.record=Recorder(); self.checks=[]; self.details={}
    def check(self, name, condition, **data): self.checks.append({"name":name,"pass":bool(condition),**data})
    async def request(self, s, method, path, op="read", **kw):return await self.record.request(s.client,method,path,op,**kw)
    async def project(self,s,name):
        r=await self.request(s,"POST","/api/projects","project_create",json={"name":name,"requirements":"使用Python读取合成数据并查询内容", "preferred_platforms":["bilibili"]})
        assert r.status_code==201; return r.json()["project_id"]
    async def view(self,s,pid):return (await self.request(s,"GET",f"/api/projects/{pid}")).json()
    async def analyze(self,s,pid):
        r=await self.request(s,"POST",f"/api/projects/{pid}/analyze","analysis_submit",json={"expected_version":0})
        assert r.status_code==202
        return await until(lambda:self.view(s,pid),lambda x:x["version"]["status"]!="analyzing")
    async def confirm(self,s,pid):
        r=await self.request(s,"POST",f"/api/projects/{pid}/confirm","confirm",json={"version":1});assert r.status_code==200
    async def search(self,s,pid):return await self.request(s,"POST",f"/api/projects/{pid}/search","project_search_submit",json={"version":1})
    async def job(self,s,context):
        return await self.request(s,"POST","/api/search-jobs","job_submit",json={"knowledge_points":["Python 列表索引"],"preferred_platforms":["bilibili"],"project_context":context})
    async def jobview(self,s,jid):return (await self.request(s,"GET",f"/api/search-jobs/{jid}")).json()

    async def normal(self):
        async with local_server(self.env,self.out/'normal.sqlite3') as s:
            started=time.monotonic();pids=await asyncio.gather(*(self.project(s,f"合成并发{i}") for i in range(4)))
            views=await asyncio.gather(*(self.analyze(s,p) for p in pids))
            self.check('normal_analysis_all_accepted',all(v['version']['status']=='analyzed' for v in views))
            self.check('analysis_execution_concurrency_two',s.world.maximum['analysis']==2,observed=s.world.maximum['analysis'])
            await asyncio.gather(*(self.confirm(s,p) for p in pids))
            submitted=await asyncio.gather(*(self.search(s,p) for p in pids));self.check('normal_search_all_accepted',all(r.status_code==202 for r in submitted))
            results=await asyncio.gather(*(until(lambda p=p:self.view(s,p),lambda x:x['version']['status']!='running') for p in pids))
            health=[await self.request(s,'GET','/health','health') for _ in range(12)]
            self.check('normal_projects_terminal_without_failure',all(x['version']['status'] in {'completed','no_results','partial'} for x in results))
            self.check('normal_health_responsive',all(r.status_code==200 for r in health))
            jobs=[s.app.state.store.get_job(b['job_id']) for x in results for b in x['version']['batches']]
            self.check('all_search_budgets_respected',all(j['progress']['search_requests']<=j['budgets']['max_search_requests'] for j in jobs))
            self.check('source_concurrency_within_configured_slots',s.world.maximum['search']<=2,observed=s.world.maximum['search'])
            self.details['normal']={'projects':4,'elapsed_seconds':time.monotonic()-started,'completed_projects_per_second':4/(time.monotonic()-started),'mock_calls':len(s.world.calls),'maxima':s.world.maximum}

    async def rate(self):
        world=MockWorld(self.env.httpx);world.search_gate.clear()
        async with local_server(self.env,self.out/'rate.sqlite3',{'api_write_limit_per_minute':3},world) as s:
            first=await self.job(s,'rate-held');jid=first.json()['job_id'];await asyncio.wait_for(world.search_entered.wait(),2)
            await self.project(s,'rate1');await self.project(s,'rate2')
            rejected=await self.request(s,'POST','/api/projects','rate_rejection',json={'name':'reject','requirements':'合成'})
            self.check('write_limit_429_retry_after',rejected.status_code==429 and rejected.json().get('code')=='api_write_rate_limited' and 1<=int(rejected.headers.get('Retry-After','0'))<=60)
            start=time.perf_counter();cancel=await self.request(s,'POST',f'/api/search-jobs/{jid}/cancel','cancel')
            self.check('cancel_bypasses_full_write_limiter',cancel.status_code==200 and cancel.json()['cancelled'] and (time.perf_counter()-start)*1000<1000)
            self.check('read_survives_write_limit',(await self.request(s,'GET','/health','health')).status_code==200)

    async def queue(self):
        world=MockWorld(self.env.httpx);world.search_gate.clear()
        async with local_server(self.env,self.out/'queue.sqlite3',{'max_pending_jobs':2},world) as s:
            first=await self.job(s,'queue-active');jid=first.json()['job_id'];await asyncio.wait_for(world.search_entered.wait(),2)
            waiting=[await self.job(s,f'queue-wait-{i}') for i in range(2)]
            count=len(s.app.state.store.job_counts())
            rejected=await self.job(s,'queue-reject')
            self.check('job_queue_full_429',all(r.status_code==202 for r in waiting) and rejected.status_code==429 and rejected.json().get('code')=='queue_full' and int(rejected.headers.get('Retry-After','0'))==5)
            cancelled=await self.request(s,'POST',f"/api/search-jobs/{waiting[0].json()['job_id']}/cancel",'cancel')
            admitted=await self.job(s,'queue-after-cancel')
            self.check('queued_cancel_releases_admission',cancelled.json()['cancelled'] and admitted.status_code==202)
            await self.request(s,'POST',f'/api/search-jobs/{jid}/cancel','cancel');world.search_gate.set()
            settled=await until(lambda:self.jobview(s,admitted.json()['job_id']),lambda j:j['status'] not in {'queued','running'})
            self.check('worker_recovers_after_active_cancel',settled['status'] in {'completed','partial'})

    async def analysis_admission(self):
        world=MockWorld(self.env.httpx);world.analysis_gate.clear()
        async with local_server(self.env,self.out/'analysis-queue.sqlite3',{'max_pending_analyses':3},world) as s:
            pids=[await self.project(s,f'analysis-cap-{i}') for i in range(4)]
            accepted=[await self.request(s,'POST',f'/api/projects/{p}/analyze','analysis_submit',json={'expected_version':0}) for p in pids[:3]]
            reject=await self.request(s,'POST',f'/api/projects/{pids[3]}/analyze','analysis_submit',json={'expected_version':0})
            duplicate=await self.request(s,'POST',f'/api/projects/{pids[0]}/analyze','analysis_submit',json={'expected_version':1})
            self.check('analysis_pending_cap_and_retry_after',all(r.status_code==202 for r in accepted) and reject.status_code==429 and reject.json().get('code')=='analysis_queue_full' and reject.headers.get('Retry-After')=='5')
            self.check('analysis_duplicate_not_new_version',duplicate.status_code==202 and duplicate.json()['current_version']==1)
            world.analysis_gate.set()
            await asyncio.gather(*(until(lambda p=p:self.view(s,p),lambda v:v['version']['status']!='analyzing') for p in pids[:3]))
            last=await self.analyze(s,pids[3]);self.check('analysis_admission_recovers',last['version']['status']=='analyzed' and world.maximum['analysis']<=2)

    async def project_admission(self):
        world=MockWorld(self.env.httpx)
        async with local_server(self.env,self.out/'project-queue.sqlite3',{'max_pending_project_searches':1},world) as s:
            pids=[await self.project(s,f'project-cap-{i}') for i in range(2)]
            for p in pids:await self.analyze(s,p);await self.confirm(s,p)
            world.search_gate.clear();await self.search(s,pids[0]);await asyncio.wait_for(world.search_entered.wait(),2)
            before=sum(s.app.state.store.job_counts().values());r=await self.search(s,pids[1])
            self.check('project_pending_cap_no_hidden_job',r.status_code==429 and r.json().get('code')=='project_search_queue_full' and r.headers.get('Retry-After')=='5' and sum(s.app.state.store.job_counts().values())==before)
            await self.request(s,'POST',f'/api/projects/{pids[0]}/cancel','cancel',json={'version':1})
            await until(lambda:self.view(s,pids[0]),lambda v:v['version']['status']=='cancelled')
            # Cancellation is visible before the scheduler's 0.3s polling task
            # has returned. Wait for that task, then make one explicit retry.
            start=time.monotonic()
            while any(not task.done() for task in s.app.state.projects.tasks.values()):
                if time.monotonic()-start>1:raise TimeoutError('project admission release deadline')
                await asyncio.sleep(.025)
            self.check('project_cancel_scheduler_release_bounded',time.monotonic()-start<1)
            world.search_gate.set();r=await self.search(s,pids[1])
            self.check('project_cancel_releases_admission',r.status_code==202)
            end=await until(lambda:self.view(s,pids[1]),lambda v:v['version']['status']!='running')
            self.check('project_scheduler_recovers',end['version']['status'] in {'completed','partial','no_results'})

    async def upstream(self):
        async with local_server(self.env,self.out/'failure.sqlite3',{'deadline_seconds':1}) as s:
            for mode in ['fail_once','hang_once']:
                p=await self.project(s,'analysis-'+mode);s.world.analysis_mode=mode
                start=time.monotonic();v=await self.analyze(s,p)
                self.check('analysis_'+mode+'_bounded_failure',v['version']['status']=='analysis_failed' and v['version']['error']['code'] in {'unavailable','timeout'} and time.monotonic()-start<3)
                healthy=await self.project(s,'analysis-recovery-'+mode);v=await self.analyze(s,healthy)
                self.check('analysis_'+mode+'_recovery',v['version']['status']=='analyzed')
                s.world.search_mode=mode;r=await self.job(s,'source-'+mode)
                v=await until(lambda:self.jobview(s,r.json()['job_id']),lambda j:j['status'] not in {'queued','running'})
                self.check('search_'+mode+'_bounded_failure',v['status']=='partial' and v['progress']['search_requests']==2)
                r=await self.job(s,'source-recovery-'+mode)
                v=await until(lambda:self.jobview(s,r.json()['job_id']),lambda j:j['status'] not in {'queued','running'})
                self.check('search_'+mode+'_worker_recovery',v['status'] in {'completed','partial'})

    async def restart(self):
        database=self.out/'restart.sqlite3';world=MockWorld(self.env.httpx)
        async with local_server(self.env,database,{'max_knowledge_points':1,'max_search_requests':2},world) as s:
            pid=await self.project(s,'restart-project');await self.analyze(s,pid);await self.confirm(s,pid)
            world.search_gate.clear();await self.search(s,pid);await asyncio.wait_for(world.search_entered.wait(),2)
            version=(await self.view(s,pid))['version'];jid=version['batches'][0]['job_id']
            before=await self.jobview(s,jid);project_budget=deepcopy(version['budgets'])
            world.analysis_gate.clear();analysis_pid=await self.project(s,'restart-analysis')
            await self.request(s,'POST',f'/api/projects/{analysis_pid}/analyze','analysis_submit',json={'expected_version':0})
            await asyncio.wait_for(world.analysis_entered.wait(),2)
        fresh=MockWorld(self.env.httpx)
        async with local_server(self.env,database,{'max_knowledge_points':1,'max_search_requests':2},fresh) as s:
            await asyncio.sleep(.5)
            after=await self.jobview(s,jid);v=await self.view(s,pid);analysis=await self.view(s,analysis_pid)
            self.check('restart_old_job_interrupted_no_budget_reset',after['status']=='interrupted' and after['progress']==before['progress'] and after['budgets']==before['budgets'])
            self.check('restart_analysis_interrupted_no_auto_model',analysis['version']['status']=='analysis_failed' and analysis['version']['error']['code']=='interrupted' and not any(x['kind']=='analysis' for x in fresh.calls))
            self.check('restart_no_implicit_new_source_work',not fresh.calls,observed_mock_calls=len(fresh.calls),project_status=v['version']['status'])
            self.check('restart_project_budget_not_enlarged',v['version']['budgets']==project_budget)
            self.details['restart']={'before_job':before,'after_job':after,'recovered_project_version':v['version'],'new_mock_calls':fresh.calls}

    async def streams(self):
        world=MockWorld(self.env.httpx);world.search_gate.clear()
        async with local_server(self.env,self.out/'streams.sqlite3',world=world) as s:
            r=await self.job(s,'streams');jid=r.json()['job_id'];await asyncio.wait_for(world.search_entered.wait(),2)
            opened=[];statuses=[]
            try:
                for _ in range(20):
                    start=time.perf_counter()
                    ctx=s.client.stream('GET',f'/api/search-jobs/{jid}/events');response=await ctx.__aenter__();statuses.append(response.status_code)
                    if response.status_code==200:
                        lines=response.aiter_lines()
                        await anext(lines);opened.append((ctx,response,lines))
                    else:
                        self.check('SSE_rejection_retry_after',response.status_code==429 and response.headers.get('Retry-After')=='2');await ctx.__aexit__(None,None,None)
                    self.record.stream(response.status_code,time.perf_counter()-start)
                self.check('SSE_global_admission_bound',statuses==[200]*16+[429]*4,observed_statuses=statuses,profile_declares_cap=hasattr(s.settings,'max_event_streams'))
                health=await asyncio.gather(*(self.request(s,'GET','/health','health_under_streams') for _ in range(12)))
                self.check('SSE_health_and_budget_unchanged',all(r.status_code==200 for r in health) and (await self.jobview(s,jid))['progress']['search_requests']==2)
                for ctx,response,lines in opened[:4]:await ctx.__aexit__(None,None,None)
                opened=opened[4:];await asyncio.sleep(.05)
                start=time.perf_counter()
                async with s.client.stream('GET',f'/api/search-jobs/{jid}/events') as response:
                    self.check('SSE_disconnect_releases_slot',response.status_code==200)
                    self.record.stream(response.status_code,time.perf_counter()-start)
            finally:
                for ctx,response,lines in opened:await ctx.__aexit__(None,None,None)
            await self.request(s,'POST',f'/api/search-jobs/{jid}/cancel','cancel')
            self.details['SSE']={'offered_connections':20,'statuses':statuses,'capacity_target':16,'new_source_requests_from_subscriptions':0}

    async def single_owner(self):
        world=MockWorld(self.env.httpx);world.search_gate.clear();database=self.out/'owner.sqlite3'
        async with local_server(self.env,database,world=world) as s:
            r=await self.job(s,'owner-held');jid=r.json()['job_id'];await asyncio.wait_for(world.search_entered.wait(),2)
            async with self.env.httpx.AsyncClient(transport=self.env.httpx.MockTransport(world.respond),trust_env=False) as upstream:
                other=self.env.create_app(s.settings,provider=self.env.SearXNGProvider(s.settings,upstream),fetcher=SyntheticFetcher(),llm=world,analyzer=self.env.ProjectAnalyzer(s.settings,upstream))
                rejected=False
                try:
                    async with other.router.lifespan_context(other):pass
                except (RuntimeError,OSError):rejected=True
                first=await self.jobview(s,jid)
                self.check('second_instance_rejected_before_recovering_active_DB',rejected and first['status']=='running',second_rejected=rejected,first_job_status=first['status'])
            await self.request(s,'POST',f'/api/search-jobs/{jid}/cancel','cancel')


def load_environment(source):
    sys.path.insert(0,str(source));sys.dont_write_bytecode=True
    from backend.app.config import Settings
    # main has a convenience global app. Do not let that import inspect any env.
    with patch.object(Settings,'from_env',classmethod(lambda cls:Settings())):
        main=importlib.import_module('backend.app.main')
    import httpx
    from backend.app.project_analysis import ProjectAnalyzer
    from backend.app.providers import SearXNGProvider
    return SimpleNamespace(Settings=Settings,create_app=main.create_app,ProjectAnalyzer=ProjectAnalyzer,SearXNGProvider=SearXNGProvider,httpx=httpx,worlds=[])


async def run_suite(source, output, scenarios=None):
    source=Path(source).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    mapping=lambda:{p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'backend/app').rglob('*.py')}
    before=mapping();assert before,'source root must contain public backend/app Python files'
    plan={'source':str(source),'source_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
          'thresholds':THRESHOLDS,'purpose':'single-process finite local admission/recovery; not supplier throughput',
          'synthetic_database':str(output),'source_and_model_real_HTTP':0,'nonloopback_transport':'hard denied before DNS/connect',
          'configuration':'explicit Settings only; active .env/settings.yml never read or hashed'}
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    started=time.monotonic()
    with LoopbackOnly() as guard:
        env=load_environment(source);suite=Suite(env,output)
        scenario_metrics=[]
        chosen=scenarios or ['normal','rate','queue','analysis_admission','project_admission','upstream','restart','streams','single_owner']
        for name in chosen:
            scenario_start=time.monotonic();check_start=len(suite.checks)
            try: await getattr(suite,name)()
            except Exception as exc:
                suite.check(name+'_harness_exception',False,error_type=type(exc).__name__,
                    frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                            for f in traceback.extract_tb(exc.__traceback__)[-5:]])
            scenario_metrics.append({'scenario':name,'seconds':time.monotonic()-scenario_start,
                                     'checks':len(suite.checks)-check_start,
                                     'passed':all(c['pass'] for c in suite.checks[check_start:])})
        after=mapping()
        reads=[r['ms'] for r in suite.record.rows if r['method']=='GET']
        writes=[r['ms'] for r in suite.record.rows if r['method']=='POST' and r['operation']!='cancel']
        suite.check('source_tree_unchanged',before==after)
        suite.check('no_accidental_external_attempts',guard.blocked==0,blocked=guard.blocked)
        suite.check('finite_read_latency',not reads or percentile(reads,.95)<=THRESHOLDS['read_p95_ms'],p95_ms=percentile(reads,.95))
        suite.check('finite_write_latency',not writes or percentile(writes,.95)<=THRESHOLDS['write_p95_ms'],p95_ms=percentile(writes,.95))
    report={'schema':1,'at':datetime.now(timezone.utc).isoformat(),'scope':plan,'passed':all(c['pass'] for c in suite.checks),
        'checks':suite.checks,'observed_elapsed_seconds':time.monotonic()-started,
        'real_loopback_HTTP_requests':len(suite.record.rows),'operation_metrics':aggregate(suite.record.rows),
        'response_summary':{'server_errors':sum(r['status']>=500 for r in suite.record.rows),
                            'admission_rejections_429':sum(r['status']==429 for r in suite.record.rows),
                            'other_4xx':sum(400<=r['status']<500 and r['status']!=429 for r in suite.record.rows)},
        'scenario_metrics':scenario_metrics,
        'mock_transport_requests':{'analysis':sum(sum(c['kind']=='analysis' for c in w.calls) for w in env.worlds),
                                   'search':sum(sum(c['kind']=='search' for c in w.calls) for w in env.worlds)},
        'HTTP_requests_per_second':len(suite.record.rows)/(time.monotonic()-started),'details':suite.details,
        'source_before':before,'source_after':after,
        'limitations':['Synthetic small responses and deterministic 40ms upstream latency; no vendor or public internet capacity proved.',
                       'Single process only. API limiter cooldown expiry is not wall-clock load-tested for a full minute.',
                       'Analysis has bounded timeout but no analysis-specific cancellation API; search cancellation is tested.',
                       'Restart test uses graceful owned server stop/restart, including pending project batches; no unrelated process is signalled.']}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'HTTP-observations.json').write_text(json.dumps(suite.record.rows,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New C-only synthetic output directory; must not exist')
    parser.add_argument('--scenarios',nargs='*',choices=['normal','rate','queue','analysis_admission','project_admission','upstream','restart','streams','single_owner'])
    args=parser.parse_args()
    if args.output.resolve().drive.upper()!='C:':parser.error('Use a fresh C-only synthetic output directory')
    report=asyncio.run(run_suite(args.source_root,args.output,args.scenarios))
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'failed':[c['name'] for c in report['checks'] if not c['pass']],
        'loopback_HTTP':report['real_loopback_HTTP_requests'],'external_HTTP':0,'report':str(args.output/'report.json')}))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
