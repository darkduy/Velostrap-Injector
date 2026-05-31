"""
core/__init__.py — Import từ Rust backend (core_rs.pyd).
"""

from core_rs import (
    MemoryManager,
    PatternScanner,
    MemoryError,
    ProcessNotFound  as ProcessNotFoundError,
    ModuleNotFound   as ModuleNotFoundError,
    AttachTimeout    as AttachTimeoutError,
    StringCapacity   as StringCapacityError,
)

__all__ = [
    "MemoryManager",
    "PatternScanner",
    "MemoryError",
    "ProcessNotFoundError",
    "ModuleNotFoundError",
    "AttachTimeoutError",
    "StringCapacityError",
]