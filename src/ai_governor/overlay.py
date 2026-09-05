from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, ttk

from .config import (
    Settings,
    load_persisted_settings,
    save_persisted_settings,
    user_settings_path,
)
from .window import SteamWindowAdapter, WindowError, Win32WindowBackend


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOTKEY_ID = 0x4D54
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_HOME = 0x24


class GlobalHomeHotkey:
    """Register and poll a process-wide Home hotkey without extra packages."""

    class _Msg(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt_x", wintypes.LONG),
            ("pt_y", wintypes.LONG),
        ]

    def __init__(self, hwnd: int) -> None:
        if os.name != "nt":
            raise RuntimeError("global Home hotkey requires Windows")
        self.hwnd = hwnd
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.user32.PeekMessageW.argtypes = [ctypes.POINTER(self._Msg), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self.user32.PeekMessageW.restype = wintypes.BOOL
        if not self.user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_NOREPEAT, VK_HOME):
            error = ctypes.get_last_error()
            raise RuntimeError(f"Home hotkey registration failed: {error}")
        self.registered = True

    def poll(self) -> bool:
        message = self._Msg()
        pressed = False
        while self.user32.PeekMessageW(ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, 1):
            if int(message.wParam) == HOTKEY_ID:
                pressed = True
        return pressed

    def close(self) -> None:
        if getattr(self, "registered", False):
            self.user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self.registered = False


class OverlayApp:
    """Small topmost assistant panel that follows the configured game window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("满庭芳 AI Governor")
        self.root.geometry("390x250+40+40")
        self.root.minsize(350, 220)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.settings = Settings.from_env()
        self.window_adapter = SteamWindowAdapter(self.settings.game_window_title, Win32WindowBackend())
        self.hotkey: GlobalHomeHotkey | None = None
        self.game_info = None
        self.process: subprocess.Popen[bytes] | None = None
        self.last_exit_code: int | None = None
        self._settings_dialog: tk.Toplevel | None = None
        self._last_geometry = ""

        self.game_var = tk.StringVar(value="游戏窗口：等待检测")
        self.config_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="安全模式：dry-run（不会发送鼠标键盘输入）")
        self.hotkey_var = tk.StringVar(value="Home：显示/隐藏浮窗")
        self.process_var = tk.StringVar(value="托管状态：未启动")
        self._build_widgets()

        try:
            self.hotkey = GlobalHomeHotkey(self.root.winfo_id())
        except RuntimeError as exc:
            self.hotkey_var.set(f"Home 快捷键不可用：{exc}")
        self.root.after(100, self._poll_hotkey)
        self.root.after(250, self._follow_game)
        self.root.after(500, self._refresh_status)

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="满庭芳 AI Governor", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.game_var).pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, textvariable=self.config_var, wraplength=360).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.mode_var, wraplength=360).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.hotkey_var, wraplength=360).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.process_var, wraplength=360).pack(anchor="w", pady=(4, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))
        self.start_button = ttk.Button(buttons, text="启动 AI 托管", command=self.start_governor)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="停止托管", command=self.stop_governor, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="设置 DeepSeek", command=self.open_settings).pack(side="right")

    def _poll_hotkey(self) -> None:
        if self.hotkey is not None and self.hotkey.poll():
            self.toggle_visibility()
        self.root.after(100, self._poll_hotkey)

    def _follow_game(self) -> None:
        try:
            self.game_info = self.window_adapter.locate()
            self.game_var.set(f"游戏窗口：已连接 {self.game_info.client_width}×{self.game_info.client_height}")
            if self.root.state() != "withdrawn":
                width, height = 390, 250
                x = self.game_info.screen_left + 16
                y = self.game_info.screen_top + 16
                if self.game_info.client_width > width + 32:
                    x = self.game_info.screen_left + self.game_info.client_width - width - 16
                if self.game_info.client_height > height + 32:
                    y = self.game_info.screen_top + self.game_info.client_height - height - 16
                geometry = f"{width}x{height}+{x}+{y}"
                if geometry != self._last_geometry:
                    self.root.geometry(geometry)
                    self._last_geometry = geometry
        except WindowError:
            self.game_info = None
            self.game_var.set("游戏窗口：未找到，等待《满庭芳》启动")
        self.root.after(250, self._follow_game)

    def _refresh_status(self) -> None:
        settings = Settings.from_env()
        configured = bool(settings.deepseek_api_key and settings.deepseek_reasoning_model and settings.deepseek_vision_model)
        self.config_var.set("DeepSeek：已配置" if configured else "DeepSeek：未完成配置，请点击“设置 DeepSeek”")
        if self.process is not None:
            exit_code = self.process.poll()
            if exit_code is None:
                self.process_var.set("托管状态：运行中（dry-run）")
            else:
                self.last_exit_code = exit_code
                self.process = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.process_var.set(f"托管状态：已停止（退出码 {exit_code}）")
        self.root.after(500, self._refresh_status)

    def toggle_visibility(self) -> None:
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.attributes("-topmost", True)
        else:
            self.root.withdraw()

    def open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self._settings_dialog = dialog
        dialog.title("DeepSeek 设置")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        saved = load_persisted_settings()
        current = Settings.from_env()
        values = {
            "deepseek_api_base": saved.get("deepseek_api_base", current.deepseek_api_base),
            "deepseek_api_key": saved.get("deepseek_api_key", current.deepseek_api_key or ""),
            "deepseek_vision_model": saved.get("deepseek_vision_model", current.deepseek_vision_model or ""),
            "deepseek_reasoning_model": saved.get("deepseek_reasoning_model", current.deepseek_reasoning_model or ""),
        }
        labels = {
            "deepseek_api_base": "API Base",
            "deepseek_api_key": "API Key",
            "deepseek_vision_model": "视觉模型",
            "deepseek_reasoning_model": "推理模型",
        }
        entries: dict[str, ttk.Entry] = {}
        for row, key in enumerate(values):
            ttk.Label(frame, text=labels[key]).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            entry = ttk.Entry(frame, width=46, show="*" if key == "deepseek_api_key" else "")
            entry.insert(0, values[key])
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            entries[key] = entry
        ttk.Label(
            frame,
            text=f"保存位置：{user_settings_path()}",
            wraplength=430,
        ).grid(row=len(values), column=0, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Label(
            frame,
            text="API Key 只保存到当前 Windows 用户目录，不会写入 Git 仓库。",
            wraplength=430,
        ).grid(row=len(values) + 1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(values) + 2, column=0, columnspan=2, sticky="e")
        def close_dialog() -> None:
            dialog.grab_release()
            self._settings_dialog = None
            dialog.destroy()

        ttk.Button(buttons, text="取消", command=close_dialog).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="保存并应用", command=lambda: self._save_settings(dialog, entries)).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def _save_settings(self, dialog: tk.Toplevel, entries: dict[str, ttk.Entry]) -> None:
        values = {key: entry.get().strip() for key, entry in entries.items()}
        save_persisted_settings(values)
        env_names = {
            "deepseek_api_base": "DEEPSEEK_API_BASE",
            "deepseek_api_key": "DEEPSEEK_API_KEY",
            "deepseek_vision_model": "DEEPSEEK_VISION_MODEL",
            "deepseek_reasoning_model": "DEEPSEEK_REASONING_MODEL",
        }
        for key, env_name in env_names.items():
            if values[key]:
                os.environ[env_name] = values[key]
            else:
                os.environ.pop(env_name, None)
        dialog.grab_release()
        self._settings_dialog = None
        dialog.destroy()
        self.settings = Settings.from_env()
        self.window_adapter = SteamWindowAdapter(self.settings.game_window_title, Win32WindowBackend())

    def start_governor(self) -> None:
        settings = Settings.from_env()
        missing = [
            name
            for name, value in (
                ("DEEPSEEK_API_KEY", settings.deepseek_api_key),
                ("DEEPSEEK_REASONING_MODEL", settings.deepseek_reasoning_model),
                ("DEEPSEEK_VISION_MODEL", settings.deepseek_vision_model),
            )
            if not value
        ]
        if missing:
            messagebox.showwarning("DeepSeek 配置不完整", "请先填写：" + "、".join(missing), parent=self.root)
            self.open_settings()
            return
        if self.process is not None and self.process.poll() is None:
            return
        log_path = PROJECT_ROOT / "data" / "overlay.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        source_path = str(PROJECT_ROOT / "src")
        environment["PYTHONPATH"] = source_path + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
        environment["GOVERNOR_EXECUTION_MODE"] = "dry-run"
        log_handle = log_path.open("ab")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "ai_governor.cli", "run"],
                cwd=PROJECT_ROOT,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        finally:
            log_handle.close()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.process_var.set(f"托管状态：启动中（日志：{log_path}）")

    def stop_governor(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.last_exit_code = self.process.returncode
        self.process = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.process_var.set("托管状态：已停止")

    def close(self) -> None:
        self.stop_governor()
        if self.hotkey is not None:
            self.hotkey.close()
        self.root.destroy()


def run_overlay() -> int:
    if os.name != "nt":
        print("ERROR: the floating assistant requires Windows")
        return 2
    root = tk.Tk()
    OverlayApp(root)
    root.mainloop()
    return 0
