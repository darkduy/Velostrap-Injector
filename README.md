# Velostrap Injector
Roblox FFlag injector — tìm FFlagList động qua pattern scan, không cần offset cứng hay server.

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

### Trường hợp 1 — Flags không apply được (scan thành công nhưng flag fail)

Nghĩa là FFlagList struct layout đã thay đổi. Cần cập nhật `OFF_*` constants trong `main.py`.

**Cách tìm lại bằng Cheat Engine:**

**Bước 1 — Attach vào Roblox**
- Mở Cheat Engine → click icon máy tính góc trên trái
- Chọn `RobloxPlayerBeta.exe` → Open

**Bước 2 — Tìm FFlagList address**
- Chạy tool một lần với logging bật, lấy địa chỉ từ dòng:
  ```
  [ + ] FFlagList at 0xXXXXXXXXXXXX
  ```
- Trong Cheat Engine: **Memory View** → Ctrl+G → nhập địa chỉ đó

**Bước 3 — Xác định OFF_MAP_LIST và OFF_MAP_MASK**

Nhìn vào bytes tại `FFlagList + 0x08` (hashmap bắt đầu ở đây):
```
+0x00  → map_end   : phải là pointer hợp lệ (0x00007F...)
+0x10  → map_list  : phải là pointer hợp lệ (0x00007F...)
+0x28  → map_mask  : phải là dạng 2^n-1 (ví dụ 0xFF, 0x1FF, 0x3FF...)
```
Nếu các offset này sai (giá trị trông không hợp lệ), dịch chuyển từng offset 8 byte một cho đến khi thấy đúng pattern. Sửa `OFF_MAP_END`, `OFF_MAP_LIST`, `OFF_MAP_MASK` trong `main.py`.

**Bước 4 — Xác định OFF_ENTRY_FORWARD, OFF_ENTRY_STRING, OFF_ENTRY_GETSET**

Click vào địa chỉ trong `map_list` để nhảy đến một node. Dùng **Dissect Data/Structures** (Ctrl+D) để visualize:
```
node + 0x08  → forward pointer  : trỏ đến node tiếp theo (pointer hợp lệ)
node + 0x10  → string struct    : chứa tên flag
node + 0x30  → getset pointer   : trỏ đến value
```
Verify bằng cách đọc tên flag tại `node + 0x10 + 0x10` (size) và `node + 0x10` (bytes) — phải ra chuỗi dạng `FFlag...`.

**Bước 5 — Xác định OFF_FFLAG_VALUE_PTR**

Click vào getset pointer, tìm offset bên trong struct đó trỏ đến giá trị thực của flag:
```
getset + 0xC0  → value pointer  : trỏ đến int32 hoặc string value
```

**Bước 6 — Sửa main.py**
```python
OFF_FFLAG_VALUE_PTR = 0xC0   # ← sửa nếu đổi
OFF_MAP_END         = 0x00   # ← sửa nếu đổi
OFF_MAP_LIST        = 0x10   # ← sửa nếu đổi
OFF_MAP_MASK        = 0x28   # ← sửa nếu đổi
OFF_ENTRY_FORWARD   = 0x08   # ← sửa nếu đổi
OFF_ENTRY_STRING    = 0x10   # ← sửa nếu đổi
OFF_ENTRY_GETSET    = 0x30   # ← sửa nếu đổi
OFF_STR_SIZE        = 0x10   # ← sửa nếu đổi
OFF_STR_CAPACITY    = 0x18   # ← sửa nếu đổi
```

---

### Trường hợp 2 — Tool báo "Pattern scan failed"

Nghĩa là Roblox đã đổi instruction truy cập FFlagList. Cần thêm pattern mới vào `core/scanner.py`.

**Cách tìm pattern mới bằng x64dbg:**

**Bước 1** — Attach x64dbg vào `RobloxPlayerBeta.exe`

**Bước 2** — Tìm FFlagList bằng cách search string `"FFlagList"` trong memory hoặc dùng Cheat Engine để scan pointer

**Bước 3** — Trong x64dbg: References → Find references to address → nhập địa chỉ FFlagList

**Bước 4** — Tìm instruction dạng:
```asm
lea rax, [rip + 0x...]    ; 48 8D 05 ?? ?? ?? ??
lea rcx, [rip + 0x...]    ; 48 8D 0D ?? ?? ?? ??
```

**Bước 5** — Copy byte pattern và thêm vào `PATTERNS` trong `core/scanner.py`:
```python
PATTERNS = [
    [0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x89],  # pattern cũ
    [0x48, 0x8D, 0x05, None, None, None, None, 0xXX, 0xXX],  # ← thêm pattern mới
]
```

---

## Build

Workflow GitHub Actions tự build `.exe` mỗi khi push lên `main`:

```
Actions → Build Windows EXE → Artifacts → main.exe
```

Hoặc trigger thủ công: **Actions → Build Windows EXE → Run workflow**

---

## Requirements

- Windows 10/11 x64
- Roblox đang chạy trước khi mở tool
- `fflags.json` đặt cùng thư mục với `main.exe`