"""Launch the native desktop application: python main_ui.py."""
import os
import sys


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("准星助手当前仅支持 Windows 10/11。")
    from aim_assist.ui import main
    sys.exit(main())
