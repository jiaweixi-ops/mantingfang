from __future__ import annotations

import ctypes
import os
import struct
import threading
import zlib
from dataclasses import dataclass, field
from typing import Protocol

from .window import SteamWindowAdapter, WindowInfo


class CaptureError(RuntimeError):
    pass


class CaptureBackendUnavailable(CaptureError):
    """The requested capture backend is not installed or supported."""


class CaptureBackendFailure(CaptureError):
    """The requested capture backend failed; callers must not silently downgrade."""


class CaptureBlackFrameError(CaptureError):
    """Raised when a configured live capture backend returns a near-black frame."""

    def __init__(self, diagnostic: "CaptureDiagnostic") -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.status)


@dataclass(frozen=True)
class CaptureDiagnostic:
    hwnd: int
    client_width: int
    client_height: int
    capture_backend: str
    raster_mode: str
    near_black_frame: bool
    status: str
    backend_name: str = ""
    is_occlusion_independent: bool = False
    supports_directx_window_capture: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "client_width": self.client_width,
            "client_height": self.client_height,
            "capture_backend": self.capture_backend,
            "raster_mode": self.raster_mode,
            "near_black_frame": self.near_black_frame,
            "status": self.status,
            "backend_name": self.backend_name or self.capture_backend,
            "is_occlusion_independent": self.is_occlusion_independent,
            "supports_directx_window_capture": self.supports_directx_window_capture,
        }


@dataclass(frozen=True)
class CapturedFrame:
    width: int
    height: int
    png: bytes
    rgba: bytes
    diagnostic: CaptureDiagnostic | None = None


class ClientCaptureBackend(Protocol):
    def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes: ...


def _backend_capability(backend: object, name: str, default: object) -> object:
    return getattr(backend, name, default)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def encode_rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions must be positive")
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer size does not match dimensions")
    scanlines = b"".join(
        b"\x00" + rgba[row * width * 4:(row + 1) * width * 4]
        for row in range(height)
    )
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(scanlines)) + _png_chunk(b"IEND", b"")


def is_near_black_frame(rgba: bytes, *, channel_threshold: int = 8, min_black_ratio: float = 0.98) -> bool:
    """Return whether a frame is overwhelmingly black without inspecting its contents semantically."""
    if not rgba or len(rgba) % 4:
        return True
    pixel_count = len(rgba) // 4
    stride = max(1, pixel_count // 10000)
    sampled = 0
    black = 0
    for pixel in range(0, pixel_count, stride):
        offset = pixel * 4
        red, green, blue = rgba[offset:offset + 3]
        sampled += 1
        if red <= channel_threshold and green <= channel_threshold and blue <= channel_threshold:
            black += 1
    return sampled == 0 or black / sampled >= min_black_ratio


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", ctypes.c_uint32 * 1)]


class Win32ClientCaptureBackend:
    backend_name = "Win32ClientCaptureBackend"
    is_occlusion_independent = False
    supports_directx_window_capture = False
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000
    DEFAULT_RASTER_OP = SRCCOPY
    DEFAULT_RASTER_MODE = "SRCCOPY"
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    def __init__(self, *, raster_op: int | None = None) -> None:
        if os.name != "nt":
            raise CaptureError("client capture requires Windows")
        self.raster_op = self.DEFAULT_RASTER_OP if raster_op is None else raster_op
        self.raster_mode = self.DEFAULT_RASTER_MODE if self.raster_op == self.SRCCOPY else f"0x{self.raster_op:08x}"
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.GetDC.argtypes = [ctypes.c_void_p]
        self.user32.GetDC.restype = ctypes.c_void_p
        self.user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        self.gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        self.gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
        self.gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi32.SelectObject.restype = ctypes.c_void_p
        self.gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]
        self.gdi32.BitBlt.restype = ctypes.c_int
        self.gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), ctypes.c_uint]
        self.gdi32.GetDIBits.restype = ctypes.c_int
        self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self.gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes:
        window_handle = ctypes.c_void_p(hwnd)
        source_dc = self.user32.GetDC(window_handle)
        if not source_dc:
            raise CaptureError(f"GetDC failed: {ctypes.get_last_error()}")
        memory_dc = None
        bitmap = None
        previous = None
        try:
            memory_dc = self.gdi32.CreateCompatibleDC(source_dc)
            bitmap = self.gdi32.CreateCompatibleBitmap(source_dc, width, height)
            if not memory_dc or not bitmap:
                raise CaptureError(f"GDI surface creation failed: {ctypes.get_last_error()}")
            previous = self.gdi32.SelectObject(memory_dc, bitmap)
            if not self.gdi32.BitBlt(memory_dc, 0, 0, width, height, source_dc, 0, 0, self.raster_op):
                raise CaptureError(f"BitBlt failed: {ctypes.get_last_error()}")
            return self._read_bitmap_rgba(memory_dc, bitmap, width, height)
        finally:
            if previous and memory_dc:
                self.gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(window_handle, source_dc)

    def _read_bitmap_rgba(self, memory_dc: int, bitmap: int, width: int, height: int) -> bytes:
        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = self.BI_RGB
        raw = (ctypes.c_ubyte * (width * height * 4))()
        rows = self.gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, ctypes.byref(info), self.DIB_RGB_COLORS)
        if rows != height:
            raise CaptureError(f"GetDIBits failed: {ctypes.get_last_error()}")
        bgra = bytes(raw)
        rgba = bytearray(len(bgra))
        for index in range(0, len(bgra), 4):
            rgba[index:index + 4] = bytes((bgra[index + 2], bgra[index + 1], bgra[index], 255))
        return bytes(rgba)


class PrintWindowCaptureBackend(Win32ClientCaptureBackend):
    """Diagnostic-only PrintWindow capture; never selected for production."""

    backend_name = "PrintWindowCaptureBackend"
    raster_mode = "PRINTWINDOW"
    PW_CLIENTONLY = 0x00000001

    def __init__(self) -> None:
        super().__init__()
        self.user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        self.user32.PrintWindow.restype = ctypes.c_int

    def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes:
        source_dc = self.user32.GetDC(None)
        if not source_dc:
            raise CaptureError(f"GetDC failed: {ctypes.get_last_error()}")
        memory_dc = None
        bitmap = None
        previous = None
        try:
            memory_dc = self.gdi32.CreateCompatibleDC(source_dc)
            bitmap = self.gdi32.CreateCompatibleBitmap(source_dc, width, height)
            if not memory_dc or not bitmap:
                raise CaptureError(f"GDI surface creation failed: {ctypes.get_last_error()}")
            previous = self.gdi32.SelectObject(memory_dc, bitmap)
            if not self.user32.PrintWindow(ctypes.c_void_p(hwnd), memory_dc, self.PW_CLIENTONLY):
                raise CaptureError(f"PrintWindow failed: {ctypes.get_last_error()}")
            return self._read_bitmap_rgba(memory_dc, bitmap, width, height)
        finally:
            if previous and memory_dc:
                self.gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(None, source_dc)


def crop_rgba_to_client(
    rgba: bytes,
    frame_width: int,
    frame_height: int,
    client_width: int,
    client_height: int,
    client_left: int,
    client_top: int,
    window_width: int,
    window_height: int,
) -> bytes:
    """Crop a WGC window frame to the requested client rectangle.

    WGC may return the complete window, including non-client chrome, and may
    apply DPI scaling.  Coordinates are therefore transformed from window
    pixels to the returned frame before cropping.  No monitor or desktop crop
    is involved.
    """
    if frame_width <= 0 or frame_height <= 0 or client_width <= 0 or client_height <= 0:
        raise CaptureBackendFailure("CAPTURE_BACKEND_FAILURE: invalid WGC/client dimensions")
    if len(rgba) != frame_width * frame_height * 4:
        raise CaptureBackendFailure("CAPTURE_BACKEND_FAILURE: invalid WGC RGBA buffer")
    if frame_width == client_width and frame_height == client_height:
        return rgba
    if window_width <= 0 or window_height <= 0:
        raise CaptureBackendFailure("CAPTURE_BACKEND_FAILURE: invalid WGC window dimensions")
    scale_x = frame_width / window_width
    scale_y = frame_height / window_height
    left = max(0, round(client_left * scale_x))
    top = max(0, round(client_top * scale_y))
    right = min(frame_width, left + round(client_width * scale_x))
    bottom = min(frame_height, top + round(client_height * scale_y))
    crop_width = right - left
    crop_height = bottom - top
    if crop_width < client_width or crop_height < client_height:
        raise CaptureBackendFailure(
            f"CAPTURE_BACKEND_FAILURE: WGC client crop is too small ({crop_width}x{crop_height}, expected {client_width}x{client_height})"
        )
    rows = []
    for y in range(client_height):
        source_y = top + min(crop_height - 1, round(y * crop_height / client_height))
        start = (source_y * frame_width + left) * 4
        row = bytearray()
        for x in range(client_width):
            source_x = left + min(crop_width - 1, round(x * crop_width / client_width))
            offset = (source_y * frame_width + source_x) * 4
            row.extend(rgba[offset:offset + 4])
        rows.append(bytes(row))
    return b"".join(rows)


class WindowsGraphicsCaptureBackend:
    """Production window-scoped WGC backend with fail-closed behavior."""

    backend_name = "WindowsGraphicsCaptureBackend"
    raster_mode = "WGC"
    is_occlusion_independent = True
    supports_directx_window_capture = True

    def __init__(self, *, timeout_seconds: float = 8.0) -> None:
        if os.name != "nt":
            raise CaptureBackendUnavailable("WGC_UNAVAILABLE: Windows Graphics Capture requires Windows")
        try:
            from windows_capture import WindowsCapture
        except Exception as exc:
            raise CaptureBackendUnavailable(
                "WGC_UNAVAILABLE: install the windows-capture optional dependency"
            ) from exc
        self._WindowsCapture = WindowsCapture
        self.timeout_seconds = timeout_seconds
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._Rect = type("_Rect", (ctypes.Structure,), {"_fields_": [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]})
        self._Point = type("_Point", (ctypes.Structure,), {"_fields_": [
            ("x", ctypes.c_long), ("y", ctypes.c_long),
        ]})
        self.user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._Rect)]
        self.user32.GetWindowRect.restype = ctypes.c_int
        self.user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._Point)]
        self.user32.ClientToScreen.restype = ctypes.c_int
        self.dwmapi.DwmGetWindowAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self.dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

    def _window_geometry(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = self._Rect()
        # WGC returns the visible extended frame bounds.  GetWindowRect may
        # include invisible resize borders, which would skew the client crop
        # under DPI scaling (for Song: 1282x992 vs 1296x999).
        extended_bounds_ok = self.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)
        ) == 0
        if not extended_bounds_ok and not self.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            raise CaptureBackendFailure(f"CAPTURE_BACKEND_FAILURE: GetWindowRect failed: {ctypes.get_last_error()}")
        point = self._Point(0, 0)
        if not self.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(point)):
            raise CaptureBackendFailure(f"CAPTURE_BACKEND_FAILURE: ClientToScreen failed: {ctypes.get_last_error()}")
        return rect.right - rect.left, rect.bottom - rect.top, point.x - rect.left, point.y - rect.top

    def capture_rgba(self, hwnd: int, width: int, height: int) -> bytes:
        finished = threading.Event()
        frames: list[tuple[bytes, int, int]] = []
        errors: list[BaseException] = []
        try:
            capture = self._WindowsCapture(
                cursor_capture=False,
                draw_border=False,
                secondary_window=False,
                minimum_update_interval=100,
                window_hwnd=hwnd,
            )

            @capture.event
            def on_frame_arrived(frame, control):
                try:
                    import numpy as np
                    buffer = np.array(frame.frame_buffer, copy=True)
                    if buffer.ndim != 3 or buffer.shape[2] < 4:
                        raise RuntimeError("WGC frame is not BGRA")
                    bgra = np.ascontiguousarray(buffer[:, :, :4])
                    rgba = bgra[:, :, [2, 1, 0, 3]].tobytes()
                    frames.append((rgba, int(frame.width), int(frame.height)))
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    control.stop()
                    finished.set()

            @capture.event
            def on_closed():
                finished.set()

            control = capture.start_free_threaded()
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureBackendFailure(f"CAPTURE_BACKEND_FAILURE: {type(exc).__name__}: {exc}") from exc
        if not finished.wait(self.timeout_seconds):
            try:
                control.stop()
            except Exception:
                pass
            raise CaptureBackendFailure("CAPTURE_BACKEND_FAILURE: WGC frame timeout")
        if errors:
            raise CaptureBackendFailure(f"CAPTURE_BACKEND_FAILURE: {type(errors[0]).__name__}: {errors[0]}") from errors[0]
        if not frames:
            raise CaptureBackendFailure("CAPTURE_BACKEND_FAILURE: WGC closed without a frame")
        raw_rgba, raw_width, raw_height = frames[0]
        window_width, window_height, client_left, client_top = self._window_geometry(hwnd)
        return crop_rgba_to_client(
            raw_rgba,
            raw_width,
            raw_height,
            width,
            height,
            client_left,
            client_top,
            window_width,
            window_height,
        )


@dataclass
class ClientAreaCapture:
    window: SteamWindowAdapter
    backend: ClientCaptureBackend
    reject_near_black: bool = False
    last_diagnostic: CaptureDiagnostic | None = field(default=None, init=False)

    def capture(self, *, restore_minimized: bool = False) -> CapturedFrame:
        info: WindowInfo = self.window.locate(restore_minimized=restore_minimized)
        if info.minimized:
            raise CaptureError("game window is minimized")
        rgba = self.backend.capture_rgba(info.hwnd, info.client_width, info.client_height)
        near_black = is_near_black_frame(rgba)
        diagnostic = CaptureDiagnostic(
            hwnd=info.hwnd,
            client_width=info.client_width,
            client_height=info.client_height,
            capture_backend=str(_backend_capability(self.backend, "backend_name", type(self.backend).__name__)),
            raster_mode=str(getattr(self.backend, "raster_mode", "unknown")),
            near_black_frame=near_black,
            status="CAPTURE_BLACK_FRAME" if near_black else "OK",
            backend_name=str(_backend_capability(self.backend, "backend_name", type(self.backend).__name__)),
            is_occlusion_independent=bool(_backend_capability(self.backend, "is_occlusion_independent", False)),
            supports_directx_window_capture=bool(_backend_capability(self.backend, "supports_directx_window_capture", False)),
        )
        self.last_diagnostic = diagnostic
        if near_black and self.reject_near_black:
            raise CaptureBlackFrameError(diagnostic)
        return CapturedFrame(
            info.client_width,
            info.client_height,
            encode_rgba_png(info.client_width, info.client_height, rgba),
            rgba,
            diagnostic,
        )
