"""用真实鼠标事件（XTEST）验证「在目录中搜索」的结果行：

1. 单击只选中，不打开文件、不关闭对话框
2. 双击打开文件并定位到关键词行，且关键词被选中
3. 右键弹出菜单，菜单里有「替换此内容…」

为什么需要真事件：`emit()` / 直接调回调只能证明回调写对了，证明不了鼠标点得动。
本项目踩过一次 Gtk.ListBox 在 CAPTURE 阶段 claim 掉点击、嵌套行收不到鼠标事件
的坑（键盘与程序化调用全绿，只有真鼠标失效），所以同一类交互都保留真事件测试。

依赖 python-xlib（Ubuntu: `sudo apt install python3-xlib`）。没有就跳过。
需要 X11 会话（Wayland 下走 XWayland，脚本已设 GDK_BACKEND=x11）。
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

from gi.repository import GdkX11, Gio, GLib, Graphene, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.fssearch_ui import _HitRow  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="xtest-search-"))
DATA = TMP / "data"
DOCS = TMP / "docs"
KEY = "关键内容"

app = ScratchpadApp()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
out: dict[str, object] = {}
dpy = display.Display()


def rows(container) -> list:
    node = container.get_first_child()
    found = []
    while node is not None:
        found.append(node)
        node = node.get_next_sibling()
    return found


def click_widget(widget, button: int = 1, presses: int = 1) -> None:
    """把指针 warp 到控件中心并点击（presses=2 时快速按两下）。"""
    native = widget.get_native()
    _ok, point = widget.compute_point(native, Graphene.Point().init(0.0, 0.0))
    surface = native.get_surface()
    dx = 0
    dy = 0
    if isinstance(native, Gtk.Window):
        # GTK4 的 CSD 阴影：GdkSurface 比 GtkWindow 大一圈，不加偏移会点到别处
        dx = (surface.get_width() - native.get_width()) // 2
        dy = (surface.get_height() - native.get_height()) // 2
    cx = int(point.x + widget.get_width() / 2) + dx
    cy = int(point.y + widget.get_height() / 2) + dy
    win = dpy.create_resource_object("window", GdkX11.X11Surface.get_xid(surface))
    win.warp_pointer(cx, cy)
    dpy.sync()
    time.sleep(0.35)
    for _ in range(presses):
        xtest.fake_input(dpy, X.ButtonPress, button)
        dpy.sync()
        time.sleep(0.05)
        xtest.fake_input(dpy, X.ButtonRelease, button)
        dpy.sync()
        time.sleep(0.05)


def step1() -> bool:
    window = app.window
    if window is None:
        return True
    window.new_tab("txt")
    window.set_default_size(1100, 760)
    window.present()
    window.open_folder_search()
    GLib.timeout_add(700, lambda: setup_dialog(window))
    return False


def setup_dialog(window) -> bool:
    dialog = window._folder_dialog
    out["dialog_type"] = type(dialog).__name__
    dialog._set_folder(DOCS, remember=False)
    dialog.entry.set_text(KEY)
    dialog._run_now()
    GLib.timeout_add(900, lambda: click_single(window, dialog))
    return False


def target_row(dialog) -> _HitRow | None:
    for child in rows(dialog.results):
        if isinstance(child, _HitRow) and child.line_no == 2:
            return child
    return None


def click_single(window, dialog) -> bool:
    row = target_row(dialog)
    out["row_found"] = row is not None
    out["pages_before"] = window.tabview.get_n_pages()
    out["dialog_mapped_before"] = dialog.get_mapped()
    click_widget(row, 1, presses=1)
    GLib.timeout_add(700, lambda: after_single(window, dialog, row))
    return False


def after_single(window, dialog, row) -> bool:
    out["single_selected"] = dialog._current_row is row
    out["single_no_open"] = window.tabview.get_n_pages() == out["pages_before"]
    out["single_dialog_still_open"] = dialog.get_mapped()
    click_widget(row, 1, presses=2)  # 真双击
    GLib.timeout_add(1200, lambda: after_double(window, dialog))
    return False


def after_double(window, dialog) -> bool:
    page = window._current_page()
    out["double_pages"] = window.tabview.get_n_pages()
    out["double_opened"] = out["double_pages"] > out["pages_before"]
    buf = page.buffer if page else None
    if buf is not None:
        it = buf.get_iter_at_mark(buf.get_insert())
        out["double_line"] = it.get_line() + 1
        bounds = buf.get_selection_bounds()
        out["double_selected"] = (
            buf.get_text(bounds[0], bounds[1], False) if bounds and bounds[0] is not None else ""
        )
    out["dialog_closed_after_double"] = dialog.get_root() is None
    # 重新搜一次，测右键菜单
    window.open_folder_search()
    GLib.timeout_add(700, lambda: click_right(window))
    return False


def click_right(window) -> bool:
    dialog = window._folder_dialog
    dialog._set_folder(DOCS, remember=False)
    dialog.entry.set_text(KEY)
    dialog._run_now()
    GLib.timeout_add(900, lambda: do_right(window, dialog))
    return False


def do_right(window, dialog) -> bool:
    row = target_row(dialog)
    out["right_row_found"] = row is not None
    out["right_pages_before"] = window.tabview.get_n_pages()
    click_widget(row, 3, presses=1)
    GLib.timeout_add(700, lambda: after_right(window, row))
    return False


def after_right(window, row) -> bool:
    popover = getattr(row, "_menu", None)
    out["right_menu_visible"] = bool(popover and popover.get_visible())
    out["right_did_not_open"] = window.tabview.get_n_pages() == out["right_pages_before"]
    labels: list[str] = []
    if popover is not None and popover.get_child() is not None:
        for child in rows(popover.get_child()):
            if isinstance(child, Gtk.Button):
                labels.append(child.get_label())
    out["right_menu_labels"] = labels
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = (
        out.get("row_found") is True
        and out.get("single_selected") is True
        and out.get("single_no_open") is True
        and out.get("single_dialog_still_open") is True
        and out.get("double_opened") is True
        and out.get("double_line") == 2
        and out.get("double_selected") == KEY
        and out.get("right_menu_visible") is True
        and out.get("right_did_not_open") is True
        and "替换此内容…" in labels
    )
    print("XTEST SEARCH CLICK OK" if ok else "XTEST SEARCH CLICK FAILED")
    app.quit()
    return False


if __name__ == "__main__":
    DOCS.mkdir(parents=True)
    DATA.mkdir(parents=True)
    (DOCS / "a.md").write_text(f"alpha\n{KEY}\nbeta\n", encoding="utf-8")
    (DOCS / "b.md").write_text(f"{KEY}\n", encoding="utf-8")
    os.environ["XDG_DATA_HOME"] = str(DATA)
    os.environ["HOME"] = str(TMP / "home")
    (TMP / "home").mkdir(parents=True, exist_ok=True)
    GLib.timeout_add(1200, step1)
    GLib.timeout_add(30000, app.quit)
    app.run(["xtest-search"])
