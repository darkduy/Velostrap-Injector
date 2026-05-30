//! Pattern scanner — tìm FFlagList offset động bằng cách scan memory.

use pyo3::prelude::*;
use crate::memory::NtMemory;

const CHUNK_SIZE:    usize = 0x10_000;
const CHUNK_OVERLAP: usize = 16;
const RIP_DISP_OFF:  usize = 3;
const LEA_INSN_LEN:  u64   = 7;
const MIN_VALID_PTR: u64   = 0x10_000;
const MAX_VALID_PTR: u64   = 0x7FFF_FFFF_FFFF;

fn all_lea_opcodes() -> Vec<(u8, u8)> {
    vec![
        (0x48, 0x05), (0x48, 0x0D), (0x48, 0x15), (0x48, 0x1D),
        (0x48, 0x35), (0x48, 0x3D),
        (0x4C, 0x05), (0x4C, 0x0D), (0x4C, 0x15), (0x4C, 0x1D),
        (0x4C, 0x35), (0x4C, 0x3D),
    ]
}

#[pyclass]
pub struct PatternScanner {
    handle:      isize,
    module_base: u64,
    module_size: u32,
    mem:         NtMemory,
    lea_opcodes: Vec<(u8, u8)>,
}

#[pymethods]
impl PatternScanner {
    #[new]
    fn new(handle: isize, module_base: u64, module_size: u32, _mem: &NtMemory) -> Self {
        Self {
            handle,
            module_base,
            module_size,
            mem: NtMemory,
            lea_opcodes: all_lea_opcodes(),
        }
    }

    fn find_fflaglist_offset(&self) -> PyResult<Option<u64>> {
        let total = self.module_size as usize;
        let mut pos = 0usize;

        while pos < total {
            let chunk_va  = self.module_base + pos as u64;
            let read_size = CHUNK_SIZE.min(total - pos);

            // Fix: dùng read_raw thay vì read (pub Rust method)
            let data = match self.mem.read_raw(self.handle, chunk_va, read_size) {
                Ok(d)  => d,
                Err(_) => { pos += CHUNK_SIZE; continue; }
            };

            if let Some(offset) = self.scan_chunk(&data, chunk_va) {
                return Ok(Some(offset));
            }

            pos += CHUNK_SIZE.saturating_sub(CHUNK_OVERLAP);
        }

        Ok(None)
    }
}

impl PatternScanner {
    fn scan_chunk(&self, data: &[u8], chunk_va: u64) -> Option<u64> {
        let min_len = RIP_DISP_OFF + 4 + 2;
        if data.len() < min_len {
            return None;
        }

        for i in 0..=(data.len() - min_len) {
            let rex = data[i];
            if rex != 0x48 && rex != 0x4C {
                continue;
            }

            let modrm = data[i + 1];
            if !self.lea_opcodes.iter().any(|&(r, m)| r == rex && m == modrm) {
                continue;
            }

            let target = match resolve_rip(chunk_va, i, data) {
                Some(t) => t,
                None    => continue,
            };

            if self.verify_fflaglist(target) {
                return Some(target - self.module_base);
            }
        }

        None
    }

    fn verify_fflaglist(&self, ptr_addr: u64) -> bool {
        // Đọc FFlagList pointer
        let fflaglist = match self.mem.read_u64_raw(self.handle, ptr_addr) {
            Ok(v) if is_valid_ptr(v) => v,
            _ => return false,
        };

        // Đọc hashmap tại FFlagList + 8
        let map_data = match self.mem.read_raw(self.handle, fflaglist + 8, 96) {
            Ok(d) if d.len() >= 48 => d,
            _ => return false,
        };

        self.find_map_list(&map_data) && self.find_map_mask(&map_data)
    }

    fn find_map_list(&self, map_data: &[u8]) -> bool {
        for i in 0..(map_data.len() / 8) {
            let off = i * 8;
            if off + 8 > map_data.len() { break; }
            let val = u64::from_le_bytes(map_data[off..off+8].try_into().unwrap());
            if is_valid_ptr(val) {
                // Fix: dùng read_raw thay vì read
                if self.mem.read_raw(self.handle, val, 8).is_ok() {
                    return true;
                }
            }
        }
        false
    }

    fn find_map_mask(&self, map_data: &[u8]) -> bool {
        for i in 0..(map_data.len() / 8) {
            let off = i * 8;
            if off + 8 > map_data.len() { break; }
            let val = u64::from_le_bytes(map_data[off..off+8].try_into().unwrap());
            if val >= 0x3F && val <= 0xFFFF && (val & val.wrapping_add(1)) == 0 {
                return true;
            }
        }
        false
    }
}

#[inline]
fn resolve_rip(chunk_va: u64, match_off: usize, data: &[u8]) -> Option<u64> {
    let disp_start = match_off + RIP_DISP_OFF;
    if disp_start + 4 > data.len() { return None; }
    let disp32  = i32::from_le_bytes(data[disp_start..disp_start+4].try_into().ok()?);
    let insn_va = chunk_va + match_off as u64;
    let rip     = insn_va + LEA_INSN_LEN;
    Some(rip.wrapping_add(disp32 as i64 as u64))
}

#[inline]
fn is_valid_ptr(ptr: u64) -> bool {
    ptr >= MIN_VALID_PTR && ptr <= MAX_VALID_PTR
}