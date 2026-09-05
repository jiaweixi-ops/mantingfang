from __future__ import annotations

import ctypes
import os
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
    def move_absolute(self, x: int, y: int) -> None: ...
    def mouse_click(self) -> None: ...
    def key(self, virtual_key: int, down: bool) -> None: ...


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

    def execute(self, command: InputCommand) -> dict[str, Any]:
        if not self.enabled:
            raise InputDisabled("SendInput is disabled; use dry-run or explicitly arm live input")
        info = self.window.locate()
        if command.kind == "click" and not self.allow_clicks:
            raise InputDisabled("mouse clicks are not enabled by input policy")
        if command.kind in {"key_down", "key_up"} and not self.allow_keyboard:
            raise InputDisabled("keyboard input is not enabled by input policy")
        if command.kind in {"move", "click"}:
            x, y = info.screen_point(command.x_ratio, command.y_ratio)
            self.backend.move_absolute(x, y)
            if command.kind == "click":
                self.backend.mouse_click()
            return {"kind": command.kind, "screen_point": (x, y), "simulated": False}
        self.backend.key(command.key, command.kind == "key_down")
        return {"kind": command.kind, "key": command.key, "simulated": False}


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

    def __init__(self) -> None:
        if os.name != "nt":
            raise InputError("SendInput requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_Win32Input), ctypes.c_int]
        self.user32.SendInput.restype = ctypes.c_uint
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int

    def _send(self, input_value: _Win32Input) -> None:
        sent = self.user32.SendInput(1, ctypes.byref(input_value), ctypes.sizeof(_Win32Input))
        if sent != 1:
            raise InputError(f"SendInput failed: {ctypes.get_last_error()}")

    def move_absolute(self, x: int, y: int) -> None:
        width = self.user32.GetSystemMetrics(0)
        height = self.user32.GetSystemMetrics(1)
        if width <= 1 or height <= 1:
            raise InputError("screen metrics are unavailable")
        value = _Win32Input(type=self.INPUT_MOUSE, mi=_Win32MouseInput(
            dx=round(x * 65535 / (width - 1)),
            dy=round(y * 65535 / (height - 1)),
            dwFlags=self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE,
        ))
        self._send(value)

    def mouse_click(self) -> None:
        for flags in (self.MOUSEEVENTF_LEFTDOWN, self.MOUSEEVENTF_LEFTUP):
            self._send(_Win32Input(type=self.INPUT_MOUSE, mi=_Win32MouseInput(dwFlags=flags)))

    def key(self, virtual_key: int, down: bool) -> None:
        flags = 0 if down else self.KEYEVENTF_KEYUP
        self._send(_Win32Input(type=self.INPUT_KEYBOARD, ki=_Win32KeyboardInput(wVk=virtual_key, dwFlags=flags)))
