//! Process và module enumeration via Toolhelp32 snapshots.
//! SafeHandle — RAII wrapper cho Win32 HANDLE.

use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;

use pyo3::prelude::*;
use windows::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Module32FirstW, Module32NextW, Process32FirstW, Process32NextW,
    MODULEENTRY32W, PROCESSENTRY32W, TH32CS_SNAPMODULE, TH32CS_SNAPMODULE32, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{OpenProcess, PROCESS_ALL_ACCESS};

use crate::errors::{ModuleNotFound, ProcessNotFound};

// ──────────────────────────────────────────────
// SafeHandle
// ──────────────────────────────────────────────

/// RAII wrapper cho Win32 HANDLE.
/// Tự động gọi CloseHandle khi drop — không thể leak.
#[pyclass]
pub struct SafeHandle {
    pub(crate) handle: HANDLE,
    pub(crate) module_base: u64,
    pub(crate) module_size: u32,
}

impl SafeHandle {
    pub fn new(handle: HANDLE) -> Self {
        Self {
            handle,
            module_base: 0,
            module_size: 0,
        }
    }

    pub fn is_valid(&self) -> bool {
        !self.handle.is_invalid() && self.handle != HANDLE(0)
    }
}

impl Drop for SafeHandle {
    fn drop(&mut self) {
        if self.is_valid() {
            // CloseHandle tự log lỗi nếu fail ở debug build
            unsafe { let _ = CloseHandle(self.handle); }
            self.handle = HANDLE(0);
        }
    }
}

#[pymethods]
impl SafeHandle {
    /// Raw handle value dưới dạng int — dùng để truyền vào NtMemory
    #[getter]
    fn value(&self) -> isize {
        self.handle.0
    }

    #[getter]
    fn module_base(&self) -> u64 {
        self.module_base
    }

    #[getter]
    fn module_size(&self) -> u32 {
        self.module_size
    }

    fn close(&mut self) {
        if self.is_valid() {
            unsafe { let _ = CloseHandle(self.handle); }
            self.handle = HANDLE(0);
        }
    }
}

// ──────────────────────────────────────────────
// ProcessManager
// ──────────────────────────────────────────────

#[pyclass]
pub struct ProcessManager;

#[pymethods]
impl ProcessManager {
    #[new]
    fn new() -> Self {
        Self
    }

    /// Tìm PID của process theo tên. Raises ProcessNotFound nếu không có.
    fn find_pid(&self, process_name: &str) -> PyResult<u32> {
        let name_lower = process_name.to_lowercase();

        let snap = unsafe {
            CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                .map_err(|e| ProcessNotFound::new_err(format!("CreateToolhelp32Snapshot failed: {e}")))?
        };

        // SafeHandle đảm bảo snap luôn được đóng
        let _guard = scopeguard::defer(|| unsafe { let _ = CloseHandle(snap); });

        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };

        let ok = unsafe { Process32FirstW(snap, &mut entry) };
        if ok.is_err() {
            return Err(ProcessNotFound::new_err(format!("Process32FirstW failed")));
        }

        loop {
            let exe = wstr_to_string(&entry.szExeFile);
            if exe.to_lowercase() == name_lower {
                return Ok(entry.th32ProcessID);
            }
            if unsafe { Process32NextW(snap, &mut entry) }.is_err() {
                break;
            }
        }

        Err(ProcessNotFound::new_err(format!("Process not found: {process_name:?}")))
    }

    /// Tìm base address và size của module trong process. Raises ModuleNotFound nếu không có.
    fn get_module_base(&self, pid: u32, module_name: &str) -> PyResult<(u64, u32)> {
        let name_lower = module_name.to_lowercase();
        let flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32;

        let snap = unsafe {
            CreateToolhelp32Snapshot(flags, pid)
                .map_err(|e| ModuleNotFound::new_err(format!("CreateToolhelp32Snapshot failed: {e}")))?
        };

        let _guard = scopeguard::defer(|| unsafe { let _ = CloseHandle(snap); });

        let mut entry = MODULEENTRY32W {
            dwSize: std::mem::size_of::<MODULEENTRY32W>() as u32,
            ..Default::default()
        };

        let ok = unsafe { Module32FirstW(snap, &mut entry) };
        if ok.is_err() {
            return Err(ModuleNotFound::new_err("Module32FirstW failed"));
        }

        loop {
            let modname = wstr_to_string(&entry.szModule);
            if modname.to_lowercase() == name_lower {
                let base = entry.modBaseAddr as u64;
                let size = entry.modBaseSize;
                return Ok((base, size));
            }
            if unsafe { Module32NextW(snap, &mut entry) }.is_err() {
                break;
            }
        }

        Err(ModuleNotFound::new_err(format!(
            "Module not found: {module_name:?} in pid={pid}"
        )))
    }

    /// Mở process với PROCESS_ALL_ACCESS. Trả về SafeHandle. Raises ProcessNotFound nếu fail.
    fn open_process(&self, pid: u32) -> PyResult<SafeHandle> {
        let handle = unsafe {
            OpenProcess(PROCESS_ALL_ACCESS, false, pid)
                .map_err(|e| ProcessNotFound::new_err(format!("OpenProcess failed pid={pid}: {e}")))?
        };
        Ok(SafeHandle::new(handle))
    }
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

fn wstr_to_string(wstr: &[u16]) -> String {
    let end = wstr.iter().position(|&c| c == 0).unwrap_or(wstr.len());
    OsString::from_wide(&wstr[..end])
        .to_string_lossy()
        .into_owned()
}