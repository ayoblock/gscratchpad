#!/usr/bin/env python3
"""开发环境启动器：注入本地 typelib 与源码路径。"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
VENDOR = PROJECT_ROOT / "vendor"


def _configure() -> None:
    for path in (str(SRC), str(VENDOR)):
        if path not in sys.path:
            sys.path.insert(0, path)

    gir_dirs = [str(p) for p in sorted(VENDOR.glob("gir/*")) if p.is_dir()]
    system_gir = "/usr/lib/x86_64-linux-gnu/girepository-1.0"
    existing = os.environ.get("GI_TYPELIB_PATH", "")
    parts = [d for d in gir_dirs if d] + [system_gir]
    if existing:
        parts.append(existing)
    os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(parts)

    # 测试/调试时可指定独立数据目录，避免污染真实数据
    # export SCRATCHPAD_DATA_DIR=/tmp/sp-test   （数据将写入 <dir>/gscratchpad）
    if os.environ.get("SCRATCHPAD_DATA_DIR"):
        os.environ["XDG_DATA_HOME"] = os.environ["SCRATCHPAD_DATA_DIR"]


if __name__ == "__main__":
    _configure()
    from scratchpad.application import main

    sys.exit(main())
