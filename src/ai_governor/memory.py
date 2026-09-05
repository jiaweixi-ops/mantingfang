from __future__ import annotations

import csv
import ctypes
import json
import os
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import Observation


class MemoryConfigurationError(ValueError):
    pass


class MemoryAccessError(RuntimeError):
    pass


class UnsupportedPlatformError(RuntimeError):
    pass


SUPPORTED_TYPES = {
    "int32": (4, "<i"),
    "uint32": (4, "<I"),
    "int64": (8, "<q"),
    "uint64": (8, "<Q"),
    "float32": (4, "<f"),
    "float64": (8, "<d"),
    "bool": (1, "<?"),
}


def _int(value: Any, field: str) -> int:
    try:
        parsed = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise MemoryConfigurationError(f"{field} must be an integer or hex string") from exc
    if parsed < 0:
        raise MemoryConfigurationError(f"{field} must be non-negative")
    return parsed


@dataclass(frozen=True)
class MemoryField:
    name: str
    value_type: str
    base_offset: int
    offsets: tuple[int, ...] = ()
    module: str | None = None

    @classmethod
    def from_dict(cls, name: str, raw: dict[str, Any]) -> "MemoryField":
        if not isinstance(raw, dict):
            raise MemoryConfigurationError(f"memory field {name} must be an object")
        value_type = raw.get("type")
        if value_type not in SUPPORTED_TYPES:
            raise MemoryConfigurationError(f"unsupported type for {name}: {value_type}")
        offsets = raw.get("offsets", [])
        if not isinstance(offsets, list) or any(not isinstance(v, (int, str)) for v in offsets):
            raise MemoryConfigurationError(f"offsets for {name} must be a list of integers")
        return cls(
            name=name,
            value_type=value_type,
            base_offset=_int(raw.get("base_offset", 0), f"base_offset for {name}"),
            offsets=tuple(_int(value, f"offset for {name}") for value in offsets),
            module=str(raw["module"]) if raw.get("module") else None,
        )


@dataclass(frozen=True)
class MemoryProfile:
    process_name: str
    fields: tuple[MemoryField, ...]
    pointer_size: int = 8

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MemoryProfile":
        if not isinstance(raw, dict) or not isinstance(raw.get("process_name"), str) or not raw["process_name"].strip():
            raise MemoryConfigurationError("profile requires a non-empty process_name")
        raw_fields = raw.get("fields")
        if not isinstance(raw_fields, dict) or not raw_fields:
            raise MemoryConfigurationError("profile requires a non-empty fields object")
        pointer_size = _int(raw.get("pointer_size", 8), "pointer_size")
        if pointer_size not in {4, 8}:
            raise MemoryConfigurationError("pointer_size must be 4 or 8")
        return cls(
            process_name=raw["process_name"].strip(),
            fields=tuple(MemoryField.from_dict(name, value) for name, value in raw_fields.items()),
            pointer_size=pointer_size,
        )

    @classmethod
    def from_json(cls, path: Path | str) -> "MemoryProfile":
        profile_path = Path(path)
        try:
            raw = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryConfigurationError(f"could not read memory profile: {profile_path}") from exc
        return cls.from_dict(raw)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str


class ProcessEnumerator(Protocol):
    def find(self, process_name: str) -> ProcessInfo | None: ...


class MemoryBackend(Protocol):
    def open_process(self, pid: int) -> Any: ...
    def close_process(self, handle: Any) -> None: ...
    def module_base(self, pid: int, module_name: str) -> int: ...
    def read(self, handle: Any, address: int, size: int) -> bytes: ...


class WindowsProcessEnumerator:
    def list(self) -> list[ProcessInfo]:
        if os.name != "nt":
            raise UnsupportedPlatformError("process enumeration requires Windows")
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
        )
        processes: list[ProcessInfo] = []
        for row in csv.reader(completed.stdout.splitlines()):
            if len(row) >= 2 and row[1].isdigit():
                processes.append(ProcessInfo(pid=int(row[1]), name=row[0]))
        return processes

    def find(self, process_name: str) -> ProcessInfo | None:
        wanted = process_name.casefold()
        return next((item for item in self.list() if item.name.casefold() == wanted), None)


class WindowsMemoryBackend:
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _ModuleEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("th32ModuleID", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("GlblcntUsage", ctypes.c_ulong),
            ("ProccntUsage", ctypes.c_ulong),
            ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", ctypes.c_ulong),
            ("hModule", ctypes.c_void_p),
            ("szModule", ctypes.c_wchar * 256),
            ("szExePath", ctypes.c_wchar * 260),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise UnsupportedPlatformError("memory access requires Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel32.ReadProcessMemory.restype = ctypes.c_int
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        self.kernel32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._ModuleEntry32W)]
        self.kernel32.Module32FirstW.restype = ctypes.c_int
        self.kernel32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(self._ModuleEntry32W)]
        self.kernel32.Module32NextW.restype = ctypes.c_int

    def open_process(self, pid: int) -> ctypes.c_void_p:
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_INFORMATION | self.PROCESS_VM_READ, 0, pid)
        if not handle:
            raise MemoryAccessError(f"OpenProcess failed for pid {pid}: {ctypes.get_last_error()}")
        return handle

    def close_process(self, handle: ctypes.c_void_p) -> None:
        self.kernel32.CloseHandle(handle)

    def module_base(self, pid: int, module_name: str) -> int:
        snapshot = self.kernel32.CreateToolhelp32Snapshot(self.TH32CS_SNAPMODULE | self.TH32CS_SNAPMODULE32, pid)
        if snapshot == self.INVALID_HANDLE_VALUE or not snapshot:
            raise MemoryAccessError(f"module snapshot failed for pid {pid}: {ctypes.get_last_error()}")
        try:
            entry = self._ModuleEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not self.kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
                raise MemoryAccessError(f"module enumeration failed for pid {pid}: {ctypes.get_last_error()}")
            wanted = module_name.casefold()
            while True:
                if entry.szModule.casefold() == wanted:
                    return int(entry.modBaseAddr)
                if not self.kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
            raise MemoryAccessError(f"module not found: {module_name}")
        finally:
            self.kernel32.CloseHandle(snapshot)

    def read(self, handle: ctypes.c_void_p, address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        copied = ctypes.c_size_t(0)
        ok = self.kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(copied))
        if not ok or copied.value != size:
            raise MemoryAccessError(f"ReadProcessMemory failed at 0x{address:X}: {ctypes.get_last_error()}")
        return buffer.raw


@dataclass
class MemorySampler:
    profile: MemoryProfile
    processes: ProcessEnumerator
    backend: MemoryBackend

    def sample(self) -> dict[str, Any]:
        process = self.processes.find(self.profile.process_name)
        if process is None:
            raise MemoryAccessError(f"process not found: {self.profile.process_name}")
        handle = self.backend.open_process(process.pid)
        values: dict[str, Any] = {}
        errors: dict[str, str] = {}
        try:
            for field in self.profile.fields:
                try:
                    module_name = field.module or process.name
                    base = self.backend.module_base(process.pid, module_name)
                    address = self._resolve_address(handle, base, field)
                    size, fmt = SUPPORTED_TYPES[field.value_type]
                    values[field.name] = struct.unpack(fmt, self.backend.read(handle, address, size))[0]
                except (MemoryAccessError, struct.error, KeyError) as exc:
                    errors[field.name] = str(exc)
        finally:
            self.backend.close_process(handle)
        return {"process": process.name, "pid": process.pid, "values": values, "errors": errors}

    def observe(self) -> Observation:
        return Observation(data=self.sample(), source="readonly-memory", region="memory")

    def _resolve_address(self, handle: Any, base: int, field: MemoryField) -> int:
        address = base + field.base_offset
        if not field.offsets:
            return address
        for offset in field.offsets[:-1]:
            raw_pointer = self.backend.read(handle, address + offset, self.profile.pointer_size)
            pointer = struct.unpack("<I" if self.profile.pointer_size == 4 else "<Q", raw_pointer)[0]
            if pointer == 0:
                raise MemoryAccessError(f"null pointer while resolving {field.name}")
            address = pointer
        return address + field.offsets[-1]
