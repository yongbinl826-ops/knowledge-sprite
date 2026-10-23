"""Detached, source-bound offline regression runner with a durable receipt."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    source, evidence = Path(args.source).resolve(), Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    os.chdir(source)
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    # Child tests must never inherit an operator's real supplier credentials.
    # Assign empty strings directly; do not inspect or log prior values.
    for name in ('LLM_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY', 'SERPER_API_KEY'):
        os.environ[name] = ''
    os.environ['LLM_PROVIDER'] = 'none'
    os.environ['SEARCH_PROVIDER'] = 'searxng'
    os.environ['SEARXNG_URL'] = ''
    os.environ['APP_MODE'] = 'legacy'
    os.environ['TEMP'] = str(evidence)
    os.environ['TMP'] = str(evidence)
    sys.path.insert(0, str(source))
    receipt_path = evidence / 'receipt.json'
    def hashes():
        return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (source / 'backend/app').rglob('*.py')}
    receipt = {'status': 'running', 'pid': os.getpid(), 'source': str(source),
               'started_at': datetime.now(timezone.utc).isoformat(), 'backend_before': hashes(),
               'scope': 'repository offline/mock regression; no actual configuration or student DB'}
    def save():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    import pytest
    from scripts.validate_mobile_boundary import LoopbackOnly
    with LoopbackOnly() as guard:
        result = pytest.main(['-q', '-p', 'no:cacheprovider', '-o', 'faulthandler_timeout=60',
                              '--junitxml=' + str(evidence / 'results.xml')])
        receipt['blocked_external_transport_attempts'] = guard.blocked
    receipt.update(status='completed', exit_code=int(result), backend_after=hashes(),
                   finished_at=datetime.now(timezone.utc).isoformat())
    receipt['backend_source_unchanged'] = receipt['backend_before'] == receipt['backend_after']
    save()
    return int(result) if receipt['backend_source_unchanged'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
