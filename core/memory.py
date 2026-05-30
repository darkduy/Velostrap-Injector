"""
memory.py — Windows process memory utilities via NtDll + Kernel32.
Wraps NtReadVirtualMemory / NtWriteVirtualMemory for low-level access.

Memory leak prevention:
- Tất cả Win32 handles được wrap trong SafeHandle (context manager)
- Snapshot handles luôn đóng qua finally block
- Process handle trong attach() được đóng đúng trong mọi trường hợp lỗi
- CloseHandle luôn verify return value và log nếu fail
- Caller dùng `with` statement — không thể quên close handle
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import time
from contextlib import contextmanager
from ctypes import POINTER, Structure, byref, c_size_t, c_ulong, c_void_p, sizeof, windll
from typing import Generator, Optional, Tuple

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

PROCESS_ALL_ACCESS  = 0x1F0FFF
TH32CS_SNAPPROCESS  = 0x00000002
TH32CS_SNAPMODULE   = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

FFLAG_STRUCT_SIZE   = 0xD0
FFLAG_STRING_BUF_OFF = 0x00
FFLAG_STRING_LEN_OFF = 0x08
FFLAG_STRING_CAP_OFF = 0x10

# Win32 sentinel values
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value  # 0xFFFFFFFFFFFFFFFF on 64-bit
NULL_HANDLE          = 0


# ──────────────────────────────────────────────
# C Structures
# ──────────────────────────────────────────────

class PROCESSENTRY32(Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   POINTER(c_ulong)),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      wintypes.LONG),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]


class MODULEENTRY32(Structure):
    _fields_ = [
        ("dwSize",        wintypes.DWORD),
        ("th32ModuleID",  wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage",  wintypes.DWORD),
        ("ProccntUsage",  wintypes.DWORD),
        ("modBaseAddr",   POINTER(ctypes.c_byte)),
        ("modBaseSize",   wintypes.DWORD),
        ("hModule",       wintypes.HMODULE),
        ("szModule",      ctypes.c_char * 256),
        ("szExePath",     ctypes.c_char * 260),
    ]


# ──────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────

class MemoryError(Exception):
    """Raised when a memory read/write operation fails."""

class ProcessNotFoundError(Exception):
    """Raised when the target process cannot be located."""

class ModuleNotFoundError(Exception):
    """Raised when the target module cannot be found in a process."""

class AttachTimeoutError(Exception):
    """Raised when attach() exceeds the given timeout."""

class StringCapacityError(Exception):
    """Raised when the new string value exceeds the in-process buffer capacity."""


# ──────────────────────────────────────────────
# SafeHandle — RAII wrapper cho Win32 handle
# ──────────────────────────────────────────────

class SafeHandle:
    """
    RAII wrapper cho Win32 HANDLE.

    Đảm bảo CloseHandle luôn được gọi kể cả khi có exception,
    tránh handle leak hoàn toàn.

    Dùng như context manager::

        with SafeHandle(raw_handle) as h:
            do_something(h.value)
        # handle đã được đóng ở đây

    Hoặc manual::

        h = SafeHandle(raw_handle)
        try:
            do_something(h.value)
        finally:
            h.close()
    """

    _k32 = windll.kernel32

    def __init__(self, handle: int) -> None:
        self._handle  = handle
        self._closed  = False

    @property
    def value(self) -> int:
        return self._handle

    @property
    def is_valid(self) -> bool:
        return (
            self._handle != NULL_HANDLE
            and self._handle != INVALID_HANDLE_VALUE
            and not self._closed
        )

    def close(self) -> None:
        """Đóng handle. Idempotent — gọi nhiều lần không có side effect."""
        if self._closed or not self.is_valid:
            return
        self._closed = True
        result = self._k32.CloseHandle(self._handle)
        if not result:
            gle = self._k32.GetLastError()
            log.warning("CloseHandle failed for 0x%X (GLE=%d)", self._handle, gle)
        else:
            log.debug("CloseHandle OK for 0x%X", self._handle)
        self._handle = NULL_HANDLE

    def detach(self) -> int:
        """
        Trả về raw handle và từ bỏ ownership.
        Dùng khi muốn transfer handle ra ngoài mà không đóng.
        """
        self._closed = True
        h = self._handle
        self._handle = NULL_HANDLE
        return h

    def __enter__(self) -> "SafeHandle":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __del__(self) -> None:
        # Fallback — đóng nếu caller quên không dùng context manager
        if not self._closed and self.is_valid:
            log.warning(
                "SafeHandle 0x%X garbage collected without explicit close — "
                "use 'with' statement or call .close() explicitly",
                self._handle,
            )
            self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else f"0x{self._handle:X}"
        return f"SafeHandle({state})"


# ──────────────────────────────────────────────
# Low-level NT memory I/O
# ──────────────────────────────────────────────

class NtMemory:
    """
    Thin wrapper around NtReadVirtualMemory / NtWriteVirtualMemory.
    Dùng NtDll thay Kernel32 để tránh user-mode hooks.
    """

    NT_SUCCESS = 0

    def __init__(self) -> None:
        ntdll = ctypes.WinDLL("ntdll.dll")

        self._read = ntdll.NtReadVirtualMemory
        self._read.argtypes = [
            wintypes.HANDLE, c_void_p, c_void_p, c_size_t, POINTER(c_size_t)
        ]
        self._read.restype = ctypes.c_long

        self._write = ntdll.NtWriteVirtualMemory
        self._write.argtypes = [
            wintypes.HANDLE, c_void_p, c_void_p, c_size_t, POINTER(c_size_t)
        ]
        self._write.restype = ctypes.c_long

    # ── raw bytes ──────────────────────────────

    def read(self, handle: int, address: int, size: int) -> bytes:
        buf    = ctypes.create_string_buffer(size)
        n      = c_size_t(0)
        status = self._read(handle, c_void_p(address), buf, size, byref(n))
        if status != self.NT_SUCCESS:
            raise MemoryError(
                f"NtReadVirtualMemory failed: status=0x{status & 0xFFFFFFFF:08X} "
                f"addr=0x{address:X} size={size}"
            )
        return buf.raw[: n.value]

    def write(self, handle: int, address: int, data: bytes) -> None:
        buf    = ctypes.create_string_buffer(data)
        n      = c_size_t(0)
        status = self._write(handle, c_void_p(address), buf, len(data), byref(n))
        if status != self.NT_SUCCESS or n.value != len(data):
            raise MemoryError(
                f"NtWriteVirtualMemory failed: status=0x{status & 0xFFFFFFFF:08X} "
                f"addr=0x{address:X} written={n.value}/{len(data)}"
            )

    # ── typed helpers ──────────────────────────

    def read_i32(self, handle: int, address: int) -> int:
        return int.from_bytes(self.read(handle, address, 4), "little", signed=True)

    def read_u32(self, handle: int, address: int) -> int:
        return int.from_bytes(self.read(handle, address, 4), "little")

    def read_i64(self, handle: int, address: int) -> int:
        return int.from_bytes(self.read(handle, address, 8), "little", signed=True)

    def read_u64(self, handle: int, address: int) -> int:
        return int.from_bytes(self.read(handle, address, 8), "little")

    def write_i32(self, handle: int, address: int, value: int) -> None:
        self.write(handle, address, value.to_bytes(4, "little", signed=True))

    def write_i64(self, handle: int, address: int, value: int) -> None:
        self.write(handle, address, value.to_bytes(8, "little", signed=True))


# ──────────────────────────────────────────────
# Process / module enumeration
# ──────────────────────────────────────────────

class ProcessManager:
    """Locates processes and modules via Toolhelp32 snapshots."""

    def __init__(self) -> None:
        self._k32 = windll.kernel32

    @staticmethod
    def _decode(raw: bytes) -> str:
        return raw.decode("utf-8", errors="ignore").lower()

    def _is_valid_snap(self, snap: int) -> bool:
        return snap != NULL_HANDLE and snap != INVALID_HANDLE_VALUE

    def find_pid(self, process_name: str) -> int:
        """Return PID của process đầu tiên match *process_name*.

        Raises ProcessNotFoundError nếu không tìm thấy.
        Snapshot handle luôn được đóng kể cả khi có exception.
        """
        name = process_name.lower()
        snap = self._k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

        if not self._is_valid_snap(snap):
            raise ProcessNotFoundError(
                f"Cannot create process snapshot (GLE={self._k32.GetLastError()})"
            )

        with SafeHandle(snap):  # đảm bảo đóng snapshot trong mọi trường hợp
            entry = PROCESSENTRY32()
            entry.dwSize = sizeof(PROCESSENTRY32)

            if self._k32.Process32First(snap, byref(entry)):
                while True:
                    if self._decode(entry.szExeFile) == name:
                        return entry.th32ProcessID
                    if not self._k32.Process32Next(snap, byref(entry)):
                        break

        raise ProcessNotFoundError(f"Process not found: {process_name!r}")

    def get_module_base(self, pid: int, module_name: str) -> Tuple[int, int]:
        """Return *(base_address, size)* của *module_name* trong *pid*.

        Raises ModuleNotFoundError nếu không tìm thấy.
        Snapshot handle luôn được đóng kể cả khi có exception.
        """
        name  = module_name.lower()
        flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
        snap  = self._k32.CreateToolhelp32Snapshot(flags, pid)

        if not self._is_valid_snap(snap):
            raise ModuleNotFoundError(
                f"Cannot create module snapshot for pid={pid} "
                f"(GLE={self._k32.GetLastError()})"
            )

        with SafeHandle(snap):  # đảm bảo đóng snapshot trong mọi trường hợp
            entry = MODULEENTRY32()
            entry.dwSize = sizeof(MODULEENTRY32)

            if self._k32.Module32First(snap, byref(entry)):
                while True:
                    if self._decode(entry.szModule) == name:
                        base = ctypes.cast(entry.modBaseAddr, c_void_p).value
                        return base, entry.modBaseSize
                    if not self._k32.Module32Next(snap, byref(entry)):
                        break

        raise ModuleNotFoundError(f"Module not found: {module_name!r} in pid={pid}")

    def open_process(self, pid: int) -> SafeHandle:
        """Open *pid* với PROCESS_ALL_ACCESS. Trả về SafeHandle.

        Raises ProcessNotFoundError on failure.
        Caller chịu trách nhiệm đóng handle bằng .close() hoặc with statement.
        """
        raw = self._k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not raw:
            raise ProcessNotFoundError(
                f"OpenProcess failed for pid={pid} (GLE={self._k32.GetLastError()})"
            )
        return SafeHandle(raw)


# ──────────────────────────────────────────────
# High-level memory manager
# ──────────────────────────────────────────────

class MemoryManager:
    """
    High-level façade: attach vào process và manipulate FFlag structs.

    Dùng context manager để đảm bảo process handle luôn được đóng::

        mm = MemoryManager()
        with mm.attach("RobloxPlayerBeta.exe", "RobloxPlayerBeta.exe") as (handle, base, size):
            mm.write_fflag_int(handle, base + OFFSET, VALUE_PTR_OFFSET, 1)
        # handle tự động đóng ở đây

    Hoặc manual (không khuyến khích)::

        handle, base, size = mm.attach_raw(...)
        try:
            mm.write_fflag_int(handle, ...)
        finally:
            handle.close()
    """

    def __init__(self) -> None:
        self.mem  = NtMemory()
        self.proc = ProcessManager()

    # ── attach (context manager) ───────────────

    @contextmanager
    def attach(
        self,
        process_name:  str,
        module_name:   str,
        poll_interval: float = 1.0,
        timeout:       Optional[float] = None,
    ) -> Generator[Tuple[int, int, int], None, None]:
        """
        Context manager — poll cho đến khi attach được, yield (handle, base, size),
        rồi tự đóng handle khi thoát khỏi block.

        Usage::

            with mm.attach("game.exe", "game.exe") as (handle, base, size):
                mm.write_fflag_int(handle, base + offset, value_offset, 1)
        """
        safe_handle = self._poll_attach(process_name, module_name, poll_interval, timeout)
        try:
            yield safe_handle.value, safe_handle._module_base, safe_handle._module_size
        finally:
            safe_handle.close()

    def attach_raw(
        self,
        process_name:  str,
        module_name:   str,
        poll_interval: float = 1.0,
        timeout:       Optional[float] = None,
    ) -> Tuple["SafeHandle", int, int]:
        """
        Attach và trả về (SafeHandle, base, size) — caller chịu trách nhiệm đóng handle.
        Dùng khi cần giữ handle lâu hơn một block.

        Usage::

            handle, base, size = mm.attach_raw("game.exe", "game.exe")
            try:
                ...
            finally:
                handle.close()
        """
        return self._poll_attach(process_name, module_name, poll_interval, timeout)

    def _poll_attach(
        self,
        process_name:  str,
        module_name:   str,
        poll_interval: float,
        timeout:       Optional[float],
    ) -> "SafeHandle":
        """
        Internal — poll loop thực sự.

        Xử lý memory leak cases:
        - Nếu open_process thành công nhưng get_module_base fail → đóng handle ngay
        - Nếu get_module_base throw exception không phải ModuleNotFoundError → đóng handle trước khi re-raise
        - Nếu timeout → không leak handle nào vì handle chỉ được tạo sau khi attach thành công
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            try:
                pid         = self.proc.find_pid(process_name)
                safe_handle = self.proc.open_process(pid)

                try:
                    base, size = self.proc.get_module_base(pid, module_name)
                except Exception:
                    safe_handle.close()  # đóng handle trước khi retry hoặc re-raise
                    raise

                # Gắn thêm metadata vào handle để context manager có thể yield
                safe_handle._module_base = base
                safe_handle._module_size = size
                log.info(
                    "Attached to %r pid=%d base=0x%X size=0x%X",
                    process_name, pid, base, size,
                )
                return safe_handle

            except ModuleNotFoundError as exc:
                log.debug("Module not ready: %s", exc)
            except ProcessNotFoundError as exc:
                log.debug("Process not found: %s", exc)

            if deadline is not None and time.monotonic() >= deadline:
                raise AttachTimeoutError(
                    f"Could not attach to {process_name!r} within {timeout}s"
                )
            time.sleep(poll_interval)

    # ── internal: read fflag struct ────────────

    def _read_fflag_struct(
        self,
        handle:      int,
        fflag_addr:  int,
        struct_size: int = FFLAG_STRUCT_SIZE,
    ) -> bytes:
        data = self.mem.read(handle, fflag_addr, struct_size)
        if len(data) < struct_size:
            raise MemoryError(
                f"Short read of FFlag struct at 0x{fflag_addr:X}: "
                f"got {len(data)} bytes, expected {struct_size}"
            )
        return data

    def _extract_ptr(self, struct_data: bytes, offset: int) -> int:
        ptr = int.from_bytes(struct_data[offset: offset + 8], "little")
        if not ptr:
            raise MemoryError(f"Null pointer at struct offset 0x{offset:X}")
        return ptr

    # ── fflag writers ──────────────────────────

    def write_fflag_int(
        self,
        handle:           int,
        fflag_addr:       int,
        value_ptr_offset: int,
        value:            int,
        struct_size:      int = FFLAG_STRUCT_SIZE,
    ) -> None:
        struct    = self._read_fflag_struct(handle, fflag_addr, struct_size)
        value_ptr = self._extract_ptr(struct, value_ptr_offset)
        self.mem.write_i32(handle, value_ptr, value)
        log.debug("write_fflag_int addr=0x%X offset=0x%X value=%d", fflag_addr, value_ptr_offset, value)

    def write_fflag_string(
        self,
        handle:           int,
        fflag_addr:       int,
        value_ptr_offset: int,
        value:            str,
        struct_size:      int = FFLAG_STRUCT_SIZE,
    ) -> None:
        struct   = self._read_fflag_struct(handle, fflag_addr, struct_size)
        inst_ptr = self._extract_ptr(struct, value_ptr_offset)

        buf_ptr  = self.mem.read_u64(handle, inst_ptr + FFLAG_STRING_BUF_OFF)
        capacity = self.mem.read_u64(handle, inst_ptr + FFLAG_STRING_CAP_OFF)

        encoded = value.encode("utf-8")
        new_len = len(encoded)

        if new_len > capacity:
            raise StringCapacityError(
                f"New value ({new_len} bytes) exceeds buffer capacity ({capacity} bytes)"
            )

        self.mem.write(handle, buf_ptr, encoded + b"\x00")
        self.mem.write_i64(handle, inst_ptr + FFLAG_STRING_LEN_OFF, new_len)
        log.debug(
            "write_fflag_string addr=0x%X offset=0x%X value=%r len=%d cap=%d",
            fflag_addr, value_ptr_offset, value, new_len, capacity,
        )


# ──────────────────────────────────────────────
# Backward compat helper
# ──────────────────────────────────────────────

def close_handle(handle) -> None:
    """
    Đóng handle an toàn.
    Nhận SafeHandle hoặc raw int.
    Giữ lại để tương thích với code cũ.
    """
    if isinstance(handle, SafeHandle):
        handle.close()
    elif isinstance(handle, int) and handle not in (NULL_HANDLE, INVALID_HANDLE_VALUE):
        result = windll.kernel32.CloseHandle(handle)
        if not result:
            log.warning("close_handle: CloseHandle failed for 0x%X (GLE=%d)",
                        handle, windll.kernel32.GetLastError())