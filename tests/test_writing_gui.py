"""写作模式端到端测试：四个档位的实际宽度、居中位置、缩放跟随、持久化、入口控件。

用法：/usr/bin/python3 tests/test_writing_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME；宽度断言允许 ±3 px（滚动条/取整）。

场景：
1. 头部写作模式按钮位于三态模式按钮组内、新建标签按钮之前；
2. 关闭态：编辑区宽度 == 编辑区视口宽（不收缩）；
3. 85% / 75% / 50%：实际宽度 == round(视口宽 × 比例)，且左右偏移相等（居中）；
4. 窗口缩放后按新视口重算；
5. 每页独立应用：第二个标签页同样受限；
6. meta 持久化：writing_width 记录当前档位；
7. 垂直滚动仍正常工作（writing 模式不破坏滚动）。
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
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.editor import MODE_PREVIEW, MODE_SOURCE  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-writing-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

LONG = "\n".join(f"第 {i} 行：写作模式回归测试文本内容。" for i in range(1, 400))


class WritingTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(60000, self.app.quit)
        self.app.run(["writing-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 辅助

    def _offset(self, page) -> int:
        """编辑区滚动窗在 Box 内的水平偏移（居中则左右相等）。"""
        ok, rect = page.source_scroller.compute_bounds(page.source_box)
        return round(rect.get_x()) if ok else -1

    def _viewport(self, page) -> int:
        return page.source_box.get_width()

    def _check_pct(self, page, pct: int, key: str) -> None:
        viewport = self._viewport(page)
        if page.source_box.get_visible():
            expected = max(360, round(viewport * pct / 100))
            actual = page.source_scroller.get_width()
            self.out[f"{key}_viewport"] = viewport
            self.out[f"{key}_expected"] = expected
            self.out[f"{key}_actual"] = actual
            self.out[f"{key}_width_ok"] = abs(actual - expected) <= 3
            off = self._offset(page)
            self.out[f"{key}_offset"] = off
            self.out[f"{key}_centered"] = abs(off - (viewport - actual) / 2) <= 3
        # 预览区（预览/分屏可见时）同样收窄居中
        if page.preview_box.get_visible():
            prev_viewport = page.preview_box.get_width()
            prev_expected = max(360, round(prev_viewport * pct / 100))
            prev_actual = page.preview.get_width()
            ok, rect = page.preview.compute_bounds(page.preview_box)
            prev_off = round(rect.get_x()) if ok else -1
            self.out[f"{key}_prev_viewport"] = prev_viewport
            self.out[f"{key}_prev_actual"] = prev_actual
            self.out[f"{key}_prev_width_ok"] = abs(prev_actual - prev_expected) <= 3
            self.out[f"{key}_prev_centered"] = (
                abs(prev_off - (prev_viewport - prev_actual) / 2) <= 3
            )

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        w.set_default_size(1200, 760)
        doc = w.store.create_document("md")
        self.page = w.add_tab(doc)
        self.page.buffer.set_text(LONG)
        w.tabview.set_selected_page(self.page.tab)

        btn = getattr(w, "writing_button", None)
        self.out["writing_button_exists"] = btn is not None
        # 位置：在 mode_box 内（与三态按钮同组），且整个 mode_box 在新建标签按钮之前
        self.out["writing_button_in_mode_box"] = (
            btn is not None and btn.get_parent() is w.mode_box
        )
        self.out["new_tab_after_mode_box"] = w.new_tab_button.get_prev_sibling() is w.mode_box
        GLib.timeout_add(700, self.s1_off)
        return False

    def s1_off(self) -> bool:
        w = self.app.window
        page = self.page
        w.set_writing_mode("off")
        GLib.timeout_add(400, self.s1_check)
        return False

    def s1_check(self) -> bool:
        page = self.page
        viewport = self._viewport(page)
        self.out["off_scroller_w"] = page.source_scroller.get_width()
        self.out["off_view_w"] = page.view.get_width()
        self.out["off_equals_viewport"] = abs(page.source_scroller.get_width() - viewport) <= 3
        self.out["off_view_fills"] = abs(page.view.get_width() - viewport) <= 3
        self.s2_pcts()
        return False

    def s2_pcts(self) -> bool:
        w = self.app.window
        w.set_writing_mode("85")
        GLib.timeout_add(400, self.s2_check)
        return False

    def s2_check(self) -> bool:
        self._check_pct(self.page, 85, "p85")
        w = self.app.window
        w.set_writing_mode("75")
        GLib.timeout_add(400, self.s3_check)
        return False

    def s3_check(self) -> bool:
        self._check_pct(self.page, 75, "p75")
        self.app.window.set_writing_mode("50")
        GLib.timeout_add(400, self.s4_check)
        return False

    def s4_check(self) -> bool:
        self._check_pct(self.page, 50, "p50")
        # 缩放窗口后应跟随
        self.app.window.set_default_size(900, 760)
        GLib.timeout_add(800, self.s5_resized)
        return False

    def s5_resized(self) -> bool:
        w = self.app.window
        w.set_writing_mode("85")
        GLib.timeout_add(400, self.s5_check)
        return False

    def s5_check(self) -> bool:
        self._check_pct(self.page, 85, "p85_resized")
        # 切到实时预览模式：预览区也应收窄居中
        self.page.set_mode(MODE_PREVIEW)
        GLib.timeout_add(900, self.s5b_preview)
        return False

    def s5b_preview(self) -> bool:
        self._check_pct(self.page, 85, "p85_preview")
        self.page.set_mode(MODE_SOURCE)
        GLib.timeout_add(300, self.s5c_second)
        return False

    def s5c_second(self) -> bool:
        # 第二个标签页同样受限
        second = self.app.window.new_tab()
        second.buffer.set_text(LONG)
        GLib.timeout_add(600, lambda: self.s6_second(second))
        return False

    def s6_second(self, second) -> bool:
        viewport = second.source_box.get_width()
        expected = max(360, round(viewport * 85 / 100))
        self.out["second_tab_actual"] = second.source_scroller.get_width()
        self.out["second_tab_width_ok"] = abs(second.source_scroller.get_width() - expected) <= 3
        # 切回第一个标签页再测滚动（隐藏页面的 adjustment 无意义），等布局完成
        self.app.window.tabview.set_selected_page(self.page.tab)
        GLib.timeout_add(700, self.s6b_scroll_first)
        return False

    def s6b_scroll_first(self) -> bool:
        page = self.page
        # 模拟 Ctrl+End：光标移到文末并滚入视野（真实用户路径）
        page.buffer.place_cursor(page.buffer.get_end_iter())
        page.view.scroll_mark_onscreen(page.buffer.get_insert())
        GLib.timeout_add(500, lambda: self.s7_scroll(page))
        return False

    def s7_scroll(self, page) -> bool:
        vadj = page.source_scroller.get_vadjustment()
        self.out["vadj_upper"] = round(vadj.get_upper())
        self.out["vadj_value"] = round(vadj.get_value())
        self.out["vadj_page_size"] = round(vadj.get_page_size())
        self.out["view_height"] = page.view.get_height()
        # 光标在文末：滚动位置距底部应只剩 View 的 bottom-margin（64 px）以内
        bottom_gap = vadj.get_upper() - vadj.get_page_size() - vadj.get_value()
        self.out["bottom_gap"] = round(bottom_gap)
        self.out["scrolled_to_end"] = 0 <= bottom_gap <= 80
        self.out["meta_writing_width"] = self.app.window.store.get_meta("writing_width")
        self.out["meta_persisted"] = self.app.window.store.get_meta("writing_width") == "85"
        # 循环顺序：85 → 75 → 50 → off → 85
        w = self.app.window
        seq = []
        for _ in range(4):
            w.cycle_writing_mode()
            seq.append(w._writing_mode)
        self.out["cycle_sequence"] = seq
        self.out["cycle_ok"] = seq == ["75", "50", "off", "85"]
        self.finish()
        return False


if __name__ == "__main__":
    WritingTest().run()
