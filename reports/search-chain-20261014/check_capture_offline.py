"""Offline negative cases against the installed curl_cffi callback ABI."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from curl_cffi import curl as curl_module

source = Path('/tmp/knowledge-sprite-capture-bing-once.py').read_text()
tree = ast.parse(source)
names = {'BudgetStop', 'body_chunk', 'ensure_no_credentials', 'require_complete_body'}
namespace = {'BODY': bytearray(), 'MAX_BYTES': 8, 'R': {}}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names],
                        type_ignores=[]), '<isolated-budget-functions>', 'exec'), namespace)
checks = {}
assert namespace['body_chunk'](b'abcd') == 4
handle = curl_module.ffi.new_handle(SimpleNamespace(callback=namespace['body_chunk']))
buf = curl_module.ffi.new('char[]', b'12345')
ret = curl_module.write_callback(buf, 1, 5, handle)
assert ret == curl_module.CURL_WRITEFUNC_ERROR == 0xFFFFFFFF
assert len(namespace['BODY']) == 4 and namespace['R']['body_limit_hit']
checks['actual_curl_cffi_wrapper_preserves_abort_signal'] = True
try:
    namespace['require_complete_body']()
except namespace['BudgetStop']:
    checks['overlimit_cannot_reach_success_or_parser'] = True
else:
    raise AssertionError('partial body accepted')
assert namespace['R']['received_body_complete'] is False
namespace['BODY'].clear()
namespace['R'].clear()
assert namespace['body_chunk'](b'12345678') == 8
namespace['require_complete_body']()
checks['at_limit_body_accepted_without_overflow'] = True
for key in ('Authorization', 'Proxy-Authorization', 'Cookie', 'aUtHoRiZaTiOn'):
    try:
        namespace['ensure_no_credentials']({'headers': {key: 'fixture-only'}})
    except namespace['BudgetStop']:
        pass
    else:
        raise AssertionError('credential header accepted')
checks['credential_header_keys_rejected'] = True
namespace['ensure_no_credentials']({'headers': {'Accept': 'text/html'}, 'auth': None, 'cookies': {}})
checks['ordinary_headers_allowed'] = True
print(json.dumps({'network_requests': 0, 'checks': checks, 'all_passed': all(checks.values()),
                  'runner_sha256': hashlib.sha256(source.encode()).hexdigest(),
                  'curl_callback_source_sha256': hashlib.sha256(Path(curl_module.__file__).read_bytes()).hexdigest()}))
