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

- Use Python 3.11+ with a standard-library-first core to keep local/offline setup portable.
- Use SQLite for durable local state and an append-only audit trail.
- Use typed dataclasses and JSON validation at boundaries instead of passing arbitrary model output to an executor.
- Default all execution to dry-run and require explicit configuration for real input injection.
- Memory profiles are explicit JSON with process name, module, pointer size, pointer offsets, and scalar types; invalid profiles and missing processes fail closed.
- Latest acceptance confirmed the V0.1 foundation is valid but only about 35–40% of the full automation goal. The first V0.2 integration task is the Steam Window Adapter; live input, screenshot capture, real profiles, loop, Feishu transport, and verification remain separate tasks.
