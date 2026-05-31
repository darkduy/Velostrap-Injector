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

    let py = m.py();
    m.add("MemoryError",     py.get_type::<errors::MemoryError>())?;
    m.add("ProcessNotFound", py.get_type::<errors::ProcessNotFound>())?;
    m.add("ModuleNotFound",  py.get_type::<errors::ModuleNotFound>())?;
    m.add("AttachTimeout",   py.get_type::<errors::AttachTimeout>())?;
    m.add("StringCapacity",  py.get_type::<errors::StringCapacity>())?;
    Ok(())
}