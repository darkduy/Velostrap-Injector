mod errors;
mod memory;
mod process;
mod scanner;

use pyo3::prelude::*;

#[pymodule]
fn core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<memory::NtMemory>()?;
    m.add_class::<memory::MemoryManager>()?;
    m.add_class::<process::ProcessManager>()?;
    m.add_class::<process::SafeHandle>()?;
    m.add_class::<scanner::PatternScanner>()?;

    m.add("MemoryError",     errors::MemoryError::type_object(m.py()))?;
    m.add("ProcessNotFound", errors::ProcessNotFound::type_object(m.py()))?;
    m.add("ModuleNotFound",  errors::ModuleNotFound::type_object(m.py()))?;
    m.add("AttachTimeout",   errors::AttachTimeout::type_object(m.py()))?;
    m.add("StringCapacity",  errors::StringCapacity::type_object(m.py()))?;
    Ok(())
}