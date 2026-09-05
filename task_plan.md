# 《满庭芳：宋上繁华》AI Governor — Task Plan

## Goal

Build the first usable, safe local foundation for the Steam AI Governor described in the referenced conversation: DeepSeek-only AI reasoning, region-focused perception, persistent city state, guarded action execution, Feishu command/report/event integration, and recovery-oriented logging. Keep real credentials and irreversible game actions opt-in.

## Scope and acceptance criteria

- [x] A runnable Python package exists with a local CLI entry point.
- [x] Configuration is environment-driven and never requires committing secrets.
- [x] SQLite persists observations, actions, events, goals, and audit records.
- [x] Perception is region-focused and can operate in deterministic dry-run mode.
- [x] DeepSeek is the only LLM provider abstraction; missing credentials fail clearly.
- [x] Action plans are schema-validated, risk-gated, and idempotency-aware; live post-action verification remains disabled until a real adapter exists.
- [x] Feishu text commands support report/status/goals/pause/resume and explicit goal changes.
- [x] Reports and major-event notifications are generated from persisted state; daily reports are on-demand.
- [x] Watchdog/recovery state prevents unsafe continuation after stale or uncertain execution.
- [x] Automated tests cover the safety-critical paths and pass locally.
- [x] A Windows read-only memory sampler supports configured pointer paths without any memory-write API.
- [x] Git history contains the implementation; the implementation and delivery record are pushed to the user-provided remote.

## Phases

| Phase | Status | Deliverable |
|---|---|---|
| 0. Recovery and repository baseline | complete | Plan files, empty-workspace finding, scope boundary |
| 1. Foundation and persistence | complete | Package, config, SQLite schema/repository, CLI |
| 2. Perception and DeepSeek contracts | complete | Region models, provider client, structured contracts |
| 3. Safe action engine and watchdog | complete | Risk gates, dry-run executor, uncertainty halt, recovery |
| 4. Feishu gateway and reporting | complete | Commands, reports, major-event notifications, adapter boundary |
| 4b. Read-only memory diagnostics | complete | Windows process reader, configured pointer profile, diagnostic CLI |
| 5. Verification and delivery | complete | Tests, docs, Git commit, remote push, and post-push verification |

## Decisions

- Target is the Steam Windows version.
- DeepSeek is the only AI provider; ordinary deterministic work stays in code.
- Complex screenshots are handled by task-specific region crops; full-screen analysis is a fallback.
- Daily reports are on-demand via Feishu commands; major events are proactively notified.
- A Feishu custom app/bot is the intended bidirectional integration, not only an incoming webhook.
- Real mouse/keyboard automation is disabled by default until a user explicitly enables it and post-action verification is available.
- The empty workspace means this turn establishes a production-oriented scaffold, not proof of live game control.
- Numeric game state should be sourced from a read-only memory sampler when stable addresses are discovered; visual perception remains responsible for map/UI/events.
- Memory addresses, pointer chains, and field types must come from an explicit user-maintained profile; the program must never guess or scan arbitrary memory ranges.
- No memory-write API belongs in this project. Live mouse/keyboard input remains disabled until calibrated and verified.

## Errors encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `git status` reports “not a git repository” | 1 | Confirmed the target directory is empty; initialize Git only after implementation is ready |
| Referenced conversation text exceeds one tool item limit | 1 | Read the thread metadata and extracted its complete turn/heading inventory; use the available plan headings as the architecture baseline |
| `codex-deepseek-direct` skill path not found | 1 | Continue with the required control-plane review workflow and implement directly because no callable worker skill is available |
| Global pytest plugin fails importing `httpx._client` | 1 | Re-run project tests with third-party plugin autoload disabled; do not alter global packages |
| Combined PowerShell CLI smoke command rejected by command policy | 1 | Split compile, CLI, and cleanup checks into separate commands |
| CLI invoked before package installation reports `ModuleNotFoundError` | 1 | Use `PYTHONPATH=src` for source-tree smoke; documented users install the package editable |
| CLI `--db` override passed `str` where `Settings` expects `Path` | 1 | Convert the override with `Path(args.db)` and add a smoke check |
| Exact temporary smoke DB cleanup was rejected by shell safety policy | 1 | Leave the ignored `data\\smoke.db` local artifact; verify it is not staged |
| Example memory profile initially leaked a process-not-found traceback | 1 | Include `sampler.sample()` in CLI fail-closed error handling |
| `git commit` cannot determine author identity | 1 | Resolved by setting repository-local `jiaweixi-ops` GitHub no-reply identity |
| `git remote -v` is empty | 1 | Resolved by adding the user-provided GitHub URL as `origin` |
| Direct GitHub push hit Schannel TLS handshake failure | 1 | Use the machine's configured GitHub proxy URL for this push attempt; do not disable TLS verification |
| `gh run watch` ended with a transient GitHub API EOF after both jobs showed green | 1 | Rechecked with `gh run list`; the run is completed with `success` for the pushed commit |
| Task 4 ctypes nested input structures failed during test collection | 1 | Move Win32 input structures to module scope and rerun the suite |

## New memory-scan acceptance checks

- [x] Process enumeration can identify the configured executable without opening unrelated processes.
- [x] A configured module + pointer path can be read through a mock backend and returns typed values.
- [x] Windows backend exposes only query/read/close operations and gives clear non-Windows errors.
- [x] Missing/invalid profiles fail closed; no address guessing or broad memory scan is performed.

## Next action

Keep the local worktree clean. The remaining acceptance work is external calibration: validated memory fields and a separately gated real Steam E2E run with the game window, UI IDs, and DeepSeek configuration available.

## V0.2 Game Integration backlog from latest acceptance

Execute and push each item as its own verified task:

1. [x] Steam Window Adapter: locate the exact game window, read client bounds, handle minimized state, and expose normalized client coordinates.
2. [x] Real client-area screenshot capture.
3. [x] Actual ROI image cropping before DeepSeek Vision.
4. [x] Windows `SendInput` adapter, initially limited to explicitly safe dry-run/calibration actions.
5. [x] Post-action screenshot/state verification.
6. [x] Fix major-event pause ordering and ensure the watchdog is paused before notification.
7. [x] Replace permanent action de-duplication with scoped idempotency.
8. [x] Add a long-running Governor loop with change detection and recovery.
9. [x] Add a real Feishu custom-app transport boundary.
10. [ ] Calibrate the first real read-only memory fields for the installed game build.
    - [x] Identify the installed Steam AppID, executable, process name, and window title.
    - [x] Add a read-only loaded-module diagnostic command; do not scan arbitrary memory.
    - [ ] Obtain and validate real population/money/food/wood/stone/time field addresses.
11. [x] Aggregate memory and vision observations into a canonical GameState.
12. [ ] Add stronger strategy/reporting/watchdog features after integration is observable.

### Current V0.2 task

Task 10 — Calibrate the first real read-only memory fields for the installed game build.

## Latest acceptance follow-up

- [x] Serialize Governor state context as JSON text before DeepSeek Chat Completions requests.
- [x] Add a guarded PlannedAction-to-game-skill bridge; live execution remains disabled until semantic verification exists.
- [x] Strengthen post-action verification from screenshot availability to semantic state change.
- [x] Add multi-source observation support to GovernorLoop.
- [x] Add a real multi-source `GovernorLoop` entry point and keep it dry-run by default.
- [x] Add DeepSeek transient retry/backoff and persist usage counters.
- [x] Add Feishu callback server/decryption, retry and usage accounting.
- [x] Expand the daily report with local-day deltas and decision summaries.
- [x] Add bounded exception restart/backoff supervision without bypassing safety recovery.

### Latest acceptance follow-up — live input safety and skill contract

- [x] Validate `expected_state`/`changed_fields` and the complete input command sequence before any live executor call.
- [x] Refuse SendInput when the exact game window is not the foreground window; never auto-focus another application.
- [x] Publish the first whitelist of game skills for menu, tabs, camera, speed, finance/technology/policy, save, and dialog controls.
- [x] Add regression tests proving invalid live actions are blocked before the executor and foreground mismatches emit no input.
- [x] Add local ROI/frame change filtering so unchanged regions do not call DeepSeek Vision.
- [x] Add calibrated UI bounding-box output and a resolver from UI elements to skill commands.
- [x] Convert ROI-local UI bounding boxes to full-window normalized coordinates before input.
- [x] Preserve UI elements by source region and require `target_region` in Skill payloads.
- [x] Align Governor prompt and SkillTranslator contract; add `SELECT_EVENT_OPTION`.
- [x] Add structured major-event detection and connect it to the runtime loop.
- [x] Save the latest client frame for detected events and notify Feishu when configured.
- [x] Replace exact ROI hashing with downsampled grayscale change scores and per-region thresholds.
- [x] Add an explicitly gated E2E-001 build-menu harness with 100-cycle metrics and fail-closed stop behavior.
- [x] Add Feishu screenshot upload and explicit remote decision reply handling.
- [x] Add CI for the source-level safety and integration checks.
- [x] Move major-event pause and pending-decision persistence into a runtime coordinator independent of Feishu availability.
- [x] Enforce semantic Vision fields for `build_menu` and `dialog` regions, with regression tests.
- [x] Add a Windows floating assistant window that follows the game, toggles with global `Home`, and exposes saved DeepSeek settings.
- [x] Update the desktop shortcut to launch the floating assistant safely.
- [ ] Add a separately gated real Steam E2E harness; real E2E remains unverified until the game is running with calibrated UI/profile data.

### Real E2E preflight remediation (2026-09-05)

- [x] Remove `CAPTUREBLT` from the normal client capture raster operation and retain it only as an explicit future diagnostic constant.
- [x] Add near-black frame diagnostics and fail-closed `CAPTURE_BLACK_FRAME` handling without fallback.
- [x] Add non-focus-stealing foreground wait with 30-second timeout, 500ms polling, and 3-second stability.
- [x] Add read-only `e2e-preflight --wait-for-game-foreground` and wire the same wait option into the explicitly gated E2E command.
- [x] Add regression tests and complete local verification.

## WGC capture remediation (2026-09-05)

- [x] Add a real Windows Graphics Capture backend scoped to the Song HWND.
- [x] Keep GDI and PrintWindow as explicit diagnostics only; no silent production fallback.
- [x] Add capture-diagnostic artifacts and a safe DeepSeek Vision probe.
- [x] Make production runtime and read-only preflight select WGC.
- [x] Add capability, crop, failure, and safety regression tests.
- [x] Run pytest, compileall, diff check, capture diagnostic, Vision probe, and read-only preflight.
- [ ] Commit/push only if all required checks pass; never arm Live or run e2e-build-menu.
