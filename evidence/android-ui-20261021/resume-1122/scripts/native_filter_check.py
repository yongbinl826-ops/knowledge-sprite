from pathlib import Path
from types import SimpleNamespace
import json
import sys
import xml.etree.ElementTree as ET
from adb_qa import ADBQA

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'adb-evidence'
qa = ADBQA(str(ROOT.parent / 'sdk/platform-tools/adb.exe'), 'emulator-5556', OUT, 45)
results = []

def tap(text, cls=None):
    qa.tap(SimpleNamespace(text=text, desc=None, resource_id=None, class_name=cls, index=None))

def capture(step, count, platform=None, topic=None, empty=False):
    qa.capture(step)
    root = ET.parse(OUT / f'{step}.xml').getroot()
    titles = [n.get('text', '') for n in root.iter('node') if n.get('class') == 'android.widget.TextView' and n.get('text', '').startswith('[QA合成]')]
    assert len(titles) == count, (step, titles, count)
    if platform: assert all(platform in title for title in titles), (step, titles)
    if topic: assert all(topic in title for title in titles), (step, titles)
    if empty: assert any('该来源暂无视频，可切换其他来源。' in n.get('text', '') for n in root.iter('node'))
    results.append(dict(step=step, passed=True, count=count, titles=titles, platform=platform, topic=topic))
    (ROOT / 'native-filter-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)

def source(value):
    tap('视频来源')
    tap(value, 'android.widget.CheckedTextView')

capture('stage-3-all', 5)
source('B站')
capture('stage-3-bilibili', 3, 'B站')
source('MOOC')
capture('stage-3-mooc', 2, 'MOOC')
tap('表单输入', 'android.widget.ToggleButton')
capture('stage-3-k1-mooc', 1, 'MOOC', '表单输入')
source('学堂在线')
capture('stage-3-empty', 0, empty=True)
source('全部')
capture('stage-3-k1-all', 3, topic='表单输入')
tap('会话状态管理', 'android.widget.ToggleButton')
capture('stage-3-k2-all', 2, topic='会话状态管理')
print('NATIVE FILTER CHECKS PASSED', flush=True)
