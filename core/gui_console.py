"""
core/gui_console.py — Console UI layer cho FFlag Injector.
Xử lý toàn bộ input/output, banner, progress display.
Business logic nằm trong FlagInjector (main.py).
"""

import logging
import os
import sys

from core import AttachTimeoutError

log = logging.getLogger(__name__)

BANNER = r"""
██╗   ██╗███████╗██╗      ██████╗ ██████╗ ██╗███╗   ██╗
██║   ██║██╔════╝██║     ██╔═══██╗██╔══██╗██║████╗  ██║
██║   ██║█████╗  ██║     ██║   ██║██████╔╝██║██╔██╗ ██║
╚██╗ ██╔╝██╔══╝  ██║     ██║   ██║██╔══██╗██║██║╚██╗██║
 ╚████╔╝ ███████╗███████╗╚██████╔╝██║  ██║██║██║ ╚████║
  ╚═══╝  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
"""

SUBTITLE = "[ + ] Velorin FFlag Injector — discord.gg/F8kkN62Apk"


def setup_logging(is_debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if is_debug else logging.WARNING,
        format=(
            "%(asctime)s %(levelname)s %(name)s — %(message)s"
            if is_debug else
            "%(levelname)s %(message)s"
        ),
    )


def is_debug_build() -> bool:
    exe_name = os.path.splitext(os.path.basename(sys.executable))[0].upper()
    return exe_name.endswith("DEBUG")


def print_banner() -> None:
    print(BANNER)
    print(SUBTITLE + "\n")


def print_attach_status(handle: int, base: int, size: int) -> None:
    print(f"[ + ] Attached  handle=0x{handle:X}")
    print(f"[ + ] Module    base=0x{base:X}  size=0x{size:X}")


def print_scan_status(offset: int) -> None:
    print(f"[ + ] FFlagList offset: 0x{offset:X}")


def print_apply_results(results: list[tuple[bool, str]]) -> None:
    """
    Nhận list (ok, message) từ FlagInjector.apply_all() và in ra console.
    """
    success = 0
    for ok, msg in results:
        print(msg)
        success += ok
    total = len(results)
    print(f"\n[ + ] Applied {success}/{total} flags.")


def prompt_json_path(base_dir: str) -> str | None:
    """
    Tìm fflags.json trong base_dir.
    Trả về path nếu tồn tại, None nếu không.
    """
    json_path = os.path.join(base_dir, "fflags.json")
    print(f"[ + ] Looking for fflags.json in: {base_dir}")
    if not os.path.exists(json_path):
        print("[ - ] fflags.json not found.")
        print(f"      Place it in: {base_dir}")
        return None
    return json_path


def run_console(injector_factory, get_base_path) -> None:
    """
    Main console loop.

    Parameters
    ----------
    injector_factory : callable
        Hàm không tham số, trả về FlagInjector đã attach và scan xong.
        Ví dụ: lambda: FlagInjector()
    get_base_path : callable
        Hàm không tham số, trả về str đường dẫn thư mục chứa fflags.json.
    """
    is_debug = is_debug_build()
    setup_logging(is_debug)

    if is_debug:
        print("[DEBUG MODE — logging chi tiết được bật]")

    print_banner()

    injector = None

    try:
        injector = injector_factory()

        base_dir  = get_base_path()
        json_path = prompt_json_path(base_dir)

        if json_path is not None:
            results = injector.apply_json_results(json_path)
            print_apply_results(results)

    except AttachTimeoutError as exc:
        print(f"\n[ - ] Attach timed out: {exc}")
    except RuntimeError as exc:
        print(f"\n[ - ] {exc}")
    except Exception as exc:
        print(f"\n[ - ] Unexpected error: {exc}")
        log.exception("Unhandled exception")
    finally:
        if injector is not None:
            injector.cleanup()

    print("\n[ + ] Done. Press Enter to exit …")
    input()