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
| Windows CI failed because `zoneinfo` could not find `Asia/Shanghai` | 1 | Declare `tzdata>=2022.7` as a runtime dependency so Windows installs the IANA database through the package install |

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
- [x] Commit/push only if all required checks pass; never arm Live or run e2e-build-menu.

## Semantic build-menu calibration (2026-09-05)

- [x] Separate read-only perception PASS from action-target calibration and Live E2E readiness.
- [x] Normalize Vision semantic roles into canonical element IDs, preserving raw IDs only for diagnostics.
- [x] Add `build_controls` ROI and calibration-only full-client fallback.
- [x] Add read-only `e2e-calibrate-build-menu --state open|closed` and state artifacts.
- [x] Support toggle and separate open/close targets without persisting pixel coordinates.
- [x] Add calibration/E2E/resolver regression tests and run pytest/compileall/diff check.
- [x] Run OPEN calibration only while the menu is currently open; stop for manual CLOSED-state transition.
- [x] Commit/push only after the requested two-state calibration and CI checks succeed; never arm Live or run e2e-build-menu.

## Runtime Calibration Contract (2026-09-05/06)

- [x] Add the evidence-backed `build_entry` runtime ROI for the closed-state open control.
- [x] Re-run calibration through formal runtime ROIs and reject full-client targets that cannot be mapped safely.
- [x] Require finalized calibration to be runtime-resolvable before any E2E runtime is assembled.
- [x] Add read-only `e2e-resolve-build-menu-targets --state open|closed` with current-frame Vision resolution.
- [x] Add regression coverage for ROI membership, runtime-region wiring, resolver safety, and no calibration-bbox input fallback.
- [x] Run pytest/compileall/diff check and perform only read-only resolver validation; never arm Live or run e2e-build-menu.
- [x] Commit/push as `fix: align build menu calibration with runtime regions` and verify CI.

## V2.3 Verified Live Build Menu Roundtrip (2026-09-06)

- [x] Add an explicitly confirmed, two-click-only `closed -> open -> closed` Live E2E command.
- [x] Require exact Song HWND foreground and stable PID immediately before every click; never focus or retry input.
- [x] Require WGC capture, non-black frames, formal calibrated ROI targets, confidence >= 0.90, and post-action Vision verification.
- [x] Persist roundtrip evidence and fail-closed reports for setup, Vision, capture, foreground, PID, and postcondition failures.
- [x] Add a bounded dialog-schema retry that never emits input and never retries a click.
- [x] Run pytest, compileall, and diff check before the authorized real attempt.
- [x] Execute the authorized two-click roundtrip and inspect its evidence; do not proceed to placement/building.
- [x] Fail closed after the first click when `build_menu_open` remained false; no close click or input retry was sent.

## V2.3 Click Audit and Read-only Post-click Observation (2026-09-06)

- [x] Compare the existing before/after screenshots and preserve the interpretation in a bounded audit artifact.
- [x] Record calibrated/observed IDs, normalized bbox, client point, screen point, client origin, and DPI; generate an annotated screenshot.
- [x] Explain `build_menu_toggle` -> `build_menu_open_control` as controlled semantic-role normalization with compatibility, not an unchecked coordinate fallback.
- [x] Add structured post-click read-only checkpoints at 200/500/1000/2000ms for future authorized attempts; no input retry is attached to these checkpoints.
- [x] Run pytest, compileall, and diff check after the audit changes.

## V2.3B Input Injection Audit (2026-09-06)

- [x] Audit the real Win32 input path without running Live E2E.
- [x] Correct absolute mouse mapping for the virtual desktop instead of treating screen pixels as `0..65535` coordinates.
- [x] Require cursor-position verification within 2px before mouse down.
- [x] Require exact HWND/PID/foreground checks before mouse down and mouse up.
- [x] Record `SendInput` return counts for move, down, and up, and fail closed on non-1 results.
- [x] Keep the existing fallback only for test doubles; the production Win32 backend uses separate down/up calls with a 50ms interval.
- [x] Add regression tests and run pytest, compileall, and diff check.
- [ ] Run the separate one-click open-only Live diagnostic only after explicit user authorization.

## V2.3C Open-only Live E2E (2026-09-06)

- [x] Add a dedicated `e2e-build-menu-open-only` command with a hard maximum of one click.
- [x] Disable close, placement, keyboard input, and click retry in this path.
- [x] Reuse cursor/SendInput/foreground/PID audits and persist before/annotated/200/500/1000/2000ms evidence.
- [x] Run the authorized open-only attempt; it stopped at the closed-state precondition because the menu was already open.
- [x] Re-run only after the user manually returns the menu to closed; do not close it programmatically.
- [x] V2.3C PASS: one audited click opened the menu and all four read-only checkpoints confirmed the open state.

## V2.3C Acceptance (2026-09-06)

- [x] Precondition closed, target confidence >= 0.90, valid bbox, exact Song HWND/PID/foreground.
- [x] One click only; no retry, no close, no placement, no keyboard input.
- [x] Cursor verification and `SendInput` down/up return counts passed.
- [x] WGC and non-black capture passed at 200/500/1000/2000ms.
- [x] Automatic disarm completed and evidence saved under `data/e2e/build_menu_open_only/`.
- [ ] V2.3D close-only Live E2E remains pending.

## V2.3D Close-only Live E2E (2026-09-06)

- [x] Add a dedicated `e2e-build-menu-close-only` command with a hard maximum of one click.
- [x] Require the menu-open precondition, current-frame CLOSE target resolution, exact Song HWND/PID/foreground, WGC, and non-black capture.
- [x] Disable open, placement, keyboard input, and click retry in this path.
- [x] Persist before/annotated/200/500/1000/2000ms evidence and disarm automatically.
- [x] Run pytest, compileall, and diff check before the authorized real attempt.
- [ ] Execute the authorized close-only attempt; do not start V2.3E in the same turn.

## V2.3X Direct Game State Probe (2026-09-06)

- [x] Locate the installed Song executable, Mono managed directory, and core assemblies.
- [x] Confirm `Unity.Model.dll` contains the `WSFramework` gameplay/state model; `Assembly-CSharp.dll` is not the primary state assembly.
- [x] Identify the local common save as an Odin binary containing `WSFramework.CommonData`; preserve original files.
- [x] Enumerate the Odin `SerializationUtility` read-only deserialization API.
- [x] Inspect `RecordData` and save-file routing for the active city record.
- [x] Parse the available common save bytes read-only and extract safe state candidates.
- [x] Document the concrete blocker: no active-city `RecordData` file is currently present, so no repository probe was added yet.
- [x] Run focused tests, compileall, and diff check; no Live E2E, memory writes, or game input.

### V2.3X2 Real City Save Probe (2026-09-06)

- [x] Capture a read-only baseline inventory of the Song save root without invoking the game save API.
- [x] User manually saves one real city in-game.
- [x] Compare the post-save inventory and identify candidate city-record files.
- [x] Copy only candidate files to ignored probe storage and inspect metadata/header/hash.
- [x] Deserialize only the copy and cross-check `CityName`, `Year`, `Month`, `Gold`, `Villagers.Count`, `SceneData.Buildings.Count`, and `ShowRes`.
- [x] Run tests/compileall/diff check; commit/push remains subject to the GitHub credential gate.

## V2.3X3 Runtime Telemetry and Qwen Provider Migration (2026-09-06)

- [x] Inspect the V5 ZIP in an isolated directory; do not overwrite the validated repository or trust placeholder adapters as real implementation.
- [x] Add a generic Qwen chat/vision provider with retry, usage recording, and secret-safe errors.
- [x] Migrate runtime configuration and overlay labels/settings to Qwen-only while preserving the existing live-input safety chain.
- [x] Add a read-only runtime telemetry client/source with explicit `UNKNOWN/BLOCKED` behavior when the bridge is absent or schema is incomplete.
- [x] Add a separately documented Windows/Mono bridge contract; do not install or inject it automatically until exact external assemblies are verified.
- [x] Add tests for Qwen configuration/provider behavior and telemetry schema/fail-safe handling.
- [x] Run pytest, compileall, and diff check; never arm Live or send game input.
- [x] Commit and push after checks; the previous Qwen/telemetry commit is already on `origin/main`.

## V2.3X3 Runtime Telemetry implementation safety closure (2026-09-06)

- [x] Remove DeepSeek production/test references and make Qwen the only provider path.
- [x] Require telemetry PID, game version, timezone-aware `observed_at`, and a bounded snapshot age.
- [x] Lock the production Live Governor to the Song HWND/PID at runtime creation.
- [x] Add opt-in automatic foreground activation with stable wait, best-effort previous-window restore, and fail-closed behavior.
- [x] Add geometry snapshots to observed UI targets; reject `TARGET_STALE` before mouse down/up when HWND, PID, client size, origin, or DPI changes.
- [x] Add the read-only BepInEx/Unity bridge reference source and external-reference build contract; do not inject it automatically.
- [x] Add Windows CI coverage for Python 3.11/3.12 module import, tests, compileall, and diff check.
- [x] Run CI after push and inspect both Linux and Windows jobs; do not run Live E2E in this phase. Initial Windows failure was fixed by declaring `tzdata>=2022.7`; rerun `34024937213` passed all four jobs.
- [x] Correct the bridge inventory source to `BaseData.CenterStoreData.Res` and require named core resources.
- [x] Reject `status=OK` snapshots containing null, missing, or invalid core values.
- [x] Move Unity sampling to the main thread and serve only the last serialized snapshot from the HTTP worker.
- [x] Require `GOVERNOR_RUNTIME_GAME_VERSION` whenever runtime telemetry is enabled.
- [x] Refresh observation cache after an opt-in foreground transition before resolving any live target.
- [x] Add regression tests for schema, bridge contract, version gating, and foreground refresh ordering.
- [x] Bound Bridge sampling to 4Hz and cache reflection metadata.
- [x] Bind `telemetry-read` to the current Song PID and configured game version with exit code 2 on failure.
- [x] Fix the instance-only resource reader and avoid permanently caching missing reflection types.
- [x] Add a dependency-free C# bridge source compile check with minimal BepInEx/Unity stubs and CI coverage.

## V2.3X4 Runtime/Save Cross-check

- [x] Confirm the exact installed game path, Unity version, and managed assembly set by read-only inspection.
- [x] Confirm whether a BepInEx/Doorstop installation already exists without changing the game directory.
- [x] Confirm the existing ignored city-save probe remains available for later comparison.
- [x] After explicit user confirmation, install the verified x64 BepInEx package without overwriting a loader or installing a separate Doorstop.
- [ ] Build the bridge against the exact installed BepInEx/Unity assemblies.
- [ ] Run the bridge read-only in the real game and verify `/health` and `/state`.
- [ ] Compare a fresh runtime snapshot against a manually saved `RecordData` copy.
- [ ] Keep `GOVERNOR_RUNTIME_TELEMETRY=false` until all three checks pass.
- [x] Run read-only Doorstop diagnosis and record the concrete Preloader failure; no loader replacement or config edit is authorized by this phase.
- [ ] Resolve BepInEx/Unity Mono Preloader compatibility, then re-check `BEPINEX_BOOT` before considering any build toolchain work.

## V2.3X4-B Exact Unity Corlib Compatibility Test

- [x] Preserve and hash the current Unity managed core assemblies.
- [x] Download and hash the official Unity 2022.3.62 corlibs in staging only.
- [x] Inspect the staged `mscorlib.dll` metadata without loading it.
- [x] Back up `doorstop_config.ini` and apply only the UnityMono search-path override.
- [ ] Stop and wait for the user to restart the game; inspect only the resulting loader artifacts.
- [x] Push the preparation records without committing staged binaries or game-directory files.

## V2.3X4-C Doorstop-only debugger bootstrap preparation

- [x] Restore the pre-corlib Doorstop configuration after the game process exited; keep the failed corlib set outside its configured lookup path for recoverability.
- [x] Add a minimal, no-op Doorstop entrypoint that references neither BepInEx nor Unity.
- [x] Validate CI compilation and artifact publication for the bootstrap only (GitHub Actions run `34029235704`).
- [x] Confirm the restored baseline game starts normally before any Doorstop-only debugger test.
- [x] Receive explicit authorization to prepare the isolated Doorstop debugger test.
- [x] Verify port `10000` is unused and download the exact `DoorstopTelemetryBootstrap` artifact from run `34029294783`.
- [x] Verify the artifact DLL hash, PE/.NET metadata, and `net40` target evidence without executing it.
- [x] Install only the bootstrap DLL under `DoorstopProbe`, preserving all game managed assemblies and BepInEx files.
- [x] Back up `doorstop_config.ini` byte-for-byte and change only the bootstrap target plus loopback debugger settings.
- [x] Stop at `READY_FOR_DOORSTOP_DEBUGGER_TEST`; do not start the game or connect a debugger.

## V2.3X4-C Doorstop debugger transport boot validation

- [x] User starts the game manually; never use process launch automation or game input.
- [x] Confirm the new `Song.exe` is responsive and running from the expected Steam installation path.
- [x] Confirm exactly one listener exists at `127.0.0.1:10000` and its owning PID exactly matches the current `Song.exe` PID.
- [x] Re-check after a short interval and confirm there are no established debugger client connections.
- [x] Record `DOORSTOP_DEBUGGER_TRANSPORT=PASS` and stop before any debugger client connection, assembly enumeration, or runtime-field access.

## V2.3X4-D Mono debugger minimal read-only attachment

- [x] Receive explicit authorization and re-confirm `Song.exe` plus loopback listener PID ownership.
- [x] Add a single-purpose Mono Soft Debugger client restricted to one connect, root-domain assembly-name enumeration, and disconnect.
- [x] Add source-contract tests that prohibit suspend, breakpoints, stepping, invocation, type/object/thread enumeration, field/local/stack reads, mutation, and reconnect loops.
- [x] Build and publish the exact Windows client in CI; do not substitute locally compiled source.
- [x] Download and verify the CI artifact, then audit its source commit and metadata before execution.
- [x] Execute at most one connection with a five-second outer timeout; save only assembly names and required-assembly booleans.
- [x] Confirm disconnect, zero established connections, unchanged PID/listener ownership, and a responsive game.
- [x] Record and push the result, then stop before V2.3X4-E.

## V2.3X4-E Mono debugger minimal type-existence check

- [x] Receive explicit authorization and preserve Codex-only implementation per the user's request.
- [x] Re-confirm the responsive `Song.exe`, exact loopback listener ownership, and zero established debugger connections.
- [x] Add a single-purpose client that checks only the existence of `WSFramework.BaseData`, `WSFramework.SceneData`, `WSFramework.RootData`, and `UIBuildMenuViewCtrl`.
- [x] Add source-contract tests that prohibit instance enumeration, field/property/value reads, method invocation, threads/frames/locals/stacks, breakpoints, suspend/resume, mutation, reconnect loops, and configurable endpoints.
- [x] Build and publish the exact client in CI, then download and verify that artifact before execution.
- [x] Execute at most one connection with a five-second outer timeout; the client timed out without producing type booleans and was not retried.
- [x] Confirm the timed-out client was terminated, zero established connections remained, PID/listener ownership was unchanged, and the game stayed responsive.
- [x] Record and push the result, then stop before any instance or field access phase.

### Errors encountered

| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell on the installed .NET runtime does not support `ReflectionOnlyLoadFrom` | 1 | Did not retry; use `dnfile` plus raw CLR metadata string inspection for the CI artifact. |
| The single authorized type-existence probe exceeded the five-second outer timeout and emitted no stdout/stderr | 1 | Terminated only the probe process, verified zero debugger connections and a responsive game, prohibited retry, and recorded `FAIL_TIMEOUT_SAFE`. |
| The E2 diagnostic contract test looked for the runtime-composed marker string instead of the fixed marker call | 1 | Corrected the test to assert the source-level `Marker("CONNECT_BEGIN")` and `Marker("DISCONNECT_BEGIN")` calls; no debugger connection occurred. |

## V2.3X4-E2 flushed phase diagnostics

- [x] Add only flushed markers around connect, assembly lookup, each exact type query, and disconnect.
- [x] Run the CI-built diagnostic artifact once with the same read-only constraints; it stopped at `CONNECT_BEGIN` after the five-second timeout.
- [x] Record the stopping phase and post-run safety state, then push and stop.

Result: `FAIL_TIMEOUT_AT_CONNECT`. No type query was reached and no retry is authorized.

## V2.4 Build Menu Navigation — read-only foundation

- [x] Add a fail-closed build-menu state model for `UNKNOWN`, `CLOSED`, `ROOT_OPEN`, `CATEGORY_OPEN`, and `BUILDING_SELECTED`.
- [x] Add strict parsing for current-frame categories, building options, lock state, costs, and frame geometry.
- [x] Add unit tests for state evidence, malformed/low-confidence observations, geometry preservation, and locked/cost-bearing options.
- [x] Keep the new module disconnected from Qwen, live input, E2E executors, telemetry, and V2.5 placement.
- [x] Run pytest, compileall, diff check, commit, push, and verify `HEAD == origin/main`.

Scope decision: V2.3X4 Mono Debugger is research-only after the safe connect timeout; do not retry it while implementing V2.4.

## V2.4A/B-R Real-game read-only calibration

- [x] Add a fresh-frame Build Menu observation adapter around the existing WGC and Vision resolver.
- [x] Keep Vision calls bounded to one calibration call per phase; use local frame/template stability checks for later samples.
- [x] Add closed, root-open, and category-open three-sample workflows with current-frame geometry and IoU validation.
- [x] Persist bounded JSON evidence under `data/probe/V2.4ABR/`; never commit large screenshots or secrets.
- [ ] Run the real read-only calibration only after code verification and required manual UI state changes; do not enter V2.4C. CLOSED and ROOT_OPEN have passed; CATEGORY_OPEN stopped safely on the one permitted Flash schema failure and remains pending a separately authorized calibration approach.
- [ ] Run pytest, compileall, diff check, commit, push, and CI verification for the deterministic control/category-fusion implementation.

Current execution note: CLOSED is PASS (3/3). ROOT_OPEN is PASS (3/3) through a current-frame deterministic red close-control resolver at confidence 0.9807 plus eight geometry-calibrated categories reused only as non-actionable seeds. CATEGORY_OPEN made its one permitted `qwen3.8-flash` request and received an invalid response shape (`CALIBRATION_MODEL_SCHEMA_FAIL`); it was not retried. No `qwen3.8-max`, input, map click, save write, or memory write occurred during R2.

## V2.4A/B-R3 Deterministic Build Option Geometry Calibration

- [x] Keep Qwen fully disconnected from CATEGORY_OPEN; do not retry or loosen any model schema.
- [x] Add a local current-frame option-slot geometry detector constrained to the existing `build_controls` ROI.
- [x] Add synthetic negative cases for root tabs, closed/menu-map controls, size limits, bounds, and overlap suppression.
- [x] Sample the user-held CATEGORY_OPEN page three times with no input and require stable current-frame option geometry.
- [ ] Run full verification, commit, push, wait for CI, and stop before V2.4C.

Result: `V2.4A/B-R=PASS_GEOMETRY_CALIBRATED`. CLOSED, ROOT_OPEN, and CATEGORY_OPEN each passed 3/3; CATEGORY_OPEN produced eight stable local slots, with fresh WGC/current HWND/PID/geometry on every sample and zero Qwen calls in R3.
