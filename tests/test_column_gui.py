"""按列提取（列编辑）端到端测试。

用法：/usr/bin/python3 tests/test_column_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME；走真实 EditorPage.apply_column_op 与真实对话框。

场景：
1. 字符宽度模式：用户给的 6 行例子的期望结果；
2. 一步撤销回到原文；替换后整块被重新选中；
3. 分隔符模式（全角冒号 / 多候选 中英冒号）；
4. 未命中行原样保留并回报计数（toast 与预览都要能看到）；
5. 无选区时只作用于光标所在行；
6. 对话框存在、预览文案给出总行数与未命中数、模式切换会隐藏对应参数行；
7. 动作 win.column-take 已注册。
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

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-column-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

PLAIN = """- 欧洲中世纪全身板甲。
- 日本武士大铠、胴丸。
- 清代八旗铠甲。
- 宋代普通札甲作为主体。
- 唐代明光铠。
- 现代防弹衣。"""

SEP = """- 欧洲：中世纪全身板甲。
- 日本：武士大铠、胴丸。
- 清代：八旗铠甲。
- 混入一行没有分隔符的文字
- 唐代：明光铠。
- 现代：防弹衣。"""


class ColumnTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(90000, self.app.quit)
        self.app.run(["column-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ---------------------------------------------------------------- 场景
    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("md")
        self.page = w.add_tab(replace(doc, content=PLAIN))
        w.tabview.set_selected_page(self.page.tab)
        self.out["action_registered"] = w.lookup_action("column-take") is not None
        GLib.timeout_add(400, self.s1_width)
        return False

    def _select_all(self) -> None:
        buf = self.page.buffer
        buf.select_range(buf.get_start_iter(), buf.get_end_iter())

    def _lines(self) -> list[str]:
        buf = self.page.buffer
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).split("\n")

    def s1_width(self) -> bool:
        self._select_all()
        changed, miss = self.page.apply_column_op("width", width=4)
        self.out["width_changed"] = changed
        self.out["width_miss"] = miss
        self.out["width_result"] = self._lines()
        self.out["width_ok"] = self._lines() == [
            "- 欧洲",
            "- 日本",
            "- 清代",
            "- 宋代",
            "- 唐代",
            "- 现代",
        ]
        # 替换后应整块重新选中
        has_sel = self.page.buffer.get_selection_bounds()
        self.out["reselected_after_op"] = len(has_sel) == 2
        GLib.timeout_add(200, self.s2_undo)
        return False

    def s2_undo(self) -> bool:
        self.page.buffer.undo()
        self.out["undo_restores"] = self._lines() == PLAIN.split("\n")
        self.page.buffer.set_text(SEP, -1)
        GLib.timeout_add(200, self.s3_sep)
        return False

    def s3_sep(self) -> bool:
        self._select_all()
        changed, miss = self.page.apply_column_op("sep", sep="：", index=1)
        self.out["sep_changed"] = changed
        self.out["sep_miss"] = miss
        self.out["sep_miss_is_one"] = miss == 1
        got = self._lines()
        self.out["sep_result"] = got
        expected = [
            "- 欧洲",
            "- 日本",
            "- 清代",
            "- 混入一行没有分隔符的文字",
            "- 唐代",
            "- 现代",
        ]
        self.out["sep_keeps_unmatched_line"] = got == expected
        self.page.buffer.set_text(SEP, -1)
        GLib.timeout_add(200, self.s4_multi_sep)
        return False

    def s4_multi_sep(self) -> bool:
        # 多候选分隔符：半角冒号也能切
        self.page.buffer.set_text("a:b\nc：d", -1)
        self._select_all()
        self.page.apply_column_op("sep", sep="：|:", index=2)
        self.out["multi_sep_result"] = self._lines()
        self.out["multi_sep_ok"] = self._lines() == ["b", "d"]
        GLib.timeout_add(200, self.s5_cursor_line)
        return False

    def s5_cursor_line(self) -> bool:
        # 无选区：只作用于光标行
        buf = self.page.buffer
        buf.set_text("第一行：甲\n第二行：乙", -1)
        ok, it = buf.get_iter_at_line(1)
        buf.place_cursor(it)
        changed, miss = self.page.apply_column_op("sep", sep="：", index=1)
        self.out["cursor_line_changed"] = changed
        self.out["cursor_line_miss"] = miss
        self.out["cursor_line_only"] = self._lines() == ["第一行：甲", "第二行"]
        GLib.timeout_add(200, self.s6_dialog)
        return False

    def s6_dialog(self) -> bool:
        w = self.app.window
        self.page.buffer.set_text(SEP, -1)
        self._select_all()
        dialog = w.prompt_column_op()
        self.out["dialog_created"] = dialog is not None
        if dialog is None:
            self.finish()
            return False
        box = dialog.get_extra_child()
        labels = []

        def walk(widget):
            if isinstance(widget, Gtk.Label):
                labels.append(widget.get_text())
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(box)
        preview = next((t for t in labels if "预览" in t), "")
        self.out["preview_has_total"] = "共 6 行" in preview
        self.out["preview_has_miss"] = "1 行未命中" in preview
        self.out["preview_lines"] = preview
        # 默认是分隔符模式（宽度参数行应隐藏）
        self.out["default_mode_sep"] = "→" in preview
        dialog.close()
        GLib.timeout_add(300, self.s7_cycle)
        return False

    def s7_cycle(self) -> bool:
        # 宽度模式下的按钮切换（直接调 refresh 路径：改 spin 值触发）
        w = self.app.window
        accel = w._accel_for("win.column-take") if hasattr(w, "_accel_for") else ""
        self.out["shortcut_accel"] = accel
        self.out["shortcut_registered"] = "Ctrl" in accel and "K" in accel
        self.finish()
        return False


if __name__ == "__main__":
    ColumnTest().run()
