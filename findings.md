# Findings

## 2026-09-05 — Initial recovery

- Target workspace: `E:\GAME\满庭芳：宋上繁华`.
- The target directory is empty; there is no `.git`, source tree, test suite, config, or existing user data to preserve.
- The referenced ChatGPT task is a completed planning conversation titled `满庭芳自动经营分析`.
- The conversation's final architecture is a Steam Windows AI Governor with six major subsystems: perception, game state, DeepSeek governor, action engine, Feishu gateway, and recovery/watchdog.
- Important behavior decisions from the conversation: DeepSeek-only AI, region-first visual analysis, persistent state and long-term/phase/current goals, on-demand daily reports, proactive major-event notifications, and a Feishu custom app/bot for bidirectional control.
- The plan explicitly distinguishes deterministic program work (screenshots, OCR, mouse/keyboard, logging, SQLite, scheduling) from DeepSeek reasoning.
- The project cannot claim live game automation until a real Steam window, game-specific UI calibration, and user-provided DeepSeek/Feishu configuration are available.
- The current Windows process diagnostic listed Steam processes but no clearly identifiable 满庭芳 game process; no process handle was opened for a guessed target.
- No real memory profile or stable addresses are known. The repository therefore ships only an example profile and a read-only sampler; it does not pretend to extract live population/resources yet.
- Steam library inspection found AppID `1956800` (`Thriving City: Song`) at `F:\SteamLibrary\steamapps\common\Thriving City Song`, with executable `Song.exe`. After launching through Steam, the process was observed as responsive with window title `Song`; this identifies the target process but does not provide field addresses.
- Live diagnostics against that process were fail-closed: `window-info --title Song` reported a `0x0` client area, and `memory-modules --process-name Song.exe` received Windows error 5 (access denied). These are recorded as calibration blockers, not reasons to guess addresses or enable writes.

## Technical direction

## 2026-09-05 — E2E preflight remediation findings

- `CAPTUREBLT` was the direct cause of layered/overlay content being eligible for the GDI capture path. The normal backend now passes the exact `SRCCOPY` raster operation; no automatic fallback exists.
- A near-black frame is classified locally from sampled RGBA pixels. The diagnostic is safe to print and contains no credentials. Runtime capture can fail closed with `CAPTURE_BLACK_FRAME` so a black frame cannot reach Vision or trigger guessed input.
- Foreground waiting is implemented at the window adapter boundary with injected clock/sleep functions for deterministic tests. It only observes `GetForegroundWindow()` and never calls `SetForegroundWindow()` or input APIs.
- The new `e2e-preflight` command is read-only and requires only the DeepSeek API key plus Vision model. It does not require live mode, arming, or the reasoning model.
- Read-only foreground decoupling is safe only when scoped to `e2e-preflight`: the capture path can inspect a valid HWND while another app is foreground, but `WindowsSendInputAdapter` continues to compare the exact game HWND immediately before every input.
- The installed Steam window is currently titled `Song` while the persisted default title is Chinese; the read-only command now has a narrow fallback to `Song` after the configured title is not found. This fallback does not alter the Live runtime window title.
- A real SRCCOPY capture succeeded but still visibly included the assistant panel at the client area's upper-left. This is evidence that the current GDI window-DC capture semantics need a future PrintWindow/Windows Graphics Capture evaluation; no CAPTUREBLT fallback was added.

## 2026-09-05 — WGC remediation handoff

- User confirmed the apparent assistant panel is not physically present in the game; classify the current GDI result as `GDI_CAPTURE_CONTAMINATION` / capture-backend artifact, not a user overlay.
- The installed `windows-capture==2.0.1` package successfully captured the live Song HWND `11866876` in a one-frame probe. The raw frame was `1282x992`; the Song client is `1280x960`, requiring a client-coordinate crop rather than a desktop crop.
- Production must use WGC and fail closed if WGC is unavailable or fails. Do not silently fall back to GDI, PrintWindow, CAPTUREBLT, or desktop capture.
- The current persisted DeepSeek Vision model is rejected by the API with HTTP 400; target model is `deepseek-v4-flash-vision-exp` at `https://api.deepseek.com`.
- Real `capture-diagnostic` result: GDI succeeded at 1280x960 but visibly included the AI Governor panel; WGC succeeded at 1280x960 with a clean Song client; PrintWindow returned Win32 error 5. The WGC crop must use DWM extended frame bounds because `GetWindowRect` included invisible resize borders (1296x999 vs WGC 1282x992).

## 2026-09-05 — Semantic build-menu calibration requirements

- Vision currently returns arbitrary raw IDs such as `build_option_1`; preflight can have valid schemas while default `build_menu_button` / `close_build_menu` targets are absent.
- Calibration must normalize controlled roles (`BUILD_MENU_TOGGLE`, `BUILD_MENU_OPEN`, `BUILD_MENU_CLOSE`, `BUILD_CATEGORY_TAB`, `BUILD_OPTION`, `BUILD_DISABLED_OPTION`, `UNKNOWN`) into stable canonical IDs and retain raw IDs only in diagnostics.
- The currently open Song frame must be used for the first read-only calibration state. No input or focus changes are allowed; the second state requires the user to manually close the menu.
- OPEN calibration result: WGC captured Song at 1280x960 with `build_menu_open=true`; `build_controls` found `BUILD_MENU_CLOSE` → `build_menu_close_control`, raw ID `close_button`, confidence `0.90`, global bbox `[0.76, 0.825, 0.86, 0.8775]`. No full-client fallback was needed. The first implementation briefly selected the wrong open-state role and was corrected before accepting this result.
- CLOSED calibration result: WGC captured `build_menu_open=false`; `build_controls` was empty, so calibration-only full-client fallback found `BUILD_MENU_OPEN` → `build_menu_open_control`, raw ID `build_menu_button_top_right`, confidence `0.90`, global bbox `[0.8, 0.04, 0.85, 0.08]`.
- Final mapping is `SEPARATE`: closed-state open target is `build_menu_open_control`; open-state close target is `build_menu_close_control`. Both states are validated and `live_e2e_ready=true`; no input was used.

## 2026-09-05 — Runtime Calibration Contract

- The closed-state open target evidence is global bbox `[0.8, 0.04, 0.85, 0.08]`; it belongs to the formal `build_entry` ROI (`0.60..1.00 x 0.00..0.45`), not `build_controls`.
- Full-client Vision remains calibration-only. A target is persisted as a runtime target only after its global bbox is contained by the formal ROI and a second Vision pass resolves the same canonical ID/compatible role at confidence `>= 0.90`.
- The runtime must derive its Vision region set from finalized calibration and must fail closed if either calibrated target region is not observed.
- A read-only resolver will use only the current formal ROI and current Vision elements; it must never send calibration bboxes or raw IDs to the input path.
- Final calibration succeeded with `SEPARATE`: `open=build_entry/build_menu_toggle`, `close=build_controls/build_menu_close_control`, both states valid, `runtime_resolvable=true`, and `live_e2e_ready=true`.
- Real open resolver passed at confidence `0.90`; real closed resolver passed at confidence `0.90` after accepting the semantic `BUILD_MENU_TOGGLE`/`BUILD_MENU_OPEN` family as compatible. Both used WGC and reported `near_black_frame=false`; neither sent input.

## 2026-09-05 — Latest acceptance safety batch

- A semantic post-action verifier alone was too late: the previous flow could emit live input and only then discover that `expected_state`/`changed_fields` was absent. The action engine now performs preflight validation before recording RUNNING or invoking the executor.
- The live preflight also translates the entire command list before input. A whitelisted game Skill without calibrated commands is rejected rather than falling back to guessed coordinates or hotkeys.
- Foreground protection is enforced in the SendInput adapter using the exact HWND returned by the Steam window adapter. The adapter does not activate/focus the game, so an unexpected foreground application is a hard stop.
- This batch is code/test verified only. It does not prove a real Steam run, because no live game window, UI calibration, or valid read-only memory profile is available in this environment.
- The existing GovernorLoop fingerprint could skip a decision only after paying for all Vision calls. The runtime source now performs a local per-ROI SHA-256 comparison first, so unchanged regions do not spend DeepSeek Vision tokens; cached observations remain stable for the loop fingerprint.
- UI automation must not let the reasoning model invent screen coordinates. Vision output now has a strict normalized `ui_elements` contract, and the high-level Skill translator resolves `target_element` IDs against the latest cached perception state. If the element is missing or malformed, preflight fails before SendInput.
- Feishu remote control is now an explicit decision boundary: screenshot upload failures are audited while text notification still goes out, and a pending major event must be resolved with a decision command before the watchdog can resume. The selected decision is included in the next DeepSeek strategy context.
- CI is now configured as a repository check, but a local green test run is not evidence that GitHub's hosted job completed. The remote workflow result must be checked separately after push.
- The latest acceptance found a real misclick risk: Vision bbox coordinates are local to a cropped ROI. The implementation now preserves both local `bbox` and full-window `global_bbox`; only the latter reaches the input adapter. Region-qualified UI IDs prevent a dialog control from shadowing a build-menu control with the same id.
- A module-only Feishu notifier was insufficient for the requested behavior. Runtime now parses structured event facts from observations before strategy execution, deduplicates them against persisted events, captures the latest client frame, and either sends through the configured Feishu gateway or records an explicit audit when notification credentials are absent.
- Exact RGBA hashing was too sensitive for animated maps. The cache now uses deterministic grayscale sampling and normalized mean absolute difference thresholds; this reduces avoidable Vision calls without removing the periodic force-refresh safety net.
- The E2E harness is intentionally separate from the normal `run` loop. It refuses dry-run, missing arming, missing semantic verification, or absent explicit confirmation, and stops at the first failed open/close action; no live E2E was run in this environment.
- Latest acceptance identified a safety gap: when Feishu credentials are absent, runtime event handling recorded events but did not pause on `requires_decision`; pause and pending-decision persistence must belong to a runtime event coordinator, while Feishu remains an optional notifier.
- Build-menu/dialog E2E depends on semantic fields that generic Vision output did not previously require. The perception boundary must validate `build_menu_open`/`dialog_open`, `current_screen`, and dialog `options` before observations reach strategy or live verification.
- The existing desktop shortcut launched `cli run` directly, so it required DeepSeek model environment variables and had no settings UI. The overlay should own the user-facing configuration flow and persist only local settings outside the repository.
- A standard-library Tkinter overlay can use Win32 `RegisterHotKey(Home)` for a global toggle and `SteamWindowAdapter`/`Win32WindowBackend` to follow the game client area; it must remain topmost and keep live input opt-in.

## 2026-09-06 — V2.3 Live Roundtrip Preparation

- Added a controlled `e2e-build-menu-roundtrip` path with an explicit confirmation flag and a hard maximum of two high-level clicks.
- Live input remains protected by exact foreground HWND and expected Song PID checks; no focus activation, keyboard input, placement, or automatic retry is permitted.
- The first authorized attempt stopped before input on `FOREGROUND_TIMEOUT`; the second reached the read-only Vision phase but stopped before input because DeepSeek returned a dialog object without the required `ui_elements` list.
- The dialog request now has one bounded schema retry with an explicit four-field contract. This retry is Vision-only and does not retry or emit any input.
- Pre-attempt verification after the schema fix: `92 passed, 1 skipped`; Python 3.11 compileall PASS; diff check PASS.

## 2026-09-06 — V2.3 Live Attempt Result

- The authorized run passed the exact Song HWND/PID foreground gate, WGC capture, `near_black_frame=false`, and the closed-state target gate at confidence `0.90`.
- Exactly one click was emitted for `build_menu_open_control`; the post-click WGC/Vision check still reported `build_menu_open=false`.
- The harness stopped immediately with `open_after_click state precondition mismatch`; the close click was not attempted and no input retry occurred.
- Evidence is in `data/e2e/build_menu_roundtrip.json` and `data/e2e/build_menu_roundtrip_open_after.png`. The frame is a normal Song game client with the menu still closed.
- Temporary runtime arming was reset to `live_armed=false`; no placement/building action was performed.

## 2026-09-06 — Click Audit and Multi-frame Verification

- The existing closed-before and open-after frames are both normal Song client frames. The post-click frame still shows the map and the same upper-right entrance icon; no build-menu panel is visible.
- Raw pixel comparison reports `1,096,283 / 1,228,800` changed pixels (`89.22%`) and mean absolute RGB sum `12.36`; the files were captured about 16 seconds apart, so animated water/map markers account for substantial difference. This is not evidence that the menu opened.
- The actual target chain was: normalized bbox `[0.772, 0.08775, 0.7952, 0.12285]` -> client `(1003,101)` -> screen `(1101,191)`, client origin `(98,90)`, DPI `96`.
- Calibration stores `build_menu_toggle` with role `BUILD_MENU_TOGGLE`; current Vision returned raw `build_entry_blue_icon`, role `BUILD_MENU_OPEN`, normalized as `build_menu_open_control`. The resolver intentionally accepts this toggle/open semantic family, so the ID change is role normalization, not a coordinate fallback.
- Runtime now records both ID contracts and click geometry, writes annotated click screenshots, and collects read-only post-click frames at 200/500/1000/2000ms before accepting a state transition. No additional input was sent during this audit.

## 2026-09-06 — V2.3B Input Injection Audit

- The previous Win32 absolute mapping used screen pixels directly in the `0..65535` fields, which is incorrect for `MOUSEEVENTF_ABSOLUTE`. The production backend now maps against the virtual desktop origin/extent and sets `MOUSEEVENTF_VIRTUALDESK`.
- The live adapter records requested screen point, cursor-before, cursor-after-move, move return count, and separate mouse down/up return counts. A cursor mismatch over 2px or any non-1 `SendInput` return fails closed with an explicit error.
- Foreground and expected PID are rechecked before mouse down and before mouse up. No focus activation is performed.
- The real Win32 path uses separate down/up calls with a 50ms interval. Test doubles retain a compatibility `mouse_click` fallback only so existing non-Windows tests remain isolated from real input.
- Verification: `95 passed, 1 skipped`; Python 3.11 compileall PASS; `git diff --check` PASS. No Live E2E and no game input were executed in this audit.

## 2026-09-06 — V2.3C Open-only Attempt

- Added `e2e-build-menu-open-only` with `max_clicks=1`, `retry_input=false`, close/placement disabled, and automatic disarm in `finally`.
- The authorized attempt located Song HWND `526608`, PID `26320`, but read-only precondition Vision reported `build_menu_open=true`.
- It failed closed before target click: `total_inputs=0`, `unexpected_inputs=0`, no close action, no placement, and final `live_armed=false`.
- A new attempt requires the user to manually close the build menu first; the tool will not send a close input as part of open-only diagnosis.

## 2026-09-06 — V2.3C UI Visibility Precondition

- A second open-only attempt passed the Song foreground wait but stopped before input because the calibrated OPEN target was not visible/resolvable.
- The fresh `data/e2e/build_menu_open_only/before.png` shows the game map with the HUD hidden: the upper-right build entry and bottom construction toolbar are absent.
- This confirms `F2` toggles the game HUD/UI visibility rather than merely closing the build menu. The next attempt requires the user to press `F2` once to restore the HUD; the tool will not send that key.

## 2026-09-06 — V2.3C PASS

- After the HUD was restored and Song was kept foreground during the wait, the open-only path passed with exactly one click.
- Game identity remained HWND `526608`, PID `26320`, resolution `1280x960`; WGC capture remained healthy and `near_black_frame=false`.
- Input audit passed: requested/actual screen point `[1158,125]`, cursor verification true, `mouse_down.return_count=1`, `mouse_up.return_count=1`, foreground/PID checks true before both edges.
- Read-only Vision observed `build_menu_open=true` at 200ms, 500ms, 1000ms, and 2000ms; no unexpected dialog was reported.
- The open menu screenshot visibly shows the construction panel. No close, placement, keyboard, or retry input was performed; final `live_armed=false`.

- Use Python 3.11+ with a standard-library-first core to keep local/offline setup portable.
- Use SQLite for durable local state and an append-only audit trail.
- Use typed dataclasses and JSON validation at boundaries instead of passing arbitrary model output to an executor.
- Default all execution to dry-run and require explicit configuration for real input injection.
- Memory profiles are explicit JSON with process name, module, pointer size, pointer offsets, and scalar types; invalid profiles and missing processes fail closed.
- Latest acceptance confirmed the V0.1 foundation is valid but only about 35–40% of the full automation goal. The first V0.2 integration task is the Steam Window Adapter; live input, screenshot capture, real profiles, loop, Feishu transport, and verification remain separate tasks.
