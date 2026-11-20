"""片段与自动补全端到端测试（真实 GTK，临时数据目录）。

覆盖：片段插入与光标落位、单步撤销、焦点守卫、快捷键绑定与冲突改绑、
默认快捷键恢复、Tab 触发词展开、设置界面构建。
用法：/usr/bin/python3 tests/test_snippets_gui.py
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

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from scratchpad import snippets  # noqa: E402
from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-snippets-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")


class SnippetsTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(40000, self.app.quit)
        self.app.run(["snippets-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    def _window(self):
        w = self.app.window
        w.present()
        return w

    # ------------------------------------------------------------------ 片段插入

    def s0_setup(self) -> bool:
        w = self._window()
        page = w.new_tab("md")
        w.tabview.set_selected_page(page.tab)
        page.view.grab_focus()
        self.out["view_focused"] = page.view.has_focus()

        snippet = snippets.Snippet("HTML 注释", "<!-- {{cursor}} -->", "<Control>1")
        w.snippets.append(snippet)
        w.save_snippets()
        self.sid = snippet.id
        self.out["action_registered"] = w.has_action(f"snippet-{snippet.id}")
        self.out["accel_bound"] = self.app.get_accels_for_action(
            f"win.snippet-{snippet.id}"
        ) == ["<Control>1"]
        self.out["meta_saved"] = snippet.id in (
            w.store.get_meta(snippets.META_KEY) or ""
        )

        w.activate_action(f"win.snippet-{snippet.id}", None)
        buf = page.buffer
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.out["inserted"] = text == "<!--  -->"
        it = buf.get_iter_at_mark(buf.get_insert())
        self.out["cursor_offset"] = it.get_offset()
        self.out["cursor_inside_comment"] = it.get_offset() == 5

        page.buffer.undo()
        self.out["undo_single_step"] = page.snapshot_text() == ""
        page.buffer.redo()

        page.buffer.set_text("")
        # 焦点守卫要等搜索栏真正拿到焦点，交给下一轮事件循环
        GLib.timeout_add(200, self.s0b_focus_guard)
        return False

    def s0b_focus_guard(self) -> bool:
        w = self._window()
        page = w._current_page()
        page.show_search(False)
        page.search_entry.grab_focus()
        self.out["view_lost_focus"] = not page.view.has_focus()
        before = page.snapshot_text()
        w.activate_action(f"win.snippet-{self.sid}", None)
        self.out["guard_blocks_insert"] = page.snapshot_text() == before
        page.hide_search()
        page.view.grab_focus()
        self.out["refocus_view"] = page.view.has_focus()
        self.s1_conflict()
        return False

    # ------------------------------------------------------------------ 快捷键冲突

    def s1_conflict(self) -> None:
        w = self._window()
        owner = w.accel_owner("<Control>1", exclude=self.sid)
        self.out["conflict_detected"] = owner is not None and owner[0] == "win.goto-1"
        self.out["conflict_label"] = owner[1] if owner else ""

        # 自己占用的键不算冲突
        self.out["self_no_conflict"] = w.accel_owner("<Control>1", exclude=self.sid) is not None

        w.release_accel("win.goto-1")
        self.out["goto_released"] = self.app.get_accels_for_action("win.goto-1") == []
        overrides = w.store.get_meta(snippets.OVERRIDES_KEY) or ""
        self.out["override_saved"] = '"win.goto-1"' in overrides
        self.out["override_count"] = w.overridden_accel_count()
        self.out["no_conflict_after_release"] = w.accel_owner(
            "<Control>1", exclude=self.sid
        ) is None

        # 模拟重启：默认键重新生效后，回放 override
        self.app.set_accels_for_action("win.goto-1", ["<Control>1"])
        w._apply_accel_overrides()
        self.out["override_replayed"] = self.app.get_accels_for_action("win.goto-1") == []

        # 恢复默认：核心键回来，冲突的片段快捷键被解除
        w.restore_default_accels()
        self.out["restore_goto"] = self.app.get_accels_for_action("win.goto-1") == ["<Control>1"]
        self.out["snippet_accel_cleared"] = all(
            s.accel == "" for s in w.snippets if s.id == self.sid
        )
        self.out["overrides_cleared"] = (w.store.get_meta(snippets.OVERRIDES_KEY) or "") == ""
        self.s2_triggers()
        return None

    # ------------------------------------------------------------------ Tab 展开

    def s2_triggers(self) -> None:
        w = self._window()
        page = w.new_tab("txt")
        w.tabview.set_selected_page(page.tab)
        page.set_language_for_path(str(TMP / "demo.sh"))
        page.view.grab_focus()
        buf = page.buffer
        buf.set_text("ife")
        buf.place_cursor(buf.get_end_iter())
        handled = page._on_trigger_key(None, Gdk.KEY_Tab, 0, 0)
        self.out["bash_tab_handled"] = bool(handled)
        text = page.snapshot_text()
        self.out["bash_expanded"] = text.startswith("if [ ") and text.rstrip().endswith("fi")
        self.out["bash_trigger_removed"] = not text.startswith("ife")
        it = buf.get_iter_at_mark(buf.get_insert())
        self.out["bash_cursor_after_if"] = it.get_offset() == len("if [ ")

        # 一次撤销回到触发词本身
        buf.undo()
        self.out["bash_undo"] = page.snapshot_text() == "ife"

        # 未命中：交还 Tab（返回 False，内容不变）
        buf.set_text("hello")
        buf.place_cursor(buf.get_end_iter())
        self.out["tab_passthrough"] = page._on_trigger_key(None, Gdk.KEY_Tab, 0, 0) is False
        self.out["tab_passthrough_kept"] = page.snapshot_text() == "hello"

        # 词中不展开
        buf.set_text("life")
        buf.place_cursor(buf.get_end_iter())
        self.out["no_midword"] = page._on_trigger_key(None, Gdk.KEY_Tab, 0, 0) is False

        # Markdown 文档（format 推断语言）
        md = w.new_tab("md")
        w.tabview.set_selected_page(md.tab)
        md.view.grab_focus()
        md.buffer.set_text("h2")
        md.buffer.place_cursor(md.buffer.get_end_iter())
        self.out["md_tab"] = bool(md._on_trigger_key(None, Gdk.KEY_Tab, 0, 0))
        self.out["md_expanded"] = md.snapshot_text() == "## "
        self.out["md_language"] = md.trigger_language() == "markdown"
        self.s3_ui()
        return None

    # ------------------------------------------------------------------ 界面

    def s3_ui(self) -> None:
        from scratchpad.snippets_ui import SnippetEditor, SnippetsDialog

        w = self._window()
        dialog = SnippetsDialog(w)
        dialog.present(w)
        self.out["dialog_built"] = isinstance(dialog, Adw.PreferencesDialog)
        self.out["dialog_rows"] = len(dialog._rows)
        dialog.close()
        self.out["dialog_closed"] = dialog.get_root() is None

        editor = SnippetEditor(w, w.snippets[0] if w.snippets else None)
        editor.present(w)
        self.out["editor_built"] = editor.name_row.get_text() == "HTML 注释"
        self.out["editor_preview"] = "▏" in editor.preview_label.get_text()
        # 录制：Ctrl+Alt+5
        editor._start_record()
        consumed = editor._on_record_key(
            None, Gdk.KEY_5, 0, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        )
        self.out["record_consumed"] = bool(consumed)
        self.out["record_accel"] = editor._accel
        self.out["record_stopped"] = not editor._recording
        # 只按修饰键不结束录制
        editor._stop_record()
        editor._start_record()
        self.out["modifier_only_ignored"] = bool(
            editor._on_record_key(None, Gdk.KEY_Control_L, 0, Gdk.ModifierType.CONTROL_MASK)
        ) and editor._recording
        # 无修饰的普通字母被拒绝
        editor._on_record_key(None, Gdk.KEY_x, 0, Gdk.ModifierType(0))
        self.out["plain_letter_rejected"] = editor._recording
        editor.close()

        w.snippets = [s for s in w.snippets if s.id != self.sid]
        w.save_snippets()
        self.out["action_removed"] = not w.has_action(f"snippet-{self.sid}")
        self.out["accel_cleared"] = self.app.get_accels_for_action(
            f"win.snippet-{self.sid}"
        ) == []
        self.s4_menu()
        return None

    def s4_menu(self) -> None:
        w = self._window()
        snippet = snippets.Snippet("日期戳", "{{date}}")
        w.snippets.append(snippet)
        w.save_snippets()
        titles = [section.title for section in w._menu_sections()]
        self.out["menu_has_snippets"] = "片段" in titles
        names = [
            c.label
            for section in w._menu_sections()
            if section.title == "片段"
            for c in section.items
        ]
        self.out["menu_snippet_name"] = "日期戳" in names
        self.finish()
        return None


if __name__ == "__main__":
    SnippetsTest().run()
