"""用真实键盘事件（XTEST）验证片段快捷键与 Tab 触发词展开。

为什么需要真事件：动作回调、`_on_trigger_key()` 直接调用只能证明函数写对了。
真正会出问题的是按键有没有走到窗口（X 焦点、GTK 加速键注册、CAPTURE 阶段被谁吞掉），
这些只有真按键能验证——本项目已因此踩过 Gtk.ListBox 吞鼠标事件的坑。

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
    from Xlib import X, XK, display
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

from gi.repository import GdkX11, Gio, GLib, Gtk  # noqa: E402

from scratchpad import snippets  # noqa: E402
from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="xtest-snippet-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

app = ScratchpadApp()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
out: dict[str, object] = {}
dpy = display.Display()


def key(name: str, mods: tuple[str, ...] = ()) -> None:
    """真实按键：先按修饰键，再按/放主键，最后逆序放修饰键。"""
    codes = [dpy.keysym_to_keycode(XK.string_to_keysym(m)) for m in mods]
    kc = dpy.keysym_to_keycode(XK.string_to_keysym(name))
    for code in codes:
        xtest.fake_input(dpy, X.KeyPress, code)
    xtest.fake_input(dpy, X.KeyPress, kc)
    dpy.sync()
    time.sleep(0.03)
    xtest.fake_input(dpy, X.KeyRelease, kc)
    for code in reversed(codes):
        xtest.fake_input(dpy, X.KeyRelease, code)
    dpy.sync()
    time.sleep(0.12)


def type_text(text: str) -> None:
    for ch in text:
        key(ch if ch != " " else "space")


def focus_window(window) -> None:
    surface = window.get_surface()
    xid = GdkX11.X11Surface.get_xid(surface)
    win = dpy.create_resource_object("window", xid)
    dpy.set_input_focus(win, X.RevertToParent, X.CurrentTime)
    dpy.sync()


def text_of(page) -> str:
    buf = page.buffer
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)


def step_setup() -> bool:
    window = app.window
    if window is None:
        return True
    page = window.new_tab("txt")
    window.set_default_size(900, 660)
    window.present()
    window.tabview.set_selected_page(page.tab)
    page.set_language_for_path(str(TMP / "demo.sh"))

    snippet = snippets.Snippet("插入注释", "<!-- {{cursor}} -->", "<Control><Alt>1")
    window.snippets.append(snippet)
    window.save_snippets()
    out["accel_registered"] = app.get_accels_for_action(
        f"win.snippet-{snippet.id}"
    ) == ["<Control><Alt>1"]
    # 等窗口真的映射到 X 上再抢焦点，否则按键落不到任何窗口
    GLib.timeout_add(900, lambda: step_focus(page))
    return False


def step_focus(page) -> bool:
    focus_window(app.window)
    page.view.grab_focus()
    GLib.timeout_add(300, lambda: step_type_tab(page))
    return False


def step_type_tab(page) -> bool:
    type_text("ife")
    # 按键在 X 队列里排队，主循环要先跑一轮才落到 buffer 上
    GLib.timeout_add(400, lambda: step_tab(page))
    return False


def step_tab(page) -> bool:
    out["typed"] = text_of(page)
    key("Tab")
    GLib.timeout_add(400, lambda: check_tab(page))
    return False


def check_tab(page) -> bool:
    text = text_of(page)
    out["tab_expanded"] = text.startswith("if [ ") and text.rstrip().endswith("fi")
    out["tab_trigger_gone"] = not text.lstrip().startswith("ife")
    buf = page.buffer
    out["tab_cursor_offset"] = buf.get_iter_at_mark(buf.get_insert()).get_offset()
    page.buffer.set_text("")
    page.view.grab_focus()
    GLib.timeout_add(200, lambda: step_accel(page))
    return False


def step_accel(page) -> bool:
    page.view.grab_focus()
    key("1", ("Control_L", "Alt_L"))
    GLib.timeout_add(400, lambda: check_accel(page))
    return False


def check_accel(page) -> bool:
    text = text_of(page)
    out["accel_inserted"] = text == "<!--  -->"
    buf = page.buffer
    out["accel_cursor"] = buf.get_iter_at_mark(buf.get_insert()).get_offset()
    # 未绑定的组合不应插入（Ctrl+Alt+2）
    page.buffer.set_text("")
    page.view.grab_focus()
    key("2", ("Control_L", "Alt_L"))
    GLib.timeout_add(400, lambda: finish(page))
    return False


def finish(page) -> bool:
    out["unbound_no_insert"] = text_of(page) == ""
    print(json.dumps(out, ensure_ascii=False, default=str), flush=True)
    app.quit()
    return False


if __name__ == "__main__":
    GLib.idle_add(step_setup)
    GLib.timeout_add(30000, lambda: (print("TIMEOUT", json.dumps(out, ensure_ascii=False), flush=True), app.quit(), False)[2])
    app.run([])
