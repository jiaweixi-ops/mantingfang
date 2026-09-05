from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Protocol


class WindowError(RuntimeError):
    pass


class WindowNotFound(WindowError):
    pass


class WindowNotForeground(WindowError):
    pass


class WindowBackend(Protocol):
    def find_window(self, title: str) -> int | None: ...
    def is_window(self, hwnd: int) -> bool: ...
    def is_minimized(self, hwnd: int) -> bool: ...
    def restore(self, hwnd: int) -> None: ...
    def client_rect(self, hwnd: int) -> tuple[int, int, int, int]: ...
    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]: ...
    def foreground_window(self) -> int | None: ...


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    client_width: int
    client_height: int
    screen_left: int
    screen_top: int
    minimized: bool

    def screen_point(self, x_ratio: float, y_ratio: float) -> tuple[int, int]:
        if not 0 <= x_ratio <= 1 or not 0 <= y_ratio <= 1:
            raise ValueError("normalized client coordinates must be between 0 and 1")
        return (
            self.screen_left + round(self.client_width * x_ratio),
            self.screen_top + round(self.client_height * y_ratio),
        )


class Win32WindowBackend:
    SW_RESTORE = 9

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowError("Steam window integration requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        self.user32.FindWindowW.restype = ctypes.c_void_p
        self.user32.IsWindow.argtypes = [ctypes.c_void_p]
        self.user32.IsWindow.restype = ctypes.c_int
        self.user32.IsIconic.argtypes = [ctypes.c_void_p]
        self.user32.IsIconic.restype = ctypes.c_int
        self.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._Rect)]
        self.user32.GetClientRect.restype = ctypes.c_int
        self.user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._Point)]
        self.user32.ClientToScreen.restype = ctypes.c_int
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p

    def find_window(self, title: str) -> int | None:
        hwnd = self.user32.FindWindowW(None, title)
        return int(hwnd) if hwnd else None

    def is_window(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindow(ctypes.c_void_p(hwnd)))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(ctypes.c_void_p(hwnd)))

    def restore(self, hwnd: int) -> None:
        self.user32.ShowWindow(ctypes.c_void_p(hwnd), self.SW_RESTORE)

    def client_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = self._Rect()
        if not self.user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            raise WindowError(f"GetClientRect failed: {ctypes.get_last_error()}")
        return rect.left, rect.top, rect.right, rect.bottom

    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        point = self._Point(x, y)
        if not self.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(point)):
            raise WindowError(f"ClientToScreen failed: {ctypes.get_last_error()}")
        return point.x, point.y

    def foreground_window(self) -> int | None:
        hwnd = self.user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None


@dataclass
class SteamWindowAdapter:
    title: str
    backend: WindowBackend

    def locate(self, *, restore_minimized: bool = False) -> WindowInfo:
        hwnd = self.backend.find_window(self.title)
        if hwnd is None or not self.backend.is_window(hwnd):
            raise WindowNotFound(f"game window not found: {self.title}")
        minimized = self.backend.is_minimized(hwnd)
        if minimized and restore_minimized:
            self.backend.restore(hwnd)
            minimized = self.backend.is_minimized(hwnd)
        left, top, right, bottom = self.backend.client_rect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise WindowError(f"game client area is invalid: {width}x{height}")
        screen_left, screen_top = self.backend.client_to_screen(hwnd, 0, 0)
        return WindowInfo(hwnd, self.title, width, height, screen_left, screen_top, minimized)

    def require_foreground(self, info: WindowInfo | None = None) -> WindowInfo:
        info = info or self.locate()
        foreground = self.backend.foreground_window()
        if foreground != info.hwnd:
            raise WindowNotForeground(
                f"refusing input: game window is not foreground (game={info.hwnd}, foreground={foreground})"
            )
        return info
