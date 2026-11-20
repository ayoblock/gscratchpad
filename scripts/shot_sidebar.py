"""截图取证：悬浮侧栏 / 磁盘视图 / Markdown 大纲。

用临时 HOME 与临时数据目录启动真实应用（X11 后端），截图后退出。
输出 docs/screenshots/*.png。
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

TMP = Path(tempfile.mkdtemp(prefix="shot-"))
HOME = TMP / "home"
DATA = TMP / "data"
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

(HOME / "notes" / "sub").mkdir(parents=True)
(DATA).mkdir(parents=True)
(HOME / "notes" / "大纲示例.md").write_text("# 示例\n", encoding="utf-8")
(HOME / "notes" / "sub" / "b.txt").write_text("hello\n", encoding="utf-8")

os.environ["XDG_DATA_HOME"] = str(DATA)
os.environ["HOME"] = str(HOME)

from scratchpad.application import ScratchpadApp  # noqa: E402

MD = """# 悬浮侧栏与大纲

这是一篇用来演示 **Markdown 大纲** 的笔记。

## 一、悬浮式侧边栏

- 圆角、阴影、半透明
- 覆盖在正文之上

### 1.1 不再挤压正文

开关侧栏时编辑区宽度不变。

## 二、Markdown 目录

点击大纲条目即可跳转。

### 2.1 源码模式

光标会移动到对应行。

### 2.2 预览模式

预览会滚动到对应标题。

## 三、代码块里的 # 不算标题

```bash
# 这是注释
echo hi
```

## 四、结尾

完。
"""


def find_window_id() -> str | None:
    out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "Gscratchpad" in line and line.strip().startswith("0x"):
            return line.split()[0]
    return None


def shot(name: str) -> None:
    win = find_window_id()
    target = str(OUT / name)
    if win is None:
        print(f"[shot] 找不到窗口，跳过 {name}", flush=True)
        return
    subprocess.run(["import", "-window", win, target], check=False)
    print(f"[shot] {target} win={win}", flush=True)


app = ScratchpadApp()
# 用户可能正开着 gscratchpad：单实例会让本次进程直接退出
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)


def step1() -> bool:
    w = app.window
    if w is None:
        return True
    page = w._current_page()
    if page is not None:
        page.set_format("md")
        page.buffer.set_text(MD, -1)
        page.title = "大纲示例"
        page.tab.set_title("大纲示例")
    w.set_default_size(1120, 780)
    GLib.timeout_add(1400, lambda: (shot("01-floating-notes.png"), False)[1])
    GLib.timeout_add(1800, step2)
    return False


def step2() -> bool:
    w = app.window
    w.sidebar.show_view("outline")
    w._refresh_outline_now()
    GLib.timeout_add(900, lambda: (shot("02-outline.png"), False)[1])
    GLib.timeout_add(1200, step3)
    return False


def step3() -> bool:
    w = app.window
    w.sidebar.show_view("disk")
    GLib.timeout_add(900, lambda: (shot("03-disk.png"), False)[1])
    GLib.timeout_add(1200, step4)
    return False


def step4() -> bool:
    w = app.window
    w.sidebar_button.set_active(False)
    print(f"[debug] reveal after hide = {w.sidebar_revealer.get_reveal_child()}", flush=True)
    GLib.timeout_add(700, lambda: (shot("04-sidebar-hidden.png"), False)[1])
    GLib.timeout_add(1000, step5)
    return False


def step5() -> bool:
    w = app.window
    w.sidebar_button.set_active(True)
    w.sidebar.show_view("notes")
    w.command_menu.popup_with_search()
    w.command_menu.search.set_text("大纲")
    # 命令菜单是独立 X 窗口，截主窗口拍不到它；弹出状态由 GUI 测试 + XTEST 验证
    GLib.timeout_add(900, lambda: (print("[debug] menu visible =", w.command_menu.get_visible(), flush=True), False)[1])
    GLib.timeout_add(1100, step6)
    return False


def step6() -> bool:
    w = app.window
    w.command_menu.popdown()
    w.command_menu.search.set_text("")
    w.sidebar.search_entry.set_text("")
    GLib.timeout_add(700, lambda: (shot("06-sidebar-sort.png"), False)[1])
    GLib.timeout_add(1000, step7)
    return False


def step7() -> bool:
    app.quit()
    return False


GLib.idle_add(step1)
GLib.timeout_add(15000, app.quit)
app.run(["shot"])
