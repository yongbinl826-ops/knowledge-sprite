# Frontend QA — 2026-10-18

The flow under test is: project entry → describe a project → review and select learning units → retrieve recommended videos → adjust learning units or inspect a saved version. Manual knowledge-point search remains available through `?mode=manual` and saved `?job=` links.

## Evidence boundaries

- `project.spec.ts` and `search.spec.ts` use isolated HTTP fixtures. Fixture links, courses, analysis output and availability states are **not** live discovery or production acceptance evidence. Unexpected external/API requests are blocked in these tests.
- `live-smoke.spec.ts` is opt-in and uses the real local service without fixture responses. It only reads capabilities and project history, and tests the rendered entry. It does not call the model, create projects, execute search or verify third-party playback.
- Node tests separately check chapter/source evidence, recommendation presentation and image URL policy. Playwright only discovers `*.spec.ts`, so Node assertions are not silently executed as browser-suite imports.
- The cover regression applies the actual production image directive, `img-src 'self' https: data:`, to an isolated fixture page. Other production CSP directives are not injected into Vite's development bootstrap. CDN image responses are fixtures, so this proves URL handling and policy compatibility, not live CDN availability; production CSP is unchanged.

## Final run status

| Verification | Result | Record |
| --- | --- | --- |
| Node chapter/topic/image-policy tests, rerun after cover-timeout revision | **45 passed, 0 failed** | `evidence/browser/unit-final-cover-timeout-results.tap.txt` |
| Complete final isolated browser suite, including unit technology and bounded covers | **56 passed, 0 failed, 0 flaky** in 56.6 seconds: project 23 + manual search 33 | `evidence/browser/e2e-final-cover-timeout-results.json` |
| Preserved isolated browser suite baseline, before the optional unit-technology field | **52 passed, 0 failed, 0 flaky** in 55.5 seconds: project 22 + manual search 30 | `evidence/browser/e2e-results.json` |
| Preserved project incremental regression, including unit technology and data-flow disclosure | **23 passed, 0 failed, 0 flaky** in 30.7 seconds | `evidence/browser/project-technology-incremental-results.json` |
| Image-policy baseline real local-service read-only smoke | **3 passed, 0 failed** at `http://127.0.0.1:8000`, 1440×1000 / 768×1024 / 390×844 | `evidence/browser/live-smoke-results.json` |
| Sampled key text contrast, all three stages and widths | **Passed**; lowest sampled ratio **5.15989:1** | `evidence/browser/contrast-{desktop,tablet,mobile}*.json` |

The final complete isolated suite explicitly skips its three opt-in live tests; those same three tests passed in the earlier separate real-service run. The final 56-case run reruns all 23 project cases and all 33 manual cases, including the three new bounded-cover cases. This is not an omitted live failure. The earlier interrupted report is retained as `prior-incomplete-e2e-results.json` and is not acceptance evidence. The genuine contrast failure discovered during review is preserved in `contrast-before-fix.json` and `contrast-failure-e2e-results.json`.

A subsequent isolated project revision adds the optional per-unit technology field and an explicit local-storage/model-service/search data-flow disclosure. Its 23-case project regression is reported separately; the 52-case baseline remains untouched, and unchanged manual search was not redundantly rerun. The original 45 Node result was reused for that technology-only increment after hashing all four Node test files and six runtime/type dependencies and confirming no changes (`unit-node-dependency-verification.json`); all 45 Node cases were rerun for the final cover-timeout revision. The initial technology field inherited a 130px numeric-input cap and clipped a representative tool/version value; its observed 128px client width versus 238px content width is retained in `unit-technology-width-before-fix.json` and the corresponding failed targeted report. Limiting that cap to number inputs fixed the issue: final client/content widths are both 809px, the full representative value is readable, and all 23 project cases passed. Desktop and mobile input screenshots show the data-flow notice without clipping or overlap.

The real-service smoke observed capabilities and project-list HTTP 200 responses, meaningful page content, the expected title, two-line headings, no framework overlay, no runtime/console errors and no horizontal document overflow. It issued no mutation requests. Screenshots were opened and visually inspected against the references and across success, loading, error, empty and focus states. Screenshots settle transient animations; reduced-motion behavior is checked separately through computed styles.

## Test coverage

| Area | Acceptance check | Evidence |
| --- | --- | --- |
| Three screens | Only the active input, confirmation or results screen is rendered; unreached stages are disabled | `project.spec.ts`, three viewport flow tests |
| Unit granularity UI | Every shared unit appears once; associated project tasks and learning details remain inspectable | Shared-unit and sorting tests |
| Learning order | Default list follows global `learning_order`; task grouping is optional and preserves selections | Sorting test |
| Student control | Only selected units are searched; skipped prerequisites require acknowledgement; all-skipped selection creates no empty search | Selection and prerequisite tests |
| Per-unit technology | Existing value appears in expanded details, maxLength is 80, editing changes only that field in the complete saved analysis; missing historical values render empty and both present/missing historical controls are disabled | Incremental unit-technology case and `unit-technology-browser-observations.json` |
| Data-flow disclosure | New-project form visibly states local persistence, configured-model transfer, knowledge-point search use and avoiding sensitive information | All three viewport project-entry cases; desktop/mobile action screenshots inspected |
| Recovery | Input draft, learning-unit draft, saved version and active analysis survive refresh | Draft, version and loading tests |
| Failure/retry | Analysis failure retains input; retry reuses the saved project; confirmation failure preserves saved edits; new search creates a fresh version | Failure and retry tests |
| Empty/partial results | Distinguishes no result, partial completion, platform-filter empty state and service failure | Project and manual empty-state tests |
| Platform-search fallback | Fixed HTTPS platform, literal keyword encoding, safe new-tab attributes, explicit search/non-recommendation label, no automatic external request, only shown for the chosen platform in terminal unfiltered empty states | Dedicated fallback test and loading/filter assertions |
| Version isolation | New versions do not display old results; history remains inspectable and exposes no enabled retry mutation | History tests |
| Evidence and safe links | Rejects mismatched/forged chapter provenance, unsafe URLs, unsupported resources and XSS-shaped text; retains original valid links | 45 Node tests and manual browser tests |
| Bounded cover loading | A pending visible cover falls back after the 10-second window while the original course link still opens a new tab; a successfully loaded image survives 30 seconds; a native-observer offscreen image survives 30 seconds and starts its bounded wait only on approach/visibility | Three clock-controlled browser cases; `cover-{pending,loaded,lazy}-timeout-observations.json` |
| HTTPS course images | Only the observed numeric Bilibili CDN HTTP host family upgrades to HTTPS with original path/query; unknown HTTP/host lookalikes issue no request; blocked or failed images show an unavailable-cover placeholder and preserve the course link | Dedicated CSP browser test, 4 image-policy Node cases, `course-image-browser-observations.json` |
| Keyboard | Skip link, brief entry, submit, selection, prerequisite acknowledgement and stage focus work by keyboard | Keyboard test and focus screenshot |
| Contrast | Sampled heading, description, field labels, assumptions, primary action and enabled step navigation meet the appropriate large/normal text threshold | Per-stage, per-width contrast JSON |
| Motion | Reduced-motion media preference suppresses animation and transitions during loading | Motion test and `motion-observations.json` |
| Responsive | 1440×1000, 768×1024 and 390×844; no document horizontal overflow; stage titles remain two lines | Responsive tests and screenshots |

## Original design comparison

All four actual references were opened and visually inspected:

- `design/imagegen/2026-10-18-three-screens-v2/01-project-description.png`
- `design/imagegen/2026-10-18-three-screens-v2/02-knowledge-selection.png`
- `design/imagegen/2026-10-18-three-screens-v2/03-video-recommendations.png`
- `design/imagegen/2026-10-18-three-screens-v2/04-transition-storyboard.png`

The implementation preserves the warm white `#F5F3EE`, graphite `#181818` and blue `#3157FF` palette, asymmetric narrative/action layout, outlined stage numbers, restrained borders and three-stage navigation. It adds editable learning details, explicit assumptions, saved history, evidence status and retry controls required for the functional product. These additions intentionally make some screens longer than the illustrative references. Analysis keeps the input visible and disabled with status feedback; search loading uses state-driven skeletons. Course covers use actual supplied thumbnails when available and an original typographic fallback otherwise; fixture images are not represented as real course covers.

| Finding from rendered inspection | Change requested | Final verification |
| --- | --- | --- |
| Desktop result heading wrapped into three lines in the narrow sidebar | Size the result heading relative to its container | Passed two-line heading assertions at all three widths; result screenshots inspected |
| Entering results from a long confirmation page retained scroll, hiding the header | Reset scroll on stage change while focusing the heading without another scroll | Passed scrollY=0 and heading-focus checks; header remains visible in refreshed screenshots |
| Historical results offered a retry that used an old expected version | Remove or disable the history retry and explain returning to the latest version | Passed history assertion; only current version exposes retry |
| Mobile selected-topic list used multiple lines before the first result | Compact horizontal topic navigation with usable touch targets | Refreshed mobile result screenshot inspected; document remains within viewport |
| Description contrast was 4.1919:1, below the normal-text requirement on tablet/mobile | Use the darker shared muted color for descriptions and enabled navigation | Passed all three stages and widths; lowest sampled ratio 5.15989:1 |
| A real provider returned HTTP course thumbnails, which the unchanged HTTPS image CSP blocked | Normalize only observed numeric Bilibili CDN image hosts to HTTPS; retain a clear unavailable-cover placeholder for other HTTP or failed images | 45 Node tests and complete 52-case browser suite passed; isolated image-policy run observed HTTPS requests only and no CSP/mixed-content error |
| A third-party CDN request could stay pending and leave a blank course cover indefinitely | Bound visible/nearby cover loading to 10 seconds; clear the timer on success and defer offscreen timing with native IntersectionObserver | Three clock-controlled cases verify pending fallback plus actual new-tab navigation, loaded-image retention and no premature offscreen failure |
| New unit-technology text inherited a numeric-only 130px cap, clipping the tool/version value | Limit the width cap to number inputs | Latest project regression 23/23 passed; text field client/content width 809/809 and saved value fully visible |

There are no known unresolved high/medium frontend defects in the tested scope. No award or universal accessibility certification is claimed. Testing used Edge; Firefox, Safari and an actual screen-reader session were not exercised. Contrast sampling is not a full-page automated accessibility audit. Live model quality, real video relevance and provider integration are evaluated separately by the integration owner.

## Environment and reproduction

Browser plugin/`browser` skill was not listed, so the existing `@playwright/test` workflow was used with installed Microsoft Edge (`PLAYWRIGHT_CHANNEL=msedge`). The later CUA connection also exposed no available browser. No browser or package was downloaded. Windows sandbox Edge launch and loopback access failed before page execution; the resumed tests use the authorized local execution environment and a hidden Vite preview.

The exact QA preview command, PID and URL are recorded in `evidence/browser/vite-5175-process.json`; stdout/stderr are adjacent. Earlier QA PID 36040 was individually stopped (`vite-5175-stopped.json`). The image-policy regression started a new hidden Vite process, PID 28272. After final QA, the integration owner verified its command line and creation time and stopped that specific process; see `evidence/browser/vite-5175-final-stopped.json`. The built application preview on port 8000 is separate. Verify the recorded identity before stopping a process; do not send console-wide Ctrl+C or kill every Node/browser process.

From the workspace:

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\frontend'
$env:PLAYWRIGHT_CHANNEL = 'msedge'
$env:PLAYWRIGHT_EXTERNAL_SERVER = '1'
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:5175'
npm run test:e2e -- --workers=1
node --test --test-reporter=tap tests/chapter-recommendations.test.mjs tests/partial-chapter-evidence.test.mjs tests/topic-evidence.test.mjs tests/course-images.test.mjs
```

For a separately started final built local preview, use the confirmed URL rather than assuming an old process serves current files:

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\frontend'
$env:PLAYWRIGHT_CHANNEL = 'msedge'
$env:PLAYWRIGHT_EXTERNAL_SERVER = '1'
$env:QA_LIVE_SMOKE = '1'
$env:QA_LIVE_BASE_URL = 'http://127.0.0.1:8000'
$env:PLAYWRIGHT_JSON_OUTPUT = '../evidence/browser/live-smoke-results.json'
$env:PLAYWRIGHT_OUTPUT_DIR = '../evidence/browser/live-artifacts'
npm run test:e2e -- tests/live-smoke.spec.ts --workers=1
```

Screenshots are in `evidence/browser/screenshots/` for mocked interaction states, and `evidence/browser/live/` for real-service entry. JSON results, source-safe observations, traces on failure and Node TAP output are retained under `evidence/browser/`.

Representative screenshots:

- Real entry: `live/desktop-entry.png`, `live/tablet-entry.png`, `live/mobile-entry.png`.
- Three screens: `screenshots/mock-{desktop,tablet,mobile}-01-input.png`, `-02-selection.png`, `-03-results.png`.
- Loading/empty/error: `screenshots/mock-{desktop,tablet,mobile}-search-loading.png`, `-loading-reduced-motion.png`, `-no-results.png`, `-analysis-error.png`.
- Keyboard focus: `screenshots/mock-desktop-keyboard-skip-link.png`.
- HTTPS cover behavior: `https-cover-policy.png` in the dedicated `test-artifacts/search-HTTPS...` case folder; request and policy observations are also saved as readable JSON.
- Per-unit technology: `screenshots/mock-unit-technology-saved.png`; full save/history/layout observations are in `unit-technology-browser-observations.json`.

The final cover-timeout revision is verified with deliberately unresolved image routes and Playwright clock control. The tests retain native IntersectionObserver behavior. They do not wait for network idle and do not contact a real CDN; one pending-image case also opens the unchanged course URL in a new tab whose landing document is an isolated fixture. This demonstrates that image availability is independent of the student’s course navigation. Timeout observations and the visually inspected fallback screenshot (`screenshots/mock-pending-cover-timeout.png`) are retained separately from the earlier 52-case and 23-case reports. The final manifest hashes all current frontend sources, tests and built assets. The final complete regression also refreshes the three-width screenshots and nine sampled-contrast records; the minimum remains 5.15989:1 with zero failures.
