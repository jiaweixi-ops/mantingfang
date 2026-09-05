from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

from .config import Settings
from .capture import CaptureError, ClientAreaCapture, Win32ClientCaptureBackend
from .deepseek import DeepSeekConfigurationError
from .feishu import CommandRouter
from .memory import (
    MemoryAccessError,
    MemoryConfigurationError,
    MemoryProfile,
    MemorySampler,
    UnsupportedPlatformError,
    WindowsMemoryBackend,
    WindowsProcessEnumerator,
)
from .window import SteamWindowAdapter, Win32WindowBackend, WindowError
from .reporting import ReportService
from .runtime import RuntimeConfigurationError, build_runtime
from .storage import SQLiteStore
from .watchdog import Watchdog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="满庭芳 AI Governor local control")
    parser.add_argument("--db", help="SQLite path; defaults to GOVERNOR_DB_PATH")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize the local database")
    sub.add_parser("status")
    sub.add_parser("report")
    sub.add_parser("goals")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("arm-live", help="arm live input after explicit configuration")
    sub.add_parser("disarm-live", help="disarm live input immediately")
    run = sub.add_parser("run", help="run the DeepSeek Governor loop")
    run.add_argument("--max-cycles", type=int, help="stop after this many cycles; omit for continuous run")
    run.add_argument("--interval", type=float, default=10.0, help="seconds between cycles")
    run.add_argument("--region", action="append", dest="regions", help="vision region; repeat for multiple regions")
    sub.add_parser("memory-processes", help="list Windows processes for profile calibration")
    memory_modules = sub.add_parser("memory-modules", help="list loaded modules for one Windows process")
    memory_modules.add_argument("--process-name", required=True, help="exact process name, for example Song.exe")
    window_info = sub.add_parser("window-info", help="inspect the configured Steam game window")
    window_info.add_argument("--title", help="exact window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    capture = sub.add_parser("capture", help="capture the configured game client area as PNG")
    capture.add_argument("--title", help="exact window title; defaults to GOVERNOR_GAME_WINDOW_TITLE")
    capture.add_argument("--out", required=True, help="PNG output path")
    memory_read = sub.add_parser("memory-read", help="read only fields from an explicit memory profile")
    memory_read.add_argument("--profile", help="JSON memory profile; defaults to GOVERNOR_MEMORY_PROFILE")
    command = sub.add_parser("command")
    command.add_argument("text", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.db:
        from dataclasses import replace
        settings = replace(settings, db_path=Path(args.db))
    settings.ensure_directories()
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
            frame = ClientAreaCapture(adapter, Win32ClientCaptureBackend()).capture()
            output = Path(args.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(frame.png)
        except (CaptureError, WindowError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"path": str(output), "width": frame.width, "height": frame.height}, ensure_ascii=False))
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
        if args.command == "run":
            if args.interval < 0:
                print("ERROR: --interval must be non-negative", file=sys.stderr)
                return 2
            try:
                runtime = build_runtime(settings, store, args.regions or ("resources", "map", "events"))
                runtime.loop.interval_seconds = args.interval
                cycles = runtime.loop.run(max_cycles=args.max_cycles)
            except (RuntimeConfigurationError, DeepSeekConfigurationError, MemoryConfigurationError, MemoryAccessError, UnsupportedPlatformError, WindowError, CaptureError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(json.dumps([cycle.__dict__ for cycle in cycles], ensure_ascii=False, indent=2))
            return 0
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
