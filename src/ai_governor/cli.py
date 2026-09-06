from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

from .config import Settings
from .capture import (
    CaptureBlackFrameError,
    CaptureError,
    ClientAreaCapture,
    PrintWindowCaptureBackend,
    WindowsGraphicsCaptureBackend,
    Win32ClientCaptureBackend,
    encode_rgba_png,
)
from .qwen import QwenConfigurationError, QwenRequestError, QwenClient
from .e2e import (
    BuildMenuE2EHarness,
    E2EConfigurationError,
    E2EPreflightError,
    calibrate_build_menu_state,
    calibrated_runtime_regions,
    resolve_build_menu_target,
    run_live_build_menu_open_only,
    run_live_build_menu_close_only,
    run_live_build_menu_roundtrip,
    run_read_only_preflight,
)
from .build_category_e2e import BuildCategoryE2EError, run_build_category_dry_run, run_live_build_category_once
from .build_menu_observer import BuildMenuCalibrationError, sample_build_menu_phase
from .feishu import CommandRouter
from .feishu_http import FeishuApiClient, FeishuCallbackServer, FeishuEventHandler
from .memory import (
    MemoryAccessError,
    MemoryConfigurationError,
    MemoryProfile,
    MemorySampler,
    UnsupportedPlatformError,
    WindowsMemoryBackend,
    WindowsProcessEnumerator,
)
from .window import SteamWindowAdapter, Win32WindowBackend, WindowError, WindowNotFound
from .reporting import ReportService
from .runtime import RuntimeConfigurationError, build_runtime
from .storage import SQLiteStore
from .supervisor import GovernorSupervisor
from .watchdog import Watchdog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="满庭芳 AI Governor local control")
    parser.add_argument("--db", help="SQLite path; defaults to GOVERNOR_DB_PATH")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize the local database")
    sub.add_parser("status")
    sub.add_parser("report")
    sub.add_parser("goals")
    sub.add_parser("overlay", help="open the floating Windows assistant window")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("arm-live", help="arm live input after explicit configuration")
    sub.add_parser("disarm-live", help="disarm live input immediately")
    server = sub.add_parser("feishu-server", help="serve Feishu callback events locally")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    run = sub.add_parser("run", help="run the Qwen Governor loop")
    run.add_argument("--max-cycles", type=int, help="stop after this many cycles; omit for continuous run")
    run.add_argument("--interval", type=float, default=10.0, help="seconds between cycles")
    run.add_argument("--region", action="append", dest="regions", help="vision region; repeat for multiple regions")
    run.add_argument("--supervise", action="store_true", help="restart unexpected loop crashes with bounded backoff")
    run.add_argument("--restart-limit", type=int, default=3)
    run.add_argument("--restart-backoff", type=float, default=5.0)
    e2e = sub.add_parser("e2e-build-menu", help="run the explicitly gated real Steam build-menu E2E")
    e2e.add_argument("--attempts", type=int, default=100)
    e2e.add_argument("--confirm-live-e2e", action="store_true", help="required confirmation before real input")
    e2e.add_argument("--open-region")
    e2e.add_argument("--open-element")
    e2e.add_argument("--close-region")
    e2e.add_argument("--close-element")
    e2e.add_argument("--wait-for-game-foreground", action="store_true", help="wait up to 30 seconds for Song to remain foreground for 3 seconds")
    calibration = sub.add_parser("e2e-calibrate-build-menu", help="read-only semantic build-menu calibration")
    calibration.add_argument("--state", choices=("open", "closed"), required=True)
    calibration.add_argument("--output-dir", default="data/e2e")
    calibration.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    resolver = sub.add_parser("e2e-resolve-build-menu-targets", help="read-only resolve a calibrated build-menu target")
    resolver.add_argument("--state", choices=("open", "closed"), required=True)
    resolver.add_argument("--output-dir", default="data/e2e")
    resolver.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    roundtrip = sub.add_parser("e2e-build-menu-roundtrip", help="run one guarded closed-open-closed Live build-menu roundtrip")
    roundtrip.add_argument("--confirm-live-roundtrip", action="store_true", help="required confirmation before the two real clicks")
    roundtrip.add_argument("--output-dir", default="data/e2e")
    roundtrip.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    roundtrip.add_argument("--verify-timeout-seconds", type=float, default=5.0)
    roundtrip.add_argument("--poll-seconds", type=float, default=0.25)
    roundtrip.add_argument("--wait-for-game-foreground", action="store_true", help="wait without focusing until Song is foreground for 3 seconds")
    open_only = sub.add_parser("e2e-build-menu-open-only", help="run one guarded Live click to open the build menu; never close or place")
    open_only.add_argument("--confirm-live-open", action="store_true", help="required confirmation before the one real click")
    open_only.add_argument("--output-dir", default="data/e2e/build_menu_open_only")
    open_only.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    open_only.add_argument("--verify-timeout-seconds", type=float, default=5.0)
    open_only.add_argument("--poll-seconds", type=float, default=0.25)
    open_only.add_argument("--wait-for-game-foreground", action="store_true", help="wait without focusing until Song is foreground for 3 seconds")
    close_only = sub.add_parser("e2e-build-menu-close-only", help="run one guarded Live click to close the build menu; never open or place")
    close_only.add_argument("--confirm-live-close", action="store_true", help="required confirmation before the one real click")
    close_only.add_argument("--output-dir", default="data/e2e/build_menu_close_only")
    close_only.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    close_only.add_argument("--verify-timeout-seconds", type=float, default=5.0)
    close_only.add_argument("--poll-seconds", type=float, default=0.25)
    close_only.add_argument("--wait-for-game-foreground", action="store_true", help="wait without focusing until Song is foreground for 3 seconds")
    category_plan = sub.add_parser("e2e-plan-build-category", help="read-only current-frame V2.4C category click planning")
    category_plan.add_argument("--output-dir", default="data/probe/V2.4C")
    category_plan.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    category_once = sub.add_parser("e2e-build-category-once", help="run exactly one guarded Live click on a fresh Build Menu category target")
    category_once.add_argument("--confirm-live-category", action="store_true", help="required confirmation before the one real category click")
    category_once.add_argument("--output-dir", default="data/probe/V2.4C")
    category_once.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    category_once.add_argument("--wait-for-game-foreground", action="store_true", help="wait without focusing until Song is foreground for 3 seconds")
    category_once.add_argument("--foreground-timeout-seconds", type=float, default=30.0)
    category_once.add_argument("--settle-seconds", type=float, default=0.6)
    preflight = sub.add_parser("e2e-preflight", help="run read-only Steam capture and Vision preflight")
    preflight.add_argument("--wait-for-game-foreground", action="store_true", help="wait up to 30 seconds for Song to remain foreground for 3 seconds")
    preflight.add_argument("--timeout-seconds", type=float, default=30.0)
    preflight.add_argument("--stable-seconds", type=float, default=3.0)
    preflight.add_argument("--poll-seconds", type=float, default=0.5)
    preflight.add_argument("--output-dir", default="data/e2e")
    preflight.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    readonly_calibration = sub.add_parser(
        "e2e-calibrate-build-menu-readonly",
        help="sample one real-game Build Menu phase with WGC and zero input",
    )
    readonly_calibration.add_argument("--phase", choices=("closed", "root", "category"), required=True)
    readonly_calibration.add_argument("--samples", type=int, default=3)
    readonly_calibration.add_argument("--interval", type=float, default=0.5)
    readonly_calibration.add_argument("--output-dir", default="data/probe/V2.4ABR")
    readonly_calibration.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    readonly_calibration.add_argument("--vision-model", default="qwen3.8-flash")
    sub.add_parser("memory-processes", help="list Windows processes for profile calibration")
    memory_modules = sub.add_parser("memory-modules", help="list loaded modules for one Windows process")
    memory_modules.add_argument("--process-name", required=True, help="exact process name, for example Song.exe")
    window_info = sub.add_parser("window-info", help="inspect the configured Steam game window")
    window_info.add_argument("--title", help="exact window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    capture = sub.add_parser("capture", help="capture the configured game client area as PNG")
    capture.add_argument("--title", help="exact window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    capture.add_argument("--out", required=True, help="PNG output path")
    diagnostic = sub.add_parser("capture-diagnostic", help="compare GDI, PrintWindow, and WGC without input")
    diagnostic.add_argument("--title", help="exact window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    diagnostic.add_argument("--output-dir", default="data/e2e")
    probe = sub.add_parser("vision-probe", help="send a safe temporary PNG to the configured Qwen Vision model")
    telemetry = sub.add_parser("telemetry-read", help="read the configured local runtime telemetry bridge without input")
    telemetry.add_argument("--title", help="exact game window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    probe.add_argument("--out", help="optional safe probe PNG path")
    memory_read = sub.add_parser("memory-read", help="read only fields from an explicit memory profile")
    memory_read.add_argument("--profile", help="JSON memory profile; defaults to GOVERNOR_MEMORY_PROFILE")
    command = sub.add_parser("command")
    command.add_argument("text", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.db:
        from dataclasses import replace
        settings = replace(settings, db_path=Path(args.db))
    settings.ensure_directories()
    if args.command == "telemetry-read":
        from .telemetry import RuntimeTelemetryClient, RuntimeTelemetryError
        try:
            if not settings.runtime_game_version:
                raise RuntimeConfigurationError(
                    "GOVERNOR_RUNTIME_GAME_VERSION is required for telemetry-read"
                )
            window = SteamWindowAdapter(args.title or settings.game_window_title, Win32WindowBackend())
            info = window.locate()
            game_pid = window.backend.window_process_id(info.hwnd)
            if game_pid is None:
                raise RuntimeConfigurationError("telemetry-read requires a readable Song PID")
            client = RuntimeTelemetryClient(
                settings.runtime_bridge_url,
                expected_pid=game_pid,
                expected_game_version=settings.runtime_game_version,
            )
            print(json.dumps({"health": client.health(), "state": client.read()}, ensure_ascii=False, indent=2))
        except (RuntimeTelemetryError, RuntimeConfigurationError, WindowError, OSError) as exc:
            print(json.dumps({"status": "UNKNOWN", "error": str(exc)}, ensure_ascii=False))
            return 2
        return 0
    if args.command == "overlay":
        from .overlay import run_overlay
        return run_overlay()
    if args.command == "memory-processes":
        try:
            processes = WindowsProcessEnumerator().list()
        except UnsupportedPlatformError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps([item.__dict__ for item in processes], ensure_ascii=False, indent=2))
        return 0
    if args.command == "memory-modules":
        try:
            process = WindowsProcessEnumerator().find(args.process_name)
            if process is None:
                raise MemoryAccessError(f"process not found: {args.process_name}")
            modules = WindowsMemoryBackend().list_modules(process.pid)
        except (MemoryAccessError, UnsupportedPlatformError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps([module.__dict__ for module in modules], ensure_ascii=False, indent=2))
        return 0
    if args.command == "window-info":
        try:
            info = SteamWindowAdapter(args.title or settings.game_window_title, Win32WindowBackend()).locate()
        except WindowError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(info.__dict__, ensure_ascii=False, indent=2))
        return 0
    if args.command == "capture":
        try:
            adapter = SteamWindowAdapter(args.title or settings.game_window_title, Win32WindowBackend())
            frame = ClientAreaCapture(adapter, WindowsGraphicsCaptureBackend(), reject_near_black=True).capture()
            output = Path(args.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(frame.png)
        except (CaptureError, WindowError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        diagnostic = frame.diagnostic.to_dict() if frame.diagnostic else None
        print(json.dumps({"path": str(output), "width": frame.width, "height": frame.height, "diagnostic": diagnostic}, ensure_ascii=False))
        return 0
    if args.command == "capture-diagnostic":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        window_backend = Win32WindowBackend()
        requested_title = args.title or settings.game_window_title
        adapter = SteamWindowAdapter(requested_title, window_backend)
        try:
            info = adapter.locate()
        except WindowNotFound:
            if args.title or requested_title == "Song":
                raise
            adapter = SteamWindowAdapter("Song", window_backend)
            info = adapter.locate()
        report: dict[str, object] = {
            "game_hwnd": info.hwnd,
            "game_pid": window_backend.window_process_id(info.hwnd),
            "window_title": info.title,
            "client_width": info.client_width,
            "client_height": info.client_height,
            "foreground": adapter.foreground_diagnostic(info).to_dict(),
            "gdi": {},
            "printwindow": {},
            "wgc": {},
        }

        def run_backend(name: str, factory, filename: str) -> dict[str, object]:
            result: dict[str, object] = {"backend": name}
            try:
                backend = factory()
                result["backend"] = getattr(backend, "backend_name", type(backend).__name__)
                frame = ClientAreaCapture(adapter, backend).capture()
                path = output_dir / filename
                path.write_bytes(frame.png)
                result.update({
                    "success": True,
                    "near_black": bool(frame.diagnostic.near_black_frame) if frame.diagnostic else False,
                    "dimensions": [frame.width, frame.height],
                    "diagnostic": frame.diagnostic.to_dict() if frame.diagnostic else None,
                    "path": str(path),
                })
            except Exception as exc:
                result.update({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return result

        report["gdi"] = run_backend("gdi", Win32ClientCaptureBackend, "capture_gdi.png")
        report["printwindow"] = run_backend("printwindow", PrintWindowCaptureBackend, "capture_printwindow.png")
        report["wgc"] = run_backend("wgc", WindowsGraphicsCaptureBackend, "capture_wgc.png")
        report_path = output_dir / "capture_diagnostic.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["wgc"].get("success") else 2
    if args.command == "vision-probe":
        if not settings.qwen_api_key:
            print("ERROR: QWEN_API_KEY is not configured", file=sys.stderr)
            return 2
        if not settings.qwen_vision_model:
            print("ERROR: QWEN_VISION_MODEL is not configured", file=sys.stderr)
            return 2
        rgba = bytes((32, 96, 160, 255)) * (32 * 32)
        png = encode_rgba_png(32, 32, rgba)
        if args.out:
            probe_path = Path(args.out)
            probe_path.parent.mkdir(parents=True, exist_ok=True)
            probe_path.write_bytes(png)
        client = QwenClient(settings.qwen_api_base, settings.qwen_api_key, settings.qwen_vision_model)
        try:
            response = client.analyze_image_json(
                png,
                '返回 JSON：{"vision_probe": true}。只输出 JSON，不要解释。',
                model=settings.qwen_vision_model,
            )
        except QwenRequestError as exc:
            print(json.dumps({
                "status": "FAIL",
                "api_base": settings.qwen_api_base,
                "model": settings.qwen_vision_model,
                "http_status": exc.status_code,
                "error_type": exc.error_type,
                "error": str(exc),
            }, ensure_ascii=False))
            return 2
        print(json.dumps({
            "status": "PASS",
            "api_base": settings.qwen_api_base,
            "model": settings.qwen_vision_model,
            "http_status": 200,
            "json": response,
            "usage": client.last_usage.to_dict() if client.last_usage else None,
        }, ensure_ascii=False))
        return 0
    if args.command == "memory-read":
        profile_path = Path(args.profile) if args.profile else settings.memory_profile_path
        if profile_path is None:
            raise SystemExit("memory-read requires --profile or GOVERNOR_MEMORY_PROFILE")
        try:
            profile = MemoryProfile.from_json(profile_path)
            sampler = MemorySampler(profile, WindowsProcessEnumerator(), WindowsMemoryBackend())
            result = sampler.sample()
        except (MemoryConfigurationError, MemoryAccessError, UnsupportedPlatformError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    store = SQLiteStore(settings.db_path)
    try:
        if args.command == "init":
            print(f"initialized {settings.db_path}")
            return 0
        if args.command == "arm-live":
            if settings.execution_mode != "live" or not settings.allow_live_input:
                print("ERROR: set GOVERNOR_EXECUTION_MODE=live and GOVERNOR_ALLOW_LIVE_INPUT=true first", file=sys.stderr)
                return 2
            store.set_runtime("live_armed", True)
            print("live input armed; semantic verification is still required")
            return 0
        if args.command == "disarm-live":
            store.set_runtime("live_armed", False)
            print("live input disarmed")
            return 0
        if args.command == "feishu-server":
            if not settings.feishu_app_id or not settings.feishu_app_secret:
                print("ERROR: FEISHU_APP_ID and FEISHU_APP_SECRET are required", file=sys.stderr)
                return 2
            router = CommandRouter(store, ReportService(store), Watchdog(store))
            client = FeishuApiClient(settings.feishu_app_id, settings.feishu_app_secret, settings.feishu_api_base)
            handler = FeishuEventHandler(router, client, settings.feishu_verification_token, settings.feishu_encrypt_key)
            try:
                server = FeishuCallbackServer(handler, args.host, args.port)
                print(json.dumps({"listening": server.address}, ensure_ascii=False))
                server.serve_forever()
            except (OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            return 0
        if args.command == "run":
            if args.interval < 0:
                print("ERROR: --interval must be non-negative", file=sys.stderr)
                return 2
            try:
                regions = args.regions or ("resources", "map", "events", "build_menu", "dialog")
                runtime = build_runtime(settings, store, regions)
                runtime.loop.interval_seconds = args.interval
                if args.supervise:
                    supervisor = GovernorSupervisor(
                        lambda: build_runtime(settings, store, regions).loop,
                        store,
                        Watchdog(store),
                        max_restarts=args.restart_limit,
                        backoff_seconds=args.restart_backoff,
                    )
                    cycles = supervisor.run(max_cycles=args.max_cycles)
                else:
                    cycles = runtime.loop.run(max_cycles=args.max_cycles)
            except (RuntimeConfigurationError, QwenConfigurationError, MemoryConfigurationError, MemoryAccessError, UnsupportedPlatformError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps([cycle.__dict__ for cycle in cycles], ensure_ascii=False, indent=2))
            return 0
        if args.command == "e2e-build-menu":
            try:
                if args.wait_for_game_foreground:
                    run_read_only_preflight(settings, store, wait_for_game_foreground=True)
                calibration_path = Path("data/e2e") / "build_menu_calibration.json"
                if not calibration_path.exists():
                    raise E2EConfigurationError("build_menu_calibration.json is missing")
                calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
                regions = calibrated_runtime_regions(calibration)
                open_target = calibration.get("open") or {}
                close_target = calibration.get("close") or {}
                runtime = build_runtime(settings, store, regions)
                vision_source = runtime.source.sources[0]
                observed_regions = set(getattr(vision_source, "regions", ()))
                calibrated_regions = {open_target.get("region"), close_target.get("region")} - {None}
                if not calibrated_regions.issubset(observed_regions):
                    raise E2EConfigurationError("calibrated target region is not observed by runtime")
                result = BuildMenuE2EHarness(
                    settings,
                    store,
                    runtime.governor.actions,
                    open_region=args.open_region or open_target.get("region"),
                    open_element=args.open_element or open_target.get("canonical_id"),
                    close_region=args.close_region or close_target.get("region"),
                    close_element=args.close_element or close_target.get("canonical_id"),
                ).run(attempts=args.attempts, confirm_live=args.confirm_live_e2e)
            except (E2EConfigurationError, E2EPreflightError, RuntimeConfigurationError, QwenConfigurationError, MemoryConfigurationError, MemoryAccessError, UnsupportedPlatformError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "e2e-calibrate-build-menu":
            try:
                result = calibrate_build_menu_state(
                    settings,
                    store,
                    state=args.state,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                )
            except (E2EPreflightError, QwenConfigurationError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("calibration_pass") else 2
        if args.command == "e2e-resolve-build-menu-targets":
            try:
                result = resolve_build_menu_target(
                    settings,
                    store,
                    state=args.state,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                )
            except (E2EConfigurationError, E2EPreflightError, QwenConfigurationError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("found") else 2
        if args.command == "e2e-build-menu-roundtrip":
            if not args.confirm_live_roundtrip:
                print("ERROR: real roundtrip requires --confirm-live-roundtrip", file=sys.stderr)
                return 2
            try:
                result = run_live_build_menu_roundtrip(
                    settings,
                    store,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                    verify_timeout_seconds=args.verify_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    wait_for_game_foreground=args.wait_for_game_foreground,
                )
            except (E2EConfigurationError, E2EPreflightError, QwenConfigurationError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("result") == "PASS" else 2
        if args.command == "e2e-build-menu-open-only":
            if not args.confirm_live_open:
                print("ERROR: open-only live diagnostic requires --confirm-live-open", file=sys.stderr)
                return 2
            try:
                result = run_live_build_menu_open_only(
                    settings,
                    store,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                    verify_timeout_seconds=args.verify_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    wait_for_game_foreground=args.wait_for_game_foreground,
                )
            except (E2EConfigurationError, E2EPreflightError, QwenConfigurationError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("result") == "PASS" else 2
        if args.command == "e2e-build-menu-close-only":
            if not args.confirm_live_close:
                print("ERROR: close-only live diagnostic requires --confirm-live-close", file=sys.stderr)
                return 2
            try:
                result = run_live_build_menu_close_only(
                    settings,
                    store,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                    verify_timeout_seconds=args.verify_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    wait_for_game_foreground=args.wait_for_game_foreground,
                )
            except (E2EConfigurationError, E2EPreflightError, QwenConfigurationError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("result") == "PASS" else 2
        if args.command == "e2e-plan-build-category":
            try:
                result = run_build_category_dry_run(
                    settings,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                )
            except (BuildCategoryE2EError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "e2e-build-category-once":
            if not args.confirm_live_category:
                print("ERROR: V2.4C requires --confirm-live-category", file=sys.stderr)
                return 2
            try:
                result = run_live_build_category_once(
                    settings,
                    store,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                    wait_for_game_foreground=args.wait_for_game_foreground,
                    foreground_timeout_seconds=args.foreground_timeout_seconds,
                    settle_seconds=args.settle_seconds,
                )
            except (BuildCategoryE2EError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("result") == "PASS" else 2
        if args.command == "e2e-preflight":
            try:
                result = run_read_only_preflight(
                    settings,
                    store,
                    wait_for_game_foreground=args.wait_for_game_foreground,
                    timeout_seconds=args.timeout_seconds,
                    stable_seconds=args.stable_seconds,
                    poll_seconds=args.poll_seconds,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                )
            except (E2EPreflightError, QwenConfigurationError, WindowError, CaptureBlackFrameError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "e2e-calibrate-build-menu-readonly":
            try:
                result = sample_build_menu_phase(
                    settings,
                    store,
                    phase=args.phase,
                    samples=args.samples,
                    interval_seconds=args.interval,
                    output_dir=Path(args.output_dir),
                    window_title=args.title,
                    vision_model=args.vision_model,
                )
            except (
                BuildMenuCalibrationError,
                QwenConfigurationError,
                WindowError,
                CaptureError,
                OSError,
                ValueError,
            ) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("stability", {}).get("stable") else 2
        reports = ReportService(store)
        watchdog = Watchdog(store)
        router = CommandRouter(store, reports, watchdog)
        output = {
            "status": reports.status,
            "report": reports.daily_report,
            "goals": reports.goals,
            "pause": lambda: (watchdog.pause(), "已暂停托管")[1],
            "resume": lambda: (watchdog.resume(), "已恢复托管")[1],
        }.get(args.command)
        if output:
            print(output())
        elif args.command == "command":
            print(router.handle(" ".join(args.text)))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
