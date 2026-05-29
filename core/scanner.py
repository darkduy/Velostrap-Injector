"""
scanner.py — Pattern scanner để tìm FFlagList offset động.
Thay thế hoàn toàn offset cứng và server fetch.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import struct
from ctypes import c_void_p, c_size_t, POINTER, byref, windll
from typing import Optional

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Patterns — LEA rax, [rip + disp32]
#
# Roblox truy cập FFlagList qua một instruction dạng:
#   48 8D 05 ?? ?? ?? ??   →   lea rax, [rip + disp32]
#
# Sau instruction này thường có:
#   48 89 ?? / 48 8B ??    →   mov liên quan đến singleton
#
# Nếu pattern chính fail thì thử pattern phụ.
# ──────────────────────────────────────────────

# Format: (mask_byte = None nghĩa là wildcard)
PATTERNS = [
    # Pattern chính: LEA rax, [rip+disp] + MOV
    [0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x89],
    # Pattern phụ: LEA rcx, [rip+disp]
    [0x48, 0x8D, 0x0D, None, None, None, None, 0x48, 0x8B],
    # Pattern phụ 2: LEA rdx
    [0x48, 0x8D, 0x15, None, None, None, None],
]

# Offset của disp32 bên trong instruction LEA (byte 3-6)
RIP_DISP_OFFSET = 3
# Độ dài instruction LEA (để tính RIP = địa chỉ byte kế tiếp)
LEA_INSN_LEN    = 7

# Giới hạn scan để tránh đọc quá nhiều memory
CHUNK_SIZE      = 0x10_000   # 64 KB mỗi lần đọc
MIN_VALID_PTR   = 0x10_000


class PatternScanner:
    """
    Scan bộ nhớ của một process để tìm FFlagList qua byte pattern.

    Usage::

        scanner = PatternScanner(process_handle, module_base, module_size, mem)
        offset = scanner.find_fflaglist_offset()
        # offset là RVA từ module_base, hoặc None nếu không tìm thấy
    """

    def __init__(
        self,
        process_handle: int,
        module_base:    int,
        module_size:    int,
        mem,                   # NtMemory instance từ memory.py
    ) -> None:
        self._handle      = process_handle
        self._base        = module_base
        self._size        = module_size
        self._mem         = mem

    # ── pattern matching ───────────────────────

    @staticmethod
    def _match(data: bytes, offset: int, pattern: list) -> bool:
        """Kiểm tra pattern tại vị trí *offset* trong *data*."""
        if offset + len(pattern) > len(data):
            return False
        for i, byte in enumerate(pattern):
            if byte is None:
                continue  # wildcard
            if data[offset + i] != byte:
                return False
        return True

    # ── RIP-relative address resolver ─────────

    def _resolve_rip_relative(
        self,
        chunk_va:    int,   # virtual address của đầu chunk
        match_off:   int,   # offset trong chunk nơi tìm thấy pattern
        data:        bytes,
    ) -> Optional[int]:
        """
        Tính địa chỉ tuyệt đối từ LEA [rip + disp32].

        disp32 nằm ở byte 3-6 của instruction.
        RIP = địa chỉ của instruction kế tiếp = va_of_insn + LEA_INSN_LEN.
        """
        disp_off = match_off + RIP_DISP_OFFSET
        if disp_off + 4 > len(data):
            return None

        disp32 = struct.unpack_from("<i", data, disp_off)[0]  # signed int32
        insn_va = chunk_va + match_off
        rip     = insn_va + LEA_INSN_LEN
        target  = (rip + disp32) & 0xFFFF_FFFF_FFFF_FFFF

        return target

    # ── validity check ─────────────────────────

    def _looks_like_fflaglist(self, ptr_addr: int) -> bool:
        """
        Đọc giá trị tại ptr_addr (tức là *ptr_addr = FFlagList pointer),
        rồi verify sơ bộ rằng struct tại đó trông giống FFlagList:
          - map_list  (+0x10) là pointer hợp lệ
          - map_mask  (+0x28) là dạng 2^n - 1
        """
        try:
            fflaglist = self._mem.read_u64(self._handle, ptr_addr)
            if not (MIN_VALID_PTR <= fflaglist <= 0x7FFF_FFFF_FFFF):
                return False

            hashmap_addr = fflaglist + 8
            map_data = self._mem.read(self._handle, hashmap_addr, 56)
            if len(map_data) < 56:
                return False

            map_list = int.from_bytes(map_data[0x10:0x18], "little")
            map_mask = int.from_bytes(map_data[0x28:0x30], "little")

            if not (MIN_VALID_PTR <= map_list <= 0x7FFF_FFFF_FFFF):
                return False

            # map_mask phải là 2^n - 1 (tất cả bit thấp đều 1)
            if map_mask == 0 or (map_mask & (map_mask + 1)) != 0:
                return False

            return True

        except Exception:
            return False

    # ── main scan ──────────────────────────────

    def find_fflaglist_offset(self) -> Optional[int]:
        """
        Scan module memory, trả về RVA (offset từ module_base) của
        FFlagList pointer, hoặc None nếu không tìm thấy.
        """
        log.info(
            "Scanning 0x%X bytes from base 0x%X …",
            self._size, self._base,
        )

        pos = 0
        # Overlap giữa các chunk để không bỏ sót pattern nằm trên ranh giới
        overlap = 16

        while pos < self._size:
            chunk_va   = self._base + pos
            read_size  = min(CHUNK_SIZE, self._size - pos)

            try:
                data = self._mem.read(self._handle, chunk_va, read_size)
            except Exception:
                pos += CHUNK_SIZE
                continue

            for pattern in PATTERNS:
                plen = len(pattern)
                for i in range(len(data) - plen):
                    if not self._match(data, i, pattern):
                        continue

                    target = self._resolve_rip_relative(chunk_va, i, data)
                    if target is None:
                        continue

                    if not self._looks_like_fflaglist(target):
                        continue

                    offset = target - self._base
                    log.info(
                        "Found FFlagList at 0x%X  RVA=0x%X  (pattern idx %d, chunk pos 0x%X)",
                        target, offset, PATTERNS.index(pattern), pos + i,
                    )
                    return offset

            # Advance chunk, giữ lại overlap để không bỏ sót
            pos += CHUNK_SIZE - overlap

        log.warning("Pattern scan completed — FFlagList not found.")
        return None