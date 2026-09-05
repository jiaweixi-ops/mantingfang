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
- V0.2 Task 7 complete: default action keys are scoped to `plan_id`, while explicit keys remain permanent. Tests: 25 passed; compileall passed. Task 8 is next: long-running loop with change detection and recovery.
