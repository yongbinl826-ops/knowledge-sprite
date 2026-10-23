from pathlib import Path
import json, subprocess, time, sys
import xml.etree.ElementTree as ET
from adb_qa import ADBQA, QAError
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'adb-evidence'
ADB = str(ROOT.parent / 'sdk/platform-tools/adb.exe')
PKG = 'dev.knowledgeguide.sprite'
def adb(*args):
    return subprocess.run([ADB, '-s', 'emulator-5556', *args], check=True, capture_output=True).stdout
qa = ADBQA(ADB, 'emulator-5556', OUT, 45)
before = adb('shell', 'pidof', '-s', PKG).decode().strip()
requests_before = (ROOT.parent/'fixture-requests.jsonl').read_text(encoding='utf-8').splitlines()
if b'tcp:18027' in adb('reverse', '--list'):
    adb('reverse', '--remove', 'tcp:18027')
adb('shell', 'am', 'force-stop', PKG)
adb('shell', 'am', 'start', '-n', PKG+'/.MainActivity')
for attempt in range(6):
    time.sleep(2)
    try:
        qa.capture('offline-restart')
    except QAError as error:
        if attempt == 5: raise
        print('Waiting for startup UI:', str(error), flush=True)
        continue
    root = ET.parse(OUT/'offline-restart.xml').getroot()
    titles = [n.get('text','') for n in root.iter('node') if n.get('class') == 'android.widget.TextView' and n.get('text','').startswith('[QA合成]')]
    if len(titles) == 5: break
assert len(titles) == 5, titles
assert any(n.get('text') == 'Android UI QA' for n in root.iter('node'))
after = adb('shell', 'pidof', '-s', PKG).decode().strip()
assert before != after
requests_after = (ROOT.parent/'fixture-requests.jsonl').read_text(encoding='utf-8').splitlines()
assert requests_before == requests_after, 'Unexpected QA server request after removing reverse'
for pid in (before, after):
    (ROOT/f'app-warnings-{pid}.log').write_bytes(adb('logcat','-d','--pid='+pid,'*:W'))
crashes = adb('logcat','-d','-b','crash')
(ROOT/'crash-buffer.log').write_bytes(crashes)
assert b'FATAL EXCEPTION' not in crashes
assert b'dev.knowledgeguide.sprite' not in crashes
prefs = adb('shell','run-as',PKG,'ls','-l','shared_prefs/KnowledgeSpriteDevice.xml').decode().strip()
result=dict(passed=True,beforePid=before,afterPid=after,fixtureForwardRemoved=True,newServerRequests=0,restoredProject='Android UI QA',restoredCards=len(titles),cards=titles,preferencesMetadata=prefs,crashBuffer=crashes.decode(errors='replace'),realSearch=False,realPlayback=False)
(ROOT/'native-restart-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
