use pyo3::prelude::*;
use pyo3::create_exception;
use pyo3::exceptions::PyException;

create_exception!(core_rs, MemoryError,     PyException, "Raised on memory read/write failure.");
create_exception!(core_rs, ProcessNotFound, PyException, "Raised when target process is not found.");
create_exception!(core_rs, ModuleNotFound,  PyException, "Raised when target module is not found.");
create_exception!(core_rs, AttachTimeout,   PyException, "Raised when attach_raw times out.");
create_exception!(core_rs, StringCapacity,  PyException, "Raised when string exceeds buffer capacity.");

/// Map NTSTATUS code to a human-readable string.
pub fn ntstatus_str(status: i32) -> String {
    match status as u32 {
        0x00000000 => "STATUS_SUCCESS".into(),
        0xC0000005 => "STATUS_ACCESS_VIOLATION".into(),
        0xC0000008 => "STATUS_INVALID_HANDLE".into(),
        0xC000000D => "STATUS_INVALID_PARAMETER".into(),
        0xC0000022 => "STATUS_ACCESS_DENIED".into(),
        0xC000001C => "STATUS_INVALID_DEVICE_REQUEST".into(),
        0xC0000034 => "STATUS_OBJECT_NAME_NOT_FOUND".into(),
        _ => format!("0x{:08X}", status as u32),
    }
}