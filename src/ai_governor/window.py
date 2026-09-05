from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from ctypes import wintypes


class WindowError(RuntimeError):
    pass


class WindowNotFound(WindowError):
    pass


class WindowNotForeground(WindowError):
    pass


class ForegroundTimeout(WindowError):
    pass


class WindowBackend(Protocol):
    def find_window(self, title: str) -> int | None: ...
    def is_window(self, hwnd: int) -> bool: ...
    def is_minimized(self, hwnd: int) -> bool: ...
    def restore(self, hwnd: int) -> None: ...
    def client_rect(self, hwnd: int) -> tuple[int, int, int, int]: ...
    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]: ...
    def foreground_window(self) -> int | None: ...
    def window_process_id(self, hwnd: int) -> int | None: ...
    def window_title(self, hwnd: int) -> str: ...
    def process_name(self, pid: int | None) -> str | None: ...


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


@dataclass(frozen=True)
class ForegroundDiagnostic:
    game_hwnd: int
    foreground_hwnd: int | None
    foreground_title: str
    game_pid: int | None
    game_process_name: str | None
    foreground_pid: int | None
    foreground_process_name: str | None
    foreground_matches_game_hwnd: bool
    same_process: bool
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "game_hwnd": self.game_hwnd,
            "foreground_hwnd": self.foreground_hwnd,
            "foreground_title": self.foreground_title,
            "game_pid": self.game_pid,
            "game_process_name": self.game_process_name,
            "foreground_pid": self.foreground_pid,
            "foreground_process_name": self.foreground_process_name,
            "foreground_matches_game_hwnd": self.foreground_matches_game_hwnd,
            "same_process": self.same_process,
            "flags": list(self.flags),
        }


class Win32WindowBackend:
    SW_RESTORE = 9
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

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
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

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

    def window_process_id(self, hwnd: int) -> int | None:
        pid = wintypes.DWORD()
        if not self.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid)):
            return None
        return int(pid.value)

    def window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
        buffer = ctypes.create_unicode_buffer(max(256, length + 1))
        self.user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, len(buffer))
        return buffer.value

    def process_name(self, pid: int | None) -> str | None:
        if not pid:
            return None
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return buffer.value.rsplit("\\", 1)[-1]
        finally:
            self.kernel32.CloseHandle(handle)


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

    def foreground_diagnostic(self, info: WindowInfo | None = None) -> ForegroundDiagnostic:
        info = info or self.locate()
        foreground_hwnd = self.backend.foreground_window()
        game_pid = self.backend.window_process_id(info.hwnd)
        foreground_pid = self.backend.window_process_id(foreground_hwnd) if foreground_hwnd else None
        matches = foreground_hwnd == info.hwnd
        same_process = bool(game_pid and foreground_pid and game_pid == foreground_pid)
        flags = ()
        if same_process and not matches:
            flags = ("FOREGROUND_SAME_GAME_PROCESS_DIFFERENT_HWND",)
        return ForegroundDiagnostic(
            game_hwnd=info.hwnd,
            foreground_hwnd=foreground_hwnd,
            foreground_title=self.backend.window_title(foreground_hwnd) if foreground_hwnd else "",
            game_pid=game_pid,
            game_process_name=self.backend.process_name(game_pid),
            foreground_pid=foreground_pid,
            foreground_process_name=self.backend.process_name(foreground_pid),
            foreground_matches_game_hwnd=matches,
            same_process=same_process,
            flags=flags,
        )

    def wait_for_foreground(
        self,
        *,
        timeout_seconds: float = 30.0,
        stable_seconds: float = 3.0,
        poll_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> WindowInfo:
        """Wait without focusing or activating the game window."""
        if timeout_seconds <= 0 or stable_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("foreground wait durations must be positive")
        deadline = clock() + timeout_seconds
        stable_since: float | None = None
        while True:
            now = clock()
            if now >= deadline:
                raise ForegroundTimeout("FOREGROUND_TIMEOUT: Song did not remain foreground within the timeout")
            try:
                info = self.locate()
            except WindowError:
                stable_since = None
            else:
                if self.backend.foreground_window() == info.hwnd:
                    if stable_since is None:
                        stable_since = now
                    if now - stable_since >= stable_seconds:
                        return info
                else:
                    stable_since = None
            remaining = deadline - clock()
            if remaining <= 0:
                raise ForegroundTimeout("FOREGROUND_TIMEOUT: Song did not remain foreground within the timeout")
            sleep(min(poll_seconds, remaining))
