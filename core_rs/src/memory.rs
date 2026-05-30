//! NtDll memory I/O và MemoryManager high-level façade.

use std::ffi::c_void;
use std::time::{Duration, Instant};

use pyo3::prelude::*;

use crate::errors::{
    AttachTimeout, MemoryError, ModuleNotFound, ProcessNotFound, StringCapacity, ntstatus_str,
};
use crate::process::{ProcessManager, SafeHandle};

// ──────────────────────────────────────────────
// NtDll bindings
// ──────────────────────────────────────────────

#[link(name = "ntdll")]
extern "system" {
    fn NtReadVirtualMemory(
        ProcessHandle:       isize,
        BaseAddress:         *const c_void,
        Buffer:              *mut c_void,
        NumberOfBytesToRead: usize,
        NumberOfBytesRead:   *mut usize,
    ) -> i32;

    fn NtWriteVirtualMemory(
        ProcessHandle:        isize,
        BaseAddress:          *mut c_void,
        Buffer:               *const c_void,
        NumberOfBytesToWrite: usize,
        NumberOfBytesWritten: *mut usize,
    ) -> i32;
}

const NT_SUCCESS: i32 = 0;

// ──────────────────────────────────────────────
// NtMemory — internal impl (pub fn để các module khác dùng)
// ──────────────────────────────────────────────

#[pyclass]
pub struct NtMemory;

impl NtMemory {
    /// Đọc *size* bytes từ *address* trong process *handle*.
    /// pub (không phải pymethods) để scanner.rs gọi được.
    pub fn read_raw(&self, handle: isize, address: u64, size: usize) -> PyResult<Vec<u8>> {
        let mut buf  = vec![0u8; size];
        let mut read = 0usize;

        let status = unsafe {
            NtReadVirtualMemory(
                handle,
                address as *const c_void,
                buf.as_mut_ptr() as *mut c_void,
                size,
                &mut read,
            )
        };

        if status != NT_SUCCESS {
            return Err(MemoryError::new_err(format!(
                "NtReadVirtualMemory failed: status={} addr=0x{:X} size={}",
                ntstatus_str(status), address, size
            )));
        }

        buf.truncate(read);
        Ok(buf)
    }

    pub fn write_raw(&self, handle: isize, address: u64, data: &[u8]) -> PyResult<()> {
        let mut written = 0usize;

        let status = unsafe {
            NtWriteVirtualMemory(
                handle,
                address as *mut c_void,
                data.as_ptr() as *const c_void,
                data.len(),
                &mut written,
            )
        };

        if status != NT_SUCCESS || written != data.len() {
            return Err(MemoryError::new_err(format!(
                "NtWriteVirtualMemory failed: status={} addr=0x{:X} written={}/{}",
                ntstatus_str(status), address, written, data.len()
            )));
        }

        Ok(())
    }

    pub fn read_u64_raw(&self, handle: isize, address: u64) -> PyResult<u64> {
        let b = self.read_raw(handle, address, 8)?;
        Ok(u64::from_le_bytes(b.try_into().unwrap()))
    }
}

// ──────────────────────────────────────────────
// NtMemory — Python API (#[pymethods])
// ──────────────────────────────────────────────

#[pymethods]
impl NtMemory {
    #[new]
    fn new() -> Self { Self }

    fn read(&self, handle: isize, address: u64, size: usize) -> PyResult<Vec<u8>> {
        self.read_raw(handle, address, size)
    }

    fn write(&self, handle: isize, address: u64, data: &[u8]) -> PyResult<()> {
        self.write_raw(handle, address, data)
    }

    fn read_u32(&self, handle: isize, address: u64) -> PyResult<u32> {
        let b = self.read_raw(handle, address, 4)?;
        Ok(u32::from_le_bytes(b.try_into().unwrap()))
    }

    fn read_i32(&self, handle: isize, address: u64) -> PyResult<i32> {
        let b = self.read_raw(handle, address, 4)?;
        Ok(i32::from_le_bytes(b.try_into().unwrap()))
    }

    fn read_u64(&self, handle: isize, address: u64) -> PyResult<u64> {
        self.read_u64_raw(handle, address)
    }

    fn read_i64(&self, handle: isize, address: u64) -> PyResult<i64> {
        let b = self.read_raw(handle, address, 8)?;
        Ok(i64::from_le_bytes(b.try_into().unwrap()))
    }

    fn write_i32(&self, handle: isize, address: u64, value: i32) -> PyResult<()> {
        self.write_raw(handle, address, &value.to_le_bytes())
    }

    fn write_i64(&self, handle: isize, address: u64, value: i64) -> PyResult<()> {
        self.write_raw(handle, address, &value.to_le_bytes())
    }
}

// ──────────────────────────────────────────────
// Internal helpers
// ──────────────────────────────────────────────

fn extract_ptr(data: &[u8], offset: usize) -> PyResult<u64> {
    if offset + 8 > data.len() {
        return Err(MemoryError::new_err(format!(
            "extract_ptr: offset 0x{:X} out of bounds (data len={})", offset, data.len()
        )));
    }
    let ptr = u64::from_le_bytes(data[offset..offset + 8].try_into().unwrap());
    if ptr == 0 {
        return Err(MemoryError::new_err(format!(
            "Null pointer at struct offset 0x{:X}", offset
        )));
    }
    Ok(ptr)
}

// ──────────────────────────────────────────────
// MemoryManager
// ──────────────────────────────────────────────

const FFLAG_STRUCT_SIZE: usize = 0xD0;
const FFLAG_STR_BUF_OFF: u64  = 0x00;
const FFLAG_STR_LEN_OFF: u64  = 0x08;
const FFLAG_STR_CAP_OFF: u64  = 0x10;

#[pyclass]
pub struct MemoryManager {
    pub mem:  NtMemory,
    pub proc: ProcessManager,
}

#[pymethods]
impl MemoryManager {
    #[new]
    fn new() -> Self {
        Self { mem: NtMemory, proc: ProcessManager }
    }

    #[pyo3(signature = (process_name, module_name, poll_interval=1.0, timeout=None))]
    fn attach_raw(
        &self,
        process_name:  &str,
        module_name:   &str,
        poll_interval: f64,
        timeout:       Option<f64>,
    ) -> PyResult<SafeHandle> {
        let deadline  = timeout.map(|t| Instant::now() + Duration::from_secs_f64(t));
        let sleep_dur = Duration::from_secs_f64(poll_interval);

        loop {
            match self._try_attach(process_name, module_name) {
                Ok(h) => return Ok(h),
                Err(_) => {
                    if let Some(dl) = deadline {
                        if Instant::now() >= dl {
                            return Err(AttachTimeout::new_err(format!(
                                "Could not attach to {process_name:?} within {timeout:?}s"
                            )));
                        }
                    }
                    std::thread::sleep(sleep_dur);
                }
            }
        }
    }

    #[pyo3(signature = (handle, fflag_addr, value_ptr_offset, value, struct_size=None))]
    fn write_fflag_int(
        &self,
        handle:           isize,
        fflag_addr:       u64,
        value_ptr_offset: usize,
        value:            i32,
        struct_size:      Option<usize>,
    ) -> PyResult<()> {
        let sz   = struct_size.unwrap_or(FFLAG_STRUCT_SIZE);
        let data = self.mem.read_raw(handle, fflag_addr, sz)?;
        let vptr = extract_ptr(&data, value_ptr_offset)?;
        self.mem.write_raw(handle, vptr, &value.to_le_bytes())
    }

    #[pyo3(signature = (handle, fflag_addr, value_ptr_offset, value, struct_size=None))]
    fn write_fflag_string(
        &self,
        handle:           isize,
        fflag_addr:       u64,
        value_ptr_offset: usize,
        value:            &str,
        struct_size:      Option<usize>,
    ) -> PyResult<()> {
        let sz       = struct_size.unwrap_or(FFLAG_STRUCT_SIZE);
        let data     = self.mem.read_raw(handle, fflag_addr, sz)?;
        let inst_ptr = extract_ptr(&data, value_ptr_offset)?;

        let buf_ptr  = self.mem.read_u64_raw(handle, inst_ptr + FFLAG_STR_BUF_OFF)?;
        let capacity = self.mem.read_u64_raw(handle, inst_ptr + FFLAG_STR_CAP_OFF)?;

        let encoded = value.as_bytes();
        let new_len = encoded.len() as u64;

        if new_len > capacity {
            return Err(StringCapacity::new_err(format!(
                "New value ({new_len} bytes) exceeds buffer capacity ({capacity} bytes)"
            )));
        }

        let mut buf_with_null = encoded.to_vec();
        buf_with_null.push(0);
        self.mem.write_raw(handle, buf_ptr, &buf_with_null)?;
        self.mem.write_raw(handle, inst_ptr + FFLAG_STR_LEN_OFF, &(new_len as i64).to_le_bytes())
    }
}

impl MemoryManager {
    fn _try_attach(&self, process_name: &str, module_name: &str) -> PyResult<SafeHandle> {
        let pid  = self.proc.find_pid(process_name)?;
        let mut safe = self.proc.open_process(pid)?;

        let (base, size) = match self.proc.get_module_base(pid, module_name) {
            Ok(v)  => v,
            Err(e) => { safe.close(); return Err(e); }
        };

        safe.module_base = base;
        safe.module_size = size;
        Ok(safe)
    }
}