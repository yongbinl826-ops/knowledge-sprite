"""Owned OS-process kill/restart acceptance against loopback fixtures only.

This validates observed local lifecycle semantics, not external exactly-once delivery.
Never points at the normal app, its database, or a real search provider.
"""
from __future__ import annotations

import argparse
import ctypes
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE = "scripts.isolated_process_fixture"
TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def process_inventory():
    script = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $ErrorActionPreference='Stop'; $p=@(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine); $n=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess); @{processes=$p;listeners=$n} | ConvertTo-Json -Depth 5 -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, check=True, encoding="utf-8", errors="replace",
                            creationflags=HIDDEN, timeout=15)
    return json.loads(result.stdout)


def descendants(processes, roots):
    result = set(roots)
    while True:
        larger = result | {p["ProcessId"] for p in processes if p["ParentProcessId"] in result}
        if larger == result:
            return result
        result = larger


def production_fingerprint(inventory):
    listeners = sorted((n for n in inventory['listeners'] if n['LocalPort'] == 8000),
                       key=lambda n:(n['LocalAddress'], n['OwningProcess']))
    protected = descendants(inventory['processes'], {65024} | {n['OwningProcess'] for n in listeners})
    return {'listeners': listeners,
            'processes': sorted((p for p in inventory['processes'] if p['ProcessId'] in protected),
                                key=lambda p:p['ProcessId'])}


def command_arguments(command):
    import ctypes.wintypes
    count = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.wintypes.LPWSTR)
    pointer = parse(command, ctypes.byref(count))
    if not pointer:
        raise RuntimeError("Cannot parse process command")
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))


def validate_owned(inventory, *, pid, port, db, token, startup_identity, protected):
    """Fail closed before terminating any PID, including Windows venv launchers."""
    processes = inventory["processes"]
    lookup = {p["ProcessId"]: p for p in processes}
    forbidden = descendants(processes, set(protected) | {65024} |
                            {n["OwningProcess"] for n in inventory["listeners"] if n["LocalPort"] == 8000})
    owned = descendants(processes, {pid}) & lookup.keys()
    if not owned or owned & forbidden or port == 8000 or pid not in lookup:
        raise RuntimeError("Process ownership/production exclusion failed")
    if lookup[pid]["CreationDate"] != startup_identity["CreationDate"]:
        raise RuntimeError("PID reused since Popen")
    auxiliary = set()
    for child in owned:
        command = lookup[child].get("CommandLine") or ""
        args = command_arguments(command)
        executable = (lookup[child].get("ExecutablePath") or "").lower()
        console = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "conhost.exe").lower()
        if executable == console and lookup[child]["ParentProcessId"] == pid and len(args) == 2 and args[1] == "0x4":
            # CREATE_NO_WINDOW owns a hidden Windows console host. It has no
            # application DB arguments; never terminate it directly. It exits
            # with the validated launcher and is checked for disappearance.
            auxiliary.add(child)
            continue
        expected = {"-m": MODULE, "--db": str(db), "--token": token, "--port": str(port)}
        if not all(args.count(flag) == 1 and args.index(flag) + 1 < len(args) and
                   args[args.index(flag) + 1] == value for flag, value in expected.items()):
            raise RuntimeError("Owned descendant command/database/port mismatch")
    listeners = [n for n in inventory["listeners"] if n["LocalPort"] == port]
    if any(n["OwningProcess"] not in owned for n in listeners):
        raise RuntimeError("Fixture port is owned by another process")
    return {"checked_at": stamp(), "root_pid": pid, "port": port, "db": str(db),
            "processes": [lookup[x] for x in sorted(owned - auxiliary)],
            "auxiliary_processes": [lookup[x] for x in sorted(auxiliary)], "listeners": listeners,
            "protected_pids": sorted(forbidden)}


class OwnedProcess:
    def __init__(self, mode, port, target_port, db, ledger, token, out, generation, protected):
        self.port, self.db, self.token, self.protected = port, db, token, protected
        self.out, self.name = out, f"{mode}-{generation}"
        self.log = (out / f"{self.name}.log").open("x", encoding="utf-8")
        self.audit = out / f"{self.name}-network.jsonl"
        command = [sys.executable, "-m", MODULE, "--mode", mode, "--port", str(port),
                   "--target-port", str(target_port), "--db", str(db), "--ledger", str(ledger),
                   "--token", token, "--audit", str(self.audit)]
        self.process = subprocess.Popen(command, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
                                        creationflags=HIDDEN)
        inventory = process_inventory()
        self.startup = next((p for p in inventory["processes"] if p["ProcessId"] == self.process.pid), None)
        if self.startup is None:
            self.log.close()
            raise RuntimeError(f"Fixture failed before identity collection; see {self.name}.log")
        save(out / f"{self.name}-launch.json", {"at": stamp(), "command": command, "pid": self.process.pid,
                                              "identity": self.startup})

    def verify(self):
        return validate_owned(process_inventory(), pid=self.process.pid, port=self.port, db=self.db,
                              token=self.token, startup_identity=self.startup, protected=self.protected)

    def kill(self, reason):
        if self.process.poll() is not None:
            self.log.close()
            return {"already_exited": True, "exit_code": self.process.returncode}
        proof = self.verify()
        save(self.out / f"{self.name}-{reason}-ownership.json", proof)
        # Each PID is revalidated immediately before TerminateProcess via taskkill.
        # Never /T: a newly created/unvalidated descendant must not be swept up.
        for prior in sorted(proof["processes"], key=lambda p: p["ProcessId"] == self.process.pid):
            current = process_inventory()
            row = next((p for p in current["processes"] if p["ProcessId"] == prior["ProcessId"]), None)
            if row is None:
                continue
            if row != prior:
                raise RuntimeError("Process identity changed before termination")
            if self.process.poll() is None:
                self.verify()
            else:
                raise RuntimeError("Parent exited while a previously owned descendant remains")
            subprocess.run(["taskkill", "/PID", str(row["ProcessId"]), "/F"], check=True,
                           capture_output=True, creationflags=HIDDEN, timeout=10)
        self.process.wait(timeout=10)
        self.log.close()
        remaining = process_inventory()
        ids = {p["ProcessId"] for p in [*proof["processes"], *proof["auxiliary_processes"]]}
        if any(p["ProcessId"] in ids for p in remaining["processes"]):
            raise RuntimeError("Owned process remained after termination")
        return {"at": stamp(), "exit_code": self.process.returncode, "terminated_pids": sorted(ids)}


def wait_until(probe, condition, timeout=12):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = probe()
            if condition(last):
                return last
        except (httpx.TransportError, ValueError):
            pass
        time.sleep(.05)
    raise AssertionError(f"Local fixture condition timed out: {last}")


def backup(source, destination):
    db, copy = sqlite3.connect(source), sqlite3.connect(destination)
    try:
        db.backup(copy)
    finally:
        copy.close()
        db.close()


def main(args):
    if os.name != "nt":
        raise SystemExit("This acceptance requires Windows process identity checks")
    if args.app_port == args.target_port or 8000 in (args.app_port, args.target_port):
        raise SystemExit("Fixture ports must be distinct and may not be 8000")
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    initial = process_inventory()
    production_before = production_fingerprint(initial)
    protected = descendants(initial["processes"], {65024} |
                            {n["OwningProcess"] for n in initial["listeners"] if n["LocalPort"] == 8000})
    save(out / "production-exclusion.json", {"at": stamp(), "protected_pids": sorted(protected),
                                            "processes": [p for p in initial["processes"] if p["ProcessId"] in protected],
                                            "listeners": [n for n in initial["listeners"] if n["LocalPort"] == 8000]})
    for port in (args.app_port, args.target_port):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
    from scripts.isolated_process_fixture import install_loopback_guard
    install_loopback_guard(out/'runner-network.jsonl', {args.app_port,args.target_port})
    children = []
    report = {"started_at": stamp(), "scope": "Actual isolated Windows processes and HTTP; fixture effects only; no external exactly-once claim",
              "fixture_limits": {"active_jobs": 1, "queue_capacity": 2, "global_concurrency": 1,
                  "max_search_requests": 2, "max_detail_pages": 1, "deadline_seconds": 60,
                  "scope": "Capacity 2 with one active job plus two queued; not a load test of the production default capacity 20"},
              "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [*sorted((ROOT/'backend/app').rglob('*.py')), Path(__file__), ROOT/'scripts/isolated_process_fixture.py']},
              "checks": {}}
    errors = []
    with tempfile.TemporaryDirectory(prefix="knowledge-sprite-process-", ignore_cleanup_errors=True) as temporary:
        folder = Path(temporary)
        db, ledger = folder / "application.sqlite3", folder / "side-effects.sqlite3"
        token = uuid4().hex
        report["temporary_db"] = str(db)
        try:
            target = OwnedProcess("target", args.target_port, args.target_port, db, ledger, token, out, 1, protected)
            children.append(target)
            app = OwnedProcess("app", args.app_port, args.target_port, db, ledger, token, out, 1, protected)
            children.append(app)
            with httpx.Client(base_url=f"http://127.0.0.1:{args.app_port}", trust_env=False, timeout=8) as client, \
                 httpx.Client(base_url=f"http://127.0.0.1:{args.target_port}", trust_env=False, timeout=8) as fixture:
                target_identity = wait_until(lambda: fixture.get('/__fixture/identity').json(), lambda x:x.get('token')==token)
                identity = wait_until(lambda: client.get('/__fixture/identity').json(), lambda x:x.get('token')==token)
                assert identity['db']==str(db) and identity['port']==args.app_port
                assert identity['pid'] in {p['ProcessId'] for p in app.verify()['processes']}
                save(out/'initial-identities.json', {'app':identity,'target':target_identity})
                def health():
                    response=client.get('/health'); response.raise_for_status(); return response.json()
                def job(jid):
                    response=client.get(f'/api/search-jobs/{jid}'); response.raise_for_status(); return response.json()
                def submit(topic,key):
                    response=client.post('/api/search-jobs',json={'knowledge_points':[topic], 'language':'en','student_level':'any','preferred_platforms':[]},headers={'Idempotency-Key':key})
                    assert response.status_code==202,(response.status_code,response.text)
                    return response.json()
                def cancel(jid):
                    response=client.post(f'/api/search-jobs/{jid}/cancel'); response.raise_for_status()
                    assert response.json()['status']=='cancelled',response.text
                    return response.json()
                def events():
                    response=fixture.get('/__fixture/events'); response.raise_for_status(); return response.json()
                def entered(jid):
                    return wait_until(events,lambda rows:any(r['job_id']==jid and r['kind']=='entered' for r in rows))
                def idle():
                    return wait_until(health,lambda h:h['queue_depth']==0 and h['active_jobs']==0 and h['worker_alive'])

                active=submit('hold_cancel_active','cancel-active')['job_id']; entered(active)
                first=submit('hold_cancel_next','cancel-next')['job_id']
                second=submit('queued_cancelled','cancel-queued')['job_id']
                full=health(); assert full['active_jobs']==1 and full['queue_depth']==full['queue_capacity']==2
                overflow=client.post('/api/search-jobs',json={'knowledge_points':['overflow'],'preferred_platforms':[]})
                assert overflow.status_code==429 and overflow.json()['code']=='queue_full' and int(overflow.headers['Retry-After'])>0
                save(out/'queue-full-before-cancel.json',{'at':stamp(),'health':full,'jobs':[job(x) for x in (active,first,second)],'overflow':{'status':overflow.status_code,'body':overflow.json(),'retry_after':overflow.headers['Retry-After']}})
                cancelled=[cancel(active)]; entered(first)
                cancelled.extend([cancel(second),cancel(first)])
                idle()
                wait_until(lambda:fixture.get('/__fixture/identity').json(),lambda x:x['active']==0)
                after_cancel=submit('fixture recovery after cancellation','after-cancel')['job_id']
                done=wait_until(lambda:job(after_cancel),lambda x:x['status'] in TERMINAL)
                assert done['status']=='completed' and done['progress']['details_completed']==1,done
                report['checks']['full_queue_cancellation']={'passed':True,'cancelled':cancelled,'next_completed':done,'health':idle()}

                crash=submit('hold_crash_active','crash-active')['job_id']; entered(crash)
                queued=submit('fixture restart recovery','restart-queued')['job_id']
                before={'at':stamp(),'health':health(),'running':job(crash),'queued':job(queued),'identity':identity,'ownership':app.verify(),'events':events()}
                assert before['running']['status']=='running' and before['queued']['status']=='queued'
                save(out/'before-kill.json',before)
                backup(db,out/'before-kill.sqlite3')
                killed=app.kill('hard-kill')
                wait_until(lambda:fixture.get('/__fixture/identity').json(),lambda x:x['active']==0)
                save(out/'hard-kill.json',killed)
                app2=OwnedProcess('app',args.app_port,args.target_port,db,ledger,token,out,2,protected)
                children.append(app2)
                identity2=wait_until(lambda:client.get('/__fixture/identity').json(),lambda x:x.get('token')==token and x.get('pid')!=identity['pid'])
                assert app2.process.pid!=app.process.pid and identity2['db']==str(db)
                recovered={jid:job(jid) for jid in (crash,queued,active,first,second)}
                assert recovered[crash]['status']==recovered[queued]['status']=='interrupted'
                assert all(recovered[jid]['status']=='cancelled' for jid in (active,first,second))
                assert submit('hold_crash_active','crash-active')=={'job_id':crash,'status':'interrupted','reused':True}
                assert submit('fixture restart recovery','restart-queued')=={'job_id':queued,'status':'interrupted','reused':True}
                assert idle()['queue_depth']==0
                old_events=events()
                assert not any(e['job_id'] in {second,queued} for e in old_events)
                fresh=submit('fixture restart recovery','restart-fresh')['job_id']
                final_job=wait_until(lambda:job(fresh),lambda x:x['status'] in TERMINAL)
                assert final_job['status']=='completed' and final_job['progress']['details_completed']==1
                final_health=idle()
                final_events=events()
                entries=[e for e in final_events if e['kind']=='entered']
                duplicates={key:n for key,n in Counter(e['attempt_key'] for e in entries).items() if n>1}
                assert not duplicates
                assert sum(e['job_id']==crash for e in entries)==1
                report['checks']['kill_restart']={'passed':True,'old_identity':identity,'new_identity':identity2,'recovered_jobs':recovered,'fresh_job':final_job,'final_health':final_health,'same_database':True,'duplicate_attempt_keys':duplicates,'interrupted_jobs_not_replayed':True}
                save(out/'side-effect-events.json',final_events)
                save(out/'after-restart.json',report['checks']['kill_restart'])
        except BaseException as exc:
            errors.append({'type':type(exc).__name__,'message':str(exc)[:2000]})
        finally:
            for child in reversed(children):
                try:
                    child.kill('cleanup')
                except BaseException as exc:
                    errors.append({'cleanup':child.name,'type':type(exc).__name__,'message':str(exc)})
            for source,name in ((db,'application-final.sqlite3'),(ledger,'side-effects-final.sqlite3')):
                if source.exists(): backup(source,out/name)
            if errors: save(out/'run-errors.json',errors)
    report['temporary_directory_removed'] = not folder.exists()
    if folder.exists(): errors.append({'cleanup':'Temporary database directory remains; retained for diagnosis'})
    network=[]
    for file in out.glob('*-network.jsonl'):
        network.extend(json.loads(line) for line in file.read_text(encoding='utf-8').splitlines())
    report['network']={'scope':'Loopback-only HTTP dispatch guard plus Python socket audit hooks; Windows IOCP may omit socket.connect events; event-loop localhost self-pipe initialized before guard; no OS firewall claim',
                       'audited_events':len(network),'external_connections_observed':sum(e['event']=='socket.connect' and e['host']!='127.0.0.1' for e in network),
                       'fixture_http_dispatches':sum(e['event']=='fixture_http_dispatch' for e in network),
                       'blocked_events':[e for e in network if not e['allowed']], 'os_firewall_isolation':'not claimed'}
    if report['network']['blocked_events']: errors.append({'network_guard':'Unexpected attempted connection/bind rejected'})
    report['errors']=errors
    report['finished_at']=stamp()
    report['passed']=not errors and len(report['checks'])==2
    final_inventory=process_inventory()
    report['remaining_fixture_listeners']=[n for n in final_inventory['listeners'] if n['LocalPort'] in (args.app_port,args.target_port)]
    report['production_listener_after']=[n for n in final_inventory['listeners'] if n['LocalPort']==8000]
    report['production_before']=production_before
    report['production_after']=production_fingerprint(final_inventory)
    report['production_identity_and_bindings_unchanged']=report['production_before']==report['production_after']
    if report['remaining_fixture_listeners']:report['passed']=False
    if not report['production_identity_and_bindings_unchanged']:report['passed']=False
    report['source_hash_mismatches']=[name for name,digest in report['source_hashes'].items()
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    report['source_hashes_unchanged']=not report['source_hash_mismatches']
    report['functional_checks_passed']=report['passed']
    report['passed']=report['functional_checks_passed'] and report['source_hashes_unchanged']
    save(out/'summary.json',report)
    print(json.dumps({'passed':report['passed'],'errors':errors,'output':str(out)},ensure_ascii=True))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--app-port',type=int,default=18127)
    parser.add_argument('--target-port',type=int,default=18128)
    raise SystemExit(main(parser.parse_args()))
