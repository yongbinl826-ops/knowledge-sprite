"""Safety boundary tests for the isolated Windows lifecycle runner."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.isolated_process_acceptance import MODULE, descendants, validate_owned, production_fingerprint
from scripts.isolated_process_fixture import Ledger


def inventory(db="C:\\fixture\\app.sqlite3", port=18127, token="owned-token"):
    cmd = subprocess.list2cmdline([sys.executable,"-m",MODULE,"--db",db,"--port",str(port),"--token",token])
    parent={"ProcessId":100,"ParentProcessId":50,"CreationDate":"born-1","CommandLine":cmd}
    child={"ProcessId":101,"ParentProcessId":100,"CreationDate":"born-2","CommandLine":cmd}
    return {"processes":[parent,child,{"ProcessId":65024,"ParentProcessId":1,"CreationDate":"production","CommandLine":"production"},
                         {"ProcessId":65025,"ParentProcessId":65024,"CreationDate":"production-child","CommandLine":"production"}],
            "listeners":[{"LocalAddress":"127.0.0.1","LocalPort":port,"OwningProcess":101},
                         {"LocalAddress":"127.0.0.1","LocalPort":8000,"OwningProcess":65025}]}


@pytest.mark.skipif(os.name!="nt",reason="Windows command identity guard")
def test_ownership_includes_venv_child_and_excludes_production():
    value=inventory()
    console=str(Path(os.environ.get('SystemRoot','C:\\Windows'))/'System32'/'conhost.exe')
    value['processes'].append({'ProcessId':103,'ParentProcessId':100,'CreationDate':'console',
                              'ExecutablePath':console,'CommandLine':subprocess.list2cmdline([console,'0x4'])})
    proof=validate_owned(value,pid=100,port=18127,db="C:\\fixture\\app.sqlite3",token="owned-token",
                         startup_identity=value['processes'][0],protected={65024})
    assert {x['ProcessId'] for x in proof['processes']}=={100,101}
    assert [x['ProcessId'] for x in proof['auxiliary_processes']]==[103]
    assert {65024,65025}.issubset(proof['protected_pids'])


@pytest.mark.skipif(os.name!="nt",reason="Windows command identity guard")
@pytest.mark.parametrize('change',['wrong_db','wrong_port_prefix','wrong_token','new_descendant','pid_reused','production_ancestor','foreign_listener'])
def test_ownership_refuses_ambiguous_or_protected_process(change):
    value=inventory(); original=dict(value['processes'][0])
    if change=='wrong_db':value['processes'][1]['CommandLine']+=' --db C:\\other.sqlite3'
    elif change=='wrong_port_prefix':value['processes'][1]['CommandLine']=value['processes'][1]['CommandLine'].replace('18127','181270')
    elif change=='wrong_token':value['processes'][1]['CommandLine']=value['processes'][1]['CommandLine'].replace('owned-token','other-token')
    elif change=='new_descendant':value['processes'].append({'ProcessId':102,'ParentProcessId':101,'CreationDate':'new','CommandLine':'unknown helper'})
    elif change=='pid_reused':value['processes'][0]['CreationDate']='different-birth'
    elif change=='production_ancestor':value['processes'][0]['ParentProcessId']=65024
    elif change=='foreign_listener':value['listeners'][0]['OwningProcess']=999
    with pytest.raises(RuntimeError):
        validate_owned(value,pid=100,port=18127,db="C:\\fixture\\app.sqlite3",token="owned-token",startup_identity=original,protected={65024})


def test_durable_ledger_preserves_repeated_attempts_instead_of_hiding_them(tmp_path):
    path=tmp_path/'ledger.sqlite3'
    first=Ledger(path)
    first.add('entered','job1','same-key',phase='provider')
    first.db.close()
    second=Ledger(path)
    second.add('entered','job1','same-key',phase='provider')
    second.db.close()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE attempt_key='same-key'").fetchone()[0]==2


@pytest.mark.parametrize('change',['creation','command','address','pid'])
def test_production_fingerprint_detects_changes_beyond_same_port(change):
    value=inventory(); before=production_fingerprint(value)
    # Take independent copies as the runner's separate OS snapshots do.
    value=json.loads(json.dumps(value))
    if change=='creation': value['processes'][-1]['CreationDate']='reused-pid'
    elif change=='command': value['processes'][-1]['CommandLine']='different command'
    elif change=='address': value['listeners'][-1]['LocalAddress']='0.0.0.0'
    elif change=='pid': value['listeners'][-1]['OwningProcess']=888
    assert before!=production_fingerprint(value)


def test_socket_guard_rejects_external_before_connect_without_network(tmp_path):
    audit=tmp_path/'guard.jsonl'
    code="""from scripts.isolated_process_fixture import install_loopback_guard
import socket,sys
install_loopback_guard(sys.argv[1], {18127,18128})
try:
    socket.socket().connect(('203.0.113.1',443))
except RuntimeError:
    pass
else:
    raise AssertionError('guard did not reject')
"""
    result=subprocess.run([sys.executable,'-c',code,str(audit)],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=10,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr
    rows=[json.loads(line) for line in audit.read_text().splitlines()]
    assert len(rows)==1 and rows[0]['allowed'] is False and rows[0]['host']=='203.0.113.1'
