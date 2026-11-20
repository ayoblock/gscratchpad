"""打字机模式端到端测试：光标行固定于视口百分比、抑制路径、边界钳制、
持久化、入口按钮位置、段落遮罩（TextTag）。

用法：/usr/bin/python3 tests/test_typewriter_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME。居中断言允许 ±2 行高（margin 与取整）。

场景：
1. 动作注册（含 paragraph-dim / typewriter-align）+ 按钮位于写作模式右侧；
2. align=50：光标行滚到视口垂直中心（±2 行高）；
3. 首行 / 末行钳制；
4. 拖选抑制（滚动与遮罩刷新都暂停）；
5. 关闭后不滚；
6. 新建标签页自动带三项状态（跟随 / 位置 / 遮罩）；
7. align=33：光标行落在视口约 1/3 处（0.28~0.42）；
8. 段落遮罩：普通段落 / 标题 / 围栏代码块各自成段，段外打 tag、段内不打；
9. 选区抑制：选区期间遮罩保持上一次状态；
10. 关闭遮罩后 tag 全部移除；
11. 与写作模式 75% 叠加正交；快捷键 Ctrl+Shift+T 可解析。
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

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-typewriter-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

LONG = "\n".join(f"第 {i} 行：打字机模式回归测试文本内容，供滚动定位。" for i in range(1, 200))

PARA = (
    "第一段第一行\n"
    "第一段第二行\n"
    "\n"
    "第二段第一行\n"
    "第二段第二行\n"
    "第二段第三行\n"
    "\n"
    "## 标题行\n"
    "\n"
    "```python\n"
    "print(1)\n"
    "print(2)\n"
    "```\n"
    "\n"
    "第三段第一行"
)


class TypewriterTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(60000, self.app.quit)
        self.app.run(["typewriter-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 辅助

    def _adj(self, page):
        return page.source_scroller.get_vadjustment()

    def _cursor_center_dev(self, page) -> float:
        """光标行中心与视口中心的偏差（像素，带符号）。"""
        adj = self._adj(page)
        buf = page.buffer
        insert = buf.get_iter_at_mark(buf.get_insert())
        line_y, line_h = page.view.get_line_yrange(insert)
        _wx, wy = page.view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, 0, line_y)
        win_center = adj.get_page_size() / 2
        return (wy + line_h / 2) - win_center

    def _cursor_frac(self, page) -> float:
        """光标行中心在视口内的纵向占比（0=顶，1=底）。

        buffer_to_window_coords 返回的 wy 已是视口相对坐标（探针实证），
        不再减 adj.value。
        """
        adj = self._adj(page)
        buf = page.buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        line_y, line_h = page.view.get_line_yrange(it)
        _wx, wy = page.view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, 0, line_y)
        ps = adj.get_page_size() or 1.0
        return (wy + line_h / 2) / ps

    def _place_line(self, page, line: int) -> None:
        ok, it = page.buffer.get_iter_at_line(line)
        if not ok:
            raise AssertionError(f"line {line} out of range")
        page.buffer.place_cursor(it)

    def _line_has_tag(self, page, line: int) -> bool:
        _ok, it = page.buffer.get_iter_at_line(line)
        return it.has_tag(page._dim_tag)

    def _after_idle(self, cb, delay_ms=250):
        GLib.timeout_add(delay_ms, cb)
        return False

    # ------------------------------------------------------------------ 场景

    def s0_setup(self) -> bool:
        w = self.app.window
        self.page = w._current_page()
        self.page.buffer.set_text(LONG)
        self.out["actions_registered"] = (
            w.lookup_action("typewriter-mode") is not None
            and w.lookup_action("toggle-typewriter") is not None
            and w.lookup_action("paragraph-dim") is not None
            and w.lookup_action("typewriter-align") is not None
        )
        self.out["initial_state_off"] = not w._typewriter()
        self.out["dim_initial_off"] = not w._paragraph_dim()
        self.out["align_default_33"] = (
            w._align_action.get_state().get_string() == "33"
        )
        # 按钮位于写作模式右侧（同组相邻）
        child = w.mode_box.get_first_child()
        names = []
        while child is not None:
            names.append(child is w.writing_button and "writing"
                         or child is w.typewriter_button and "typewriter" or "other")
            child = child.get_next_sibling()
        try:
            self.out["button_after_writing"] = (
                names.index("typewriter") == names.index("writing") + 1
            )
        except ValueError:
            self.out["button_after_writing"] = False
        GLib.timeout_add(400, self.s1_align50)
        return False

    def s1_align50(self) -> bool:
        page, w = self.page, self.app.window
        w.activate_action("win.typewriter-align", GLib.Variant.new_string("50"))
        self.out["align50_meta"] = w.store.get_meta("typewriter_align", "33") == "50"
        w.activate_action("win.toggle-typewriter", None)
        self.out["state_on"] = w._typewriter()
        self.out["meta_saved"] = w.store.get_meta("typewriter", "0") == "1"
        self._place_line(page, 100)
        self.out["cursor_set"] = True
        return self._after_idle(self.s2_check_center)

    def s2_check_center(self) -> bool:
        page = self.page
        adj = self._adj(page)
        dev = self._cursor_center_dev(page)
        ok, it = page.buffer.get_iter_at_line(100)
        _y, h = page.view.get_line_yrange(it)
        line_h = h or adj.get_upper() / 200 or 20
        self.out["center_dev_px"] = round(dev, 1)
        self.out["center_ok"] = abs(dev) <= 2 * line_h
        return self._after_idle(self.s3_top_clamp)

    def s3_top_clamp(self) -> bool:
        page = self.page
        self._place_line(page, 0)
        return self._after_idle(self.s3b_check_top)

    def s3b_check_top(self) -> bool:
        adj = self._adj(self.page)
        self.out["top_clamp_at_zero"] = abs(adj.get_value()) < 1.0
        return self._after_idle(self.s4_bottom_clamp)

    def s4_bottom_clamp(self) -> bool:
        page = self.page
        end = page.buffer.get_end_iter()
        page.buffer.place_cursor(end)
        return self._after_idle(self.s4b_check_bottom)

    def s4b_check_bottom(self) -> bool:
        adj = self._adj(self.page)
        bottom_gap = adj.get_upper() - (adj.get_value() + adj.get_page_size())
        # 写作模式回归同款口径：底差在 [0, 80]（bottom-margin 64 + 容差）
        self.out["bottom_gap"] = round(bottom_gap, 1)
        self.out["bottom_clamp_ok"] = 0 <= bottom_gap <= 80
        return self._after_idle(self.s5_drag_suppress)

    def s5_drag_suppress(self) -> bool:
        page = self.page
        adj = self._adj(page)
        self.out["before_scroll_value"] = round(adj.get_value(), 1)
        # 构造拖选态（选区非空 → tick 应抑制）
        ok1, a = page.buffer.get_iter_at_line(120)
        ok2, b = page.buffer.get_iter_at_line(125)
        page.buffer.select_range(a, b)
        self.out["selection_made"] = page.buffer.get_has_selection()
        return self._after_idle(self.s5b_check_no_scroll)

    def s5b_check_no_scroll(self) -> bool:
        page = self.page
        adj = self._adj(page)
        self.out["drag_suppress"] = abs(adj.get_value() - self.out["before_scroll_value"]) < 2.0
        page.buffer.place_cursor(page.buffer.get_start_iter())
        return self._after_idle(self.s6_off)

    def s6_off(self) -> bool:
        page, w = self.page, self.app.window
        w.activate_action("win.toggle-typewriter", None)
        self.out["state_off_again"] = not w._typewriter()
        adj = self._adj(page)
        before = adj.get_value()
        self._place_line(page, 150)
        self.out["off_value"] = round(before, 1)
        return self._after_idle(self.s6b_check_off)

    def s6b_check_off(self) -> bool:
        adj = self._adj(self.page)
        self.out["off_no_scroll"] = abs(adj.get_value() - self.out["off_value"]) < 2.0
        return self._after_idle(self.s7_newtab)

    def s7_newtab(self) -> bool:
        w = self.app.window
        w.activate_action("win.toggle-typewriter", None)  # 重新开启
        w.activate_action("win.new-tab", None)
        self.out["state_on_re"] = w._typewriter()
        return self._after_idle(self.s7b_newtab_state)

    def s7b_newtab_state(self) -> bool:
        page2 = self.app.window._current_page()
        self.out["newtab_carries_typewriter"] = (
            page2 is not None and page2._typewriter is True and page2 is not self.page
        )
        self.out["newtab_carries_align"] = (
            page2 is not None and page2._typewriter_yalign == 50
        )
        self.out["newtab_dim_off"] = page2 is not None and page2._dim_on is False
        return self._after_idle(self.s8_align33)

    def s8_align33(self) -> bool:
        page, w = self.page, self.app.window
        page = w._current_page()
        self.page = page
        w.activate_action("win.typewriter-align", GLib.Variant.new_string("33"))
        self.out["align33_meta"] = w.store.get_meta("typewriter_align", "50") == "33"
        if page.buffer.get_line_count() < 150:
            page.buffer.set_text(LONG)
        self._place_line(page, 100)
        return self._after_idle(self.s8b_check_frac, 400)

    def s8b_check_frac(self) -> bool:
        frac = self._cursor_frac(self.page)
        self.out["align33_frac"] = round(frac, 3)
        self.out["align33_ok"] = 0.28 <= frac <= 0.42
        return self._after_idle(self.s9_dim_on)

    def s9_dim_on(self) -> bool:
        page, w = self.page, self.app.window
        w.activate_action("win.paragraph-dim", None)
        self.out["dim_state_on"] = w._paragraph_dim()
        self.out["dim_meta_saved"] = w.store.get_meta("paragraph_dim", "0") == "1"
        page.buffer.set_text(PARA)
        self._place_line(page, 4)   # 第二段（行 3~5）
        return self._after_idle(self.s9b_check_dim)

    def s9b_check_dim(self) -> bool:
        page = self.page
        # 段外（第一段、标题、围栏块、第三段、段间空行）都应打上遮罩 tag
        self.out["dim_para1_tagged"] = self._line_has_tag(page, 0)
        self.out["dim_gap_tagged"] = self._line_has_tag(page, 2)
        # 当前段落（行 3~5）保持清晰
        self.out["dim_current_clear"] = not any(
            self._line_has_tag(page, ln) for ln in (3, 4, 5)
        )
        # 标题自成一段、围栏块自成一段 → 都在段外，被遮罩
        self.out["dim_heading_tagged"] = self._line_has_tag(page, 7)
        self.out["dim_fence_tagged"] = self._line_has_tag(page, 10)
        self.out["dim_para3_tagged"] = self._line_has_tag(page, 13)
        return self._after_idle(self.s10_dim_in_fence)

    def s10_dim_in_fence(self) -> bool:
        page = self.page
        # 光标移进围栏块：围栏块（行 9~12）整段清晰，其余被遮罩
        self._place_line(page, 10)
        return self._after_idle(self.s10b_check)

    def s10b_check(self) -> bool:
        page = self.page
        self.out["fence_current_clear"] = not any(
            self._line_has_tag(page, ln) for ln in (9, 10, 11, 12)
        )
        self.out["fence_para2_tagged"] = self._line_has_tag(page, 3)
        return self._after_idle(self.s11_dim_selection_pause)

    def s11_dim_selection_pause(self) -> bool:
        page = self.page
        # 先把光标放到第三段（行 13，段落区间 (13,14)），让 sig 固化
        self._place_line(page, 13)
        return self._after_idle(self.s11b_make_selection)

    def s11b_make_selection(self) -> bool:
        page = self.page
        self.out["sig_before_sel"] = page._dim_sig == (13, 14)
        ok1, a = page.buffer.get_iter_at_line(9)
        ok2, b = page.buffer.get_iter_at_line(12)
        page.buffer.select_range(a, b)   # 选区落点行 11，选区非空 → 刷新被抑制
        return self._after_idle(self.s11c_check_pause)

    def s11c_check_pause(self) -> bool:
        page = self.page
        # 抑制生效：sig 仍是 (13, 14)，围栏行 9 仍带旧遮罩、行 13 仍清晰
        self.out["dim_sig_frozen"] = page._dim_sig == (13, 14)
        self.out["fence9_kept_tagged"] = self._line_has_tag(page, 9)
        self.out["para3_kept_clear"] = not self._line_has_tag(page, 13)
        page.buffer.place_cursor(page.buffer.get_start_iter())  # 解除选区
        return self._after_idle(self.s11d_check_refresh)

    def s11d_check_refresh(self) -> bool:
        page = self.page
        # 选区解除后恢复刷新：光标在第一段（行 0~1）→ 段外全部遮罩
        self.out["refresh_resumed_sig"] = page._dim_sig == (0, 2)
        self.out["refresh_para1_clear"] = not self._line_has_tag(page, 0)
        self.out["refresh_para3_tagged"] = self._line_has_tag(page, 13)
        return self._after_idle(self.s12_dim_off)

    def s12_dim_off(self) -> bool:
        w = self.app.window
        w.activate_action("win.paragraph-dim", None)
        self.out["dim_state_off"] = not w._paragraph_dim()
        self.out["dim_meta_off"] = w.store.get_meta("paragraph_dim", "1") == "0"
        page = self.page
        self.out["dim_cleared_para1"] = not self._line_has_tag(page, 0)
        self.out["dim_cleared_para3"] = not self._line_has_tag(page, 13)
        return self._after_idle(self.s13_writing_combo)

    def s13_writing_combo(self) -> bool:
        page, w = self.page, self.app.window
        w.activate_action("win.writing-mode", GLib.Variant.new_string("75"))
        self.out["writing_on"] = w._writing_mode == "75"
        page = w._current_page()
        self.page = page
        if page.buffer.get_line_count() < 150:
            page.buffer.set_text(LONG)
        self._place_line(page, 100)
        return self._after_idle(self.s13b_combo_check, 400)

    def s13b_combo_check(self) -> bool:
        page = self.page
        adj = self._adj(page)
        frac = self._cursor_frac(page)
        ok, it = page.buffer.get_iter_at_line(100)
        _y, h = page.view.get_line_yrange(it)
        line_h = h or 20
        # 33% 位置：占比 0.33 ± 2 行高（行高占视口比很小，直接用 frac 容差）
        tol = 2 * line_h / (adj.get_page_size() or 1.0)
        self.out["combo_frac_ok"] = abs(frac - 0.33) <= tol
        self.out["combo_writing_still"] = self.app.window._writing_mode == "75"
        # 收尾：快捷键加速键可解析（Ctrl+Shift+T）
        ok, _k, _m = Gtk.accelerator_parse("<Control><Shift>T")
        self.out["accel_parse_ok"] = bool(ok)
        self.finish()
        return False


if __name__ == "__main__":
    TypewriterTest().run()
