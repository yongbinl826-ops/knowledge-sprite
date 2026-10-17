# Chapter evidence validation QA — 2026-10-13

Final status: **PASS for the bounded offline audit and isolated frontend regression suite**. Source files were frozen after these checks. This report does not claim real-source discovery, extraction, or video playback success.

## Changes and contract

Only the four authorized source/test files were changed:

- `frontend/src/components/ResourceCard.tsx`
- `frontend/tests/search.spec.ts`
- `scripts/live_acceptance_revision.py`
- `tests/test_acceptance_revision.py`

A verified chapter must name its own catalog evidence ID, whose `field` is exactly `chapters.<current index>`. The evidence must contain a JSON object matching the chapter's title, URL, start, end, and duration. Missing and null both mean unknown. An aggregate-only record, a record without JSON facts, a different row's evidence, or any mismatched field cannot certify the row.

Known duration must be a finite number greater than zero. Known start/end must be finite numbers at least zero; known end cannot precede known start. Booleans, strings, negative numbers, zero duration, infinity, and NaN are not valid known values. Both the chapter and its evidence are validated so Python's `True == 1` comparison cannot admit a boolean record. Unknown values stay unknown. Source and optional chapter links must be parseable HTTP(S) URLs without credentials, control characters, backslashes, malformed ports, or overlong input. No links were opened to remote course sites during this suite.

Frontend fixtures now contain real per-row JSON records. The valid injection-text case has an unknown link and remains escaped text; separate invalid-link, aggregate-only, missing-text, cross-ID, wrong-index, field-tampering, and invalid-seconds cases are rejected. Screenshots now use Playwright's per-test output path so this run preserves older evidence.

## Commands and results

Executed from the project root:

```powershell
uv run --frozen pytest tests/test_acceptance_revision.py -q --junitxml=reports/adapter-evaluation-20261013/chapter-evidence-tests.xml
```

Result: **52 passed in 0.41 seconds**. The XML file retains each case.

Executed from `frontend`:

```powershell
npm exec tsc -- -b
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_JSON_OUTPUT_FILE='D:\项目制知识引导小精灵\reports\adapter-evaluation-20261013\frontend-e2e.json'
npm run test:e2e -- --reporter=list,json --output ../reports/adapter-evaluation-20261013/frontend-test-artifacts
```

TypeScript compilation passed. Complete E2E result: **16 passed**, 0 unexpected, 0 skipped, 0 flaky; start `2026-10-13T11:11:05.697Z`, duration `18.024183` seconds. The Playwright project retains the name `chromium`; this invocation explicitly selects the installed Microsoft Edge channel. Browser plugin not available; the repository's Playwright setup was used as the skill fallback. No production dependency or Playwright configuration was changed.

## Browser QA and evidence

All interactions used `http://127.0.0.1:5173`. API responses were isolated test fixtures and were never inserted into production discovery or SQLite. The suite verifies app title, nonblank forms/results, absence of the Vite error overlay, form validation, submission/polling, platform/type filters, errors versus empty results, partial/interrupted status, source disclosure, escaped text, safe chapter link attributes, unknown values, and stale-cache labeling.

The chapter fixture collects page errors plus browser warning/error messages and passed with an empty collection. The runner emitted only existing Node `NO_COLOR`/`FORCE_COLOR` environment warnings; these were not browser errors.

Desktop `1536 × 1024` and mobile `390 × 844` full-page screenshots were inspected. The chapter list shows exactly three supported rows. The first shows start `1:05` and duration `45:43` separately; the injection text is visible as text without an image element; unknown chapter links remain labeled unknown. The mobile layout has no horizontal overflow and keeps form controls, sources, and chapter text readable. No new visual/layout issue was observed.

Artifacts:

- `frontend-e2e.json`
- `chapter-evidence-tests.xml`
- `frontend-test-artifacts/search-隔离目录fixture：章节直链、来源、时间证据与注入防护-chromium/catalog-fixture-desktop.png`
- `frontend-test-artifacts/search-隔离目录fixture：章节直链、来源、时间证据与注入防护-chromium/catalog-fixture-mobile.png`
- Additional desktop initial/results and mobile initial screenshots under `frontend-test-artifacts/`.

Earlier reports and failing artifacts were not overwritten. External navigation and playback remain outside this fixture-based check; root's separately retained live checks cover real search/page delivery.

## Frozen SHA-256

| File | SHA-256 |
|---|---|
| `frontend/src/components/ResourceCard.tsx` | `52f3e91623f8183048ef165537d2ec94f7708cb7be163ae824038edf9e1b1a61` |
| `frontend/tests/search.spec.ts` | `93dc2713b12679f2a60d7a2c1f9669b015ee7f596af0de297426bd103fe51b6b` |
| `scripts/live_acceptance_revision.py` | `d0b3b0d237f4b4c2ae53ab0c86624b58e2479d21d4e8bbc00e3b3c3eca4edbdd` |
| `tests/test_acceptance_revision.py` | `0d0dc589ad2018d35be165c4b57401f9f098cc7cd09b0c174f7d912da8d84622` |
