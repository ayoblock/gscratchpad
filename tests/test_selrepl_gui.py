"""v1.10.0 「仅选区」查找替换端到端测试。

用法：/usr/bin/python3 tests/test_selrepl_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME。替换入口与按钮点击同一函数（page.replace_all / show_search）。

场景：
1. 打开替换面板 + 多行选区 → 「仅选区」自动勾上；无选区不勾；
2. 选区内替换：选区外的同名匹配零扰动；
3. 边界约定：跨越选区边缘的匹配不替换（起点跨界 + 终点跨界两例）；
4. 整批一步撤销；
5. 关闭开关 → 整篇替换（既有行为不回归）；
6. 替换后重新选中修改区域；toast 通道送达计数。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(PROJECT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-selrepl-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")


class SelReplTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None
        self.toasts: list[str] = []

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["selrepl-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 辅助

    @staticmethod
    def _text(page) -> str:
        b = page.buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    @staticmethod
    def _select(page, a: int, b: int) -> None:
        s = page.buffer.get_iter_at_offset(a)
        e = page.buffer.get_iter_at_offset(b)
        page.buffer.select_range(s, e)

    @staticmethod
    def _has_selection(page) -> bool:
        sel = page.buffer.get_selection_bounds()
        return len(sel) == 2 and not sel[0].equal(sel[1])

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("txt")
        self.page = w.add_tab(replace(doc, content="占位"))
        w.tabview.set_selected_page(self.page.tab)
        self.page.connect("request-toast", self._capture_toast, None)
        self.out["toggle_exists"] = self.page.replace_sel_toggle is not None
        self.s1_auto_toggle()
        return False

    def _capture_toast(self, _page, text: str, _data) -> None:
        self.toasts.append(text)

    def s1_auto_toggle(self) -> bool:
        """多行选区打开替换面板 → 自动勾上；无选区 → 不勾。"""
        page = self.page
        page.buffer.set_text("alpha beta\nalpha beta\nalpha")
        self._select(page, 0, 11)  # 覆盖换行 → 多行选区
        page.show_search(replace=True)
        GLib.idle_add(self.s1b_check, None)
        return False

    def s1b_check(self, _data) -> bool:
        page = self.page
        self.out["auto_on_with_multiline_sel"] = page.replace_sel_toggle.get_active()
        page.hide_search()
        page.buffer.place_cursor(page.buffer.get_start_iter())
        page.show_search(replace=True)
        GLib.idle_add(self.s1c_check, None)
        return False

    def s1c_check(self, _data) -> bool:
        page = self.page
        self.out["auto_off_without_sel"] = not page.replace_sel_toggle.get_active()
        page.hide_search()
        self.s2_replace_in_selection()
        return False

    def s2_replace_in_selection(self) -> bool:
        """选区内替换：只换选区内那处 alpha，选区外两处不动。"""
        page = self.page
        page.buffer.set_text("alpha beta\nalpha beta\nalpha")
        # 选区 = 第 2 行整行 "alpha beta"（含换行则第 3 行会被算进整行语义，故取行内容）
        s = page.buffer.get_iter_at_offset(len("alpha beta\n"))
        e = s.copy()
        e.forward_line()
        e.backward_char()  # 退掉换行，停在行尾
        page.buffer.select_range(s, e)
        page.replace_sel_toggle.set_active(True)  # 单行选区不会自动勾，显式开
        page.search_entry.set_text("alpha")
        page.search_settings.set_search_text("alpha")  # search-changed 有延迟，直接驱动落点
        page.replace_entry.set_text("X")
        page.replace_all()
        self.out["replace_in_selection"] = self._text(page) == "alpha beta\nX beta\nalpha"
        self.out["toast_count"] = any("替换 1 处" in t for t in self.toasts)
        self.s3_boundary_start()
        return False

    def s3_boundary_start(self) -> bool:
        """起点跨界：匹配跨过选区开头 → 不替换。undo 一步先还原。"""
        w = self.app.window
        page = self.page
        w.activate_action("win.undo", None)
        self.out["single_step_undo"] = self._text(page) == "alpha beta\nalpha beta\nalpha"
        page.buffer.set_text("abcdef")
        self._select(page, 1, 4)  # "bcd"
        page.search_entry.set_text("ab")
        page.search_settings.set_search_text("ab")  # 唯一匹配 0..2，跨过选区起点
        page.replace_entry.set_text("#")
        page.replace_all()
        self.out["boundary_start_excluded"] = (
            self._text(page) == "abcdef" and not self._has_selection(page) or self._text(page) == "abcdef"
        )
        self.out["boundary_start_count0"] = any("替换 0 处" in t for t in self.toasts)
        self.s4_boundary_end()
        return False

    def s4_boundary_end(self) -> bool:
        """终点跨界：匹配跨过选区结尾 → 不替换。"""
        page = self.page
        page.buffer.set_text("abcd")
        self._select(page, 1, 3)  # "bc"
        page.search_entry.set_text("cd")
        page.search_settings.set_search_text("cd")  # 唯一匹配 2..4，跨过选区终点
        page.replace_entry.set_text("#")
        page.replace_all()
        self.out["boundary_end_excluded"] = self._text(page) == "abcd"
        self.s5_reselect_and_off()
        return False

    def s5_reselect_and_off(self) -> bool:
        """替换后重新选中修改区域；关掉开关 → 整篇替换（既有行为，异步完成需轮询）。"""
        page = self.page
        page.buffer.set_text("alpha beta\nalpha beta\nalpha")
        s = page.buffer.get_iter_at_offset(len("alpha beta\n"))
        e = s.copy()
        e.forward_line()
        e.backward_char()
        page.buffer.select_range(s, e)
        page.search_entry.set_text("alpha")
        page.search_settings.set_search_text("alpha")  # search-changed 有延迟，直接驱动落点
        page.replace_entry.set_text("X")
        page.replace_all()
        self.out["reselect_after_replace"] = self._has_selection(page)
        page.replace_sel_toggle.set_active(False)
        page.buffer.set_text("alpha beta\nalpha beta\nalpha")
        page.replace_all()  # 整篇：SearchContext.replace_all 异步，轮询等完成
        deadline = GLib.timeout_add(25, self._s5_poll)
        return False

    def _s5_poll(self) -> bool:
        page = self.page
        if self._text(page) == "X beta\nX beta\nX":
            self.out["toggle_off_whole_doc"] = True
            self.finish()
            return False
        self._s5_polls = getattr(self, "_s5_polls", 0) + 1
        if self._s5_polls > 200:
            self.out["toggle_off_whole_doc"] = f"轮询超时，当前文本：{self._text(page)!r}"
            self.finish()
            return False
        return True


if __name__ == "__main__":
    SelReplTest().run()
