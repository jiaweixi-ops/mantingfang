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

- Use Python 3.11+ with a standard-library-first core to keep local/offline setup portable.
- Use SQLite for durable local state and an append-only audit trail.
- Use typed dataclasses and JSON validation at boundaries instead of passing arbitrary model output to an executor.
- Default all execution to dry-run and require explicit configuration for real input injection.
- Memory profiles are explicit JSON with process name, module, pointer size, pointer offsets, and scalar types; invalid profiles and missing processes fail closed.
- Latest acceptance confirmed the V0.1 foundation is valid but only about 35–40% of the full automation goal. The first V0.2 integration task is the Steam Window Adapter; live input, screenshot capture, real profiles, loop, Feishu transport, and verification remain separate tasks.
