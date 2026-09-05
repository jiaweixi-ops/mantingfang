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

## Technical direction

- Use Python 3.11+ with a standard-library-first core to keep local/offline setup portable.
- Use SQLite for durable local state and an append-only audit trail.
- Use typed dataclasses and JSON validation at boundaries instead of passing arbitrary model output to an executor.
- Default all execution to dry-run and require explicit configuration for real input injection.
- Memory profiles are explicit JSON with process name, module, pointer size, pointer offsets, and scalar types; invalid profiles and missing processes fail closed.
- Latest acceptance confirmed the V0.1 foundation is valid but only about 35–40% of the full automation goal. The first V0.2 integration task is the Steam Window Adapter; live input, screenshot capture, real profiles, loop, Feishu transport, and verification remain separate tasks.
