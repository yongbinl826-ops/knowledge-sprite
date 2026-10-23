from pathlib import Path
from types import SimpleNamespace
import json, time, sys
from adb_qa import ADBQA, QAError
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent
qa=ADBQA(str(ROOT.parent/'sdk/platform-tools/adb.exe'),'emulator-5556',ROOT/'adb-evidence',45)
def tap(text=None, cls=None, index=None):
    qa.tap(SimpleNamespace(text=text,desc=None,resource_id=None,class_name=cls,index=index))
for attempt in range(8):
    try:
        ui=qa.dump('current-ready')
        titles=[n.get('text','') for n in ui.iter('node') if n.get('class')=='android.widget.TextView' and n.get('text','').startswith('[QA合成]')]
        if len(titles)==5: break
    except QAError:
        if attempt==7: raise
    time.sleep(2)
assert len(titles)==5,titles
qa.capture('stage-3')
tap('02 选择知识点')
qa.capture('stage-2')
tap('01 项目描述')
qa.capture('stage-1')
tap(cls='android.widget.EditText',index=0)
qa.capture('stage-1-keyboard')
qa.run('shell','input','keyevent','4')
tap('03 推荐视频')
qa.capture('stage-3')
(ROOT/'current-layout-results.json').write_text(json.dumps({'passed':True,'screens':['stage-1','stage-1-keyboard','stage-2','stage-3'],'loadedExistingProject':True,'cachedCards':len(titles),'networkFixtureRunning':False},indent=2),encoding='utf8')
print('CURRENT LAYOUT FLOW PASSED',flush=True)
