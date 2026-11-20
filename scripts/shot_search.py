"""截图取证：「在目录中搜索」的结果列表（双击跳转 / 右键替换）。

用临时 HOME 与临时数据目录启动真实应用（X11 后端），打开搜索对话框并出结果后截图。
输出 docs/screenshots/07-search-results.png。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(ROOT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)
os.environ["GDK_BACKEND"] = "x11"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="shot-search-"))
HOME = TMP / "home"
DATA = TMP / "data"
DOCS = TMP / "docs"
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

(DOCS / "会议").mkdir(parents=True)
(DATA).mkdir(parents=True)
(HOME).mkdir(parents=True)

(DOCS / "周报.md").write_text(
    "# 第 45 周\n\n## 本周进展\n\n- 完成目录搜索的交互改造\n- 修复替换后标签未刷新的问题\n\n"
    "## 下周计划\n\n- 继续完善目录搜索\n",
    encoding="utf-8",
)
(DOCS / "会议" / "纪要.md").write_text(
    "# 11 月 5 日 例会\n\n- 目录搜索要支持跨行\n- 目录搜索的结果行改为双击打开\n",
    encoding="utf-8",
)
(DOCS / "随手记.txt").write_text("目录搜索\n", encoding="utf-8")

os.environ["XDG_DATA_HOME"] = str(DATA)
os.environ["HOME"] = str(HOME)

from scratchpad.application import ScratchpadApp  # noqa: E402

app = ScratchpadApp()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)


def find_window_id() -> str | None:
    out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True).stdout
    best = None
    for line in out.splitlines():
        if "gscratchpad" in line or "Gscratchpad" in line:
            parts = line.split()
            for token in parts:
                if token.startswith("0x"):
                    best = token
    return best


def shot(name: str) -> None:
    win = find_window_id()
    target = OUT / name
    if win is None:
        print(f"[shot] 找不到窗口，跳过 {name}", flush=True)
        return
    subprocess.run(["import", "-window", win, str(target)], check=False)
    print(f"[shot] {target} win={win}", flush=True)


def step1() -> bool:
    window = app.window
    window.new_tab("txt")
    window.set_default_size(1100, 760)
    window.present()
    window.open_folder_search()
    GLib.timeout_add(800, step2)
    return False


def step2() -> bool:
    dialog = app.window._folder_dialog
    dialog._set_folder(DOCS, remember=False)
    dialog.entry.set_text("目录搜索")
    dialog._run_now()
    GLib.timeout_add(1200, lambda: (shot("07-search-results.png"), False)[1])
    GLib.timeout_add(2400, app.quit)
    return False


if __name__ == "__main__":
    GLib.timeout_add(1000, step1)
    GLib.timeout_add(15000, app.quit)
    app.run(["shot-search"])
