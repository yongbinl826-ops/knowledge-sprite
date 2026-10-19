# r8 existing-project read-only UI acceptance

The default command is local preparation only. It checks all 48 frozen frontend files, the exact CNRwT4ew/d42a9edc bundle, case plans, and separately labelled mock-state images. It performs no HTTP and starts no browser.

Actual execution requires explicit parent authorization, a new PID (16148 and 26048 are rejected), a matching runtime manifest, an existing project/version, and a distinct evidence phase. Every runtime source/dist SHA is checked before HTTP. It never submits a search, analysis, retry or version creation, and never clicks platform links. Cases run serially, stopping on the first failure.

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
node evidence/browser/phase2/runtime-r8/verify-existing-cases.mjs --prepare --runtime-manifest evidence/phase2/runtime-r8-manifest.json
```

After the parent explicitly confirms r8 PID20748 and the requested case is ready, use one of these read-only observations. Each phase is separate to preserve progress and terminal evidence:

```powershell
node evidence/browser/phase2/runtime-r8/verify-existing-cases.mjs --run-after-reload --runtime-label r8-pid20748-data-v6-progress --expected-pid 20748 --runtime-manifest evidence/phase2/runtime-r8-manifest.json --case bicycle_csv_advanced --phase progress-data-v6 --progress-only
node evidence/browser/phase2/runtime-r8/verify-existing-cases.mjs --run-after-reload --runtime-label r8-pid20748-dashboard-history-v1 --expected-pid 20748 --runtime-manifest evidence/phase2/runtime-r8-manifest.json --case dashboard_history_v1 --phase dashboard-history-v1
```

The five planned search versions are data/maze v6, web/Arduino v5 and dashboard v2. Their IDs remain in cases-plan.json. Prepared IDs and versions do not prove that any search started or completed. Do not use `--case all` until the parent confirms all five cases are ready.

The independent historical check reads Dashboard v1 with current_version>=2. It retains actual initial/final API responses, requires k5's explicit scope mismatch and cleared card/platform lists with unknown coverage, verifies another correct historical course remains rendered, captures 1440/768/390 views and keyboard focus, and confirms no historical retry control, API write, external document navigation, or changed job/result identity. It does not hide other correct historical units.

Browser evidence and offline fixture screenshots stay separate. Actual loading/error/card states are reported only when observed. The scripts do not verify playback, teaching completeness, audio language, learning completion or production readiness.
