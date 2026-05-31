"""
core/__init__.py — Import từ Rust backend (core_rs.pyd).
Sau khi build, copy core_rs.pyd vào thư mục này.
Mọi import trong main.py không cần thay đổi gì.
"""
from core_rs import (
    NtMemory,
    MemoryManager,
    ProcessManager,
    SafeHandle,
    PatternScanner,
)
from core_rs import (
    MemoryError,
    ProcessNotFound as ProcessNotFoundError,
    ModuleNotFound  as ModuleNotFoundError,
    AttachTimeout   as AttachTimeoutError,
    StringCapacity  as StringCapacityError,
)