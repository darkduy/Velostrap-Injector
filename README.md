# Velostrap Injector
Roblox FFlag injector — tìm FFlagList động qua pattern scan, không cần offset cứng hay server.

---

## Tải file ở đây


</body>
</html>

| FILE          | DOWNLOAD                                |
| ------------- | --------------------------------------- |
| main.exe      | [click here](https://github.com/darkduy/Velostrap-Injector/releases/latest/download/main.exe)  |
| mainDEBUG.exe | [click here](https://github.com/darkduy/Velostrap-Injector/releases/latest/download/mainDEBUG.exe) |


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

Nghĩa là FFlagList struct layout đã thay đổi. Cần tìm lại `OFF_*` constants trong `main.py` bằng Cheat Engine.

**Tool cần có:** [Cheat Engine](https://www.cheatengine.org/downloads.php)

---

#### Bước 1 — Attach Cheat Engine vào Roblox

1. Mở Roblox trước, vào bất kỳ game nào
2. Mở Cheat Engine
3. Click icon hình máy tính ở góc trên trái
4. Tìm `RobloxPlayerBeta.exe` trong danh sách → click **Open**

---

#### Bước 2 — Lấy địa chỉ FFlagList

Chạy tool một lần, nhìn vào output:
```
[ + ] FFlagList at 0x1F2A3B4C5D6E
```
Copy địa chỉ này (phần sau `0x`).

Trong Cheat Engine:
1. Vào menu **Memory View** (hoặc Ctrl+B)
2. Nhấn **Ctrl+G**
3. Dán địa chỉ vào → Enter

Bạn sẽ thấy vùng memory của FFlagList ở dạng hex.

---

#### Bước 3 — Tìm hashmap (OFF_MAP_LIST, OFF_MAP_MASK, OFF_MAP_END)

FFlagList chứa một hashmap bắt đầu tại offset `+0x08`. Nhìn vào Memory View tại địa chỉ `FFlagList + 0x08`:

```
FFlagList + 0x08 + 0x00  →  map_end   (8 bytes)
FFlagList + 0x08 + 0x10  →  map_list  (8 bytes)
FFlagList + 0x08 + 0x28  →  map_mask  (8 bytes)
```

**Cách nhận biết từng giá trị:**

- **map_end** và **map_list**: là pointer, có dạng `00 00 7F XX XX XX XX XX` (little-endian). Click vào giá trị đó → Cheat Engine sẽ nhảy đến vùng memory tương ứng, nếu đọc được thì pointer hợp lệ.
- **map_mask**: là số nguyên dạng `2^n - 1`, ví dụ:
  - `FF 00 00 00 00 00 00 00` = `0xFF` = 255
  - `FF 01 00 00 00 00 00 00` = `0x1FF` = 511
  - `FF 03 00 00 00 00 00 00` = `0x3FF` = 1023

Nếu các offset `0x00`, `0x10`, `0x28` không cho ra giá trị hợp lệ, dịch chuyển từng bước 8 byte cho đến khi tìm được. Sửa lại trong `main.py`:

```python
OFF_MAP_END  = 0x00   # ← sửa thành offset mới của map_end
OFF_MAP_LIST = 0x10   # ← sửa thành offset mới của map_list
OFF_MAP_MASK = 0x28   # ← sửa thành offset mới của map_mask
```

---

#### Bước 4 — Tìm node layout (OFF_ENTRY_FORWARD, OFF_ENTRY_STRING, OFF_ENTRY_GETSET)

1. Lấy giá trị của `map_list` (là một địa chỉ pointer)
2. Trong Memory View: **Ctrl+G** → nhập địa chỉ đó
3. Đây là bucket array, mỗi bucket có 16 bytes. Đọc 8 bytes tại `bucket + 0x08` để lấy địa chỉ **node đầu tiên**
4. **Ctrl+G** → nhập địa chỉ node đó

Trong Cheat Engine, dùng **Dissect Data/Structures** để dễ nhìn hơn:
- Menu **Tools** → **Dissect Data/Structures**
- Nhập địa chỉ node → Enter
- Cheat Engine sẽ hiển thị từng offset dạng bảng

Nhìn vào các offset trong node:

```
node + 0x08  →  forward pointer   : pointer trỏ đến node tiếp theo
                                    có dạng địa chỉ hợp lệ (00 00 7F...)
                                    hoặc bằng map_end nếu là node cuối

node + 0x10  →  string struct     : chứa tên flag, nhìn vào offset này
                                    sẽ thấy thêm các field bên trong

node + 0x30  →  getset pointer    : pointer trỏ đến struct chứa value
```

**Cách verify node + 0x10 là string struct:**

Click vào địa chỉ tại `node + 0x10 + 0x10` (8 bytes) → đây là **size** của tên flag, phải là số nhỏ (1-50).
Đọc bytes tại `node + 0x10` với độ dài bằng size đó → phải ra chuỗi dạng `FFlagXXX`, `FIntXXX`...

Nếu đọc ra rác thì offset `0x10` sai, thử `0x18`, `0x20`...

Sửa trong `main.py`:
```python
OFF_ENTRY_FORWARD = 0x08   # ← sửa nếu đổi
OFF_ENTRY_STRING  = 0x10   # ← sửa nếu đổi
OFF_ENTRY_GETSET  = 0x30   # ← sửa nếu đổi
```

---

#### Bước 5 — Tìm string struct layout (OFF_STR_SIZE, OFF_STR_CAPACITY)

Vào địa chỉ của string struct (tại `node + OFF_ENTRY_STRING`):

```
string_struct + 0x00  →  buffer pointer  : nếu tên flag > 15 ký tự,
                                           đây là pointer đến char array
                                           nếu <= 15 ký tự thì bytes nằm
                                           thẳng ở đây (SSO)

string_struct + 0x10  →  size (length)   : số ký tự của tên flag
string_struct + 0x18  →  capacity        : dung lượng buffer đã cấp phát
```

Verify: đọc 8 bytes tại `+0x10` phải ra số khớp với độ dài tên flag bạn đang nhìn.

Sửa trong `main.py`:
```python
OFF_STR_SIZE     = 0x10   # ← sửa nếu đổi
OFF_STR_CAPACITY = 0x18   # ← sửa nếu đổi
```

---

#### Bước 6 — Tìm OFF_FFLAG_VALUE_PTR

Click vào địa chỉ tại `node + OFF_ENTRY_GETSET` (getset pointer). Đây là struct chứa value thực của flag.

Trong struct này tìm offset chứa pointer trỏ đến giá trị:
- Nếu là **int/bool**: pointer trỏ đến 4 bytes chứa số nguyên
- Nếu là **string**: pointer trỏ đến string struct tương tự bên trên

Thường nằm ở `+0xC0`. Verify bằng cách:
1. Đọc pointer tại `getset + 0xC0`
2. Click vào địa chỉ đó
3. Nếu là flag int/bool → 4 bytes phải ra giá trị `0` hoặc `1`
4. Nếu không đúng → thử `+0xB8`, `+0xC8`, `+0xD0`...

Sửa trong `main.py`:
```python
OFF_FFLAG_VALUE_PTR = 0xC0   # ← sửa nếu đổi
```

---

### Trường hợp 2 — Tool báo "Pattern scan failed"

Nghĩa là Roblox đã đổi cách compiler generate code truy cập FFlagList. Cần thêm pattern mới vào `core/scanner.py`.

**Tool cần có:** [x64dbg](https://x64dbg.com/)

---

#### Bước 1 — Attach x64dbg vào Roblox

1. Mở Roblox trước
2. Mở x64dbg → **File** → **Attach**
3. Chọn `RobloxPlayerBeta.exe` → **Attach**
4. Nhấn **F9** để resume (Roblox bị pause khi attach)

---

#### Bước 2 — Tìm địa chỉ FFlagList

Dùng Cheat Engine để lấy địa chỉ FFlagList (xem Trường hợp 1 → Bước 2).

---

#### Bước 3 — Tìm references đến FFlagList

Trong x64dbg:
1. Vào tab **Memory Map** (Alt+M)
2. Tìm vùng memory của `RobloxPlayerBeta.exe` (cột **Page** hoặc **Info**)
3. Hoặc dùng **Search** → **Find references to address** → nhập địa chỉ FFlagList

x64dbg sẽ liệt kê tất cả chỗ trong code có truy cập đến địa chỉ đó.

---

#### Bước 4 — Đọc instruction tại kết quả tìm được

Double-click vào một kết quả, x64dbg nhảy đến vị trí trong code. Bạn sẽ thấy assembly dạng:

```asm
; Ví dụ instruction hợp lệ:
lea rax, qword ptr [rip+0x7CE33D8]    ; trỏ đến FFlagList
mov [rbx+0x10], rax

; Hoặc:
lea rcx, qword ptr [rip+0x7CE33D8]
mov rax, [rcx]
```

**Đọc bytes tương ứng** (nhìn cột bên trái trong x64dbg):
```
48 8D 05 D8 33 CE 07    ← lea rax, [rip+...]
48 89 43 10             ← mov [rbx+0x10], rax
```

- `48 8D 05` = opcode của `lea rax, [rip+disp32]`
- `48 8D 0D` = opcode của `lea rcx, [rip+disp32]`
- `48 8D 15` = opcode của `lea rdx, [rip+disp32]`
- 4 bytes tiếp theo (`D8 33 CE 07`) = disp32, là phần wildcard (None)
- Bytes sau đó là phần cần thêm vào pattern để tránh false positive

---

#### Bước 5 — Thêm pattern vào core/scanner.py

Mở `core/scanner.py`, tìm list `PATTERNS` và thêm pattern mới:

```python
PATTERNS = [
    # Pattern cũ (có thể giữ lại hoặc xóa nếu không còn match)
    [0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x89],

    # Pattern mới — thay XX bằng bytes tìm được ở Bước 4
    [0x48, 0x8D, 0x05, None, None, None, None, 0xXX, 0xXX],
]
```

**Ví dụ cụ thể:** nếu x64dbg hiện:
```
48 8D 05 ?? ?? ?? ?? 48 8B 43 10
```
thì thêm:
```python
[0x48, 0x8D, 0x05, None, None, None, None, 0x48, 0x8B],
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