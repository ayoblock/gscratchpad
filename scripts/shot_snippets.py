"""截图取证：片段与自动补全设置界面。

用临时 HOME 与临时数据目录启动真实应用（X11 后端），预置两条片段后打开设置对话框截图。
输出 docs/screenshots/08-snippets.png。
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

TMP = Path(tempfile.mkdtemp(prefix="shot-snippets-"))
HOME = TMP / "home"
DATA = TMP / "data"
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True)
HOME.mkdir(parents=True)

os.environ["XDG_DATA_HOME"] = str(DATA)
os.environ["HOME"] = str(HOME)

from scratchpad import snippets  # noqa: E402
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
    window.new_tab("md")
    window.set_default_size(1000, 720)
    window.present()
    window.snippets = [
        snippets.Snippet("HTML 注释", "<!-- {{cursor}} -->", "<Control><Alt>1"),
        snippets.Snippet("会议纪要骨架", "# {{date}} 例会\n\n## 结论\n\n- {{cursor}}\n", ""),
        snippets.Snippet("日期戳", "{{date}}", "<Control><Alt>2"),
    ]
    window.save_snippets()
    window.manage_snippets()
    GLib.timeout_add(1200, lambda: (shot("08-snippets.png"), False)[1])
    GLib.timeout_add(2400, app.quit)
    return False


if __name__ == "__main__":
    GLib.timeout_add(1000, step1)
    GLib.timeout_add(15000, app.quit)
    app.run(["shot-snippets"])
