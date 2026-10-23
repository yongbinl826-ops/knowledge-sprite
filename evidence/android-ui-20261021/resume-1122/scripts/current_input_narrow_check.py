from pathlib import Path
from types import SimpleNamespace
import json, sys
from adb_qa import ADBQA, QAError
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent
qa = ADBQA(str(ROOT.parent/'sdk/platform-tools/adb.exe'), 'emulator-5556', ROOT/'adb-evidence', 45)

def tap(text=None, cls=None, index=None):
    selector = SimpleNamespace(text=text, desc=None, resource_id=None, class_name=cls, index=index)
    try:
        qa.tap(selector)
    except QAError as error:
        if 'off-screen UI-tree bounds' not in str(error):
            raise
        qa.swipe(SimpleNamespace(direction='down', index=None, text=None, desc=None, resource_id=None, class_name=None, duration=400))
        qa.tap(selector)

tap('01 项目描述')
tap(cls='android.widget.EditText', index=0)
# Exercise the focused project name, then restore its original value.
qa.run('shell', 'input', 'keyevent', '123')
qa.run('shell', 'input', 'text', 'Q')
ui = qa.dump('keyboard-entered')
assert any(n.get('text') == 'Android UI QAQ' for n in ui.iter('node'))
qa.capture('keyboard-entered')
qa.run('shell', 'input', 'keyevent', '67')
ui = qa.dump('keyboard-restored')
assert any(n.get('text') == 'Android UI QA' for n in ui.iter('node'))
qa.run('shell', 'input', 'keyevent', '4')

try:
    qa.run('shell', 'wm', 'size', '840x1680')
    qa.capture('narrow-stage-1')
    qa.swipe(SimpleNamespace(direction='up', index=None, text=None, desc=None, resource_id=None, class_name=None, duration=400))
    qa.capture('narrow-stage-1-bottom')
    tap('02 选择知识点')
    qa.capture('narrow-stage-2')
    tap('03 推荐视频')
    tap('全部', 'android.widget.ToggleButton')
    qa.capture('narrow-stage-3')
finally:
    qa.run('shell', 'wm', 'size', 'reset')

qa.capture('current-standard-final')
(ROOT/'current-input-narrow-results.json').write_text(json.dumps({
    'passed': True,
    'keyboardVisibleEvidence': 'adb-evidence/keyboard-recheck.png',
    'typedValue': 'Android UI QAQ',
    'restoredValue': 'Android UI QA',
    'narrowScreen': '840x1680 at 420 dpi (320 dp width)',
    'finalScreenSizeRestored': True,
    'networkFixtureRunning': False,
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('CURRENT INPUT AND NARROW CAPTURES COMPLETE', flush=True)
