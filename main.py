"""
main.py — Roblox FFlag injector via direct memory manipulation.
Sử dụng pattern scan để tìm FFlagList động, không cần offset cứng hay server.
"""

import json
import logging
import os
import sys
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from core.memory import MemoryManager, close_handle, AttachTimeoutError
from core.scanner import PatternScanner

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants — FFlag map layout
# ──────────────────────────────────────────────

OFF_FFLAG_VALUE_PTR = 0xC0

OFF_MAP_END      = 0x00
OFF_MAP_LIST     = 0x10
OFF_MAP_MASK     = 0x28

OFF_ENTRY_FORWARD = 0x08
OFF_ENTRY_STRING  = 0x10
OFF_ENTRY_GETSET  = 0x30

OFF_STR_SIZE     = 0x10
OFF_STR_CAPACITY = 0x18

# ──────────────────────────────────────────────
# Constants — traversal limits
# ──────────────────────────────────────────────

NODE_READ_SIZE    = 64
NODE_STRIDES      = [64, 72, 56, 80, 88, 96]
MAX_CHAIN_STEPS   = 128
MAX_CHAIN_SAFETY  = 1_000
MIN_VALID_PTR     = 0x10_000
FLAG_ADDR_LRU_MAX = 4_096

# ──────────────────────────────────────────────
# Constants — FNV-1a hashing
# ──────────────────────────────────────────────

FNV1A_64_BASIS = 0xCBF29CE484222325
FNV1A_64_PRIME = 0x100000001B3

# ──────────────────────────────────────────────
# Constants — process target
# ──────────────────────────────────────────────

ROBLOX_EXE = "RobloxPlayerBeta.exe"

# ──────────────────────────────────────────────
# FFlag type prefixes
# ──────────────────────────────────────────────

STRING_PREFIXES = ("FString", "DFString")
INT_PREFIXES    = ("DFInt", "FInt", "DFLog", "FLog")
BOOL_PREFIXES   = ("DFFlag", "FFlag")

BANNER = r"""
██╗   ██╗███████╗██╗      ██████╗ ██████╗ ██╗███╗   ██╗
██║   ██║██╔════╝██║     ██╔═══██╗██╔══██╗██║████╗  ██║
██║   ██║█████╗  ██║     ██║   ██║██████╔╝██║██╔██╗ ██║
╚██╗ ██╔╝██╔══╝  ██║     ██║   ██║██╔══██╗██║██║╚██╗██║
 ╚████╔╝ ███████╗███████╗╚██████╔╝██║  ██║██║██║ ╚████║
  ╚═══╝  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
"""


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def get_base_path() -> str:
    if getattr(sys, "frozen", False) or hasattr(sys, "real_path"):
        return os.path.dirname(os.path.realpath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def parse_flag_type(key: str) -> Tuple[str, str]:
    for prefix in STRING_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix):], "string"
    for prefix in INT_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix):], "int"
    for prefix in BOOL_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix):], "bool"
    return key, "int"


# ──────────────────────────────────────────────
# Core injector
# ──────────────────────────────────────────────

class FlagInjector:
    """
    Locates and patches Roblox FFlags in memory.
    FFlagList offset tìm động qua pattern scan — không cần server hay offset cứng.
    """

    def __init__(self) -> None:
        self._mm  = MemoryManager()
        self._mem = self._mm.mem

        self._process_handle: int = 0
        self._module_base:    int = 0
        self._module_size:    int = 0
        self._flag_list_offset: int = 0

        self._singleton_addr: int = 0
        self._hash_cache:     Dict[str, int] = {}
        self._lookup_meta:    Dict[str, Dict[str, int]] = {}
        self._value_ptr_lru:  OrderedDict[str, int] = OrderedDict()
        self._map_identity:   Tuple[int, int, int] = (0, 0, 0)

        self._attach()
        self._scan_offset()

    # ── attach ─────────────────────────────────

    def _attach(self) -> None:
        print("[ + ] Waiting for Roblox …")
        self._process_handle, self._module_base, self._module_size = (
            self._mm.attach(ROBLOX_EXE, ROBLOX_EXE)
        )
        print(f"[ + ] Attached  handle=0x{self._process_handle:X}")
        print(f"[ + ] Module    base=0x{self._module_base:X}  size=0x{self._module_size:X}")

    # ── pattern scan ───────────────────────────

    def _scan_offset(self) -> None:
        print("[ + ] Scanning for FFlagList …")
        scanner = PatternScanner(
            self._process_handle,
            self._module_base,
            self._module_size,
            self._mem,
        )
        offset = scanner.find_fflaglist_offset()
        if offset is None:
            raise RuntimeError("Pattern scan failed — FFlagList not found.")
        self._flag_list_offset = offset
        print(f"[ + ] FFlagList offset: 0x{offset:X}")

    # ── ptr validation ─────────────────────────

    @staticmethod
    def _is_valid_ptr(ptr: int) -> bool:
        return isinstance(ptr, int) and MIN_VALID_PTR <= ptr <= 0x7FFF_FFFF_FFFF

    # ── FNV-1a 64 ──────────────────────────────

    def _fnv1a64(self, name: str) -> int:
        cached = self._hash_cache.get(name)
        if cached is not None:
            return cached
        h = FNV1A_64_BASIS
        for byte in name.encode("utf-8", errors="ignore"):
            h ^= byte
            h = (h * FNV1A_64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
        self._hash_cache[name] = h
        return h

    # ── cache helpers ──────────────────────────

    def _cache_value_ptr(self, name: str, ptr: int) -> None:
        if not ptr:
            return
        self._value_ptr_lru[name] = ptr
        self._value_ptr_lru.move_to_end(name)
        while len(self._value_ptr_lru) > FLAG_ADDR_LRU_MAX:
            self._value_ptr_lru.popitem(last=False)

    def _get_cached_value_ptr(self, name: str) -> int:
        ptr = self._value_ptr_lru.get(name)
        if ptr:
            self._value_ptr_lru.move_to_end(name)
            return ptr
        return 0

    def _invalidate_caches(self, clear_hash: bool = False) -> None:
        self._lookup_meta.clear()
        self._value_ptr_lru.clear()
        if clear_hash:
            self._hash_cache.clear()

    # ── node/entry reading ─────────────────────

    def _read_entry_name(self, entry_data: bytes) -> Tuple[bytes, int]:
        base = OFF_ENTRY_STRING

        str_size = int.from_bytes(
            entry_data[base + OFF_STR_SIZE: base + OFF_STR_SIZE + 8], "little"
        )
        if not (0 < str_size <= 256):
            return b"", 0

        str_alloc = int.from_bytes(
            entry_data[base + OFF_STR_CAPACITY: base + OFF_STR_CAPACITY + 8], "little"
        )

        if str_alloc > 0xF:
            ptr = int.from_bytes(entry_data[base: base + 8], "little")
            if not self._is_valid_ptr(ptr):
                return b"", 0
            name_bytes = self._mem.read(self._process_handle, ptr, str_size)
            return (name_bytes[:str_size] if name_bytes else b""), str_size

        return entry_data[base: base + str_size], str_size

    def _read_node_entry(self, node_ptr: int) -> Optional[bytes]:
        if not self._is_valid_ptr(node_ptr):
            return None
        for stride in NODE_STRIDES:
            if stride < NODE_READ_SIZE:
                continue
            try:
                data = self._mem.read(self._process_handle, node_ptr, stride)
            except Exception:
                continue
            if len(data) >= NODE_READ_SIZE:
                return data
        return None

    # ── singleton (FFlagList) ──────────────────

    def _get_singleton(self) -> int:
        if self._singleton_addr:
            return self._singleton_addr

        addr = self._module_base + self._flag_list_offset
        try:
            absolute = self._mem.read_u64(self._process_handle, addr)
        except Exception:
            absolute = 0

        if absolute > 0:
            self._singleton_addr = absolute
            print(f"[ + ] FFlagList at 0x{absolute:X}")
            return absolute

        print("[ - ] Failed to read FFlagList.")
        return 0

    # ── flag address lookup ────────────────────

    def _find_flag_addr(self, name: str) -> int:
        cached = self._get_cached_value_ptr(name)
        if cached:
            return cached

        singleton = self._get_singleton()
        if not singleton:
            return 0

        name_bytes   = name.encode("utf-8")
        hashmap_addr = singleton + 8

        try:
            map_data = self._mem.read(self._process_handle, hashmap_addr, 56)
        except Exception:
            return 0

        map_end  = int.from_bytes(map_data[OFF_MAP_END:  OFF_MAP_END  + 8], "little")
        map_list = int.from_bytes(map_data[OFF_MAP_LIST: OFF_MAP_LIST + 8], "little")
        map_mask = int.from_bytes(map_data[OFF_MAP_MASK: OFF_MAP_MASK + 8], "little")

        if not map_mask or not map_list or not self._is_valid_ptr(map_list):
            return 0

        identity = (map_list, map_end, map_mask)
        if identity != self._map_identity:
            self._invalidate_caches(clear_hash=False)
            self._map_identity = identity

        meta         = self._lookup_meta.get(name, {})
        bucket_index = meta.get("bucketindex", self._fnv1a64(name) & map_mask) & map_mask
        bucket_base  = map_list + (bucket_index * 16)

        try:
            bucket_data = self._mem.read(self._process_handle, bucket_base, 16)
        except Exception:
            return 0

        node_current = int.from_bytes(bucket_data[8:16], "little")
        if not self._is_valid_ptr(node_current) or node_current == map_end:
            return 0

        # Fast path — cached node
        cached_node = meta.get("nodeptr", 0)
        if cached_node and self._is_valid_ptr(cached_node):
            entry = self._read_node_entry(cached_node)
            if entry:
                entry_name, entry_len = self._read_entry_name(entry)
                if entry_len == len(name_bytes) and entry_name == name_bytes:
                    getset = int.from_bytes(entry[OFF_ENTRY_GETSET: OFF_ENTRY_GETSET + 8], "little")
                    if self._is_valid_ptr(getset):
                        self._lookup_meta[name] = {"bucketindex": bucket_index, "nodeptr": cached_node}
                        self._cache_value_ptr(name, getset)
                        return getset

        # Walk the chain
        visited = set()
        steps = safety = 0

        while steps < MAX_CHAIN_STEPS and safety < MAX_CHAIN_SAFETY:
            steps  += 1
            safety += 1

            if node_current in visited:
                break
            visited.add(node_current)

            entry = self._read_node_entry(node_current)
            if not entry:
                break

            forward = int.from_bytes(entry[OFF_ENTRY_FORWARD: OFF_ENTRY_FORWARD + 8], "little")
            if forward and not self._is_valid_ptr(forward):
                break

            entry_name, entry_len = self._read_entry_name(entry)
            if entry_len == len(name_bytes) and entry_name == name_bytes:
                getset = int.from_bytes(entry[OFF_ENTRY_GETSET: OFF_ENTRY_GETSET + 8], "little")
                if self._is_valid_ptr(getset):
                    self._lookup_meta[name] = {"bucketindex": bucket_index, "nodeptr": node_current}
                    self._cache_value_ptr(name, getset)
                    return getset

            if not forward or node_current == forward:
                break
            node_current = forward

        return 0

    # ── flag writers ───────────────────────────

    def _write_string(self, name: str, value: str) -> bool:
        addr = self._find_flag_addr(name)
        if not addr:
            return False
        try:
            self._mm.write_fflag_string(self._process_handle, addr, OFF_FFLAG_VALUE_PTR, value)
            return True
        except Exception as exc:
            log.debug("write_string %r failed: %s", name, exc)
            return False

    def _write_int(self, name: str, value: int) -> bool:
        addr = self._find_flag_addr(name)
        if not addr:
            return False
        try:
            self._mm.write_fflag_int(self._process_handle, addr, OFF_FFLAG_VALUE_PTR, value)
            return True
        except Exception as exc:
            log.debug("write_int %r failed: %s", name, exc)
            return False

    # ── public API ─────────────────────────────

    def apply_flag(self, key: str, val) -> Tuple[bool, str]:
        clean_name, flag_type = parse_flag_type(key)

        try:
            if flag_type == "string":
                ok = self._write_string(clean_name, str(val))
                return (ok, f'[ + ] {key} = "{val}"') if ok else (False, f"[ - ] Failed: {key}")

            if flag_type == "int":
                try:
                    int_val = int(val)
                except (TypeError, ValueError):
                    return False, f"[ - ] Invalid int for {key}: {val!r}"
                ok = self._write_int(clean_name, int_val)
                return (ok, f"[ + ] {key} = {int_val}") if ok else (False, f"[ - ] Failed: {key}")

            if flag_type == "bool":
                bool_val = val if isinstance(val, bool) else str(val).lower() == "true"
                ok = self._write_int(clean_name, int(bool_val))
                return (ok, f"[ + ] {key} = {bool_val}") if ok else (False, f"[ - ] Failed: {key}")

        except Exception as exc:
            return False, f"[ - ] Error {key}: {exc}"

        return False, f"[ - ] Unknown flag type for: {key}"

    def apply_json(self, json_path: str) -> None:
        if not os.path.exists(json_path):
            print(f"[ - ] File not found: {json_path}")
            return

        print(f"[ + ] Loading flags from: {json_path}")

        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"[ - ] JSON parse error: {exc}")
            return
        except OSError as exc:
            print(f"[ - ] Could not read file: {exc}")
            return

        total   = len(data)
        success = 0

        for key, val in data.items():
            ok, msg = self.apply_flag(key, val)
            print(msg)
            success += ok

        print(f"\n[ + ] Applied {success}/{total} flags.")

    def cleanup(self) -> None:
        self._invalidate_caches(clear_hash=True)
        if self._process_handle:
            close_handle(self._process_handle)
            self._process_handle = 0


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    print(BANNER)
    print("[ + ] Velorin FFlag Injector — discord.gg/F8kkN62Apk\n")

    injector = None

    try:
        injector = FlagInjector()

        base_dir  = get_base_path()
        json_path = os.path.join(base_dir, "fflags.json")

        print(f"[ + ] Looking for fflags.json in: {base_dir}")

        if not os.path.exists(json_path):
            print("[ - ] fflags.json not found.")
            print(f"      Place it in: {base_dir}")
        else:
            injector.apply_json(json_path)

    except AttachTimeoutError as exc:
        print(f"\n[ - ] Attach timed out: {exc}")
    except RuntimeError as exc:
        print(f"\n[ - ] {exc}")
    except Exception as exc:
        print(f"\n[ - ] Unexpected error: {exc}")
        log.exception("Unhandled exception in main")
    finally:
        if injector is not None:
            injector.cleanup()

    print("\n[ + ] Done. Press Enter to exit …")
    input()


if __name__ == "__main__":
    main()