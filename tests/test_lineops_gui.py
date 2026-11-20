"""v1.8.0 列编辑 + 撤销/重做按钮端到端测试。

用法：/usr/bin/python3 tests/test_lineops_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME；编辑操作一律走真实动作路径（activate_action），不断言内部状态位。
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

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-lineops-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

RAW = "b\na\nb\nc\n"
SORTED_4 = "a\nb\nb\nc\n"
DEDUPED = "b\na\nc\n"


class LineOpsTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["lineops-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 辅助

    @staticmethod
    def _text(page) -> str:
        b = page.buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def _select_lines(self, page, first: int, last_excl: int) -> None:
        """选中 [first, last_excl) 行：末端的 iter 落在下一行行首（offset 0）。"""
        b = page.buffer
        s = b.get_start_iter()
        s.set_line(first)
        e = b.get_start_iter()
        e.set_line(last_excl)
        b.select_range(s, e)

    def _select_all_lines(self, page, n_lines: int) -> None:
        self._select_lines(page, 0, n_lines)

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("txt")
        self.page = w.add_tab(replace(doc, content=RAW))
        w.tabview.set_selected_page(self.page.tab)
        self.out["init_text"] = self._text(self.page) == RAW
        # 新建文档无历史：撤销/重做按钮都不可用
        self.out["undo_btn_initial_off"] = not w.undo_button.get_sensitive()
        self.out["redo_btn_initial_off"] = not w.redo_button.get_sensitive()
        for name in ("undo", "redo", "line-prefix", "line-suffix", "sort-lines", "dedup-lines"):
            if w.lookup_action(name) is None:
                self.out[f"action_{name}"] = False
        self.out["actions_registered"] = all(
            w.lookup_action(n) is not None
            for n in ("undo", "redo", "line-prefix", "line-suffix", "sort-lines", "dedup-lines")
        )
        self.s1_sort()
        return False

    def s1_sort(self) -> bool:
        w = self.app.window
        page = self.page
        self._select_all_lines(page, 4)
        w.activate_action("win.sort-lines", None)
        self.out["sort_text"] = self._text(page) == SORTED_4
        # 用户可见结果：按钮随 can-undo/can-redo 变化
        self.out["undo_btn_after_edit"] = w.undo_button.get_sensitive()
        self.out["redo_btn_after_edit"] = not w.redo_button.get_sensitive()
        self.s2_undo_redo()
        return False

    def s2_undo_redo(self) -> bool:
        w = self.app.window
        page = self.page
        w.activate_action("win.undo", None)
        self.out["undo_restores_text"] = self._text(page) == RAW
        self.out["redo_btn_after_undo"] = w.redo_button.get_sensitive()
        w.activate_action("win.redo", None)
        self.out["redo_reapplies_sort"] = self._text(page) == SORTED_4
        self.s3_dedup()
        return False

    def s3_dedup(self) -> bool:
        w = self.app.window
        page = self.page
        w.activate_action("win.undo", None)  # 回到 RAW
        self._select_all_lines(page, 4)
        w.activate_action("win.dedup-lines", None)
        self.out["dedup_text"] = self._text(page) == DEDUPED
        self.s4_prefix_suffix()
        return False

    def s4_prefix_suffix(self) -> bool:
        w = self.app.window
        page = self.page
        w.activate_action("win.undo", None)
        self._select_all_lines(page, 4)
        # 对话框路径难以驱动，前缀/后缀走 apply_line_op（与对话框响应同一入口 run_line_op）
        ok = page.apply_line_op("prefix", "- ")
        self.out["prefix_applied"] = ok and self._text(page) == "- b\n- a\n- b\n- c\n"
        ok = page.apply_line_op("suffix", "。")
        self.out["suffix_applied"] = ok and self._text(page) == "- b。\n- a。\n- b。\n- c。\n"
        self.s5_partial_selection()
        return False

    def s5_partial_selection(self) -> bool:
        """行首截断语义：选区末尾停在下一行行首时，下一行不参与。"""
        w = self.app.window
        page = self.page
        page.buffer.set_text("z\ny\nx\nw\n")
        self._select_lines(page, 1, 3)  # 覆盖第 2、3 行（y、x），第 4 行不参与
        w.activate_action("win.sort-lines", None)
        self.out["partial_sort"] = self._text(page) == "z\nx\ny\nw\n"
        # 单行排序/去重 → no-op（返回 False，内容不变）
        self._select_lines(page, 0, 1)
        self.out["single_line_sort_noop"] = not page.apply_line_op("sort")
        self.out["single_line_sort_text_intact"] = self._text(page) == "z\nx\ny\nw\n"
        # 无选区前缀 → 光标所在行
        page.buffer.place_cursor(page.buffer.get_start_iter())
        self.out["cursor_line_prefix"] = (
            page.apply_line_op("prefix", "# ") and self._text(page).startswith("# z")
        )
        self.s6_tab_switch_buttons()
        return False

    def s6_tab_switch_buttons(self) -> bool:
        """切换标签后按钮反映的是当前标签的缓冲区状态。"""
        w = self.app.window
        other = w.new_tab("txt")
        self.out["other_tab_undo_off"] = not w.undo_button.get_sensitive()
        w.tabview.set_selected_page(self.page.tab)
        self.out["back_to_edited_tab_undo_on"] = w.undo_button.get_sensitive()
        self.finish()
        return False


if __name__ == "__main__":
    LineOpsTest().run()
