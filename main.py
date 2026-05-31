"""
main.py — Entry point.
Logic chính nằm trong core/gui_console.py.
OFF_* constants để cập nhật sau Roblox update cũng nằm trong core/gui_console.py.
"""

import logging
import os
import sys

from core import AttachTimeoutError
from core.gui_console import FlagInjector

BANNER = r"""
██╗   ██╗███████╗██╗      ██████╗ ██████╗ ██╗███╗   ██╗
██║   ██║██╔════╝██║     ██╔═══██╗██╔══██╗██║████╗  ██║
██║   ██║█████╗  ██║     ██║   ██║██████╔╝██║██╔██╗ ██║
╚██╗ ██╔╝██╔══╝  ██║     ██║   ██║██╔══██╗██║██║╚██╗██║
 ╚████╔╝ ███████╗███████╗╚██████╔╝██║  ██║██║██║ ╚████║
  ╚═══╝  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
"""


def get_base_path() -> str:
    if getattr(sys, "frozen", False) or hasattr(sys, "real_path"):
        return os.path.dirname(os.path.realpath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    exe_name = os.path.splitext(os.path.basename(sys.executable))[0].upper()
    is_debug = exe_name.endswith("DEBUG")

    logging.basicConfig(
        level=logging.DEBUG if is_debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s" if is_debug
               else "%(levelname)s %(message)s",
    )

    if is_debug:
        print("[DEBUG MODE — logging chi tiết được bật]")

    print(BANNER)
    print("[ + ] Velorin FFlag Injector — discord.gg/F8kkN62Apk\n")

    injector = None

    try:
        injector  = FlagInjector()
        base_dir  = get_base_path()
        json_path = os.path.join(base_dir, "fflags.json")

        print(f"[ + ] Looking for fflags.json in: {base_dir}")

        if not os.path.exists(json_path):
            print("[ - ] fflags.json not found.")
            print(f"      Place it in: {base_dir}")
        else:
            injector.apply_json(json_path)

    except AttachTimeoutError as exc:
        print(f"\n[ - ] Attach timed out: {exc}")
    except RuntimeError as exc:
        print(f"\n[ - ] {exc}")
    except Exception as exc:
        print(f"\n[ - ] Unexpected error: {exc}")
        logging.getLogger(__name__).exception("Unhandled exception in main")
    finally:
        if injector is not None:
            injector.cleanup()

    print("\n[ + ] Done. Press Enter to exit …")
    input()


if __name__ == "__main__":
    main()