use pyo3::exceptions::{PyException, PyRuntimeError, PyOSError, PyValueError};
use pyo3::PyErr;

pyo3::create_exception!(core_rs, MemoryError,      PyException, "Memory read/write failed");
pyo3::create_exception!(core_rs, ProcessNotFound,  PyException, "Process not found");
pyo3::create_exception!(core_rs, ModuleNotFound,   PyException, "Module not found");
pyo3::create_exception!(core_rs, AttachTimeout,    PyException, "Attach timed out");
pyo3::create_exception!(core_rs, StringCapacity,   PyException, "String exceeds buffer capacity");

/// Chuyển Windows NTSTATUS sang hex string
pub fn ntstatus_str(status: i32) -> String {
    format!("0x{:08X}", status as u32)
}