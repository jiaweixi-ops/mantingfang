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
- Latest acceptance safety batch complete: live actions now require a non-empty semantic predicate and a fully translatable command sequence before the executor is called; invalid actions are recorded as blocked without input or recovery escalation.
- Latest acceptance foreground batch complete: the Win32 input path now checks that the exact game HWND is foreground immediately before SendInput. It fails closed and never auto-focuses another window.
- Latest acceptance skill-contract batch complete: the first whitelist covers build menu, category tabs, camera, pause/speed, finance/technology/policy, save, and dialog controls. These skills require calibrated UI commands; the translator does not invent hotkeys or coordinates.
- Verification for this batch: `47 passed, 1 skipped`; the one skip remains the host's broken optional `cryptography` native binding. Compileall and push are pending for this batch.
- ROI efficiency batch complete: `SteamVisionObservationSource` now hashes raw RGBA bytes per configured ROI, reuses cached structured observations when the ROI is unchanged, and only refreshes changed/expired regions. Verification: `49 passed, 1 skipped`; compileall and diff checks pass.
- UI calibration batch complete: Vision responses now validate normalized `ui_elements` bounding boxes; high-level Skills resolve their target element center from the current cached observation and reject raw coordinate command arrays. Default runtime regions now include `build_menu` and `dialog`. Verification: `52 passed, 1 skipped`; compileall and diff checks pass.
- Feishu decision/media batch complete: the HTTP transport can upload PNG screenshots and send image messages; major events send an available screenshot before text, and pending decision events accept only explicit `选择方案 <内容>` or `交给AI` replies. Decisions persist in runtime state and resume the watchdog; plain `继续托管` cannot bypass a pending event. Verification: `55 passed, 1 skipped`; compileall and diff checks pass.
- CI batch complete: added GitHub Actions coverage for Python 3.11 and 3.12, package installation, pytest with third-party plugin autoload disabled, compileall, and whitespace checks. Remote CI execution is pending GitHub's run result.
- Latest acceptance P0 batch complete: ROI-local `bbox` values now gain a validated `global_bbox` through the RegionSpec transform; StateAggregator preserves `ui_elements_by_region`; Skill payloads require `target_region` plus `target_element`; Governor prompt no longer asks for `commands`; `SELECT_EVENT_OPTION` is whitelisted. Verification: `56 passed, 1 skipped`; compileall and diff checks pass.
- Major-event runtime batch complete: added deduplicated structured event detection, invoked it before strategy generation, saved the current client PNG for detected events, and connected configured Feishu credentials to `FeishuGateway`; without Feishu configuration events remain durably recorded and audited. Verification: `58 passed, 1 skipped`; compileall and diff checks pass.
- Vision sensitivity batch complete: ROI caching now compares 64x64 grayscale signatures with region-specific thresholds (`map` less sensitive than resources/events/dialog) and retains a forced refresh deadline. Large state changes still refresh the ROI while isolated animation pixels can remain cached. Verification: `58 passed, 1 skipped`; compileall and diff checks pass.
- E2E harness batch complete: added `e2e-build-menu` with explicit confirmation, live/armed/semantic gates, open-close cycle metrics, wrong-window classification, and fail-fast recovery handling. It is not executed automatically; real Steam acceptance remains pending calibrated UI IDs and a live run.
- Latest P0 remediation started: the next patch will make major-event pause/pending state independent of Feishu configuration and enforce required semantic Vision fields for the `build_menu` and `dialog` regions.
- Latest P0 remediation complete: `MajorEventCoordinator` now persists and pauses decision events before optional Feishu notification; the runtime uses it even without Feishu credentials, and the gateway avoids duplicate event persistence. Perception now requires `build_menu_open`/`dialog_open`, `current_screen`, and dialog `options` for the corresponding regions. Verification: `63 passed, 1 skipped`, compileall, and diff checks passed.
- P0 remediation delivery complete: committed as `40913c2` and pushed to `origin/main`; remote `main` resolves to the same SHA. GitHub Actions run `33968351733` completed successfully on Python 3.11 and 3.12. The worktree is clean. Real Steam E2E and real memory-field calibration remain unverified external steps.
- Overlay/settings task started: the existing desktop shortcut is a direct `cli run` launcher, which explains the missing `DEEPSEEK_REASONING_MODEL` error. The implementation will add a local saved-settings store, a Windows Tkinter overlay with global `Home` toggle and game-window tracking, and a shortcut update to launch it.
- Overlay/settings task complete: added `cli overlay`, a topmost Tkinter window that follows the game client, a global Win32 `Home` hotkey, local DeepSeek settings save/apply, and guarded start/stop controls for the dry-run Governor subprocess. Updated `C:\Users\奚嘉威\Desktop\满庭芳 AI Governor.lnk` to launch the overlay. Verification: `65 passed, 1 skipped`, compileall, diff check, module import, and hidden Tkinter construction smoke passed.
- Overlay delivery complete: committed as `92f1159` and pushed to `origin/main`; GitHub Actions run `33969654588` passed on Python 3.11 and 3.12. The repository worktree is clean and the remote branch resolves to the same commit.
# 2026-09-05 — Real Steam E2E acceptance attempt

- Confirmed the target repository is `E:\GAME\满庭芳：宋上繁华` and the worktree was clean before this acceptance attempt.
- Confirmed `Song.exe` is running and the current client geometry is `1280x960`; saved `data/e2e/preflight-window-info.json` and `data/e2e/preflight.png`.
- Confirmed local Feishu callback port `127.0.0.1:8787` is listening and the existing `cloudflared` process is responsive; preserved both processes.
- Confirmed the stale autonomous `cli run` process is no longer present. No full Governor loop was started.
- Preflight is currently blocked: the exact `Song` window is not foreground (`ChatGPT` is foreground), so live input must not be armed. The captured frame also contains a visible assistant-panel obstruction and is not a stable build-menu calibration frame.
- No `arm-live`, `e2e-build-menu`, mouse/keyboard input, or game action was executed.
- Re-ran the read-only checks after the user asked to continue: `Song.exe` remains responsive at `1280x960`; `127.0.0.1:8787` remains listening; the existing Cloudflare session remains alive and reconnects successfully. Foreground is still `ChatGPT`, and the captured PNG is byte-identical to the obstructed frame.
- Saved safe failure evidence: `data/e2e/failure_before.png`, `data/e2e/failure_report.json`, and `data/e2e/e2e_summary.md`. Vision calibration was intentionally not called because the foreground and frame-stability gates failed.

# 2026-09-05 — E2E preflight remediation

- Changed `Win32ClientCaptureBackend` default raster operation from `SRCCOPY | CAPTUREBLT` to `SRCCOPY`; `CAPTUREBLT` remains defined only for explicit future diagnostic use.
- Added bounded capture diagnostics: HWND, client dimensions, backend, raster mode, near-black detection, and `CAPTURE_BLACK_FRAME` status. Runtime capture rejects near-black frames without any CAPTUREBLT fallback.
- Added `SteamWindowAdapter.wait_for_foreground()` with a 30-second default timeout, 500ms polling, and 3-second continuous foreground requirement. It never calls a focus or activation API.
- Added read-only `e2e-preflight --wait-for-game-foreground` and the matching opt-in flag on `e2e-build-menu`; after the foreground gate passes, the preflight captures PNG and checks the `build_menu` and `dialog` Vision schemas automatically.
- Added tests for SRCCOPY-only defaults, near-black diagnostics, stable foreground waiting, and `FOREGROUND_TIMEOUT`.
- Verification: `69 passed, 1 skipped`; `compileall: PASS`; CLI parser smoke passed; real read-only capture reported `raster_mode=SRCCOPY`, `near_black_frame=false`; a 1-second wait smoke returned `FOREGROUND_TIMEOUT` as designed.
- No `arm-live`, no `e2e-build-menu`, no mouse/keyboard input, and no full Governor loop were run.

# 2026-09-05 — Read-only preflight foreground decoupling

- Changed read-only `e2e-preflight` so a non-game foreground window is diagnostic-only; it no longer calls `require_foreground()` unless the optional wait mode is explicitly requested.
- Added Windows `GetWindowThreadProcessId` diagnostics for game and foreground HWNDs, including PID, process name, title, exact-HWND match, same-process state, and `FOREGROUND_SAME_GAME_PROCESS_DIFFERENT_HWND` marker. Live SendInput still requires the exact game HWND foreground on every input.
- Required `ui_elements` lists in the `build_menu` and `dialog` Vision schemas and added OPEN/CLOSE element summaries to `preflight_vision.json`.
- Added a read-only fallback from the persisted Chinese title to the current Steam window title `Song`; no Live runtime title or input guard was changed.
- Real read-only run located Song HWND `11866876`, PID `39408`, client `1280x960`; foreground was ChatGPT HWND `722980`, PID `12116`, process `ChatGPT.exe`. Capture passed with `SRCCOPY` and `near_black_frame=false`.
- The current frame visibly retains a left-top assistant panel obstruction (approximately `x=0..318`, `y=70..350`), saved as `data/e2e/preflight_overlay_failure.png`. Vision did not run successfully because the persisted DeepSeek Vision model is rejected by the API with HTTP 400; `data/e2e/preflight_vision.json` now records the safe partial diagnostic.

## 2026-09-05 — WGC remediation started

- Recovered the prior plan and verified the current worktree is the uncommitted foreground-decoupling batch on top of `c39d0a7`.
- Confirmed the real WGC package is installed in `.venv` and a live Song HWND frame probe succeeded without input or focus changes.
- Next: implement backend/crop/diagnostic/probe, update production selection, add tests, then run only read-only verification.
- WGC backend, DWM-aware client crop, production selection, capture-diagnostic CLI, and safe DeepSeek error metadata are implemented. Real diagnostic now passes WGC and classifies the visible GDI panel as capture contamination; PrintWindow is diagnostic-only and failed closed with Win32 error 5.
- Final local verification before delivery: `79 passed, 1 skipped`; `compileall PASS`; `git diff --check PASS`; real `capture-diagnostic` WGC PASS at 1280x960; `vision-probe` PASS with HTTP 200 and usage; read-only WGC preflight PASS with valid build_menu/dialog schemas. Default OPEN/CLOSE IDs were not returned by Vision in this already-open-menu frame, so no coordinates or Live action were attempted.
- Delivery: implementation commit `d34cfaf89f1b3d542d93bb4ccbdab70b38034efb` pushed to `origin/main`; GitHub Actions run `33974476370` passed on Python 3.11 and 3.12. No Live input, `arm-live`, or `e2e-build-menu` was executed.

## 2026-09-05 — Semantic build-menu calibration started

- Current baseline is pushed at `6e70e04`; WGC and Vision are healthy, but default OPEN/CLOSE IDs were not found in the open-menu frame.
- Implementing role-to-canonical normalization, `build_controls`, read-only state calibration, and explicit readiness fields before using any E2E target.
- OPEN state calibration PASS: selected close target `build_menu_close_control` in `build_controls` with confidence 0.90. No input was sent. Waiting for manual menu close before CLOSED calibration.
- CLOSED state calibration PASS: `build_controls` required the permitted full-client fallback; selected open target `build_menu_open_control` with confidence 0.90. Final `build_menu_calibration.json` is `SEPARATE`, both states validated, `live_e2e_ready=true`.
- Calibration verification: `83 passed, 1 skipped`; compileall PASS; diff check PASS. No `arm-live`, SendInput, or `e2e-build-menu`.
- Delivery: semantic calibration commit `4fe9f57f8622f1bedee21004de54c49a38811db5` pushed to `origin/main`; GitHub Actions run `33975717301` passed on Python 3.11 and 3.12. `build_menu_calibration.json` remains local under ignored `data/e2e/`.
- Verification after the changes: `72 passed, 1 skipped`; compileall PASS; diff check PASS; `live_armed=false`; no input was sent and no Live E2E was executed.

# 2026-09-05 — Runtime Calibration Contract

- Current issue: the closed-state full-client calibration evidence found the real open control in the upper-right, but the artifact mislabeled it as `build_controls`; `e2e-build-menu` also still hardcoded a stale runtime region list.
- Scope for this batch: formalize `build_entry`, re-run target resolution through formal ROIs, reject unmappable full-client evidence, wire runtime regions from calibration, and add a read-only current-frame resolver.
- Safety boundary: no `arm-live`, no SendInput, no mouse/keyboard, and no `e2e-build-menu`.
- Implementation verification after the resolver/ROI patch: `89 passed, 1 skipped`; Python 3.11 `compileall` PASS; `git diff --check` PASS.
- Closed-state live calibration PASS: Song HWND `11866876`, PID `39408`, WGC `1280x960`, `build_entry` target resolved twice at confidence `0.95`; no fallback and no input.
- Open-state calibration first attempt found the correct close semantic at `0.85`; the flow was adjusted so sub-0.90 candidates can enter the required formal-ROI second pass while the final gate remains `>=0.90`.
- Open-state retry was blocked because Song.exe/window was no longer running (`game window not found: Song`); final two-state calibration and read-only resolver remain pending a relaunch with the menu open.
- After relaunch, open-state formal calibration passed on Song HWND `526608`, PID `26320`, with `build_controls` close target confidence `0.90`; closed-state resolver passed on the same WGC client with `build_entry` entrance confidence `0.90`.
- Final local verification after semantic-family compatibility: `89 passed, 1 skipped`; Python 3.11 `compileall` PASS; `git diff --check` PASS. No Live E2E, arm-live, or input was executed.
- Delivery: commit `12e022a118537a0caf34c7a1f47b4dc6a7868630` pushed to `origin/main`; local and remote SHA match. GitHub Actions run `34006800721` passed on Python 3.11 and 3.12.

# 2026-09-06 — V2.3 Live Roundtrip

- Status: implementation and local verification complete; real controlled attempt pending.
- Added `run_live_build_menu_roundtrip` and CLI command `e2e-build-menu-roundtrip --confirm-live-roundtrip`.
- Safety contract: live mode plus runtime arming, exact Song HWND foreground, same PID, WGC/non-black capture, current calibrated target confidence >= 0.90, exactly one click per transition, and Vision postcondition checks.
- Previous authorized attempts were fail-closed before any input: foreground timeout, then incomplete dialog Vision schema. Added one bounded dialog-schema retry and strengthened the prompt.
- Verification: `92 passed, 1 skipped`; compileall PASS; `git diff --check` PASS.
- Next action: execute one authorized two-click roundtrip only, then inspect `data/e2e/build_menu_roundtrip.json` and phase PNGs. No placement/building.

## 2026-09-06 — Live Attempt Closed Safely

- Result: FAIL, stopped after one input. The exact foreground HWND/PID and WGC capture gates passed, but the menu did not visibly open after the first click.
- `total_inputs=1`, `unexpected_inputs=0`, `retry_input=false`; no close click, no placement, and no further game input.
- Final database state: `live_armed=false`.
- Evidence: `data/e2e/build_menu_roundtrip.json`, `data/e2e/build_menu_roundtrip_closed_before.png`, and `data/e2e/build_menu_roundtrip_open_after.png`.

## 2026-09-06 — Read-only Click Audit

- Existing screenshot comparison completed; the map remained visible and no build-menu panel appeared after the first click.
- Click audit completed for bbox `[0.772, 0.08775, 0.7952, 0.12285]`: client `(1003,101)`, screen `(1101,191)`, origin `(98,90)`, DPI `96`.
- Target drift explained: persisted calibration uses the toggle role/ID, while current Vision assigns the explicit open role/ID; compatibility is role-scoped and recorded.
- Added structured read-only checkpoints at 200ms, 500ms, 1000ms, and 2000ms to future post-click verification. No Live E2E was rerun.
- Verification after changes: `93 passed, 1 skipped`; compileall PASS; diff check PASS.

## 2026-09-06 — Input Injection Audit Complete

- Implemented and tested the input audit layer only; no Live command was run.
- Corrected `SendInput` absolute mapping for multi-monitor virtual desktops.
- Added cursor-position verification, separate mouse down/up calls, 50ms down/up interval, foreground/PID rechecks, and return-count reporting.
- Verification: `95 passed, 1 skipped`; compileall PASS; diff check PASS.
- Next gated action remains a separate open-only Live diagnostic with a maximum of one click, pending explicit authorization.

## 2026-09-06 — V2.3C Open-only Attempt

- Open-only command and tests are complete: `97 passed, 1 skipped`; compileall PASS; diff check PASS.
- The authorized real attempt stopped before input because the menu was already open at precondition time.
- `total_inputs=0`; final `live_armed=false`. No close or placement input was sent.
- Next action is user-side only: manually close the build menu, then explicitly authorize one new open-only attempt.

## 2026-09-06 — Open-only UI Visibility Blocker

- The retry reached Song foreground but stopped before input because F2 had hidden the full HUD, including the calibrated build entry and bottom construction UI.
- `total_inputs=0`; final `live_armed=false`.
- User action required: press F2 once to restore HUD visibility, then authorize the open-only attempt again.

## 2026-09-06 — V2.3C PASS

- Open-only Live E2E passed after HUD restoration.
- Exactly one audited click was sent; all four read-only checkpoints reported `build_menu_open=true`.
- Input audit: cursor move verified, down/up return counts both `1`, foreground and PID stable.
- No close action, placement action, keyboard input, or retry occurred. Runtime disarmed automatically.
- Evidence: `data/e2e/build_menu_open_only/result.json`, `before_annotated.png`, and `after_200ms.png` through `after_2000ms.png`.
- Next gated phase: V2.3D close-only; do not start it automatically.

## 2026-09-06 — V2.3D preparation

- Implemented the close-only CLI and runtime path with `max_clicks=1`, `retry_input=false`, open/placement/keyboard disabled, current-frame target resolution, Win32 input audit, and read-only checkpoints at 200/500/1000/2000ms.
- Verification completed: `99 passed, 1 skipped`; compileall PASS; diff check PASS.
- Next: run exactly one authorized close click while the user keeps the already-open menu and Song window visible; then stop without starting roundtrip.

## 2026-09-06 — V2.3D first attempt and bounded diagnosis

- First close-only attempt failed closed before input: current `build_controls` Vision did not resolve the calibrated CLOSE element. Evidence is in `data/e2e/build_menu_close_only/result.json` and `before.png`; `total_inputs=0`, `arm_live=false`.
- Read-only Vision of the existing formal `build_entry` ROI found the visible close control at confidence `0.95`; added a bounded runtime-region fallback from `build_controls` to `build_entry`, with no coordinate fallback and no input retry.
- Next action remains one close-only attempt after verification; V2.3E roundtrip is still explicitly out of scope.

## 2026-09-06 — V2.3D bounded ROI correction

- The next attempt also sent zero input because the old `build_controls` ROI reported a state mismatch even though the saved screenshot visibly showed the open panel.
- Updated the bounded fallback to switch to `build_entry` on either target absence or old-ROI state mismatch, then require the richer current-frame `build_menu_open=true` and CLOSE target before input.
- Verification after this correction: `100 passed, 1 skipped`; compileall PASS; diff check PASS.

## 2026-09-06 — V2.3D final bounded result

- The final close-only execution stopped before input because the current-frame Vision precondition did not stably confirm `build_menu_open=true`, despite a valid Song capture. `total_inputs=0`, `unexpected_inputs=0`, and `arm_live=false`.
- V2.3D is not marked PASS. The implementation and tests are ready, but a future attempt needs a stable open-state Vision result; V2.3E remains blocked and was not executed.

## 2026-09-06 — V2.3X probe started

- Resumed the latest requested direction: inspect the game model and save format instead of continuing unstable build-menu Vision verification.
- Confirmed the repository is on `main`, clean, and aligned with `origin/main` before probe work.
- Confirmed `Unity.Model.dll`, `Assembly-CSharp.dll`, and `Sirenix.Serialization.dll` in the installed Mono managed directory.
- Confirmed `common.record`/`common.tmp` are identical Odin-serialized common data files and retained both originals unchanged.
- No Live E2E, no `arm-live`, no mouse/keyboard input, no process-memory write, and no repository code changes have been made in this phase.
- Next command: enumerate Odin read-only deserialization entry points and inspect `RecordData`/save routing.

## 2026-09-06 — V2.3X probe result

- Enumerated `Sirenix.Serialization.SerializationUtility`; it supports weak and typed read-only deserialization, but the available common files use the .NET BinaryFormatter envelope.
- Used an isolated .NET Framework parser with a local assembly allow-list to deserialize only the existing `common.record`/`common.tmp` files. Both yielded `WSFramework.CommonData`; no writes, save calls, or game process injection occurred.
- Inspected `WSFramework.RecordData`, `BaseData`, `SceneData`, `BuildingData`, `DataComponent`, and the `RecordPath`/load/save API surface. No active-city record file exists under the current Song save tree, so the live city-state bridge cannot yet be validated from disk.
- Installed only missing test-environment packages in `.venv` (`pytest`, `tzdata`); no project dependency declaration was changed.
- Verification: `101 passed`; `python -m compileall -q src` PASS; `git diff --check` PASS. No Live E2E, no `arm-live`, no mouse/keyboard input, and no memory writes.

## 2026-09-06 — V2.3X2 pre-save baseline

- Recorded the current Song save-root inventory and SHA-256 metadata in an external temporary baseline file; no save API was called and no original file was copied or modified.
- Current candidate tree still contains only `common.record`/`common.tmp` plus logs/settings/Unity analytics; no active city record is present before the manual save.
- Waiting for the user to manually save one city in the game. After confirmation, the next action will be a read-only before/after comparison and parsing of copied candidates only.

## 2026-09-06 — V2.3X2 Save State Extraction PASS

- User manually saved the city; the before/after scan found `Version2\\117224508162075.index` and `Version2\\117224508162075.record`.
- Copied both candidates to ignored `data/probe/117224508162075/`. The `.record` ZIP payload was copied to an ignored local payload file for parsing; no original path was written.
- Read-only .NET Framework parsing confirmed `RecordData` metadata and `RootData` state. Extracted city name, year/month, gold, core resources, population count, building count, and visible-resource count.
- Cross-check: `新的城市`, year 1, gold 1000, rice/vegetable 50, wood/stone 100, and population 10 agree with the new-city HUD values observed before saving; month 4 is the serialized zero-based month index.
- V2.3X2 is PASS. No Live E2E, no `arm-live`, no mouse/keyboard input, and no process-memory write.

## 2026-09-06 — V2.3X3 scope resumed from latest conversation

- Read the latest conversation turns and inspected `Mantingfang_AI_Governor_V5_Full.zip` in an isolated temporary directory.
- The ZIP contains useful direction but several placeholders: its SaveInspector returns `adapter_ready` without parsing, and its RuntimeBridge requires external BepInEx/Unity references not included in the archive. It will not be copied wholesale.
- New implementation scope is Qwen-only provider/config migration plus a fail-safe read-only telemetry client and a separately buildable bridge reference. Existing WGC, Win32 input audit, foreground/PID gates, save extraction, and Live E2E fail-safe behavior remain protected.

## 2026-09-06 — V2.3X3 Qwen and read-only telemetry implementation

- Added `QwenClient` using the standard library against the OpenAI-compatible Qwen Chat Completions endpoint, with retry, usage accounting, image content-parts, and API-key-safe errors.
- Migrated runtime Governor, Vision, overlay settings, reports, `.env.example`, README, and CLI help to Qwen configuration; retained old DeepSeek fields/module only as local compatibility data and test doubles, not as the production provider.
- Added `RuntimeTelemetryClient`, `RuntimeTelemetryObservationSource`, and `telemetry-read`. Missing bridge or `UNKNOWN/BLOCKED` state fails closed and never fabricates zero values.
- Added `runtime_bridge/README.md` with the loopback-only, read-only `/health` and `/state` contract. The supplied V5 bridge remains reference-only because its BepInEx/Unity assemblies are not installed or verified here.
- Added provider/telemetry tests, including rejection of incomplete `status=OK` snapshots. Verification: `107 passed`, `python -m compileall -q src` PASS, `git diff --check` PASS. No Live E2E, `arm-live`, mouse/keyboard input, process-memory write, or secret file was used.

## 2026-09-06 — V2.3X4 runtime safety closure

- Removed DeepSeek code, settings, fallback, and test references; `rg -i deepseek src tests .env.example pyproject.toml` now returns zero matches. README keeps only the explicit statement that DeepSeek is not used.
- Runtime telemetry now requires `game_pid`, `game_version`, timezone-aware `observed_at`, and complete core city fields; PID/version mismatch and snapshots outside the two-second age window fail as `RUNTIME_PROCESS_CHANGED`, `RUNTIME_VERSION_MISMATCH`, or `RUNTIME_STALE`.
- Production Live runtime locks Song PID, and the input adapter supports opt-in `GOVERNOR_AUTO_FOREGROUND`, stable foreground waiting, previous-window restore, and fail-closed activation errors. Default remains automatic foreground disabled.
- Vision UI targets now carry HWND/PID/client geometry/origin/DPI snapshots. Any change before input returns `TARGET_STALE` and prevents mouse down/up.
- Added `runtime_bridge/Plugin.cs`, `TelemetryServer.cs`, `ReadOnlyStateReader.cs`, and a conditional-reference `.csproj`. It is source-complete as a read-only reference but has not been injected or built against external BepInEx/Unity assemblies on this machine.
- Added a Windows GitHub Actions job for Python 3.11/3.12 import, tests, compileall, and diff check. Local verification: `111 passed`, compileall PASS, diff check PASS. No Live E2E, `arm-live`, game input, process-memory write, or secret file was used.

## 2026-09-06 — Windows CI timezone dependency fix

- The first post-push Windows CI run failed in four report/Feishu tests because Windows Python had no IANA timezone database for `ZoneInfo("Asia/Shanghai")`; Linux jobs passed.
- Added `tzdata>=2022.7` to the package runtime dependencies so both editable installs and normal installs provide the required cross-platform timezone data.
- No game process, Live Input, credentials, or E2E command was touched; rerun local tests and CI before considering this phase complete.
