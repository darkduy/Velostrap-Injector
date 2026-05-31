"""
core/__init__.py — Import từ Rust backend (core_rs.pyd).
Sau khi build, copy core_rs.pyd vào thư mục này.
Mọi import trong main.py không cần thay đổi gì.
"""
import os
import sys

# Khi chạy từ PyInstaller EXE, core_rs.pyd được extract vào _MEIPASS/core/.
# Python chỉ tìm extension modules ở top-level sys.path, không tìm trong sub-folder.
# → Thêm thư mục chứa file này vào sys.path để `from core_rs import` tìm thấy .pyd.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

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
