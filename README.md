# Velostrap Injector
Roblox FFlag injector — tìm FFlagList động qua pattern scan, không cần offset cứng hay server.

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
├── core/
│   ├── memory.py     — NtDll memory I/O (hiếm khi cần đụng)
│   └── scanner.py    — Pattern scan tìm FFlagList (đụng khi scan fail)
├── main.py           — Logic chính + OFF_* constants (đụng khi struct đổi)
├── fflags.json       — Flags muốn inject
└── .github/
    └── workflows/
        └── build.yml
```

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

Bạn sẽ thấy vùng memory của FFlagList ở dạng hex.

---

#### Bước 3 — Tìm hashmap (OFF_MAP_LIST, OFF_MAP_MASK, OFF_MAP_END)

FFlagList chứa một hashmap bắt đầu tại offset `+0x08`. Nhấn **Ctrl+G** lần nữa, nhập `địa_chỉ_FFlagList + 8`.

Nhìn vào 56 bytes từ đó, đọc từng slot 8 byte một:

```
+0x00  (8 bytes)  →  map_end   : pointer hợp lệ (dạng 0x00007F...)
+0x08  (8 bytes)  →  (bỏ qua)
+0x10  (8 bytes)  →  map_list  : pointer hợp lệ (dạng 0x00007F...)
+0x18  (8 bytes)  →  (bỏ qua)
+0x20  (8 bytes)  →  (bỏ qua)
+0x28  (8 bytes)  →  map_mask  : số dạng 2^n-1 (ví dụ 255, 511, 1023...)
```

**Cách nhận biết:**
- `map_end` và `map_list`: trong Memory View bytes trông như `XX XX XX XX XX 7F 00 00` (little-endian). Click vào → Cheat Engine nhảy đến vùng memory đó, nếu đọc được thì hợp lệ.
- `map_mask`: số nhỏ dạng `FF 00 00 00...` = 255, `FF 01 00 00...` = 511, `FF 03 00 00...` = 1023.

Nếu các offset này không cho ra giá trị hợp lệ, dịch chuyển từng bước 8 byte cho đến khi tìm được. Sửa trong `main.py`:

```python
OFF_MAP_END  = 0x00   # ← sửa thành offset mới
OFF_MAP_LIST = 0x10   # ← sửa thành offset mới
OFF_MAP_MASK = 0x28   # ← sửa thành offset mới
```

---

#### Bước 4 — Tìm node layout (OFF_ENTRY_FORWARD, OFF_ENTRY_STRING, OFF_ENTRY_GETSET)

1. Lấy giá trị (pointer) tại `map_list` từ bước trên
2. **Ctrl+G** → nhập địa chỉ đó — đây là bucket array, mỗi bucket 16 bytes
3. Đọc 8 bytes tại `bucket + 0x08` để lấy địa chỉ **node đầu tiên**
4. **Ctrl+G** → nhập địa chỉ node đó

Dùng **Tools → Dissect Data/Structures** để xem struct dễ hơn:
- Nhập địa chỉ node → Enter
- Cheat Engine hiển thị từng offset dạng bảng

Nhìn vào các offset trong node:

```
node + 0x08  →  forward pointer  : pointer đến node tiếp theo (0x00007F...)
                                   hoặc bằng map_end nếu là node cuối

node + 0x10  →  string struct    : chứa tên flag bên trong

node + 0x30  →  getset pointer   : pointer đến struct chứa value của flag
```

**Verify `node + 0x10` là string struct:**
- Đọc 8 bytes tại `node + 0x10 + 0x10` → phải là số nhỏ (1–50), đây là length của tên flag
- Đọc bytes tại `node + 0x10` với độ dài đó → phải ra chuỗi dạng `FFlagXXX`, `FIntXXX`...
- Nếu đọc ra rác thì offset `0x10` sai, thử `0x18`, `0x20`...

Sửa trong `main.py`:
```python
OFF_ENTRY_FORWARD = 0x08   # ← sửa nếu đổi
OFF_ENTRY_STRING  = 0x10   # ← sửa nếu đổi
OFF_ENTRY_GETSET  = 0x30   # ← sửa nếu đổi
```

---

#### Bước 5 — Tìm string struct layout (OFF_STR_SIZE, OFF_STR_CAPACITY)

**Ctrl+G** → nhập địa chỉ của string struct (tại `node + OFF_ENTRY_STRING`):

```
string_struct + 0x00  →  buffer pointer  : nếu tên flag > 15 ký tự thì đây
                                           là pointer đến char array trên heap.
                                           Nếu <= 15 ký tự thì bytes tên flag
                                           nằm thẳng ở đây (SSO — Small String)

string_struct + 0x10  →  size (length)   : số ký tự của tên flag
string_struct + 0x18  →  capacity        : dung lượng buffer đã cấp phát
```

Verify: đọc 8 bytes tại `+0x10` phải ra số khớp với độ dài tên flag.

Sửa trong `main.py`:
```python
OFF_STR_SIZE     = 0x10   # ← sửa nếu đổi
OFF_STR_CAPACITY = 0x18   # ← sửa nếu đổi
```

---

#### Bước 6 — Tìm OFF_FFLAG_VALUE_PTR

**Ctrl+G** → nhập địa chỉ tại `node + OFF_ENTRY_GETSET` (getset pointer). Đây là struct chứa value thực của flag.

Tìm offset bên trong struct này trỏ đến giá trị:
```
getset + 0xC0  →  value pointer  : pointer đến int32 (bool/int) hoặc string value
```

Verify:
1. Đọc pointer tại `getset + 0xC0`
2. **Ctrl+G** → nhập địa chỉ đó
3. Nếu là flag **bool/int**: 4 bytes phải ra `0` hoặc `1` (hoặc giá trị int bạn đã set)
4. Nếu sai → thử `+0xB8`, `+0xC8`, `+0xD0`...

Sửa trong `main.py`:
```python
OFF_FFLAG_VALUE_PTR = 0xC0   # ← sửa nếu đổi
```

---

#### Bước 7 — Push lên GitHub

Sau khi sửa xong các `OFF_*` constants trong `main.py`, push lên GitHub. Workflow tự build lại `main.exe` và `mainDEBUG.exe`.

---

### Trường hợp 2 — Tool báo "Pattern scan failed"

Nghĩa là Roblox đã đổi cách compiler generate code truy cập FFlagList — pattern byte cũ không còn match nữa. Cần tìm pattern mới và thêm vào `core/scanner.py`.

**Tool cần có:** [x64dbg](https://x64dbg.com/)

---

#### Bước 1 — Attach x64dbg vào Roblox

1. Mở Roblox trước
2. Mở x64dbg → **File** → **Attach**
3. Chọn `RobloxPlayerBeta.exe` → **Attach**
4. Nhấn **F9** để resume (Roblox bị pause khi attach)

---

#### Bước 2 — Tìm địa chỉ FFlagList

Dùng Cheat Engine để lấy địa chỉ FFlagList theo Trường hợp 1 → Bước 2.
Lần này dùng offset cũ hardcode tạm thời nếu cần — mục tiêu chỉ là lấy địa chỉ.

---

#### Bước 3 — Tìm references đến FFlagList trong x64dbg

Trong x64dbg:
1. Nhấn **Ctrl+G** → nhập địa chỉ FFlagList → Enter (nhảy đến Memory View)
2. Click chuột phải tại đó → **Find references to** → **Selected address**
3. Cửa sổ References hiện ra, liệt kê tất cả chỗ trong code truy cập địa chỉ đó

---

#### Bước 4 — Đọc bytes của instruction

Double-click vào một kết quả trong References → x64dbg nhảy đến CPU View (disassembly).

Bạn sẽ thấy instruction dạng:
```asm
lea rax, qword ptr [rip+0x7CE33D8]
lea rcx, qword ptr [rip+0x7CE33D8]
```

Nhìn vào cột **Bytes** bên cạnh (hoặc hover vào dòng đó):
```
Bytes                  Disassembly
48 8D 05 D8 33 CE 07   lea rax, [rip+0x7CE33D8]
48 89 C1               mov rcx, rax              ← bytes kế tiếp
```

- `48 8D 05` = opcode của `lea rax`
- `48 8D 0D` = opcode của `lea rcx`
- `48 8D 15` = opcode của `lea rdx`
- 4 bytes tiếp theo = disp32, **luôn thay đổi** mỗi lần Roblox update → dùng `None` (wildcard)
- Bytes sau đó (`48 89`) = phần thêm vào để tránh false positive

---

#### Bước 5 — Thêm pattern vào core/scanner.py

Mở `core/scanner.py`, tìm list `PATTERNS`, thêm pattern mới dựa trên bytes tìm được:

```python
PATTERNS = [
    # Pattern cũ — giữ lại phòng trường hợp vẫn match trên một số version
    [0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x89],

    # Pattern mới — thay 0xXX bằng bytes thực tế tìm được ở Bước 4
    [0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0xXX],
]
```

**Ví dụ cụ thể:** nếu x64dbg hiện bytes là `48 8D 05 ?? ?? ?? ?? 48 8B 43 10` thì thêm:
```python
[0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x8B],
```

Push lên GitHub → workflow tự build lại.

---

## Build

Workflow GitHub Actions tự build cả 2 file mỗi khi push lên `main`:

```
Actions → Build Windows EXE → Artifacts → main.exe / mainDEBUG.exe
```

Hoặc trigger thủ công: **Actions → Build Windows EXE → Run workflow**

---

## Requirements

- Windows 10/11 x64
- Roblox đang chạy trước khi mở tool
- `fflags.json` đặt cùng thư mục với `main.exe`