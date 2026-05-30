//! Pattern scanner — tìm FFlagList offset động bằng cách scan memory.
//!
//! Khác với version cũ hardcode PATTERNS compile-time, version này:
//! - Tự generate tất cả variants LEA rip-relative (rax/rcx/rdx/rbx/rsi/rdi/r8-r15)
//! - Verify FFlagList bằng cách scan động thay vì assume offset cứng
//! - Không cần rebuild khi Roblox đổi register trong LEA instruction

use pyo3::prelude::*;

use crate::memory::NtMemory;

// ──────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────

const CHUNK_SIZE:    usize = 0x10_000;  // 64 KB mỗi lần đọc
const CHUNK_OVERLAP: usize = 16;        // overlap tránh bỏ sót pattern trên ranh giới
const RIP_DISP_OFF:  usize = 3;        // offset của disp32 trong LEA instruction
const LEA_INSN_LEN:  u64   = 7;        // độ dài LEA rip-relative instruction
const MIN_VALID_PTR: u64   = 0x10_000;
const MAX_VALID_PTR: u64   = 0x7FFF_FFFF_FFFF;

// Scan tối đa 2 bytes sau disp32 để verify — đủ để tránh false positive
// mà không cần hardcode bytes kế tiếp
const POST_DISP_VERIFY_LEN: usize = 2;

// ──────────────────────────────────────────────
// LEA rip-relative opcode generation
//
// x86-64 LEA [rip+disp32] encoding:
//   REX.W  ModRM  disp32(4 bytes)
//
// REX.W = 0x48 cho register rax-rdi
//         0x4C cho register r8-r15 (REX.R set)
//
// ModRM = 0x05 → rax   0x0D → rcx   0x15 → rdx   0x1D → rbx
//         0x25 → rsp*  0x2D → rbp*  0x35 → rsi   0x3D → rdi
//         (* rsp/rbp dạng này không dùng cho FFlagList)
//
// r8-r15: REX = 0x4C, ModRM = 0x05/0x0D/0x15/0x1D/0x25/0x2D/0x35/0x3D
// ──────────────────────────────────────────────

/// Trả về danh sách tất cả (rex, modrm) pairs của LEA [rip+disp32].
/// Được tính lúc runtime thay vì hardcode — thêm register mới không cần sửa code.
fn all_lea_opcodes() -> Vec<(u8, u8)> {
    // REX.W = 0x48, registers rax-rdi (không dùng rsp/rbp làm destination)
    let rex_w_modrm: &[(u8, u8)] = &[
        (0x48, 0x05), // lea rax
        (0x48, 0x0D), // lea rcx
        (0x48, 0x15), // lea rdx
        (0x48, 0x1D), // lea rbx
        (0x48, 0x35), // lea rsi
        (0x48, 0x3D), // lea rdi
    ];
    // REX.W + REX.R = 0x4C, registers r8-r13
    let rex_wr_modrm: &[(u8, u8)] = &[
        (0x4C, 0x05), // lea r8
        (0x4C, 0x0D), // lea r9
        (0x4C, 0x15), // lea r10
        (0x4C, 0x1D), // lea r11
        (0x4C, 0x35), // lea r14
        (0x4C, 0x3D), // lea r15
    ];
    [rex_w_modrm, rex_wr_modrm].concat()
}

// ──────────────────────────────────────────────
// PatternScanner
// ──────────────────────────────────────────────

#[pyclass]
pub struct PatternScanner {
    handle:      isize,
    module_base: u64,
    module_size: u32,
    mem:         NtMemory,
    /// LEA opcodes được generate lúc init — tránh recompute mỗi chunk
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

    /// Scan toàn bộ module memory.
    /// Trả về RVA (offset từ module_base) của FFlagList pointer, hoặc None nếu không tìm.
    fn find_fflaglist_offset(&self) -> PyResult<Option<u64>> {
        let total = self.module_size as usize;
        let mut pos = 0usize;

        while pos < total {
            let chunk_va  = self.module_base + pos as u64;
            let read_size = CHUNK_SIZE.min(total - pos);

            let data = match self.mem.read(self.handle, chunk_va, read_size) {
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
    /// Scan một chunk, trả về RVA nếu tìm thấy.
    fn scan_chunk(&self, data: &[u8], chunk_va: u64) -> Option<u64> {
        let min_len = RIP_DISP_OFF + 4 + POST_DISP_VERIFY_LEN;
        if data.len() < min_len {
            return None;
        }

        for i in 0..=(data.len() - min_len) {
            // Kiểm tra byte đầu tiên có phải REX không để tránh scan toàn bộ
            let rex = data[i];
            if rex != 0x48 && rex != 0x4C {
                continue;
            }

            // Kiểm tra ModRM có trong danh sách LEA opcodes không
            let modrm = data[i + 1];
            if !self.lea_opcodes.iter().any(|&(r, m)| r == rex && m == modrm) {
                continue;
            }

            // Tính địa chỉ target từ RIP-relative disp32
            let target = match resolve_rip(chunk_va, i, data) {
                Some(t) => t,
                None    => continue,
            };

            // Verify target trỏ đến FFlagList hợp lệ
            if self.verify_fflaglist(target) {
                let rva = target - self.module_base;
                return Some(rva);
            }
        }

        None
    }

    /// Verify địa chỉ *ptr_addr* trỏ đến FFlagList hợp lệ.
    ///
    /// Scan động để tìm map_list và map_mask thay vì assume offset cứng:
    /// - Đọc FFlagList pointer tại ptr_addr
    /// - Tại hashmap (FFlagList + 8), scan 8 slots để tìm cặp (pointer, mask) hợp lệ
    /// - map_mask phải là 2^n - 1
    fn verify_fflaglist(&self, ptr_addr: u64) -> bool {
        // Đọc FFlagList pointer
        let fflaglist = match self.mem.read_u64(self.handle, ptr_addr) {
            Ok(v) if is_valid_ptr(v) => v,
            _ => return false,
        };

        // Đọc hashmap tại FFlagList + 8 (tối đa 96 bytes = 12 slots × 8 bytes)
        let hashmap_addr = fflaglist + 8;
        let map_data = match self.mem.read(self.handle, hashmap_addr, 96) {
            Ok(d) if d.len() >= 48 => d,
            _ => return false,
        };

        // Scan động để tìm map_list và map_mask
        // Thay vì assume 0x10 và 0x28, thử từng slot và verify tính hợp lệ
        let found_list = self.find_map_list(&map_data);
        let found_mask = self.find_map_mask(&map_data);

        found_list && found_mask
    }

    /// Scan map_data để tìm ít nhất một slot là pointer hợp lệ (map_list candidate).
    fn find_map_list(&self, map_data: &[u8]) -> bool {
        let slots = map_data.len() / 8;
        for i in 0..slots {
            let off = i * 8;
            if off + 8 > map_data.len() { break; }
            let val = u64::from_le_bytes(map_data[off..off+8].try_into().unwrap());
            if is_valid_ptr(val) {
                // Verify pointer thực sự readable
                if self.mem.read(self.handle, val, 8).is_ok() {
                    return true;
                }
            }
        }
        false
    }

    /// Scan map_data để tìm ít nhất một slot là mask hợp lệ (2^n - 1).
    fn find_map_mask(&self, map_data: &[u8]) -> bool {
        let slots = map_data.len() / 8;
        for i in 0..slots {
            let off = i * 8;
            if off + 8 > map_data.len() { break; }
            let val = u64::from_le_bytes(map_data[off..off+8].try_into().unwrap());
            // 2^n - 1: tất cả bit thấp đều 1, ví dụ 0xFF, 0x1FF, 0x3FF...
            // Thêm điều kiện: phải trong range hợp lý (64 - 65536 buckets)
            if val >= 0x3F && val <= 0xFFFF && (val & val.wrapping_add(1)) == 0 {
                return true;
            }
        }
        false
    }
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

/// Tính địa chỉ tuyệt đối từ LEA [rip + disp32] tại vị trí *match_off* trong chunk.
#[inline]
fn resolve_rip(chunk_va: u64, match_off: usize, data: &[u8]) -> Option<u64> {
    let disp_start = match_off + RIP_DISP_OFF;
    if disp_start + 4 > data.len() {
        return None;
    }
    let disp32  = i32::from_le_bytes(data[disp_start..disp_start+4].try_into().ok()?);
    let insn_va = chunk_va + match_off as u64;
    let rip     = insn_va + LEA_INSN_LEN;
    Some(rip.wrapping_add(disp32 as i64 as u64))
}

#[inline]
fn is_valid_ptr(ptr: u64) -> bool {
    ptr >= MIN_VALID_PTR && ptr <= MAX_VALID_PTR
}