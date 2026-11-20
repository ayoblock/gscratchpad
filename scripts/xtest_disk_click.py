"""用真实鼠标事件（XTEST）验证磁盘页的文件行能被点开、右键能出菜单。

为什么需要这个脚本：`emit("clicked")` 只能证明回调写对了，证明不了「鼠标点得动」。
本项目踩过一次 Gtk.ListBox 在 CAPTURE 阶段 claim 掉点击、导致嵌套行收不到鼠标
事件的问题（键盘/程序化激活正常，只有鼠标失效），所以保留这个真事件测试。

依赖 python-xlib（Ubuntu: `sudo apt install python3-xlib`）。没有就跳过。

用法：
    python3 scripts/xtest_disk_click.py
需要 X11 会话（Wayland 下可用 GDK_BACKEND=x11 走 XWayland；脚本已自动设置）。

注意 GTK4 的 CSD 阴影：GdkSurface 比 GtkWindow 大一圈，warp 指针时必须
加上 (surface - widget) / 2 的偏移，否则会点到上一行。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(ROOT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)
os.environ.setdefault("GDK_BACKEND", "x11")

try:
    from Xlib import X, display
    from Xlib.ext import xtest
except ImportError:
    print("SKIP: 未安装 python-xlib（sudo apt install python3-xlib）")
    sys.exit(0)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")
gi.require_version("GdkX11", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GdkX11, Gio, GLib, Graphene, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.sidebar import DiskDirRow, DiskFileRow  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="xtest-disk-"))
HOME = TMP / "home"
DATA = TMP / "data"

app = ScratchpadApp()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
app._register_app_actions()
out: dict[str, object] = {}
dpy = display.Display()


def rows(container) -> list:
    node = container.get_first_child()
    found = []
    while node is not None:
        found.append(node)
        node = node.get_next_sibling()
    return found


def click_widget(widget, window, button: int = 1) -> None:
    """把指针 warp 到控件中心并点击（坐标换算见模块 docstring）。"""
    ok, rect = widget.compute_bounds(window)
    ok2, point = widget.compute_point(window, Graphene.Point().init(0.0, 0.0))
    cx = int(point.x + rect.get_width() / 2)
    cy = int(point.y + rect.get_height() / 2)
    surface = window.get_surface()
    dx = (surface.get_width() - window.get_width()) // 2
    dy = (surface.get_height() - window.get_height()) // 2
    win = dpy.create_resource_object("window", GdkX11.X11Surface.get_xid(surface))
    win.warp_pointer(cx + dx, cy + dy)
    dpy.sync()
    time.sleep(0.3)
    xtest.fake_input(dpy, X.ButtonPress, button)
    dpy.sync()
    time.sleep(0.1)
    xtest.fake_input(dpy, X.ButtonRelease, button)
    dpy.sync()


def step1() -> bool:
    window = app.window
    if window is None:
        return True
    sb = window.sidebar
    window.set_default_size(1100, 760)
    window.sidebar_button.set_active(True)
    sb.show_view("disk")
    sb._ensure_disk_root()
    dir_row = next(r for r in rows(sb.disk_list) if isinstance(r, DiskDirRow))
    dir_row.set_expanded(True)
    file_row = next(r for r in rows(dir_row.children_list) if isinstance(r, DiskFileRow))
    out["file"] = file_row.path.name
    window.present()
    GLib.timeout_add(900, lambda: do_click(window, sb, file_row))
    return False


def do_click(window, sb, file_row) -> bool:
    out["pages_before"] = window.tabview.get_n_pages()
    click_widget(file_row, window, 1)
    GLib.timeout_add(1000, lambda: after_click(window, sb, file_row))
    return False


def after_click(window, sb, file_row) -> bool:
    page = window._current_page()
    out["pages_after"] = window.tabview.get_n_pages()
    out["click_opened"] = out["pages_after"] > out["pages_before"]
    out["content_ok"] = bool(page and "body" in page.snapshot_text())
    pages = window.tabview.get_n_pages()
    click_widget(file_row, window, 3)
    GLib.timeout_add(800, lambda: after_right(window, sb, pages))
    return False


def after_right(window, sb, pages) -> bool:
    popover = getattr(sb, "_active_path_menu", None)
    out["right_menu_visible"] = bool(popover and popover.get_visible())
    out["right_did_not_open"] = window.tabview.get_n_pages() == pages
    labels: list[str] = []
    if popover is not None:
        child = popover.get_child().get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                labels.append(child.get_label())
            child = child.get_next_sibling()
    out["menu_labels"] = labels
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = (
        out.get("click_opened") is True
        and out.get("content_ok") is True
        and out.get("right_menu_visible") is True
        and out.get("right_did_not_open") is True
        and "打开" in labels
    )
    print("XTEST DISK CLICK OK" if ok else "XTEST DISK CLICK FAILED")
    app.quit()
    return False


if __name__ == "__main__":
    (HOME / "dd").mkdir(parents=True)
    DATA.mkdir(parents=True)
    (HOME / "dd" / "clickme.md").write_text("# Click\n\nbody\n", encoding="utf-8")
    os.environ["XDG_DATA_HOME"] = str(DATA)
    os.environ["HOME"] = str(HOME)
    GLib.timeout_add(1200, step1)
    GLib.timeout_add(25000, app.quit)
    app.run(["xtest-disk"])
