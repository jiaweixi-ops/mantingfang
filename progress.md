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

- CI rerun `34024937213` passed `pytest (3.11)`, `pytest (3.12)`, `windows-core (3.11)`, and `windows-core (3.12)`.

## 2026-09-06 — V2.3X3 Runtime telemetry hardening

- Corrected the C# bridge inventory path to `BaseData.CenterStoreData.Res` and emit only the validated `rice`, `vegetable`, `wood`, and `stone` fields plus gold; incomplete reflection results now return `UNKNOWN`.
- Moved Unity sampling into `Plugin.Update`; `TelemetryServer` now returns only the last serialized main-thread snapshot and never reflects Unity objects on its HTTP worker.
- Added strict Python value/type validation, including required named resources and boolean `build_menu_open`; runtime telemetry now fails closed unless `GOVERNOR_RUNTIME_GAME_VERSION` is configured when enabled.
- Made opt-in auto-foreground a complete action transaction: foreground activation, fresh observation-cache invalidation, current-frame target resolution, input, and restoration are one boundary.
- Added regression and source-contract checks; local verification is `116 passed`, compileall PASS, diff check PASS. The bridge remains unbuilt/uninjected because the required .NET/BepInEx/Unity SDK references are unavailable, and no Live E2E or game input was run.
- GitHub Actions run `34025738670` passed Linux Python 3.11/3.12 and Windows Python 3.11/3.12.

## 2026-09-06 — V2.3X3 final code-level closure

- Runtime Bridge sampling is now bounded to 4Hz (`250ms`) on Unity's main thread, with cached type/member/singleton reflection metadata; the HTTP worker still serves only immutable serialized JSON.
- `telemetry-read` now locates the current Song window, binds the current Song PID and required `GOVERNOR_RUNTIME_GAME_VERSION`, and returns exit code `2` for any connection, PID, version, stale, or schema failure.
- Added CLI binding and reflection-cache contract tests. Local verification: `118 passed`, compileall PASS, diff check PASS. No Bridge build/injection, Live E2E, or game input was performed.

## 2026-09-06 — V2.3X4 preparation read-only inspection

- Confirmed the installed game at `F:\SteamLibrary\steamapps\common\Thriving City Song` is Unity `2022.3.62f2` and contains the exact Mono assemblies needed for later reference matching.
- Confirmed no BepInEx/Doorstop loader is installed in the game directory, and `Song.exe` was not running. No installation, injection, process access, or game input was performed.
- Confirmed the ignored city-save probe remains available under `data/probe/117224508162075/` for the later Runtime-vs-Save comparison.
- X4 is blocked at the deliberate loader/build prerequisite. The next step requires a version-compatible loader decision and a running game; keep `GOVERNOR_RUNTIME_TELEMETRY=false`.
- After the user started the game, read-only verification found responsive `Song.exe` PID `23392`, HWND `30738232`, and no listener on `127.0.0.1:18765`. BepInEx/Doorstop is still absent; no focus change, injection, input, or game-file modification was performed.
- After explicit confirmation, installed the verified official x64 BepInEx `5.4.23.5` package into the game root. SHA-256 matched the supplied value and the bundled Doorstop version is `4.5.0`; no separate Doorstop or project Bridge was installed. The game was not restarted, and the real Bridge build is blocked locally because no .NET SDK is installed.
- After the subsequent game restart, read-only module inspection confirmed the game loaded the root `WINHTTP.dll`, but no BepInEx `LogOutput.log`, `config`, or `plugins` artifacts appeared and no Chainloader markers were present in `Player.log`. BepInEx boot remains unconfirmed, so Bridge installation was not attempted.
- Build-tool inspection found no .NET SDK, no `msbuild.exe`, and no .NET Framework 4.7.2 reference assemblies. X4 remains blocked before production Bridge build/load; no input, injection, save write, or telemetry enablement occurred.

## 2026-09-06 — BepInEx Doorstop diagnosis

- Completed the requested read-only Doorstop diagnosis and wrote ignored evidence to `data/probe/BEPINEX_BOOT_DIAGNOSTIC.json`.
- Confirmed `doorstop_config.ini` is enabled, the target Preloader exists, all 21 installed package files match the verified archive lengths, Doorstop environment overrides are not set, and the game loaded the game-root `WINHTTP.dll`.
- Found the first concrete failure in `preloader_20260906_182826_640.log`: BepInEx Preloader throws `System.MissingMethodException` for `System.Reflection.Module.GetPEKind(...)` under the game's Unity Mono runtime. `BEPINEX_BOOT=FAIL`; Bridge build/load and `/health`/`/state` remain blocked.
- No configuration or game-file changes were made during diagnosis; no SDK was installed, no Bridge DLL was built/copied, and no Live/input/save/memory operation occurred.

## 2026-09-06 — V2.3X4-B corlib override prepared

- Downloaded and staged official Unity 2022.3.62 corlibs; ZIP hash and complete 15-entry inventory are recorded in the ignored `data/probe/V2.3X4B_corlib_manifest.json`.
- Metadata-only inspection confirmed the staged `System.Reflection.Module.GetPEKind(out peKind, out machine)` method without loading the assembly.
- Backed up `doorstop_config.ini`, created `BepInEx\\unstripped_corlib`, copied the 15 official files, and changed only `dll_search_path_override`. `Song_Data\\Managed` was not overwritten.
- Preparation is complete and intentionally paused before restart. Awaiting the user's next game launch for the read-only BepInEx boot verdict.

## 2026-09-06 — V2.3X4-B restart check inconclusive

- Read-only inspection after restart found responsive `Song.exe` PID `25644` with the game-root `WINHTTP.dll` loaded and the corlib override still present.
- No fresh preloader log, BepInEx log, config directory, plugins directory, or updated Player.log was produced. The override cannot yet be classified as passing or failing; the phase remains blocked on fresh loader evidence.
- No configuration change, file deletion, loader replacement, Bridge installation, telemetry enablement, input, save write, or memory write occurred.

## 2026-09-06 — Doorstop-only bootstrap prepared

- Restored the exact pre-corlib Doorstop configuration after the game closed. The configured corlib override directory is no longer present; its official files remain in a clearly named rollback directory outside the configured search path because local safety policy rejected permanent recursive deletion.
- Added a minimal `net40` Doorstop entrypoint and CI artifact job. It is intentionally source/CI-only: no bootstrap DLL is installed, no debugger server is enabled, and no game configuration points at it.
- Local validation: `121 passed`, Python compileall PASS, and diff check PASS. CI artifact compilation is pending the pushed workflow run.
- GitHub Actions run `34029235704` passed the no-op `net40` bootstrap build and uploaded the `DoorstopTelemetryBootstrap` artifact; all existing Python, Windows, and bridge-compile jobs also passed.

## 2026-09-06 — Baseline start confirmed; debugger test awaits authorization

- The user confirmed the restored game entered normally. Read-only inspection verified responsive `Song.exe` PID `29884` / HWND `26216382` and the expected installation path.
- Doorstop configuration is still the exact pre-corlib baseline (`4D5C6DFA0F771C6A5B1B0C559ACA0BD0ECE7D08B08FFF894708DC3B73CE73CFC`), with blank `dll_search_path_override` and `debug_enabled=false`.
- A new Preloader log repeats only the known BepInEx 5 `Module.GetPEKind` compatibility failure; `LogOutput.log` remains absent. The game itself is usable, while BepInEx remains unavailable.
- Status: `READY_FOR_DOORSTOP_DEBUGGER_TEST`. The next step requires separate explicit authorization because it would change the Doorstop target/configuration. No bootstrap deployment, debugger activation, telemetry enablement, game input, save write, or memory write occurred.

## 2026-09-06 — Doorstop-only debugger transport test prepared

- Confirmed `Song.exe` was stopped and TCP port `10000` had no listener before changing the game-directory test configuration.
- Downloaded the exact CI artifact from run `34029294783`, verified its 3,584-byte DLL and SHA-256 `4ED5E6640E8C259561BAC2989249C18911790252C6E98A5C75AEB83797B7DADE`, and inspected its managed metadata without loading it.
- Installed only `DoorstopProbe\\DoorstopTelemetryBootstrap.dll`, then created a byte-for-byte Doorstop config backup with SHA-256 `4D5C6DFA0F771C6A5B1B0C559ACA0BD0ECE7D08B08FFF894708DC3B73CE73CFC`.
- Config diff contains exactly two changes: the target now points to the isolated bootstrap and loopback Mono debugging is enabled. `debug_address=127.0.0.1:10000`, `debug_suspend=false`, and the corlib override remains blank. New config SHA-256 is `7F259C46FEA4EC8DE746854EB7F82E71FDE5B562CF30A912611CE89E24F0A682`.
- Stopped at `READY_FOR_DOORSTOP_DEBUGGER_TEST`. The game was not launched, no debugger client connected, and no runtime field, input, save, or memory operation occurred.

## 2026-09-06 — Doorstop debugger transport real-game validation passed

- The user manually started the game. Read-only inspection found responsive `Song.exe` PID `30092`, HWND `11995626`, from the expected Steam path.
- `127.0.0.1:10000` has exactly one listener, owned by PID `30092`; a three-second follow-up sample confirmed the listener and responsive game process remained stable.
- There were zero established connections, so no debugger client was attached. Configuration hash remained `7F259C46FEA4EC8DE746854EB7F82E71FDE5B562CF30A912611CE89E24F0A682`.
- Result: `DOORSTOP_DEBUGGER_TRANSPORT=PASS`. Stopped before V2.3X4-D; no assembly enumeration, runtime-field read, telemetry enablement, input, save write, or memory write occurred.

## 2026-09-06 — V2.3X4-D client implementation pending CI

- Added a minimal `net472` Mono Soft Debugger client with one hard-coded loopback connection, root-domain assembly-name enumeration, and one disconnect path.
- Added a dedicated CI publish artifact plus source-contract tests that fail if prohibited debugger capabilities or retry loops enter the client.
- Local verification: `123 passed`, Python compileall PASS, and diff check PASS. No debugger connection has occurred; execution is blocked until the pushed CI artifact is built, downloaded, and verified.

## 2026-09-06 — V2.3X4-D minimal attachment passed

- CI run `34030256428` passed all jobs and produced the exact pinned `MonoAssemblyEnumerator` artifact for commit `4e614adcbf4ddc06fd2cf9367b16d2876071264d`.
- Verified the staged executable hash `BB310C44367D4BDAE4F08397D2C4C5C11461146D40E9AB997EC907700312B9C2` and `net472` managed metadata before running it.
- Performed exactly one loopback debugger connection under a five-second outer timeout. It returned 106 assembly names and confirmed `Unity.Model`, `Assembly-CSharp`, and `UnityEngine.CoreModule`.
- The client exited `0` and disconnected; `Song.exe` PID `30092` remained responsive and retained the sole `127.0.0.1:10000` listener, with zero established connections afterward.
- Result: `MONO_DEBUGGER_ASSEMBLY_ENUM=PASS`. No field, type, object, thread, frame, local, stack, invocation, breakpoint, suspend, write, telemetry, or input operation occurred; V2.3X4-E remains untouched.

## 2026-09-06 — V2.3X4-E started

- The user authorized the minimal type-existence phase and explicitly disabled DeepSeek Harness for this task; implementation is Codex-only.
- Planning scope is limited to four type-name booleans and one loopback connection with no retry. All runtime instance/state access and game input remain prohibited.
- Added the pinned `net472` `MonoTypeExistenceProbe`, a dedicated CI artifact job, and contract tests that reject broad type enumeration plus all unauthorized runtime/state/control APIs.
- Local verification passed with `126 passed`, Python compileall PASS, and diff check PASS. No V2.3X4-E debugger connection has occurred; execution awaits the exact CI artifact.
- Pushed commit `3cd24648cd279b7c19d54fb790c84482ed60893b`; CI run `34030731666` passed all eight jobs and published the verified `MonoTypeExistenceProbe` artifact.
- Executed exactly one connection attempt with a five-second outer timeout. It timed out with empty output, was terminated, and was not retried, so the four type-existence booleans remain unknown.
- Post-failure checks passed: the same Song PID remained responsive and owned the loopback listener, with zero established connections. Result is `FAIL_TIMEOUT_SAFE`; no later debugger phase was started.

## 2026-09-06 — V2.3X4-E2 started

- The user requested continuation after the safe E timeout. The diagnostic mutation is limited to flushed phase markers around connect, assembly location, each of the four exact type queries, and disconnect.
- The same type-only operation contract remains in force; no additional debugger capability or retry is being added. The next execution will again be one connection with an outer timeout.

## 2026-09-06 — V2.3X4-E2 completed safely

- CI run `34031118319` passed and the exact diagnostic artifact was verified before execution.
- The one allowed attempt timed out after five seconds with only `PHASE CONNECT_BEGIN`; no type query or disconnect marker was reached. The client was terminated and not retried.
- The game remained responsive with PID `30092`, the listener stayed owned by that PID, and established connections were zero.
- Result: `FAIL_TIMEOUT_AT_CONNECT`; type existence remains unverified. No later runtime-read phase was started.

## 2026-09-06 — V2.3X3 Bridge compile hardening

- Fixed `TryReadResource` to use the cached reader instance instead of calling instance reflection from a static method.
- Changed type discovery to cache only successful `Type` resolutions, so an early startup miss can be retried later.
- Added `runtime_bridge/compile-check/` with minimal BepInEx, Unity, and serializer stubs, and added a GitHub Actions `dotnet build` job that compiles the real bridge source files without installing or injecting the plugin.
- Local Python verification is pending this phase; the local machine has .NET runtimes but no SDK, so the C# compile check will be verified by CI. No Live E2E, `arm-live`, game input, process-memory write, or secret file was used.
## 2026-09-06 — V2.4A/B implementation started

- Re-read the latest project thread and confirmed the requested transition: Mono Debugger research-only; implement read-only Build Menu state detection and structure parsing.
- User constraint retained: Codex-only implementation, no DeepSeek Harness, no Live E2E, no `arm-live`, no SendInput, no save/process-memory writes, no Runtime Telemetry enablement, and no V2.5 placement.
- Repository was clean at `c3889f197078075d88a4ae0db35eaf04e6f6d9c7` before this phase.

## 2026-09-06 — V2.4A/B read-only model complete

- Added `src/ai_governor/build_menu.py` with fail-closed state detection for closed/root/category/selected/unknown states.
- Added strict category and building-option parsing, including confidence, normalized bboxes, locked flags, non-negative costs, and optional frame geometry snapshots.
- Added six focused tests (including malformed structures and a no-Qwen/no-input boundary check); full suite is `132 passed`.
- `compileall` and `git diff --check` pass. No game process, debugger, capture, model API, telemetry, or input path was invoked.
- GitHub Actions run `34031578192` completed successfully across Python 3.11/3.12, Windows 3.11/3.12, Bridge compile, and existing probe jobs. The implementation commit is `a7c72d8bbee3912c06ebf750cc4424b8289aa0d1`, and the follow-up record update is being pushed after this verification.

## 2026-09-06 — V2.4A/B-R started

- User authorized real-game read-only calibration with zero SendInput, keyboard/mouse input, map clicks, save writes, memory writes, Runtime Telemetry, and Mono Debugger.
- Required manual phases are preserved: closed menu first, then user opens the menu, then user enters one ordinary category. No phase will click or change the game.

## 2026-09-06 — V2.4A/B-R adapter code complete

- Added `src/ai_governor/build_menu_observer.py` and CLI command `e2e-calibrate-build-menu-readonly`.
- The adapter reuses WGC, `PerceptionEngine`, `RegionCatalog`, existing BUILD_MENU_OPEN/TOGGLE/CLOSE roles, and current HWND/PID/geometry metadata.
- Vision is bounded to one `qwen3.8-flash` calibration call per phase. Subsequent samples use fresh-frame local patch matching and current-frame bbox output; no prior bbox is used as an actionable target.
- Added observer tests; local full suite is `135 passed`. Real-game sampling has not started yet.
- Read-only preflight found no running `Song.exe`, so no WGC frame or Vision request was made. The calibration phase is waiting for the user to start the game and leave the Build Menu closed; no input or focus change was performed.
- First CLOSED attempt after the user started the game reached fresh WGC and made one bounded Vision request, but the model returned a top-level JSON array. No evidence file was written and no input was sent; the Vision prompt and boundary validation were tightened before retrying.
- CLOSED real-game phase passed: 3/3 samples classified `closed`, WGC `near_black_frame=false`, HWND/PID/client geometry/DPI remained stable, and `build_menu_toggle` was resolved at actionable confidence `0.95`. Evidence is ignored under `data/probe/V2.4ABR/closed/result.json`; no input was sent.
- ROOT_OPEN attempt: WGC and geometry remained stable across 3/3 samples and eight category candidates were returned, but the current-frame close control was omitted, so all three snapshots stayed `unknown` and the phase correctly failed closed. A targeted prompt clarification was added; the retry returned an invalid top-level JSON array, and the exceptional `qwen3.8-max` retry timed out. No accepted ROOT_OPEN evidence exists and no input was sent.
- Qwen usage note: the accepted CLOSED run and the first ROOT_OPEN attempt each used one bounded Vision call; later samples were local tracking only. Failed/timeout requests are not treated as calibration evidence. The interrupted final retry left no calibration process running.

## 2026-09-06 — V2.4A/B-R2 deterministic control/category fusion

- Added a strict structured PerceptionEngine path for category-only and option-only calibration. It rejects malformed/non-object model outputs as `CALIBRATION_MODEL_SCHEMA_FAIL` without broadening the generic Vision parser.
- Added a current-frame-only deterministic resolver for the upper-right red `BUILD_MENU_CLOSE` control in the existing `build_entry` RegionCatalog region. It derives its bbox from each fresh WGC frame and never treats a previous calibration bbox as actionable.
- ROOT_OPEN real-game calibration passed 3/3: WGC was healthy, Song HWND/PID/geometry remained stable, the local close resolver reported confidence `0.980664...`, and eight categories were reused only as non-actionable same-geometry seeds before current-frame tracking. This R2 root run made zero Qwen calls.
- The user manually entered a category. The one permitted `qwen3.8-flash` option calibration request returned an invalid response shape, was rejected as `CALIBRATION_MODEL_SCHEMA_FAIL`, and was not retried. `qwen3.8-max` was not called. CATEGORY_OPEN remains pending; V2.4C was not entered.
- Across R2 there were zero SendInput, keyboard/mouse input, map clicks, save writes, memory writes, Runtime Telemetry access, and Mono Debugger activity.

## 2026-09-06 — V2.4A/B-R3 deterministic Build Option geometry

- Added `src/ai_governor/build_option_detector.py`: a dependency-free current-frame slot detector restricted to the upper content band of the existing `build_controls` RegionCatalog ROI. It performs local foreground segmentation, horizontal component grouping, size/aspect/bounds filtering, overlap suppression, and row-wise left-to-right ID assignment.
- CATEGORY_OPEN now uses that detector on every one of the three fresh WGC frames rather than a first-frame model response or a stale target. Local close resolution remains independent in `build_entry`.
- Added synthetic tests for repeated option slots, root-tab/closed/map/close-control exclusions, invalid size/boundary candidates, overlap suppression, left-to-right IDs, and category center-drift rejection.
- Real-game CATEGORY_OPEN calibration passed: `category_open` 3/3, eight stable options, WGC healthy, stable Song HWND `134730` / PID `32776` / `1280x960` geometry / DPI `96`, slot confidence at least `0.9728`, IoU threshold `0.85`, and center-drift threshold `4.8px`.
- R3 invoked Qwen zero times and made zero SendInput, keyboard/mouse, map-click, save-write, memory-write, Runtime Telemetry, or Mono Debugger operations. All three V2.4A/B-R states now pass, so the result is `PASS_GEOMETRY_CALIBRATED`; V2.4C remains deliberately untouched.
# 2026-09-06 — V2.4C started

- Resumed from V2.4A/B-R3 `PASS_GEOMETRY_CALIBRATED` at commit `d8a5c15`.
- User authorized exactly one controlled category-tab click after fresh ROOT_OPEN preconditions; implementation is Codex-direct with no Harness and no Qwen calls.
- Added `build_category_navigator.py`, `build_category_e2e.py`, deterministic current-frame category-tab output, guarded dry-run/live CLI commands, and unit coverage. Full local verification: `146 passed`; no input has been sent.
- First V2.4C dry-run: fail-closed before any input because local category provenance was not retained by the parser. Applying a minimal observer-only provenance preservation fix; no Qwen or input involved.
- Fixed provenance preservation, reran dry-run successfully, then executed the authorized V2.4C one-click scenario. Result: PASS (`ROOT_OPEN -> CATEGORY_OPEN`), click count 1, fresh postcondition found 8 option slots, live automatically disarmed. Local evidence remains ignored at `data/probe/V2.4C/result.json`.
- Committed the V2.4C implementation and test/plan records as `4847274` (`feat: verify one-click build category navigation`); remote push and CI confirmation are next. No V2.4D action has been started.
- Delivery completed after amend as `10a1ac6aaf4c43eff1a31096ca5501d02fa6c2f4`; `origin/main` matches. GitHub Actions run `34035192744` completed successfully. V2.4C is complete and V2.4D remains untouched.
- V2.4D started from the user-provided read-only semantic parsing contract. No input or model call has been made in this phase yet.
- Added semantic dataclasses, strict coordinate-free Qwen schema, conflict precedence, affordability tri-state, current-card crop/montage helpers, read-only CLI wiring, and tests. Two local test failures were fixed before real-game execution; no input or Qwen call has occurred.
- First read-only live semantic attempt failed before HTTP due to a montage allocation bug; no Qwen request or input occurred. Corrected the canvas size and retained the one-call limit.
- Final V2.4D sample passed at `PASS_SEMANTIC_MINIMUM`: current CATEGORY_OPEN WGC frame produced 8 local slots and one strict `qwen3.8-flash` call resolved 8 labels and 8 tri-state lock values; costs stayed `{}` because no complete resource/quantity pair was reliable. No input, map/build click, save, memory, telemetry, or debugger operation occurred.

## 2026-09-06 — V2.4D delivery completed

- The real read-only semantic sample completed as `PASS_SEMANTIC_MINIMUM`: 8 current-frame options, 8 real labels, and 8 model-reported tri-state lock values. Costs remained unresolved, so the result is not `PASS_SEMANTIC_CALIBRATED`.
- Exactly one `qwen3.8-flash` call was used; `qwen3.8-max` calls and retries were zero. Geometry stayed bound to the fresh WGC frame; model coordinates were rejected and never became actionable.
- Safety counters remained zero for SendInput, mouse/keyboard, map/build clicks, save writes, memory writes, Runtime Telemetry, and Mono Debugger.
- Code commit `5733160f65165d190b2eb6516d61f475ee1f2090` passed full local pytest (`155 passed`), compileall, diff check, and GitHub Actions run `34035801305`.
- This follow-up only records delivery status. V2.4E was not started, and `data/probe/V2.4D/result.json` remains ignored.

## 2026-09-06 — V2.4E0 started

- User requested read-only BUILDING_SELECTED / PLACEMENT_ARMED and CANCEL calibration after V2.4D `PASS_SEMANTIC_MINIMUM`.
- Scope is limited to a fresh CATEGORY_OPEN baseline, manual building selection, current-frame placement evidence, current-frame cancel calibration, manual cancel, and post-cancel read-only verification.
- No automatic input, map target, placement target, Qwen call, telemetry, debugger, save write, or memory write is authorized.
- Initial CLI attempt stopped safely at the baseline because the fresh frame classified as `UNKNOWN` rather than `CATEGORY_OPEN`. No manual selection prompt was reached and no input/model call occurred; the workflow is waiting for a fresh user-held ordinary category page.
- Second read-only run started from a valid `CATEGORY_OPEN` baseline with 8 options and stable WGC geometry. After one user click, current-frame evidence detected `BUILDING_SELECTED` with confidence `0.9648`, three independent signals, and a `BUILD_PLACEMENT_CANCEL` candidate at confidence `0.98`.
- The user then manually cancelled. The post-cancel WGC frame remained `UNKNOWN` and still contained red candidates, so the workflow returned `FAIL_SAFE_PLACEMENT_UNKNOWN`; it sent no input and did not claim V2.4E0 PASS.
- The implementation was tightened to record the manual selection count, distinguish a persistent selected cancel candidate from other red controls, and preserve fail-closed post-cancel handling. Full local verification remains `162 passed`, compileall PASS, diff check PASS.
