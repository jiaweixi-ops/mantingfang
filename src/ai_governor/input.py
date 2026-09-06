from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .window import SteamWindowAdapter


class InputError(RuntimeError):
    pass


class InputDisabled(InputError):
    pass


@dataclass(frozen=True)
class InputCommand:
    kind: str
    x_ratio: float | None = None
    y_ratio: float | None = None
    key: int | None = None
    geometry_snapshot: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"move", "click", "key_down", "key_up"}:
            raise ValueError(f"unsupported input command: {self.kind}")
        if self.kind in {"move", "click"}:
            if self.x_ratio is None or self.y_ratio is None:
                raise ValueError("mouse commands require normalized coordinates")
            if not 0 <= self.x_ratio <= 1 or not 0 <= self.y_ratio <= 1:
                raise ValueError("mouse coordinates must be normalized between 0 and 1")
        if self.kind in {"key_down", "key_up"} and self.key is None:
            raise ValueError("keyboard commands require a virtual-key code")


class SendInputBackend(Protocol):
    def move_absolute(self, x: int, y: int) -> int | None: ...
    def cursor_position(self) -> tuple[int, int]: ...
    def mouse_down(self) -> int: ...
    def mouse_up(self) -> int: ...
    def key(self, virtual_key: int, down: bool) -> int | None: ...


@dataclass
class DryRunInputAdapter:
    window: SteamWindowAdapter
    commands: list[dict[str, Any]]

    def execute(self, command: InputCommand) -> dict[str, Any]:
        info = self.window.locate()
        point = info.screen_point(command.x_ratio, command.y_ratio) if command.kind in {"move", "click"} else None
        record = {"kind": command.kind, "screen_point": point, "key": command.key, "simulated": True}
        self.commands.append(record)
        return record


@dataclass
class WindowsSendInputAdapter:
    window: SteamWindowAdapter
    backend: SendInputBackend
    enabled: bool = False
    allow_clicks: bool = False
    allow_keyboard: bool = False
    expected_pid: int | None = None
    auto_foreground: bool = False
    restore_previous_foreground: bool = True
    foreground_stable_seconds: float = 0.6
    foreground_timeout_seconds: float = 5.0

    def _guard_before_input(self, expected_hwnd: int, expected_pid: int | None, expected_geometry: dict[str, Any] | None = None) -> Any:
        info = self.window.locate()
        if info.hwnd != expected_hwnd:
            raise InputError(f"refusing input: game HWND changed (expected={expected_hwnd}, actual={info.hwnd})")
        self.window.require_foreground(info)
        if expected_pid is not None:
            actual_pid = self.window.backend.window_process_id(info.hwnd)
            if actual_pid != expected_pid:
                raise InputError(
                    f"refusing input: game PID changed (expected={expected_pid}, actual={actual_pid})"
                )
        if expected_geometry is not None:
            if self.window.geometry_snapshot(info).to_dict() != expected_geometry:
                raise InputError("TARGET_STALE: game geometry changed; re-resolve the target from a new frame")
        return info

    def execute(self, command: InputCommand) -> dict[str, Any]:
        previous_foreground: int | None = None
        if self.auto_foreground:
            info = self.window.locate(restore_minimized=True)
            info, previous_foreground = self.window.ensure_foreground(
                info,
                timeout_seconds=self.foreground_timeout_seconds,
                stable_seconds=self.foreground_stable_seconds,
            )
        try:
            return self._execute_current(command)
        finally:
            if self.auto_foreground and self.restore_previous_foreground:
                self.window.restore_foreground(previous_foreground)

    def _execute_current(self, command: InputCommand) -> dict[str, Any]:
        if not self.enabled:
            raise InputDisabled("SendInput is disabled; use dry-run or explicitly arm live input")
        info = self.window.locate()
        # The wrapper may have activated the game, but this exact HWND/PID
        # foreground check remains mandatory immediately before every input.
        self.window.require_foreground(info)
        if self.expected_pid is not None:
            actual_pid = self.window.backend.window_process_id(info.hwnd)
            if actual_pid != self.expected_pid:
                raise InputError(
                    f"refusing input: game PID changed (expected={self.expected_pid}, actual={actual_pid})"
                )
        expected_geometry = command.geometry_snapshot
        if expected_geometry is not None and self.window.geometry_snapshot(info).to_dict() != expected_geometry:
            raise InputError("TARGET_STALE: game geometry changed; re-resolve the target from a new frame")
        if command.kind == "click" and not self.allow_clicks:
            raise InputDisabled("mouse clicks are not enabled by input policy")
        if command.kind in {"key_down", "key_up"} and not self.allow_keyboard:
            raise InputDisabled("keyboard input is not enabled by input policy")
        if command.kind in {"move", "click"}:
            x, y = info.screen_point(command.x_ratio, command.y_ratio)
            cursor_before = None
            cursor_after = None
            cursor_getter = getattr(self.backend, "cursor_position", None)
            if callable(cursor_getter):
                cursor_before = list(cursor_getter())
            move_return = self.backend.move_absolute(x, y)
            if callable(cursor_getter):
                cursor_after = list(cursor_getter())
                if max(abs(cursor_after[0] - x), abs(cursor_after[1] - y)) > 2:
                    raise InputError(
                        f"CURSOR_POSITION_MISMATCH: requested=({x},{y}), actual=({cursor_after[0]},{cursor_after[1]})"
                    )
            audit: dict[str, Any] = {
                "requested_screen_point": [x, y],
                "cursor_before": cursor_before,
                "cursor_after_move": cursor_after,
                "move_return_count": move_return,
                "move_verified": None if cursor_after is None else True,
                "input_backend": type(self.backend).__name__,
            }
            if command.kind == "click":
                down_guard = self._guard_before_input(info.hwnd, self.expected_pid, expected_geometry)
                audit["foreground_before_down"] = True
                mouse_down = getattr(self.backend, "mouse_down", None)
                mouse_up = getattr(self.backend, "mouse_up", None)
                if callable(mouse_down) and callable(mouse_up):
                    down_count = mouse_down()
                    audit["mouse_down"] = {"sent": down_count == 1, "return_count": down_count}
                    if down_count != 1:
                        raise InputError(f"INPUT_INJECTION_FAILED: mouse_down return_count={down_count}")
                    time.sleep(0.05)
                    self._guard_before_input(down_guard.hwnd, self.expected_pid, expected_geometry)
                    audit["foreground_before_up"] = True
                    up_count = mouse_up()
                    audit["mouse_up"] = {"sent": up_count == 1, "return_count": up_count}
                    if up_count != 1:
                        raise InputError(f"INPUT_INJECTION_FAILED: mouse_up return_count={up_count}")
                else:
                    # Compatibility path for test/dry adapters. The real Win32
                    # backend always exposes separate down/up methods.
                    click = getattr(self.backend, "mouse_click", None)
                    if not callable(click):
                        raise InputError("INPUT_INJECTION_FAILED: backend has no mouse click primitive")
                    click()
                    audit["mouse_down"] = {"sent": None, "return_count": None}
                    audit["mouse_up"] = {"sent": None, "return_count": None}
                    audit["foreground_before_up"] = True
                return {"kind": command.kind, "screen_point": (x, y), "simulated": False, "input_audit": audit}
            return {"kind": command.kind, "screen_point": (x, y), "simulated": False, "input_audit": audit}
        key_return = self.backend.key(command.key, command.kind == "key_down")
        return {"kind": command.kind, "key": command.key, "simulated": False, "return_count": key_return}


class _Win32MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p)]


class _Win32KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p)]


class _Win32InputUnion(ctypes.Union):
    _fields_ = [("mi", _Win32MouseInput), ("ki", _Win32KeyboardInput)]


class _Win32Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", ctypes.c_uint32), ("data", _Win32InputUnion)]


class Win32SendInputBackend:
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    def __init__(self) -> None:
        if os.name != "nt":
            raise InputError("SendInput requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_Win32Input), ctypes.c_int]
        self.user32.SendInput.restype = ctypes.c_uint
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.c_long * 2)]
        self.user32.GetCursorPos.restype = ctypes.c_int

    def _send(self, input_value: _Win32Input) -> int:
        sent = self.user32.SendInput(1, ctypes.byref(input_value), ctypes.sizeof(_Win32Input))
        if sent != 1:
            raise InputError(f"INPUT_INJECTION_FAILED: SendInput return_count={sent}, error={ctypes.get_last_error()}")
        return int(sent)

    def cursor_position(self) -> tuple[int, int]:
        point = (ctypes.c_long * 2)()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise InputError(f"GetCursorPos failed: {ctypes.get_last_error()}")
        return int(point[0]), int(point[1])

    def move_absolute(self, x: int, y: int) -> int:
        left = self.user32.GetSystemMetrics(self.SM_XVIRTUALSCREEN)
        top = self.user32.GetSystemMetrics(self.SM_YVIRTUALSCREEN)
        width = self.user32.GetSystemMetrics(self.SM_CXVIRTUALSCREEN)
        height = self.user32.GetSystemMetrics(self.SM_CYVIRTUALSCREEN)
        if width <= 1 or height <= 1:
            raise InputError("screen metrics are unavailable")
        x = min(max(int(x), left), left + width - 1)
        y = min(max(int(y), top), top + height - 1)
        value = _Win32Input(type=self.INPUT_MOUSE, mi=_Win32MouseInput(
            dx=round((x - left) * 65535 / (width - 1)),
            dy=round((y - top) * 65535 / (height - 1)),
            dwFlags=self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE | self.MOUSEEVENTF_VIRTUALDESK,
        ))
        return self._send(value)

    def mouse_down(self) -> int:
        return self._send(_Win32Input(type=self.INPUT_MOUSE, mi=_Win32MouseInput(dwFlags=self.MOUSEEVENTF_LEFTDOWN)))

    def mouse_up(self) -> int:
        return self._send(_Win32Input(type=self.INPUT_MOUSE, mi=_Win32MouseInput(dwFlags=self.MOUSEEVENTF_LEFTUP)))

    def mouse_click(self) -> tuple[int, int]:
        down = self.mouse_down()
        time.sleep(0.05)
        up = self.mouse_up()
        return down, up

    def key(self, virtual_key: int, down: bool) -> int:
        flags = 0 if down else self.KEYEVENTF_KEYUP
        return self._send(_Win32Input(type=self.INPUT_KEYBOARD, ki=_Win32KeyboardInput(wVk=virtual_key, dwFlags=flags)))
