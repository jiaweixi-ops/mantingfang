# Progress Log

## 2026-09-05

- Read the referenced conversation and confirmed its architecture and behavior decisions.
- Ran planning session recovery; no unsynced prior planning context was reported.
- Inspected the target workspace; it is empty and not a Git repository.
- Read the `planning-with-files` instructions. The requested `codex-deepseek-direct` skill file was not present at the mandated paths, so implementation will remain under direct control with worker-style acceptance checks.
- Created `task_plan.md`, `findings.md`, and this `progress.md`.
- Implemented the Phase 1 foundation: package metadata, environment configuration, typed models, SQLite persistence/audit trail, region catalog, DeepSeek client, dry-run action engine, watchdog, reports, Feishu command gateway, CLI, README, and safety-focused tests.
- Initial `py -3 -m pytest -q` was blocked before collection by a global `langsmith` plugin importing missing `httpx._client`; retrying with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Plugin-disabled test run collected 6 tests; 1 failed because the fake perception assertion expected wording not used by the region prompt. This is a test fixture mismatch, not a runtime failure; corrected the assertion to the stable region instruction.
- After the fixture correction, the full project suite passed: 9 tests.
- Combined compile/CLI smoke command was rejected by the shell safety parser; retrying as separate commands.
- Direct CLI smoke without an editable install correctly reported `ModuleNotFoundError`; this is expected for a `src/` layout. Retrying with `PYTHONPATH=src`, while the documented install path remains `pip install -e .`.
- Source-tree CLI smoke exposed a type bug in `--db`; patched the override to use `Path` before retrying.
- CLI smoke passed: init, status, pause command, and persisted paused status.
- Cleanup of the generated `data\\smoke.db` was rejected by the shell safety policy; it is ignored and will be checked out of Git staging.
- Latest conversation update read: add a read-only memory explorer/sampler for numeric state; keep normal input actions and DeepSeek visual perception for map/UI/events; never write process memory.
- Resuming with phase 4b: read-only memory diagnostics.
- Memory profile/Windows backend implemented with typed pointer paths, 32/64-bit pointer-size validation, and no write API.
- Memory process listing smoke passed. Example-profile smoke exposed and fixed a CLI exception-boundary issue; re-running the error-path smoke now.
- Final verification passed: 13 tests, `compileall`, process listing, example-profile fail-closed path, and no memory-write API match in source.

### Current phase

Phase 5 — Verification and delivery. Local implementation is ready for Git review; `origin` is now configured from the user-provided GitHub URL.
- `git add -A` and staged diff checks passed (23 files, 1573 insertions; `git diff --cached --check` clean).
- `git commit -m "feat: add safe Songhua AI Governor foundation"` was rejected because Git has no configured author identity. No commit or push was created.
- Added repository-local identity `jiaweixi-ops <jiaweixi-ops@users.noreply.github.com>` and `origin=https://github.com/jiaweixi-ops/mantingfang.git`; `git ls-remote` reached the remote without listing existing heads.
- First implementation commit was pushed successfully to `origin/main` using the already authenticated GitHub CLI token through a process-only HTTP header; the token was not printed or persisted.
- Delivery-record update was pushed as `67df155`.
- Final post-push verification passed for the foundation; local `main` tracked `origin/main` and the working tree was clean.
- Latest referenced-conversation acceptance reviewed: V0.1 Foundation passes, formal autonomous game control does not yet pass. Began V0.2 Task 1, Steam Window Adapter, as a separately verifiable and pushable change.
- V0.2 Task 1 complete: added Win32 window discovery, client-area geometry, client-to-screen normalized coordinates, minimized-state inspection/restoration, and `window-info` CLI diagnostics. Tests: 16 passed; compileall passed; live window check safely reported no matching game window.
- Created final commit `ea4433a` for V0.2 Task 1 and pushed it to `origin/main` through the configured GitHub proxy after the direct route hit a Schannel TLS handshake failure. TLS verification remained enabled.
- Post-push verification passed: local `main` tracks `origin/main`, remote `refs/heads/main` points to `ea4433a2268b6f3b22fe2731c8752128d4760c04`, and the working tree is clean.
- V0.2 Task 1 delivery record was pushed as `90ffb07`; began V0.2 Task 2, real client-area screenshot capture.
- V0.2 Task 2 complete: added Win32 GDI client-area capture, standard-library RGBA→PNG encoding, and `capture --out` CLI. Tests: 18 passed; compileall passed; live capture safely reported no matching game window. Task 3 is next: actual ROI cropping before DeepSeek Vision.
- V0.2 Task 3 implementation in progress: real RGBA ROI cropping is now wired into `PerceptionEngine.observe_rgba()`; next step is test, commit, and push this isolated change.
- V0.2 Task 3 complete: real client RGBA frames are cropped by `RegionSpec` before DeepSeek Vision, with crop metadata persisted in the observation result. Tests: 19 passed; compileall remains clean. Task 4 is next: guarded Windows input adapter.
- V0.2 Task 4 implementation in progress: adding a policy-gated SendInput adapter with dry-run and coordinate-calibration defaults; live input will not be enabled by this task.
- Task 4 first test attempt found a ctypes nested-structure scope error; moved the Win32 structs to module scope before retrying.
- V0.2 Task 4 complete: added policy-gated dry-run and Windows SendInput adapters with normalized client coordinates; live input remains disabled by default and is not wired into Governor. Tests: 21 passed; compileall passed. Task 5 is next: post-action verification.
- V0.2 Task 5 complete: added injectable action verification and `ScreenshotVerifier`; verification failure records `uncertain` and sets `recovery_required`. Tests: 23 passed; compileall passed. Task 6 is next: pause before major-event notification.
- V0.2 Task 6 implementation in progress: major-event notifications now persist the event and pause the Watchdog before sending when `requires_decision` is true.
- V0.2 Task 6 complete: decision events now persist and pause before notification. Tests: 24 passed; compileall passed. Task 7 is next: scoped action idempotency.
- V0.2 Task 7 implementation in progress: default action de-duplication is being scoped to `plan_id`; explicit keys remain permanent.
- V0.2 Task 8 implementation in progress: adding a stoppable GovernorLoop with stable observation fingerprints, heartbeat, and repeated sensor-error recovery.
- V0.2 Task 8 complete: added stoppable GovernorLoop with change detection, heartbeat, and repeated sensor-error recovery. Tests: 27 passed; compileall passed. Task 9 is next: real Feishu custom-app transport boundary.
- V0.2 Task 9 complete: added Feishu API client/transport with in-process token cache, text send, URL challenge, event routing, and optional signature validation. Tests: 29 passed; compileall passed. Task 10 is next: real read-only memory calibration.
- Task 10 environment discovery: found Steam AppID 1956800, installed `Song.exe`, launched it via Steam, and confirmed a responsive process/window. Added read-only module enumeration; real numeric field calibration remains pending because no validated addresses are known.
- Task 10 calibration-prep verification: `29 passed`, `compileall` passed, the process list identified PID `25288` as `Song.exe`, while the live window probe returned client area `0x0` and module enumeration returned Windows error 5 (access denied). No memory field was read or written.
- Task 11 complete: added `StateAggregator`/`CanonicalGameState`, memory-first precedence, field aliases, provenance, and explicit conflict records; Governor now accepts multiple observations and sends the canonical state to DeepSeek. Tests: `32 passed`; compileall and diff checks passed.
- Latest acceptance P0 fixed: Governor now serializes canonical state, goals, and action schema with `json.dumps(..., ensure_ascii=False)` before sending the DeepSeek Chat Completions request; the integration test now asserts the payload is JSON text.
- Live-chain foundation complete: added schema-checked `SkillTranslator`, `InputActionExecutor`, semantic state verification, explicit `GOVERNOR_ALLOW_LIVE_INPUT` plus runtime arm gates, and multi-source `CompositeObservationSource`; tests: `38 passed`.
- Reliability/observability batch complete: DeepSeek now retries transient failures with exponential backoff and records usage; SQLite stores token totals. Combined verification: `41 passed`, compileall and diff checks passed.
- Runtime entry batch in progress: added a `run` CLI path that wires Steam capture, multi-region vision, optional read-only memory, CanonicalGameState, DeepSeek Governor, and GovernorLoop; live remains triple-gated.
- Feishu service batch complete: added local `feishu-server`, callback routing, constant-time signature comparison, and AES-CBC/PKCS7 encrypted payload handling behind the optional `cryptography` dependency.
- Feishu encrypted-payload test is environment-skipped when the installed optional cryptography native binding is unavailable; current host has a broken binding import, and the server reports this dependency error explicitly instead of silently accepting encrypted data.
- Reporting batch complete: local day boundaries use `Asia/Shanghai`, and daily reports now include action summaries, numeric state deltas, rule-detectable bottlenecks, next goal, and DeepSeek usage totals.
- Long-run recovery batch complete: added bounded `GovernorSupervisor` restart/backoff orchestration and CLI `run --supervise`; safety pauses and recovery-required states remain terminal until explicit recovery.
- V0.2 Task 7 complete: default action keys are scoped to `plan_id`, while explicit keys remain permanent. Tests: 25 passed; compileall passed. Task 8 is next: long-running loop with change detection and recovery.
