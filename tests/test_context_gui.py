"""v1.9.0 右键菜单 + 选区感知工具端到端测试。

用法：/usr/bin/python3 tests/test_context_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME；操作一律走真实动作路径（activate_action）。opencc / 排版
formatter 均为真实子进程/真实实现，不断言内部状态位。

场景：
1. 编辑视图已挂 extra-menu（列编辑子菜单 + 4 个顶层项 = 5 条）；
2. 简繁转换：有选区只转换选中片段（其余正文零扰动，结果重新选中，一步可撤销）；
3. 简繁转换：无选区回退整篇；
4. 排版：选区优先按内容嗅探语言，只排版选中代码块；
5. 排版：无选区整篇（既有行为不回归）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
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

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-context-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

CONVERT_SEL_BEFORE = "这是简体。剩余不变。"
CONVERT_SEL_AFTER = "这是簡體。剩余不变。"
CONVERT_WHOLE_BEFORE = "简体测试"
CONVERT_WHOLE_AFTER = "簡體測試"
FMT_SEL_BEFORE = 'data = 1\n{"b": [1, 2], "a": 1}\ntail\n'
# 选中行不含行尾换行，JSON 排版输出以 \n 结尾 → 替换后多出一个空行
FMT_SEL_AFTER = 'data = 1\n{\n  "b": [\n    1,\n    2\n  ],\n  "a": 1\n}\n\ntail\n'
FMT_WHOLE_BEFORE = '{"b": [1, 2], "a": 1}'
FMT_WHOLE_AFTER = '{\n  "b": [\n    1,\n    2\n  ],\n  "a": 1\n}\n'


class ContextTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(60000, self.app.quit)
        self.app.run(["context-test"])

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
        """按绝对字符偏移选中 [a, b)。"""
        s = page.buffer.get_iter_at_offset(a)
        e = page.buffer.get_iter_at_offset(b)
        page.buffer.select_range(s, e)

    @staticmethod
    def _has_selection(page) -> bool:
        sel = page.buffer.get_selection_bounds()
        return len(sel) == 2 and not sel[0].equal(sel[1])

    def _wait_then(self, cond, then, key: str) -> None:
        """每 25ms 轮询 cond（异步工具在 worker 线程 + idle 回调完成）。

        就绪后走 then（断言键由 then 所在场景写入）；超时写失败并终止。
        """
        deadline = time.monotonic() + 10.0

        def tick() -> bool:
            if cond() or time.monotonic() > deadline:
                if not cond():
                    self.out[key] = "等待超时"
                    self.finish()
                else:
                    then()
                return False
            return True

        GLib.timeout_add(25, tick)

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("txt")
        self.page = w.add_tab(replace(doc, content="占位"))
        w.tabview.set_selected_page(self.page.tab)

        extra = self.page.view.get_extra_menu()
        self.out["extra_menu_set"] = extra is not None
        # 6 项：复制为其它编码、列编辑、格式化排版、简→繁、繁→简、折叠当前区块
        self.out["extra_menu_items"] = extra is not None and extra.get_n_items() == 6
        self.s1_convert_selection()
        return False

    def s1_convert_selection(self) -> bool:
        """选中「简体」二字 → win.convert-s2t → 只有这两个字变化且重新选中。"""
        w = self.app.window
        page = self.page
        page.buffer.set_text(CONVERT_SEL_BEFORE)
        self._select(page, 2, 4)  # 「简体」
        w.activate_action("win.convert-s2t", None)
        self._wait_then(
            lambda: self._text(page) == CONVERT_SEL_AFTER,
            self.s1b_check_region,
            "convert_selection_wait",
        )
        return False

    def s1b_check_region(self) -> None:
        page = self.page
        self.out["convert_selection_text"] = self._text(page) == CONVERT_SEL_AFTER
        # 替换结果应被重新选中（2 个字符）
        sel = page.buffer.get_selection_bounds()
        self.out["convert_selection_reselect"] = (
            self._has_selection(page) and sel[1].get_offset() - sel[0].get_offset() == 2
        )
        page.buffer.select_range(
            page.buffer.get_start_iter(), page.buffer.get_start_iter()
        )
        self._wait_then(
            lambda: not self._has_selection(page),
            self.s2_convert_undo,
            "convert_selection_deselect",
        )

    def s2_convert_undo(self) -> None:
        """一步撤销恢复原文（定点替换是单步 user action）。"""
        w = self.app.window
        page = self.page
        w.activate_action("win.undo", None)
        self.out["convert_selection_undo"] = self._text(page) == CONVERT_SEL_BEFORE
        self.s3_convert_whole()
        return False

    def s3_convert_whole(self) -> bool:
        """无选区 → 整篇转换（既有行为）。"""
        w = self.app.window
        page = self.page
        page.buffer.set_text(CONVERT_WHOLE_BEFORE)
        page.buffer.place_cursor(page.buffer.get_start_iter())
        w.activate_action("win.convert-s2t", None)
        self._wait_then(
            lambda: self._text(page) == CONVERT_WHOLE_AFTER,
            self.s4_format_selection,
            "convert_whole_wait",
        )

    def s4_format_selection(self) -> bool:
        """选区排版：选区内容嗅探为 JSON，只排版该块，前后行不动。"""
        w = self.app.window
        page = self.page
        self.out["convert_whole"] = self._text(page) == CONVERT_WHOLE_AFTER
        page.buffer.set_text(FMT_SEL_BEFORE)
        lines = FMT_SEL_BEFORE.split("\n")
        start_off = len("data = 1\n")
        end_off = start_off + len(lines[1])
        self._select(page, start_off, end_off)
        w.activate_action("win.format-doc", None)
        self._wait_then(
            lambda: self._text(page) == FMT_SEL_AFTER,
            self.s5_format_whole,
            "format_selection_wait",
        )

    def s5_format_whole(self) -> bool:
        """无选区 → 整篇排版（既有行为）。"""
        w = self.app.window
        page = self.page
        self.out["format_selection"] = self._text(page) == FMT_SEL_AFTER
        page.buffer.set_text(FMT_WHOLE_BEFORE)
        page.buffer.place_cursor(page.buffer.get_start_iter())
        w.activate_action("win.format-doc", None)
        self._wait_then(
            lambda: self._text(page) == FMT_WHOLE_AFTER,
            self.s6_done,
            "format_whole_wait",
        )

    def s6_done(self) -> bool:
        self.out["format_whole"] = self._text(self.page) == FMT_WHOLE_AFTER
        self.finish()
        return False


if __name__ == "__main__":
    ContextTest().run()
