from __future__ import annotations

import ctypes
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Protocol

from .window import SteamWindowAdapter, WindowInfo


class CaptureError(RuntimeError):
    pass


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

    def to_dict(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "client_width": self.client_width,
            "client_height": self.client_height,
            "capture_backend": self.capture_backend,
            "raster_mode": self.raster_mode,
            "near_black_frame": self.near_black_frame,
            "status": self.status,
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
        finally:
            if previous and memory_dc:
                self.gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(window_handle, source_dc)


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
            capture_backend=type(self.backend).__name__,
            raster_mode=str(getattr(self.backend, "raster_mode", "unknown")),
            near_black_frame=near_black,
            status="CAPTURE_BLACK_FRAME" if near_black else "OK",
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
