"""目录搜索 / 批量替换 界面层测试（真实 GTK，临时数据目录）。

流程：建临时目录 → 搜索对话框出结果 → 右键菜单 → 单击只选中 → 双击打开并选中关键词 →
从结果行「替换此内容…」只改一个文件 → 整目录替换 → 校验文件内容、备份目录、标签刷新。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(ROOT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.fssearch_ui import (  # noqa: E402
    FolderReplaceDialog,
    FolderSearchDialog,
    _HitRow,
)

KEY = "关键内容"
NEW = "关键字"


class FsUiTest:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.docs = self.base / "docs"
        (self.docs / "sub").mkdir(parents=True)
        (self.docs / "a.md").write_text(f"alpha\n{KEY}\nbeta\n", encoding="utf-8")
        (self.docs / "sub" / "b.md").write_text(f"{KEY} also\n", encoding="utf-8")
        (self.docs / "gbk.md").write_bytes(f"{KEY}\n".encode("gb18030"))
        (self.docs / "skip.bin.md").write_bytes(b"\x00\x01\x02")
        (self.docs / "esc.md").write_text("开头\n跨越\n换行\n结尾\n", encoding="utf-8")
        self.data = self.base / "data"
        self.data.mkdir()
        os.environ["XDG_DATA_HOME"] = str(self.data)

        self.app = ScratchpadApp()
        # 用户可能正开着 gscratchpad：单实例会让测试进程直接退出（window 恒为 None）
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.step = 0
        self._tries = 0

    # ------------------------------------------------------------------ 流程

    def run(self) -> None:
        GLib.idle_add(self.s0_search)
        GLib.timeout_add(40000, self.app.quit)
        self.app.run(["fssearch-ui-test"])

    def finish(self) -> None:
        print(self.out, flush=True)
        self.app.quit()

    def _wait(self, predicate, then, tries: int = 60) -> bool:
        """轮询等待（100ms 一次），超时记失败。"""
        state = {"n": 0}

        def tick() -> bool:
            state["n"] += 1
            try:
                ok = predicate()
            except Exception as exc:  # noqa: BLE001
                self.out["error"] = f"{type(exc).__name__}: {exc}"
                self.finish()
                return False
            if ok:
                then()
                return False
            if state["n"] >= tries:
                self.out["timeout"] = predicate.__name__ if hasattr(predicate, "__name__") else "?"
                self.finish()
                return False
            return True

        GLib.timeout_add(100, tick)
        return False

    def s0_search(self) -> bool:
        window = self.app.window
        window.new_tab("txt")
        self.dialog = FolderSearchDialog(window)
        self.dialog.present(window)
        self.dialog._set_folder(self.docs, remember=False)
        self.dialog.entry.set_text(KEY)
        self.dialog._run_now()
        self._wait(lambda: self.dialog._outcome is not None, self.s1_check_search)
        return False

    def s1_check_search(self) -> None:
        outcome = self.dialog._outcome
        self.out["matched_files"] = outcome.matched_files
        self.out["total_hits"] = outcome.total_hits
        self.out["skipped"] = outcome.skipped
        hits, heads = 0, 0
        child = self.dialog.results.get_first_child()
        while child is not None:
            if isinstance(child, _HitRow):
                hits += 1
            else:
                heads += 1
            child = child.get_next_sibling()
        self.out["rows"] = hits
        self.out["file_heads"] = heads
        self.out["dialog_height"] = self.dialog.get_height()
        self.out["dialog_mapped"] = self.dialog.get_mapped()
        # 转义：输入字面量 \n，应命中跨行内容
        self.dialog.entry.set_text(r"跨越\n换行")
        self.dialog._run_now()
        self._wait(
            lambda: self.dialog._outcome is not None and self.dialog._outcome.pattern == "跨越\n换行",
            self.s1b_escape,
        )
        return None

    def s1b_escape(self) -> None:
        outcome = self.dialog._outcome
        self.out["escape_hits"] = outcome.total_hits
        hit = outcome.files[0].hits[0] if outcome.files else None
        self.out["escape_line"] = hit.line_no if hit else -1
        self.out["escape_excerpt"] = hit.excerpt if hit else ""
        self.out["escape_highlight_skipped"] = "⏎" in (hit.excerpt if hit else "")
        # 回到原关键词，继续走「双击结果行 → 打开文件定位并选中关键词」的流程
        self.dialog.entry.set_text(KEY)
        self.dialog._run_now()
        self._wait(
            lambda: self.dialog._outcome is not None and self.dialog._outcome.pattern == KEY,
            self.s1c_click,
        )
        return None

    def _find_row(self, dialog, name: str, line: int | None = None):
        child = dialog.results.get_first_child()
        while child is not None:
            if isinstance(child, _HitRow) and child.path.name == name:
                if line is None or child.line_no == line:
                    return child
            child = child.get_next_sibling()
        return None

    def s1c_click(self) -> None:
        row = self._find_row(self.dialog, "a.md", 2)
        self.out["hit_row_found"] = row is not None
        self.out["hit_length"] = row.hit.length if row else -1
        self.out["hit_column"] = row.hit.column if row else -1

        # 右键菜单：必须有「替换此内容…」
        labels = row.menu_labels() if row else []
        self.out["menu_labels"] = labels
        self.out["menu_has_replace"] = "替换此内容…" in labels
        self.out["menu_has_open"] = "打开并定位到此行" in labels

        # 单击只选中，不打开、不关闭对话框
        pages_before = self.app.window.tabview.get_n_pages()
        row._on_press(None, 1, 0, 0)
        self.out["single_click_selected"] = self.dialog._current_row is row
        self.out["single_click_no_open"] = (
            self.app.window.tabview.get_n_pages() == pages_before and self.dialog.get_mapped()
        )
        # 双击才打开
        row._on_press(None, 2, 0, 0)
        GLib.timeout_add(900, self.s2_check_goto)
        return None

    def s2_check_goto(self) -> bool:
        window = self.app.window
        page = window._current_page()
        self.out["goto_title"] = page.title if page else None
        buf = page.buffer
        self.out["goto_line"] = buf.get_iter_at_mark(buf.get_insert()).get_line() + 1
        bounds = buf.get_selection_bounds()
        self.out["goto_selected"] = (
            buf.get_text(bounds[0], bounds[1], False) if bounds and bounds[0] is not None else ""
        )
        self.out["goto_selected_is_key"] = self.out["goto_selected"] == KEY
        self.s2b_replace_from_row()
        return False

    def s2b_replace_from_row(self) -> None:
        """结果行右键「替换此内容…」：只勾选该文件，其它文件不动。"""
        window = self.app.window
        self.dialog2 = FolderSearchDialog(window)
        self.dialog2.present(window)
        self.dialog2._set_folder(self.docs, remember=False)
        self.dialog2.entry.set_text(KEY)
        self.dialog2._run_now()

        def pick() -> None:
            row = self._find_row(self.dialog2, "b.md")
            self.out["replace_row_found"] = row is not None
            row.replace_target()  # 关闭搜索框，带参打开替换对话框
            self._wait(
                lambda: getattr(self.dialog2, "replace_dialog", None) is not None
                and self.dialog2.replace_dialog._plan is not None,
                self.s2c_check_prefill,
                tries=80,
            )

        self._wait(
            lambda: self.dialog2._outcome is not None and self.dialog2._outcome.pattern == KEY,
            pick,
        )
        return None

    def s2c_check_prefill(self) -> None:
        rd = self.dialog2.replace_dialog
        self.out["prefill_find"] = rd.find_entry.get_text()
        self.out["prefill_folder"] = str(rd._folder)
        self.out["prefill_case"] = rd.case_switch.get_active()
        self.out["prefill_regex"] = rd.regex_switch.get_active()
        checked = [item.rel for check, item in rd._rows if check.get_active()]
        unchecked = [item.rel for check, item in rd._rows if not check.get_active()]
        self.out["only_checked"] = checked
        self.out["only_unchecked"] = unchecked
        self.out["only_file_single"] = checked == ["sub/b.md"] or checked == [str(Path("sub") / "b.md")]
        self.out["status_mentions_only"] = "只勾选" in rd.status.get_text()

        # 执行：只改 b.md，a.md 必须保持原样
        rd.replace_entry.set_text(NEW)
        # 改替换内容必须作废旧预览（否则会拿空替换串把命中处删掉）
        self.out["invalidate_on_replace_change"] = rd._plan is None
        self.out["apply_disabled_after_change"] = not rd.apply_button.get_sensitive()
        rd._start_preview()
        self._wait(
            lambda: rd._plan is not None, self.s2d_apply_only, tries=80
        )
        return None

    def s2d_apply_only(self) -> None:
        rd = self.dialog2.replace_dialog
        self.out["only_apply_total"] = rd._plan.total_replacements
        rd._apply([item.path for check, item in rd._rows if check.get_active()])
        self._wait(
            lambda: (not rd._busy) and rd._plan is None, self.s2e_check_applied, tries=80
        )
        return None

    def s2e_check_applied(self) -> None:
        self.out["only_b_replaced"] = (self.docs / "sub" / "b.md").read_text(encoding="utf-8")
        self.out["only_a_untouched"] = (self.docs / "a.md").read_text(encoding="utf-8")
        self.out["only_a_kept_key"] = KEY in self.out["only_a_untouched"]
        self.out["only_b_correct"] = self.out["only_b_replaced"] == f"{NEW} also\n"
        self.dialog2.replace_dialog.close()
        self.s3_replace()

    def s3_replace(self) -> None:
        window = self.app.window
        self.rdialog = FolderReplaceDialog(window)
        self.rdialog.present(window)
        self.rdialog._set_folder(self.docs, remember=False)
        self.rdialog.find_entry.set_text(KEY)
        self.rdialog.replace_entry.set_text(NEW)
        self.rdialog._start_preview()
        self._wait(lambda: self.rdialog._plan is not None, self.s4_check_plan)
        return None

    def s4_check_plan(self) -> None:
        plan = self.rdialog._plan
        self.out["plan_files"] = len(plan.changed_files)
        self.out["plan_total"] = plan.total_replacements
        self.out["plan_rows"] = len(self.rdialog._rows)
        self.out["apply_sensitive"] = self.rdialog.apply_button.get_sensitive()
        # 直接执行（跳过确认弹窗，弹窗逻辑单独由 alert 覆盖）
        self.rdialog._apply([item.path for item in plan.changed_files])
        self._wait(
            lambda: (not self.rdialog._busy) and self.rdialog._plan is None,
            self.s5_check_result,
        )
        return None

    def s5_check_result(self) -> None:
        self.out["a_md"] = (self.docs / "a.md").read_text(encoding="utf-8")
        self.out["b_md"] = (self.docs / "sub" / "b.md").read_text(encoding="utf-8")
        gbk_raw = (self.docs / "gbk.md").read_bytes()
        self.out["gbk_text"] = gbk_raw.decode("gb18030")
        self.out["gbk_still_gbk"] = b"\xe5\x85\xb3" not in gbk_raw  # 未被改写成 UTF-8
        self.out["skip_untouched"] = (self.docs / "skip.bin.md").read_bytes() == b"\x00\x01\x02"
        backups = list((self.data / "gscratchpad" / "replace-backups").rglob("*.md"))
        self.out["backup_files"] = len(backups)
        # 已打开标签是否同步刷新
        page = self.app.window._current_page()
        self.out["tab_refreshed"] = NEW in page.snapshot_text() and KEY not in page.snapshot_text()
        self.out["status"] = self.rdialog.status.get_text().splitlines()[0]
        self.rdialog.close()
        # 安全分支：应用内改过的标签不应被自动刷新覆盖
        page.buffer.insert_at_cursor("本地改动", -1)
        before = {str((self.docs / "a.md").resolve()): "替换前的旧内容（与当前编辑内容不同）"}
        reloaded, skipped = self.app.window.reload_source_tabs(
            [self.docs / "a.md"], before
        )
        self.out["dirty_reloaded"] = reloaded
        self.out["dirty_skipped"] = skipped
        self.out["local_edit_kept"] = "本地改动" in page.snapshot_text()
        self.s6_replace_escape()

    def s6_replace_escape(self) -> None:
        """替换对话框里输入字面量 \\n：预览必须命中跨行内容，且只读不写。"""
        window = self.app.window
        dialog = FolderReplaceDialog(window)
        dialog.present(window)
        dialog._set_folder(self.docs, remember=False)
        dialog.find_entry.set_text(r"跨越\n换行")
        dialog.replace_entry.set_text("合并")
        dialog._start_preview()

        def check() -> None:
            plan = dialog._plan
            self.out["escape_replace_files"] = len(plan.changed_files) if plan else -1
            self.out["escape_replace_total"] = plan.total_replacements if plan else -1
            self.out["escape_preview_readonly"] = (
                self.docs / "esc.md"
            ).read_text(encoding="utf-8") == "开头\n跨越\n换行\n结尾\n"
            dialog.close()
            self.finish()

        self._wait(lambda: dialog._plan is not None, check)


if __name__ == "__main__":
    FsUiTest().run()
