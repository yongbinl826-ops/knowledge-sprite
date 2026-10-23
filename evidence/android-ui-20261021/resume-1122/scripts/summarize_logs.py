from pathlib import Path
import json, re, subprocess

ROOT = Path(__file__).resolve().parent
ADB = str(ROOT.parent / 'sdk/platform-tools/adb.exe')
PKG = 'dev.knowledgeguide.sprite'

def adb(*args):
    return subprocess.run([ADB, '-s', 'emulator-5556', *args], check=True, capture_output=True).stdout.decode('utf-8', errors='replace')

pid = adb('shell', 'pidof', '-s', PKG).strip()
current = adb('logcat', '-d', '--pid=' + pid, '*:W')
(ROOT / f'app-warnings-{pid}.log').write_text(current, encoding='utf-8')
activity = adb('logcat', '-d', '-v', 'brief', 'ActivityManager:I', '*:S')
anrs = re.findall(r'ANR in ([\w.]+)', activity)
selected = [line for line in activity.splitlines() if 'ANR in ' in line or ('Reason:' in line and ('startup' in line or 'safetycenter' in line))]
(ROOT / 'environment-anr-summary.log').write_text('\n'.join(selected) + '\n', encoding='utf-8')

app_logs = {}
for folder, prefix in ((ROOT.parent, 'initial'), (ROOT, 'current')):
    for file in sorted(folder.glob('app-warnings-*.log')):
        content = file.read_text(encoding='utf-8', errors='replace')
        app_logs[f'{prefix}/{file.name}'] = {
            'safeAreaConsoleErrors': content.count('Error injecting safe area CSS'),
            'chromiumSeedMissingSignature': content.count('Seed missing signature'),
            'chromiumCacheErrors': sum(1 for line in content.splitlines() if re.search(r'Could not reconstruct index|cache directory inaccessible|Unable to create cache|opendir.*Code Cache', line)),
            'fatalExceptionLines': content.count('FATAL EXCEPTION'),
        }

crash = adb('logcat', '-d', '-b', 'crash')
(ROOT / 'crash-buffer.log').write_text(crash, encoding='utf-8')
result = {
    'appLogs': app_logs,
    'environment': {
        'observedDialog': "System UI isn't responding",
        'recoveryAction': 'Tapped Wait using fresh UI XML bounds; subsequent app navigation and source filtering responded.',
        'activityManagerAnrPackages': anrs,
        'appAnrPresentInCapturedActivityManagerLog': PKG in anrs,
        'cause': 'unknown; system-process startup ANRs observed, root cause not diagnosed',
        'uiAutomationNullRoot': 'One observed dump failure at source-menu transition; bounded read-only dump retry added without replaying taps.',
    },
    'crashBufferBytes': len(crash.encode()),
    'appNamedInCrashBuffer': PKG in crash,
    'realSearch': False,
    'realPlayback': False,
}
(ROOT / 'sanitized-log-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
