# Isolated process lifecycle validation

This directory is new evidence from a local fixture exercise. It does not replace earlier campaign reports and does not demonstrate external-provider exactly-once delivery.

## Scope

- Application fixture: a real Windows OS process, real HTTP on `127.0.0.1:18127`, the production `create_app`/`JobService`/`Store`, an exclusively allocated temporary SQLite database, and injected local provider/fetcher implementations.
- Independent target fixture: `127.0.0.1:18128`, with a separate SQLite side-effect ledger (`journal_mode=WAL`, `synchronous=FULL`). Each entered attempt is committed before awaiting work. Repeated keys are recorded rather than silently deduplicated.
- Queue capacity **2**, with **1 active + 2 queued** observed together before active cancellation. This is not a load test of the default capacity 20.
- The runner records and checks PID, creation time, command arguments, database path, and listener ownership before terminating its own Python processes. Hidden Windows console hosts are identified separately and allowed to exit with their launcher; they are not directly terminated.
- PID 65024, the current port-8000 owner, and their descendants are excluded from termination. Final acceptance also requires their identities and port-8000 address bindings to remain identical before and after.
- Fixture HTTP dispatch is restricted to the owned loopback target. Socket auditing is additional evidence, not an OS firewall guarantee. Windows IOCP may omit `socket.connect` audit events; the dispatcher therefore enforces its own destination boundary. CPython's localhost event-loop self-pipe is initialized before that guard. No real search service, DNS resolver, source page, playback, or browser is involved.

## Preserved development runs

| Run | Outcome and boundary |
|---|---|
| `run-1` | Fixture startup was rejected by the guard because Windows asyncio creates a localhost ephemeral self-pipe. No fixture listener remained. Its log and ledger backup remain. The runner also exposed a backup connection-close issue, corrected in the runner. |
| `run-2` | The first ownership implementation refused the hidden `conhost` child. Original logs/launch identities remain. `recovered-cleanup.json` and ownership proofs document subsequent validated fixture-only cleanup. Port 8000 was untouched. |
| `run-3` | Full queue/cancellation ran. The next-job target assertion failed because the fixture used `.invalid`, which production URL validation correctly rejects. No production change was made; the fixture now uses an inert `fixture.example.com` identity and routes its data only through the local injected transport. |
| `run-4` | Direct script launch could not import the scripts package. No fixture process launched. The runner now establishes its repository import path. |
| `run-5` | All lifecycle functional assertions passed, but `source_hashes_unchanged=false` because `backend/app/ranking.py` changed concurrently. This is not frozen-code final acceptance despite the older report's functional `passed=true`. The revised runner distinguishes `functional_checks_passed` from final `passed` and fails final acceptance on a source-hash change. |

`run-5` recorded application worker PID **70848 → 57816**, two interrupted jobs (formerly running and queued), three preserved cancelled jobs, a new completed job with one completed target detail, nine durable entries (seven provider calls and two target calls), six returned calls and three disconnected calls. No `(job_id, phase, query)` attempt key repeated. It left no fixture listeners, removed its temporary database directory, and observed port 8000 still owned by PID 61976.

The safety tests in `ownership-tests-v2.xml` passed **14 tests**, including PID reuse, wrong database/port/token, unexpected descendants, a foreign listener, production identity/binding changes, durable duplicate visibility, and an external socket destination rejected before connection.

## Final frozen-code result: run-6

**Passed**, with `functional_checks_passed=true`, `source_hashes_unchanged=true`, and `production_identity_and_bindings_unchanged=true`. Evidence is in [run-6/summary.json](run-6/summary.json), [run-6/before-kill.json](run-6/before-kill.json), [run-6/after-restart.json](run-6/after-restart.json), and [run-6/side-effect-events.json](run-6/side-effect-events.json).

- Observation window: **2026-10-14 10:05:56.838107–10:07:02.663400 UTC**. All **23** recorded backend/runner/fixture source hashes remained unchanged. The frozen ranking hash was `33af5b21869b20c179e23a34f1d7810698e5961fe153da53980c303b9c7b1f66`.
- Before cancellation, the same health observation contained **active 1 / queued 2 / capacity 2**. An extra submission returned **429 `queue_full`, Retry-After 5**. Three cancelled jobs remained cancelled after restart.
- The application worker was genuinely terminated at the OS level: worker **27624**, owned launcher **63300**. Restart used a new worker **50936** and the same temporary database. Both the formerly running job and the queued job became **interrupted**; the system did not automatically retry either. Repeating their original idempotency keys returned the original interrupted IDs. A newly keyed task completed with **2 searches and 1 fetched detail**.
- The independent durable ledger contains **9 entered calls** (**7 provider**, **2 target**), **6 returned**, and **3 disconnected**. No `(job_id, phase, query)` attempt key repeated. The cancelled queued job and interrupted queued job produced no fixture side effect. This proves the observed local window only, not external exactly-once execution.
- Final app health before cleanup: **worker alive, queue 0, active 0**; persisted totals were **3 cancelled, 2 completed, 2 interrupted**. After cleanup there were **no fixture listeners**, and the temporary database directory was removed. Final database and ledger backups are preserved in the run directory.
- Production port **127.0.0.1:8000** remained owned by **61976**. The identities, creation timestamps, commands, executables, and parent relationships of **65024 / 61976 / 63532**, plus listener address bindings, were **exactly unchanged**.
- **9 fixture HTTP dispatches**, **0 external connections observed**, and **0 blocked unexpected network events** were recorded. All work used the bounded local fixtures; no external search, DNS, source-page, or playback test was performed. The network enforcement scope and Windows IOCP caveat above still apply.

Runs 1–5 remain unchanged. No backend or script source was edited during run-6, and no further network evaluation was added.
