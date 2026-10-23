"""Startup policy: synthetic dotenv and mocked uv only; no service or supplier."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from dotenv import dotenv_values, load_dotenv

from backend.app import config


ROOT = Path(__file__).resolve().parents[1]
FEATURES = {
    "OPEN_WEB_SEARCH_ENABLED": "open_web_search_enabled",
    "PARALLEL_PLATFORM_SEARCH": "parallel_platform_search",
    "TEACHING_MATCH_ENABLED": "teaching_match_enabled",
    "SHARED_COURSE_LIBRARY_ENABLED": "shared_course_library_enabled",
    "MOOC_GAP_SEARCH_ENABLED": "mooc_gap_search_enabled",
    "MOOC_REFRESH_ENABLED": "mooc_refresh_enabled",
}


def test_runtime_parser_enables_normal_discovery_without_reading_private_dotenv(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for name in FEATURES:
        monkeypatch.delenv(name, raising=False)
    settings = config.Settings.from_env()
    assert all(getattr(settings, field) is True for field in FEATURES.values())


@pytest.mark.parametrize("disabled", FEATURES)
def test_runtime_parser_preserves_explicit_process_opt_out(monkeypatch, disabled):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for name in FEATURES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(disabled, "false")
    settings = config.Settings.from_env()
    assert getattr(settings, FEATURES[disabled]) is False
    assert all(getattr(settings, field) is True for name, field in FEATURES.items() if name != disabled)


@pytest.mark.parametrize("name", ["app.env.example", "mobile.env.example"])
def test_nonsecret_deployment_defaults_keep_features_and_safe_closed_sources(name):
    values = dotenv_values(ROOT / "deploy" / name, interpolate=False)
    assert all(values[key] == "true" for key in FEATURES)
    assert values["LLM_PROVIDER"] == "none" and values["SEARXNG_URL"] == ""
    for key in ("TAVILY_ALLOW_KEYLESS", "PUBLIC_CATALOG_FALLBACK", "OFFICIAL_SITEMAP_FALLBACK", "ALLOW_STALE_CACHE"):
        assert values[key] == "false"
    assert values["SEARCH_MAX_RETRIES"] == "0" and values["GLOBAL_CONCURRENCY"] == "2"
    assert not any(key.endswith("API_KEY") for key in values)


def run_mocked_launcher(tmp_path, *, disabled=None, fail=False):
    pwsh = os.environ.get("STARTUP_TEST_PWSH") or shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not pwsh:
        pytest.skip("Windows PowerShell launcher test; parser/default tests are platform independent")
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    start = project / "scripts/start.ps1"
    shutil.copyfile(ROOT / "scripts/start.ps1", start)
    synthetic = project / ".env"
    original = "\n".join(key + "=false" for key in FEATURES) + (
        "\nFETCH_ENABLED=false\nPUBLIC_CATALOG_FALLBACK=false\nOFFICIAL_SITEMAP_FALLBACK=false"
        "\nJS_RENDER_ENABLED=false\nTAVILY_ALLOW_KEYLESS=false\nLOCAL_ONLY=true\n"
    )
    synthetic.write_text(original, encoding="utf-8")
    harness = tmp_path / "launcher-test.ps1"
    harness.write_text('''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$names=@('OPEN_WEB_SEARCH_ENABLED','PARALLEL_PLATFORM_SEARCH','TEACHING_MATCH_ENABLED','SHARED_COURSE_LIBRARY_ENABLED','MOOC_GAP_SEARCH_ENABLED','MOOC_REFRESH_ENABLED')
$tokens=$null;$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($env:STARTUP_TEST_SCRIPT,[ref]$tokens,[ref]$errors) | Out-Null
if($errors.Count -ne 0){throw 'PowerShell syntax errors'}
$before=@{};foreach($name in $names){$before[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
$global:StartupNames=$names
$global:MockCalls=@();$global:LASTEXITCODE=0
function global:uv {
 $flags=@{};foreach($name in $global:StartupNames){$flags[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
 $call=@{arguments=@($args);features_environment=$flags}
 if($env:STARTUP_TEST_FAIL -eq '1'){throw 'Synthetic launcher failure'}
 $global:MockCalls+=,$call
 $global:LASTEXITCODE=0
}
$failed=$false
try { & $env:STARTUP_TEST_SCRIPT -SkipInstall -NoBuild } catch {
 if($env:STARTUP_TEST_FAIL -ne '1'){throw}
 $failed=$true
}
$after=@{};foreach($name in $names){$after[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
@{before=$before;after=$after;calls=$global:MockCalls;failed=$failed;syntax_errors=$errors.Count} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:STARTUP_TEST_OUTPUT -Encoding utf8
exit 0
''', encoding="utf-8")
    output = tmp_path / "result.json"
    # Build a minimal environment; never copy the operator's credential values.
    env = {"SystemRoot": os.environ.get("SystemRoot", "C:\\Windows"),
           "PATH": str(Path(pwsh).parent),
           "TEMP": str(tmp_path), "TMP": str(tmp_path), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "STARTUP_TEST_SCRIPT": str(start),
           "STARTUP_TEST_OUTPUT": str(output), "STARTUP_TEST_FAIL": "1" if fail else "0"}
    if disabled:
        env[disabled] = "false"
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(harness)],
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    assert synthetic.read_text(encoding="utf-8") == original
    observed = json.loads(output.read_text(encoding="utf-8-sig"))
    assert observed["syntax_errors"] == 0 and observed["before"] == observed["after"]
    for call in observed["calls"]:
        # Parse the exact environment uv would inherit. Replace only this
        # test's mapping with the six public values; never inspect credentials.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(os, "environ", dict(call["features_environment"]))
            patch.setattr(config, "load_dotenv", lambda *args, **kwargs: load_dotenv(synthetic, override=False))
            settings = config.Settings.from_env()
            call["settings"] = {
                "features": {key: getattr(settings, field) for key, field in FEATURES.items()},
                "closed": {field: getattr(settings, field) for field in ("fetch_enabled", "public_catalog_fallback",
                    "official_sitemap_fallback", "js_render_enabled", "tavily_allow_keyless")},
                "local_only": settings.local_only,
            }
    return observed


@pytest.mark.parametrize("disabled", [None, *FEATURES], ids=["normal", *FEATURES])
def test_normal_restart_overrides_old_dotenv_but_honors_process_opt_out(tmp_path, disabled):
    observed = run_mocked_launcher(tmp_path, disabled=disabled)
    assert not observed["failed"] and len(observed["calls"]) == 1
    call = observed["calls"][0]
    # A PowerShell function receives numeric literals as ints; a native uv
    # process receives the same tokens as strings.
    assert [str(token) for token in call["arguments"]] == ["run", "--frozen", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                                 "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
    assert call["settings"]["features"] == {key: key != disabled for key in FEATURES}
    assert call["settings"]["local_only"] is True
    assert not any(call["settings"]["closed"].values())


def test_launcher_restores_callers_environment_when_startup_fails(tmp_path):
    observed = run_mocked_launcher(tmp_path, fail=True)
    assert observed["failed"] and observed["calls"] == []
