"""v1.11.0 「转义」开关（查找 + 替换）端到端测试。

用法：/usr/bin/python3 tests/test_escape_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME。全部走真实入口（page.replace_all，含「仅选区」与整篇两条路径）。

背景（实测，GSV 5.18.0）：`SearchContext.replace()` 会展开 `\\n \\t \\\\` 与
`\\1`–`\\9`；`replace_all()` 只展开反向引用、**不**展开转义。故本次将全部替换
统一为逐匹配循环。场景据此设计：

1. 开关存在且默认关闭；
2. 正则 + 转义：`\\n\\n` → `\\n` 删空行（用户主诉）；
3. 正则模式即使不开开关也生效（上游模板自带转义）——契约钉死，防止误改；
4. 非正则 + 转义：查找串 `\\n` 命中换行、替换串 `\\t` 插入制表符；
5. 正则 + 转义 + 反向引用共存：`\\2\\n\\1` 中 `\\2` 仍作引用、`\\n` 被展开；
6. 非正则 + 关闭转义：`\\n` 仍按字面反斜杠 n 匹配（不误伤路径类文本）；
7. 选区路径推进修复：`(\\w)` → `\\1\\1` 全量命中（旧实现按模板长度推进会漏）；
8. 无选区整篇替换同样支持转义，且同步返回计数；
9. 空替换（删光匹配）不得死循环。
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

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-escape-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")


class EscapeTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None
        self.toasts: list[str] = []

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["escape-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 辅助

    @staticmethod
    def _text(page) -> str:
        b = page.buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def _prepare(self, text: str, pattern: str, repl: str, *, regex: bool, escape: bool) -> None:
        page = self.page
        page.regex_toggle.set_active(regex)    # 触发时重放查找串
        page.escape_toggle.set_active(escape)
        page.buffer.set_text(text)
        page.search_entry.set_text(pattern)
        page._on_search_text_changed(page.search_entry)  # search-changed 是延迟信号，同步驱动落点
        page.replace_entry.set_text(repl)

    def _replace_in_selection(self, text: str, pattern: str, repl: str, *, regex: bool, escape: bool) -> int:
        """选区 = 全文，走「仅选区」路径（同步），返回计数。

        toast 文案形如「已在选区内替换 2 处」：取倒数第二个空格分隔段。
        """
        page = self.page
        self._prepare(text, pattern, repl, regex=regex, escape=escape)
        page.buffer.select_range(page.buffer.get_start_iter(), page.buffer.get_end_iter())
        page.replace_sel_toggle.set_active(True)
        page.replace_all()
        assert self.toasts, "未收到计数 toast"
        return int(self.toasts[-1].split("替换")[1].split("处")[0].strip())

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("txt")
        self.page = w.add_tab(replace(doc, content="占位"))
        w.tabview.set_selected_page(self.page.tab)
        self.page.connect("request-toast", self._capture_toast, None)
        self.out["escape_toggle_exists"] = self.page.escape_toggle is not None
        self.out["escape_toggle_default_off"] = not self.page.escape_toggle.get_active()
        self.s1_regex_escape_blank_lines()
        return False

    def _capture_toast(self, _page, text: str, _data) -> None:
        self.toasts.append(text)

    def s1_regex_escape_blank_lines(self) -> bool:
        """用户主诉：正则 + 转义，\\n\\n → \\n 删空行。"""
        n = self._replace_in_selection("a\n\nb\n\nc", "\\n\\n", "\\n", regex=True, escape=True)
        self.out["blank_lines_collapsed"] = self._text(self.page) == "a\nb\nc"
        self.out["blank_lines_count"] = n == 2
        self.s2_regex_without_toggle()
        return False

    def s2_regex_without_toggle(self) -> bool:
        """正则模式不开「转义」也生效（上游 replace() 自带转义展开）。"""
        n = self._replace_in_selection("a\n\nb", "\\n\\n", "\\n", regex=True, escape=False)
        self.out["regex_escape_without_toggle"] = self._text(self.page) == "a\nb" and n == 1
        self.s3_non_regex_escape()
        return False

    def s3_non_regex_escape(self) -> bool:
        """非正则 + 转义：查找串 \\n 命中换行，替换串 \\t 插入制表符。"""
        n = self._replace_in_selection("a\nb", "\\n", "\\t", regex=False, escape=True)
        self.out["non_regex_escape"] = self._text(self.page) == "a\tb" and n == 1
        self.s4_backref_with_escape()
        return False

    def s4_backref_with_escape(self) -> bool:
        """正则 + 转义：\\2 / \\1 仍是反向引用，\\n 被展开。"""
        self._replace_in_selection("foo bar", "(\\w+) (\\w+)", "\\2\\n\\1", regex=True, escape=True)
        self.out["backref_with_escape"] = self._text(self.page) == "bar\nfoo"
        self.s5_off_keeps_literal()
        return False

    def s5_off_keeps_literal(self) -> bool:
        """非正则 + 关闭转义：\\n 仍按字面反斜杠 n 匹配（不误伤路径文本）。"""
        n = self._replace_in_selection("a\\nb", "\\n", "X", regex=False, escape=False)
        self.out["off_literal_search"] = self._text(self.page) == "aXb" and n == 1
        self.s6_backref_advance()
        return False

    def s6_backref_advance(self) -> bool:
        """选区路径推进：`(\\w)` → `\\1\\1` 必须命中全部 6 处。

        旧实现按模板长度（4）推进，会漏掉一半匹配，此为回归钉。
        """
        n = self._replace_in_selection("abcdef", "(\\w)", "\\1\\1", regex=True, escape=True)
        self.out["backref_advance_all"] = self._text(self.page) == "aabbccddeeff" and n == 6
        self.s7_whole_doc()
        return False

    def s7_whole_doc(self) -> bool:
        """无选区整篇替换：转义同样生效，且同步可知计数。"""
        page = self.page
        self._prepare("a\n\nb\n\nc", "\\n\\n", "\\n", regex=True, escape=True)
        page.buffer.place_cursor(page.buffer.get_start_iter())
        page.replace_sel_toggle.set_active(False)
        page.replace_all()
        ok = self._text(page) == "a\nb\nc"
        counted = bool(self.toasts) and "替换 2 处" in self.toasts[-1]
        self.out["whole_doc_escape"] = ok and counted
        self.s8_empty_replacement()
        return False

    def s8_empty_replacement(self) -> bool:
        """空替换（删除所有匹配）不得死循环：正则 `x` → 空。"""
        n = self._replace_in_selection("xaxbxc", "x", "", regex=True, escape=True)
        self.out["empty_replacement"] = self._text(self.page) == "abc" and n == 3
        self.s9_whole_doc_undo_and_cursor()
        return False

    def s9_whole_doc_undo_and_cursor(self) -> bool:
        """整篇替换：一步撤销恢复原文；等长替换时光标位置保持。"""
        page = self.page
        original = "alpha beta\nalpha beta\nalpha\n"
        self._prepare(original, "alpha", "XXXXX", regex=True, escape=False)
        page.replace_sel_toggle.set_active(False)
        page.buffer.place_cursor(page.buffer.get_iter_at_offset(18))
        page.replace_all()
        replaced = self._text(page)
        keep = page.buffer.get_iter_at_mark(page.buffer.get_insert()).get_offset()
        w = self.app.window
        w.activate_action("win.undo", None)
        self.out["whole_doc_undo"] = self._text(page) == original
        self.out["cursor_kept"] = keep == 18 and replaced.count("XXXXX") == 3
        self.s10_bulk_perf()
        return False

    def s10_bulk_perf(self) -> bool:
        """整篇替换的性能钉：3000 处匹配必须在 3 s 内完成。

        已挂载视图的缓冲区上逐处 replace 曾耗时 52 s（实测），此断言防止
        退回二次复杂度实现。
        """
        page = self.page
        text = "alpha beta gamma delta\n" * 3000  # 3000 处匹配
        self._prepare(text, "alpha", "X", regex=True, escape=False)
        page.replace_sel_toggle.set_active(False)
        t0 = time.perf_counter()
        page.replace_all()
        elapsed = time.perf_counter() - t0
        replaced = self._text(page).count("X")
        self.out["bulk_perf_seconds"] = round(elapsed, 3)
        self.out["bulk_perf_fast"] = elapsed < 3.0 and replaced == 3000
        self.finish()
        return False


if __name__ == "__main__":
    EscapeTest().run()
