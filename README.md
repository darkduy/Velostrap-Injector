# Velostrap Injector
Roblox FFlag injector — tìm FFlagList động qua pattern scan, không cần offset cứng hay server.

Backend memory I/O và pattern scanner viết bằng Rust — nhanh hơn 10-50x so với Python thuần.

---

## Tải file

| File | Download |
|---|---|
| `main.exe` | [click here](https://github.com/darkduy/Velostrap-Injector/releases/latest/download/main.exe) |
| `mainDEBUG.exe` | [click here](https://github.com/darkduy/Velostrap-Injector/releases/latest/download/mainDEBUG.exe) |

> **mainDEBUG.exe** là bản hiện log chi tiết — dùng khi flags không apply được để debug lỗi.

---

## Cách sử dụng

1. Mở Roblox
2. Tạo file `fflags.json` cùng thư mục với `main.exe`
3. Chạy `main.exe`

**Ví dụ fflags.json:**
```json
{
    "FIntFRMMaxGrassDistance": 0,
    "FIntRenderShadowIntensity": 0,
    "DFIntTaskSchedulerTargetFps": 640,
    "FFlagDebugGraphicsPreferVulkan": true,
    "FStringPlatformEventUrl": "https://example.com"
}
```

**Prefix và kiểu dữ liệu:**
| Prefix | Kiểu |
|---|---|
| `FFlag`, `DFFlag` | bool (`true` / `false`) |
| `FInt`, `DFInt`, `FLog`, `DFLog` | int |
| `FString`, `DFString` | string |

---

## Cấu trúc project

```
Velostrap-Injector/
├── core_rs/              — Rust crate (memory I/O + pattern scanner)
│   ├── src/
│   │   ├── lib.rs        — PyO3 module entry
│   │   ├── errors.rs     — Custom exceptions
│   │   ├── process.rs    — SafeHandle + ProcessManager
│   │   ├── memory.rs     — NtMemory + MemoryManager
│   │   └── scanner.rs    — PatternScanner
│   └── Cargo.toml
├── core/
│   ├── __init__.py       — Import từ Rust backend
│   └── core_rs.pyd       — Rust binary (tự copy vào sau build)
├── main.py               — Logic chính + OFF_* constants
├── fflags.json           — Flags muốn inject
└── .github/
    └── workflows/
        └── build.yml
```

**Thứ tự ưu tiên file cần sửa sau Roblox update:**
| File | Tần suất | Lý do |
|---|---|---|
| `main.py` | Cao | `OFF_*` constants thay đổi khi struct layout đổi |
| `core_rs/src/scanner.rs` | Trung bình | LEA opcodes thay đổi khi Roblox đổi register |
| `core_rs/src/memory.rs` | Thấp | Windows API ổn định |
| `core_rs/src/process.rs` | Thấp | Toolhelp32 API ổn định |

---

## Cập nhật sau Roblox update

Có 2 trường hợp cần sửa code sau khi Roblox update:

---

### Trường hợp 1 — Flags không apply được (scan thành công nhưng flag fail)

Nghĩa là FFlagList **struct layout** đã thay đổi. Cần tìm lại và cập nhật `OFF_*` constants trong `main.py`.

**Tool cần có:** [Cheat Engine](https://www.cheatengine.org/downloads.php)

---

#### Bước 1 — Attach Cheat Engine vào Roblox

1. Mở Roblox trước, vào bất kỳ game nào
2. Mở Cheat Engine
3. Click icon hình máy tính ở góc trên trái
4. Tìm `RobloxPlayerBeta.exe` trong danh sách → click **Open**

---

#### Bước 2 — Lấy địa chỉ FFlagList

Chạy `mainDEBUG.exe` một lần, nhìn vào output:
```
[ + ] FFlagList at 0x1F2A3B4C5D6E
```
Copy địa chỉ này.

Trong Cheat Engine:
1. Vào **Memory View** (Ctrl+B)
2. Nhấn **Ctrl+G**
3. Dán địa chỉ vào → Enter

---

#### Bước 3 — Tìm hashmap (OFF_MAP_LIST, OFF_MAP_MASK, OFF_MAP_END)

FFlagList chứa một hashmap bắt đầu tại offset `+0x08`. Nhấn **Ctrl+G** lần nữa, nhập `địa_chỉ_FFlagList + 8`.

Nhìn vào 56 bytes từ đó:

```
+0x00  (8 bytes)  →  map_end   : pointer hợp lệ (dạng 0x00007F...)
+0x08  (8 bytes)  →  (bỏ qua)
+0x10  (8 bytes)  →  map_list  : pointer hợp lệ (dạng 0x00007F...)
+0x18  (8 bytes)  →  (bỏ qua)
+0x20  (8 bytes)  →  (bỏ qua)
+0x28  (8 bytes)  →  map_mask  : số dạng 2^n-1 (255, 511, 1023...)
```

**Cách nhận biết:**
- `map_end` và `map_list`: bytes trông như `XX XX XX XX XX 7F 00 00`. Click vào → Cheat Engine nhảy đến vùng memory đó, nếu đọc được thì hợp lệ.
- `map_mask`: số nhỏ dạng `FF 00 00 00...` = 255, `FF 01 00 00...` = 511, `FF 03 00 00...` = 1023.

Nếu các offset không cho ra giá trị hợp lệ, dịch chuyển từng bước 8 byte. Sửa trong `main.py`:

```python
OFF_MAP_END  = 0x00   # ← sửa thành offset mới
OFF_MAP_LIST = 0x10   # ← sửa thành offset mới
OFF_MAP_MASK = 0x28   # ← sửa thành offset mới
```

---

#### Bước 4 — Tìm node layout (OFF_ENTRY_FORWARD, OFF_ENTRY_STRING, OFF_ENTRY_GETSET)

1. Lấy giá trị pointer tại `map_list`
2. **Ctrl+G** → nhập địa chỉ đó — đây là bucket array, mỗi bucket 16 bytes
3. Đọc 8 bytes tại `bucket + 0x08` → địa chỉ **node đầu tiên**
4. **Ctrl+G** → nhập địa chỉ node đó

Dùng **Tools → Dissect Data/Structures** để xem struct dạng bảng.

```
node + 0x08  →  forward pointer  : pointer đến node tiếp theo
node + 0x10  →  string struct    : chứa tên flag
node + 0x30  →  getset pointer   : pointer đến struct chứa value
```

**Verify `node + 0x10` là string struct:**
- Đọc 8 bytes tại `node + 0x10 + 0x10` → phải là số nhỏ (1–50), đây là length
- Đọc bytes tại `node + 0x10` với độ dài đó → phải ra chuỗi dạng `FFlagXXX`, `FIntXXX`...
- Nếu ra rác thì thử `0x18`, `0x20`...

Sửa trong `main.py`:
```python
OFF_ENTRY_FORWARD = 0x08   # ← sửa nếu đổi
OFF_ENTRY_STRING  = 0x10   # ← sửa nếu đổi
OFF_ENTRY_GETSET  = 0x30   # ← sửa nếu đổi
```

---

#### Bước 5 — Tìm string struct layout (OFF_STR_SIZE, OFF_STR_CAPACITY)

**Ctrl+G** → nhập địa chỉ string struct (tại `node + OFF_ENTRY_STRING`):

```
string_struct + 0x00  →  buffer pointer  : nếu tên > 15 ký tự thì pointer đến heap,
                                           nếu <= 15 ký tự thì bytes nằm inline (SSO)
string_struct + 0x10  →  size (length)   : số ký tự của tên flag
string_struct + 0x18  →  capacity        : dung lượng buffer
```

Sửa trong `main.py`:
```python
OFF_STR_SIZE     = 0x10   # ← sửa nếu đổi
OFF_STR_CAPACITY = 0x18   # ← sửa nếu đổi
```

---

#### Bước 6 — Tìm OFF_FFLAG_VALUE_PTR

**Ctrl+G** → nhập địa chỉ tại `node + OFF_ENTRY_GETSET`.

```
getset + 0xC0  →  value pointer  : pointer đến int32 hoặc string value
```

Verify: đọc pointer tại `getset + 0xC0` → nhảy đến đó → 4 bytes phải ra `0` hoặc `1` nếu là bool/int. Nếu sai → thử `+0xB8`, `+0xC8`, `+0xD0`...

Sửa trong `main.py`:
```python
OFF_FFLAG_VALUE_PTR = 0xC0   # ← sửa nếu đổi
```

---

#### Bước 7 — Push lên GitHub

Sau khi sửa xong `main.py`, push lên GitHub. Workflow tự build lại cả hai file.

---

### Trường hợp 2 — Tool báo "Pattern scan failed"

Nghĩa là Roblox đã đổi register trong instruction truy cập FFlagList (ví dụ từ `lea rax` sang một register khác mà scanner chưa cover).

> **Lưu ý:** Scanner hiện tại (`scanner.rs`) tự generate tất cả LEA variants cho registers `rax`, `rcx`, `rdx`, `rbx`, `rsi`, `rdi`, `r8`–`r15` lúc runtime — không hardcode pattern cố định. Vì vậy trường hợp này ít xảy ra hơn so với version cũ.
>
> Nếu vẫn fail, khả năng cao Roblox đã dùng một cách truy cập FFlagList hoàn toàn khác (không còn là `lea [rip+disp32]`).

**Tool cần có:** [x64dbg](https://x64dbg.com/)

---

#### Bước 1 — Attach x64dbg vào Roblox

1. Mở Roblox trước
2. Mở x64dbg → **File** → **Attach** → chọn `RobloxPlayerBeta.exe`
3. Nhấn **F9** để resume

---

#### Bước 2 — Tìm địa chỉ FFlagList

Dùng Cheat Engine theo Trường hợp 1 → Bước 2.

---

#### Bước 3 — Tìm references đến FFlagList

1. Trong x64dbg nhấn **Ctrl+G** → nhập địa chỉ FFlagList
2. Click chuột phải → **Find references to** → **Selected address**
3. Cửa sổ References liệt kê tất cả chỗ trong code truy cập địa chỉ đó

---

#### Bước 4 — Đọc instruction tại kết quả tìm được

Double-click vào một kết quả → x64dbg nhảy đến CPU View.

Nhìn vào cột **Bytes**:
```
Bytes                  Disassembly
48 8D 05 D8 33 CE 07   lea rax, [rip+0x7CE33D8]
48 89 C1               mov rcx, rax
```

**Nếu instruction vẫn là dạng `lea [rip+disp32]`** (REX byte `48` hoặc `4C`, tiếp theo là `8D`, tiếp theo là ModRM):

Kiểm tra xem REX và ModRM có nằm trong danh sách sau không:

| REX | ModRM | Register |
|-----|-------|----------|
| `48` | `05` | rax |
| `48` | `0D` | rcx |
| `48` | `15` | rdx |
| `48` | `1D` | rbx |
| `48` | `35` | rsi |
| `48` | `3D` | rdi |
| `4C` | `05` | r8  |
| `4C` | `0D` | r9  |
| `4C` | `15` | r10 |
| `4C` | `1D` | r11 |
| `4C` | `35` | r14 |
| `4C` | `3D` | r15 |

Nếu REX/ModRM **đã có trong bảng** nhưng scan vẫn fail → vấn đề nằm ở verify logic, không phải opcode. Xem Bước 5A.

Nếu REX/ModRM **chưa có trong bảng** → cần thêm vào. Xem Bước 5B.

**Nếu instruction không phải dạng `lea [rip+disp32]`** — ví dụ Roblox dùng `mov` với absolute address hoặc indirect load — xem Bước 5C.

---

#### Bước 5A — Verify logic fail (opcode đúng nhưng vẫn không tìm được)

Mở `core_rs/src/scanner.rs`, tìm hàm `verify_fflaglist`. Vấn đề có thể là:

- `find_map_mask` không nhận ra mask value vì nằm ngoài range `0x3F..=0xFFFF`. Mở rộng range:
```rust
if val >= 0x3F && val <= 0xFFFF && (val & val.wrapping_add(1)) == 0 {
```
Sửa thành:
```rust
if val >= 0x0F && val <= 0x3FFFF && (val & val.wrapping_add(1)) == 0 {
```

- `find_map_list` không tìm được pointer vì hashmap không còn ở `FFlagList + 8`. Thử các offset khác (`+0x10`, `+0x18`) bằng cách sửa dòng:
```rust
let map_data = match self.mem.read_raw(self.handle, fflaglist + 8, 96) {
```

---

#### Bước 5B — Thêm REX/ModRM mới vào scanner

Mở `core_rs/src/scanner.rs`, tìm hàm `all_lea_opcodes`, thêm cặp REX/ModRM mới:

```rust
fn all_lea_opcodes() -> Vec<(u8, u8)> {
    vec![
        // ... các cặp hiện có ...

        // Thêm cặp mới — thay 0xXX bằng REX và ModRM từ Bước 4
        (0xXX, 0xXX),
    ]
}
```

**Ví dụ:** nếu x64dbg hiện `4D 8D 05 ...` (REX=`4D`, ModRM=`05`) thì thêm:
```rust
(0x4D, 0x05), // lea r8 (REX.W + REX.R + REX.B)
```

---

#### Bước 5C — Roblox dùng instruction hoàn toàn khác

Đây là trường hợp phức tạp nhất — Roblox không còn dùng `lea [rip+disp32]` nữa.

Nhìn vào instruction trong CPU View của x64dbg và xác định pattern mới. Sau đó sửa hàm `scan_chunk` trong `core_rs/src/scanner.rs` để nhận dạng pattern mới đó, giữ lại logic `verify_fflaglist` vì vẫn còn dùng được.

---

#### Bước 6 — Rebuild và push

Sau khi sửa `scanner.rs`, push lên GitHub → workflow tự build lại cả hai file.

Khác với Trường hợp 1 (chỉ sửa `main.py`, không cần rebuild Rust), Trường hợp 2 **bắt buộc phải rebuild** vì `scanner.rs` là Rust code.

---

## Build local

Cần cài: [Rust](https://rustup.rs/), [maturin](https://github.com/PyO3/maturin), Python 3.10+

```bash
# Build Rust backend
cd core_rs
maturin build --release --target x86_64-pc-windows-msvc

# Copy .pyd vào core/
copy ..\dist_rs\*.pyd ..\core\core_rs.pyd

# Build EXE
cd ..
pip install pyinstaller
pyinstaller --onefile --console --name main --add-binary "core\core_rs.pyd;core" main.py
```

---

## Build tự động (GitHub Actions)

Workflow tự build cả 2 file mỗi khi push lên `main`:

```
Actions → Build Windows EXE → Artifacts → main.exe / mainDEBUG.exe
```

Hoặc trigger thủ công: **Actions → Build Windows EXE → Run workflow**

---

## Requirements

- Windows 10/11 x64
- Roblox đang chạy trước khi mở tool
- `fflags.json` đặt cùng thư mục với `main.exe`