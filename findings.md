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

## 2026-09-06 — V2.3D Close-only implementation

- Added `run_live_build_menu_close_only` as an independent one-click path. It requires `build_menu_open=true`, resolves the CLOSE target from the current WGC/Vision frame, and never executes open, placement, keyboard, or retry actions.
- Added CLI command `e2e-build-menu-close-only --confirm-live-close` with the same foreground wait option as open-only.
- Added parser and live-mode guard regression tests. Local verification before the real attempt: `99 passed, 1 skipped`; Python 3.11 compileall PASS; `git diff --check` PASS.
- No Live input has been sent by the implementation/test phase. The authorized real attempt remains the next action.
- The first authorized close-only run stopped before input because the persisted `build_controls` ROI did not resolve a CLOSE element in the current frame. WGC capture, Song HWND `526608`, PID `26320`, and the open-state Vision schema were healthy; `total_inputs=0` and `live_armed=false`.
- A read-only `build_entry` Vision probe found the actual visible `BUILD_MENU_CLOSE` control at confidence `0.95` with current-frame `global_bbox=[0.96, 0.1035, 0.984, 0.1305]`. The close-only path now permits only this formal-ROI fallback when the calibrated `build_controls` ROI has no current-frame target; no calibration bbox or guessed coordinate is reused.
- A subsequent attempt captured the same visible open panel, while `build_controls` alone returned an inconsistent `build_menu_open=false`; it stopped before input. The fallback condition now also handles this old-ROI state mismatch and rechecks the richer formal `build_entry` ROI before any click.
- Final bounded V2.3D attempt still failed closed on the `build_menu_open=true` precondition after the fallback recheck. No click was sent in any close-only attempt (`total_inputs=0` each time); the visible panel/capture is available, but Vision state is not stable enough to authorize input.

## 2026-09-06 — V2.3X Direct Game State Probe

- Installed game: `F:\SteamLibrary\steamapps\common\Thriving City Song`; Mono managed directory and `Song.exe` are present.
- `Unity.Model.dll` is the core gameplay assembly (2,504 reflected types, including `WSFramework` state/model classes); `Assembly-CSharp.dll` contains mostly UI/mod glue for this purpose.
- `WSFramework.BaseData` exposes direct state candidates such as `Gold`, `ShowRes`, `Year`, `Month`, `CityName`, population collections, and `SceneData`; `SceneData` exposes `Buildings` and `Sites`; `BuildingData` exposes building identity/state fields.
- `WSFramework.UIBuildMenuViewCtrl` exposes build-menu control methods, but this is runtime UI state and should not be confused with serialized city state.
- `C:\Users\奚嘉威\AppData\LocalLow\WhiteStar\Song\common.record` and `common.tmp` are identical 17,580-byte files. Their metadata strings identify Odin serialization and `WSFramework.CommonData`; originals were not changed.
- `Player.log` confirms Odin Serializer initialization and common-data loading. Next probe is limited to enumerating deserialization APIs and reading copied/in-memory bytes; no save/write APIs or game injection are allowed.
- The file header is standard .NET `BinaryFormatter` (`00 01 00 00 00 FF FF FF FF 01 00 00 00 00 00 00`), not a standalone Odin Binary stream. A .NET Framework read-only parser recovered both files as `WSFramework.CommonData`; no game methods were invoked.
- Safe extracted common-data facts: `MapState.count=9`, `SelectSkin.count=100`, and `ComboList` is a typed `HashSet<int>`. Both files remain byte-identical at SHA-256 `EA304374E637DB539D71CEA89BE71C58276905260E9BA707181621FE558E0521` and 17,580 bytes.
- `DataComponent` exposes `LoadRecord(string/int64)`, `LoadShareRecord`, `SaveRecordIndex`, `OverwriteRecord`, and `RecordPath`; reflection shows `RecordData` metadata and `BaseData`/`SceneData` candidates, but invoking load/save/runtime component code is out of scope for this read-only probe.
- The local save tree contains only `common.record` and `common.tmp` plus settings/logs; `Version2` is empty and no active-city `RecordData` file is present. A real-time bridge therefore remains blocked until the user creates or exposes a city record, or a separately authorized read-only runtime state source is selected.

## 2026-09-06 — V2.3X2 Real City Save Probe

- After the user manually saved in-game, the save-root diff found `Version2\\117224508162075.index` (20,275 bytes) and `Version2\\117224508162075.record` (266,562 bytes). The index is a BinaryFormatter stream; the record is a ZIP container.
- The ZIP contains a single payload text entry (the original Windows path is preserved in the archive name). The payload copy begins with the BinaryFormatter header and deserializes to `WSFramework.RootData`.
- The index copy deserializes to `WSFramework.RecordData`: `Id=117224508162075`, `Name=新的城市`, `Year=1`, `MapId=7`.
- The payload copy contains `RootData.BaseData` and `RootData.SceneData`: `CityName=新的城市`, `Year=1`, `Month=4` (game month index), `Time=184.1001`, `Villagers.Count=10`, `SceneData.Buildings.Count=1`, `SceneData.Sites.Count=0`, and `ShowRes.Count=4`.
- `BaseData.CenterStoreData.Res` contains 79 resource entries. Using the reflected `WSFramework.ResId` constants, the saved values include `Gold(id=2)=1000`, `Rice(id=3)=50`, `Vegetable(id=4)=50`, `Wood(id=8)=100`, and `Stone(id=9)=100`, matching the visible new-city HUD values.
- Only copies under `data/probe/117224508162075/` were inspected. Original save files were not modified. `data/probe/` is now ignored by Git so payloads and evidence cannot be committed accidentally.

## 2026-09-06 — V2.3X4 Runtime/Save Cross-check preparation

- Read-only inspection confirmed the installed game at `F:\SteamLibrary\steamapps\common\Thriving City Song` uses Unity `2022.3.62f2` (`Song.exe`/`UnityPlayer.dll` file version `2022.3.62.9627366`).
- The exact managed assemblies are present: `Unity.Model.dll`, `UnityEngine.CoreModule.dll`, `Assembly-CSharp.dll`, and `Sirenix.Serialization.dll`. Their local SHA-256 values were recorded only in the command output; no files were modified.
- No `BepInEx` directory, `BepInEx.dll`, `winhttp.dll`, or `doorstop_config.ini` exists under the game directory. `Song.exe` was not running during the check.
- The previously captured city save remains available as ignored copies under `data/probe/117224508162075/`, and the original save tree still contains the corresponding `.index`/`.record` pair. No original save was written.
- Production Bridge build/load and `/health`/`/state` verification are blocked until a version-compatible BepInEx/loader is deliberately installed and the game is running. Do not guess a loader version or install it automatically.
- The user later started the game; a read-only check found `Song.exe` responding at PID `23392`, HWND `30738232`, with the same Unity `2022.3.62f2` build. BepInEx/Doorstop markers remain absent and loopback port `18765` has no listener, so the Bridge is not loaded.
- After explicit user confirmation, installed only the verified official `BepInEx_win_x64_5.4.23.5.zip` into the exact game root. The archive SHA-256 matched `82f9878551030f54657792c0740d9d51a09500eeae1fba21106b0c441e6732c4`; the package's `.doorstop_version` is `4.5.0`. No existing loader conflict was present, and the project Bridge was not installed.
- The game process was not restarted after installation. A production Bridge build attempt is currently blocked because this machine has no .NET SDK (`dotnet build` reports SDK not found); only .NET runtimes are installed. No game files were overwritten, no save was changed, and no input or injection occurred.
- After a user-visible restart, the process loaded the installed game-root `WINHTTP.dll`, but BepInEx produced no `LogOutput.log`, `config`, or `plugins` output and `Player.log` contained no BepInEx/Chainloader markers. `BEPINEX_BOOT` therefore remains `UNCONFIRMED/BLOCKED`; the Runtime Bridge was not installed.
- Toolchain inspection confirms no .NET SDK, no `msbuild.exe`, and no .NET Framework 4.7.2 reference-assembly directory. Only .NET runtimes are installed. Do not change the bridge target framework or install the Bridge DLL until the loader boot and build toolchain are resolved.

## 2026-09-06 — BepInEx Doorstop read-only diagnosis

- Doorstop configuration is present and enabled. `target_assembly=BepInEx\\core\\BepInEx.Preloader.dll` resolves to an existing 43,008-byte assembly; the target and all 21 installed package files match the verified archive lengths.
- `DOORSTOP_DISABLE`, `DOORSTOP_ENABLED`, `DOORSTOP_TARGET_ASSEMBLY`, and `DOORSTOP_IGNORE_DISABLED_ENV` are all not set. The running `Song.exe` PID 28076 loaded the game-root `WINHTTP.dll`, not only the system module.
- A new `preloader_20260906_182826_640.log` proves Doorstop invoked BepInEx Preloader, but Preloader failed before normal BepInEx initialization with `System.MissingMethodException`: `System.Reflection.Module.GetPEKind(PortableExecutableKinds&, ImageFileMachine&)` is unavailable in this game's Unity Mono runtime.
- Root cause is therefore a BepInEx 5.4.23.5 Preloader/Unity Mono compatibility failure, not a missing `winhttp.dll`, missing target assembly, or disabled Doorstop. `BepInEx/LogOutput.log`, `config/`, and `plugins/` were not generated.
- The ignored evidence file is `data/probe/BEPINEX_BOOT_DIAGNOSTIC.json`. No verbose Doorstop replacement, configuration edit, SDK installation, Bridge build, plugin copy, telemetry enablement, or input occurred.

## 2026-09-06 — V2.3X4-B Exact Unity Corlib Compatibility Test preparation

- Preserved the original `Song_Data\\Managed` core files. Before the override, hashes were: `mscorlib.dll` `FC5B144B...4EA92CB`, `System.dll` `1252E720...78044E8`, `System.Core.dll` `A9A106E0...B77FC37`; `netstandard.dll` was absent.
- Downloaded the official `https://unity.bepinex.dev/corlibs/2022.3.62.zip` to staging only. Size is `5,829,157` bytes, SHA-256 is `15188999DF738E665AAFFD0C924AF16FC449B0B76808E1C035552D3663293943`, and it contains 15 files including all required core assemblies.
- Used `dnfile`/`pefile` only as a metadata reader against the staged `mscorlib.dll`; the assembly was not loaded or executed. `System.Reflection.Module.GetPEKind` is present with two `out` parameters (`peKind`, `machine`), metadata signature `2002011011a2781011a224`.
- Backed up `doorstop_config.ini` with before-hash `4D5C6DFA...3CE73CFC`, copied only the 15 official corlibs into the new `BepInEx\\unstripped_corlib` directory, and changed only `UnityMono.dll_search_path_override` to `BepInEx\\unstripped_corlib`. The after-hash is `5721896C...29FE277`; line diff confirms one setting changed.
- The game was not restarted after the override. The next step is a user-launched read-only boot check; do not install Bridge, enable telemetry, or run input before that result.

- Use Python 3.11+ with a standard-library-first core to keep local/offline setup portable.
- Use SQLite for durable local state and an append-only audit trail.
- Use typed dataclasses and JSON validation at boundaries instead of passing arbitrary model output to an executor.
- Default all execution to dry-run and require explicit configuration for real input injection.
- Memory profiles are explicit JSON with process name, module, pointer size, pointer offsets, and scalar types; invalid profiles and missing processes fail closed.
- Latest acceptance confirmed the V0.1 foundation is valid but only about 35–40% of the full automation goal. The first V0.2 integration task is the Steam Window Adapter; live input, screenshot capture, real profiles, loop, Feishu transport, and verification remain separate tasks.
