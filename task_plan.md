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
| Task 4 ctypes nested input structures failed during test collection | 1 | Move Win32 input structures to module scope and rerun the suite |

## New memory-scan acceptance checks

- [x] Process enumeration can identify the configured executable without opening unrelated processes.
- [x] A configured module + pointer path can be read through a mock backend and returns typed values.
- [x] Windows backend exposes only query/read/close operations and gives clear non-Windows errors.
- [x] Missing/invalid profiles fail closed; no address guessing or broad memory scan is performed.

## Next action

Keep the local worktree clean and use the pushed foundation as the baseline for game-specific profile calibration.

## V0.2 Game Integration backlog from latest acceptance

Execute and push each item as its own verified task:

1. [x] Steam Window Adapter: locate the exact game window, read client bounds, handle minimized state, and expose normalized client coordinates.
2. [x] Real client-area screenshot capture.
3. [x] Actual ROI image cropping before DeepSeek Vision.
4. [x] Windows `SendInput` adapter, initially limited to explicitly safe dry-run/calibration actions.
5. [x] Post-action screenshot/state verification.
6. [x] Fix major-event pause ordering and ensure the watchdog is paused before notification.
7. [x] Replace permanent action de-duplication with scoped idempotency.
8. [ ] Add a long-running Governor loop with change detection and recovery.
9. [ ] Add a real Feishu custom-app transport boundary.
10. [ ] Calibrate the first real read-only memory fields for the installed game build.
11. [ ] Aggregate memory and vision observations into a canonical GameState.
12. [ ] Add stronger strategy/reporting/watchdog features after integration is observable.

### Current V0.2 task

Task 8 — Add a long-running Governor loop with change detection and recovery.
