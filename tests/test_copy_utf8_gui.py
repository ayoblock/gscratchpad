"""显式「复制为 UTF-8 文本」回归测试（含 Ctrl+C 拦截）。

用法：/usr/bin/python3 tests/test_copy_utf8_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 XDG_DATA_HOME；
通过真实 GAction 路径 activate_action("win.copy-as-utf8-text") 触发；Ctrl+C 直接
调用窗口 CAPTURE 阶段 handler（本会话合成器不支持可靠的按键注入）；从
Gdk.Clipboard 按 UTF8_STRING 读回，逐字节比对源文本（含中文表格、<br>、|||）。

场景：
1. 右键菜单不含「复制为 UTF-8 文本」，改为「复制为其它编码」子菜单（GBK/UTF-16）；
2. GAction 有选区：只复制选区，逐字节相等；
3. GAction 无选区：复制整篇（snapshot_text），逐字节相等；
4. Ctrl+C 焦点在编辑器且有选区：被拦截（返回 True），剪贴板逐字节相等；
5. Ctrl+C 焦点不在编辑器：返回 False，交还内置行为，剪贴板不被改写；
6. 剪贴板 formats 同时含 UTF8_STRING、text/plain;charset=utf-8 与裸 text/plain
   （缺裸 text/plain 会让只请求它的消费者报「没有相容格式」，复制完全失效）；
7. 编码子菜单动作能写入 GBK / UTF-16 对应 MIME；
8. 应用启动时侧边栏默认收起。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(PROJECT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gdk, Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.clipboard import set_clipboard_utf8  # noqa: E402
from scratchpad.editor import COPY_ENCODINGS  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-copyutf8-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

TABLE = (
    "|二房|侧重|23岁 **郭德纲和**<br>二房|\n"
    "|-|-|-|\n"
    "|二房|侧重|11岁 **郭德纲清**<br>二房|\n"
)
PREFIX = "# 开头\n\n"
SUFFIX = "\n结尾\n"
WHOLE = PREFIX + TABLE + SUFFIX
SEL = TABLE


class CopyUtf8Test:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None
        self.clipboard = None
        self.expected: dict[str, str] = {}
        self.next_after_read = None
        self.read_tag = ""

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["copy-utf8-test"])

    def finish(self) -> None:
        self.w().close()
        print(json.dumps(self.out, ensure_ascii=False), flush=True)

    def w(self):
        return self.app.window

    def at(self, seconds: float, func) -> None:
        GLib.timeout_add(int(seconds * 1000), lambda: (func(), False)[1])

    def read_clip(self, tag: str, expected: str, next_step) -> None:
        """异步读回 UTF8_STRING，逐字节比对后进入下一步。"""
        self.read_tag = tag
        self.expected[tag] = expected
        self.next_after_read = next_step
        self.clipboard.read_text_async(None, self.read_done)

    def read_done(self, cb, res) -> None:
        tag = self.read_tag
        try:
            text = cb.read_text_finish(res)
            raw = text.encode("utf-8")
            self.out[f"{tag}_bytes_equal"] = raw == self.expected[tag].encode("utf-8")
            if tag == "sel":
                self.out["sel_text"] = raw.decode("utf-8", "replace")
                fmts = sorted(cb.get_formats().get_mime_types())
                self.out["formats"] = fmts
                self.out["has_utf8_string"] = "UTF8_STRING" in fmts
                self.out["has_utf8_mime"] = "text/plain;charset=utf-8" in fmts
                self.out["has_text_plain"] = "text/plain" in fmts
        except Exception as exc:  # noqa: BLE001
            self.out[f"{tag}_error"] = str(exc)
        self.at(0.2, self.next_after_read)

    def select_table(self) -> None:
        buf = self.page.buffer
        start = buf.get_iter_at_offset(len(PREFIX))
        end = buf.get_iter_at_offset(len(PREFIX) + len(SEL))
        buf.select_range(start, end)

    def clear_selection(self) -> None:
        # GtkTextBuffer 无 unselect_all；把光标与选择端放到偏移 0 即等效。
        buf = self.page.buffer
        it = buf.get_iter_at_offset(0)
        buf.select_range(it, it)

    # ------------------------------------------------------------------ steps

    def s0_setup(self) -> None:
        w = self.w()
        self.page = w._current_page()
        self.page.buffer.set_text(WHOLE)
        self.clipboard = Gdk.Display.get_default().get_clipboard()
        self.out["sidebar_hidden_on_start"] = not bool(w.sidebar_visible())
        self.at(0.2, self.s1_menu)

    def s1_menu(self) -> None:
        menu = self.page._build_context_menu()
        labels = []
        for i in range(menu.get_n_items()):
            labels.append(menu.get_item_attribute_value(i, "label", None).get_string())
        enc_labels = [label for label, _name in COPY_ENCODINGS]
        self.out["no_utf8_menu_item"] = "复制为 UTF-8 文本" not in labels
        self.out["has_encoding_submenu"] = "复制为其它编码" in labels
        self.out["encoding_labels"] = enc_labels
        self.out["has_gbk"] = "GBK" in enc_labels
        self.out["has_utf16"] = "UTF-16" in enc_labels
        self.out["encoding_action_exists"] = (
            self.w().lookup_action("copy-as-encoding") is not None
        )
        self.at(0.2, self.s2_selection)

    def s2_selection(self) -> None:
        self.select_table()
        self.w().activate_action(
            "win.copy-as-encoding", GLib.Variant.new_string("utf-8")
        )
        self.at(0.3, lambda: self.read_clip("sel", SEL, self.s3_whole))

    def s3_whole(self) -> None:
        self.clear_selection()
        self.w().activate_action(
            "win.copy-as-encoding", GLib.Variant.new_string("utf-8")
        )
        self.at(0.3, lambda: self.read_clip("whole", WHOLE, self.s4_grab_focus))

    def s4_grab_focus(self) -> None:
        self.page.view.grab_focus()
        self.at(0.2, self.s5_ctrlc)

    def s5_ctrlc(self) -> None:
        self.out["editor_has_focus"] = bool(self.page.view.has_focus())
        self.select_table()
        intercepted = self.w()._on_window_key(
            None, Gdk.KEY_c, 0, Gdk.ModifierType.CONTROL_MASK
        )
        self.out["ctrlc_intercepted"] = bool(intercepted)
        self.at(0.3, lambda: self.read_clip("ctrlc", SEL, self.s6_ctrlc_outside))

    def s6_ctrlc_outside(self) -> None:
        # 焦点移出编辑区（到查找栏）：Ctrl+C 不应被拦截，也不应改写剪贴板。
        self.page.show_search(False)
        self.at(0.2, self.s7_ctrlc_outside_check)

    def s7_ctrlc_outside_check(self) -> None:
        self.out["search_entry_has_focus"] = bool(self.page.search_entry.has_focus())
        intercepted = self.w()._on_window_key(
            None, Gdk.KEY_c, 0, Gdk.ModifierType.CONTROL_MASK
        )
        self.out["ctrlc_outside_not_intercepted"] = not bool(intercepted)
        self.at(0.2, self.s8_helper)

    def s8_helper(self) -> None:
        # 侧边栏 / 目录搜索共用的 helper 自身也写显式 UTF-8。
        ok = set_clipboard_utf8(SEL)
        self.out["helper_ok"] = bool(ok)
        self.at(0.3, lambda: self.read_clip("helper", SEL, self.s9_gbk))

    def s9_gbk(self) -> None:
        self.w().activate_action(
            "win.copy-as-encoding", GLib.Variant.new_string("gbk")
        )
        self.at(0.3, self.s10_gbk_check)

    def s10_gbk_check(self) -> None:
        fmts = sorted(self.clipboard.get_formats().get_mime_types())
        self.out["gbk_formats"] = fmts
        self.out["gbk_mime_ok"] = "text/plain;charset=gbk" in fmts
        self.at(0.2, self.s11_utf16)

    def s11_utf16(self) -> None:
        self.w().activate_action(
            "win.copy-as-encoding", GLib.Variant.new_string("utf-16")
        )
        self.at(0.3, self.s12_utf16_check)

    def s12_utf16_check(self) -> None:
        fmts = sorted(self.clipboard.get_formats().get_mime_types())
        self.out["utf16_formats"] = fmts
        self.out["utf16_mime_ok"] = "text/plain;charset=utf-16" in fmts
        self.finish()


if __name__ == "__main__":
    CopyUtf8Test().run()
