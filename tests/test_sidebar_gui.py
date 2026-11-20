"""侧边栏（笔记列表 / 文件夹 / 磁盘树）界面层测试。

用临时 HOME（磁盘树根）+ 临时数据目录（SQLite）跑真实 GTK 应用：
- 三种笔记视图（最近 / 未关闭 / 按格式）与标题筛选
- 侧栏显隐按钮与 F9 动作、持久化
- 文件夹：创建、移动、展开显示、未归档
- 磁盘树：根限定 $HOME、懒加载、reveal 自动定位、点文件打开标签
- 文档操作：open_document 重开已关闭文档、删除后侧栏刷新
"""

from __future__ import annotations

import os
import shutil
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

TMP = Path(tempfile.mkdtemp(prefix="sidebar-gui-"))
HOME = TMP / "home"
DATA = TMP / "data"


def _rows(listbox) -> list:
    child = listbox.get_first_child()
    out = []
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


class SidebarTest:
    def __init__(self) -> None:
        (HOME / "docs" / "sub").mkdir(parents=True)
        DATA.mkdir(parents=True)
        (HOME / "docs" / "a.md").write_text("# A\n", encoding="utf-8")
        (HOME / "docs" / "sub" / "b.txt").write_text("hello\n", encoding="utf-8")
        (HOME / "outside.bin").write_bytes(b"\x00\x01")
        os.environ["XDG_DATA_HOME"] = str(DATA)
        os.environ["HOME"] = str(HOME)  # 磁盘树根 = 测试用主目录
        self.app = ScratchpadApp()
        # 用户日常可能正开着 gscratchpad：单实例会让测试进程直接退出（window 恒为 None）
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.idle_add(self.s0_basic)
        GLib.timeout_add(40000, self.app.quit)
        self.app.run(["sidebar-gui-test"])

    def finish(self) -> None:
        print(self.out, flush=True)
        self.app.quit()

    def page(self):
        tab = self.app.window.tabview.get_selected_page()
        return tab.get_child() if tab is not None else None

    # ------------------------------------------------------------------ 步骤

    def s0_basic(self) -> None:
        w = self.app.window
        sb = w.sidebar
        self.out["layout"] = type(w.overlay).__name__
        self.out["floating_frame"] = w.sidebar_frame.has_css_class("sidebar-float")
        self.out["initial_visible"] = w.sidebar_visible()
        self.out["initial_view"] = sb.shown_view()

        # 磁盘页必须是「切过去就有内容」，而不是等 reveal_local_path 才加载
        sb.show_view("disk")
        disk_rows = _rows(sb.disk_list)
        self.out["disk_rows_on_switch"] = len(disk_rows)
        self.out["disk_has_docs"] = any(
            getattr(r, "path", None) and Path(r.path).name == "docs" for r in disk_rows
        )
        sb.show_view("notes")

        # 造数据：两个 md、一个 txt，其中一个关掉
        a = w.new_tab("md")
        a.title = "笔记甲"
        w.store.rename(a.doc_id, "笔记甲")
        a.buffer.set_text("# 甲\n", -1)
        b = w.new_tab("txt")
        b.title = "笔记乙"
        w.store.rename(b.doc_id, "笔记乙")
        b.buffer.set_text("hello\n", -1)
        c = w.new_tab("md")
        c.title = "笔记丙"
        w.store.rename(c.doc_id, "笔记丙")
        c.buffer.set_text("# 丙\n", -1)
        self._doc_a = a.doc_id
        self._doc_b = b.doc_id
        self._doc_c = c.doc_id

        # 关闭丙（模拟「已关闭的文档」）
        w._save_page(c, wait=True)
        w.store.set_state(c.doc_id, "closed")
        w.tabview.close_page(c.tab)
        w._refresh_sidebar_now()

        titles = [r.doc.title for r in _rows(sb.notes_list) if getattr(r, "doc", None)]
        self.out["recent_titles"] = titles
        self.out["recent_has_closed"] = "笔记丙" in titles

        # 切到「未关闭」
        sb.filter_drop.set_selected(1)
        self.out["open_titles"] = [
            r.doc.title for r in _rows(sb.notes_list) if getattr(r, "doc", None)
        ]

        # 切到「按格式」→ 出组头
        sb.filter_drop.set_selected(2)
        rows = _rows(sb.notes_list)
        headers = [
            r.get_child().get_text()
            for r in rows
            if getattr(r, "doc", None) is None and r.get_child() is not None
            and isinstance(r.get_child(), Gtk.Label)
        ]
        self.out["format_headers"] = headers
        self.out["format_docs"] = [
            r.doc.title for r in rows if getattr(r, "doc", None)
        ]

        # 标题筛选
        sb.search_entry.set_text("笔记甲")
        self.out["filtered_titles"] = [
            r.doc.title for r in _rows(sb.notes_list) if getattr(r, "doc", None)
        ]
        sb.search_entry.set_text("")
        sb.filter_drop.set_selected(0)

        GLib.timeout_add(300, self.s1_toggle)
        return None

    def s1_toggle(self) -> None:
        w = self.app.window
        w.sidebar_button.set_active(False)
        self.out["hidden"] = not w.sidebar_visible()
        self.out["meta_hidden"] = w.store.get_meta("sidebar_visible")
        w.activate_action("win.toggle-sidebar", None)
        self.out["reshown"] = w.sidebar_visible()
        self.out["meta_shown"] = w.store.get_meta("sidebar_visible")
        GLib.timeout_add(200, self.s2_folders)
        return None

    def s2_folders(self) -> None:
        w = self.app.window
        sb = w.sidebar
        sb.store.create_folder("工作")
        sb.move_document(self._doc_a, "工作")
        sb._expanded_folders.add("工作")
        sb.refresh_folders()
        folder_rows = [r for r in _rows(sb.folders_list) if hasattr(r, "name")]
        self.out["folder_names"] = [r.name for r in folder_rows]
        work = next(r for r in folder_rows if r.name == "工作")
        self.out["work_expanded"] = work.get_expanded()
        self.out["work_children"] = [
            r.doc.title for r in _rows(work.children_list) if getattr(r, "doc", None)
        ]
        # 未归档还剩 乙
        inbox = next(r for r in folder_rows if r.name == "")
        self.out["inbox_children"] = [
            r.doc.title for r in _rows(inbox.children_list) if getattr(r, "doc", None)
        ]
        # store 层确认
        self.out["doc_a_folder"] = w.store.doc_folder_of(self._doc_a)
        GLib.timeout_add(200, self.s3_disk)
        return None

    def s3_disk(self) -> None:
        w = self.app.window
        sb = w.sidebar
        self.out["disk_root"] = str(sb._disk_root) == str(HOME)
        # HOME 外的路径不展开
        outside = sb.reveal_local_path(str(TMP / "outside.bin"))
        self.out["outside_rejected"] = outside is False
        # 定位到 docs/sub/b.txt：逐级展开并选中
        ok = sb.reveal_local_path(HOME / "docs" / "sub" / "b.txt")
        self.out["reveal_ok"] = ok
        self.out["view_switched"] = sb.shown_view() == "disk"
        self.out["expanded_dirs"] = [
            str(Path(p).relative_to(HOME)) for p in sorted(sb._dir_rows)
        ]
        row = sb._file_rows.get(str(HOME / "docs" / "sub" / "b.txt"))
        self.out["file_row_found"] = row is not None
        if row is not None:
            row.open()
        GLib.timeout_add(900, self.s4_after_open)
        return None

    def s4_after_open(self) -> None:
        w = self.app.window
        sb = w.sidebar
        page = self.page()
        linked = w.store.source_path_of(page.doc_id) if page else None
        self.out["opened_is_b"] = bool(linked and linked.endswith("b.txt"))
        # 打开 → 磁盘树已定位（再次 reveal 幂等）
        self.out["reveal_again_ok"] = sb.reveal_local_path(HOME / "docs" / "a.md")
        GLib.timeout_add(300, self.s5_lifecycle)
        return None

    def s5_lifecycle(self) -> None:
        w = self.app.window
        sb = w.sidebar
        # 重开已关闭的笔记丙
        page = w.open_document(self._doc_c)
        self.out["reopen_ok"] = page is not None and page.doc_id == self._doc_c
        self.out["reopen_state"] = w.store.get(self._doc_c).state
        # 删除笔记乙（绕过确认弹窗，直接执行删除逻辑）
        w._delete_document_now(self._doc_b)
        self.out["deleted_gone"] = w.store.get(self._doc_b) is None
        w._refresh_sidebar_now()
        titles = [
            r.doc.title for r in _rows(sb.notes_list) if getattr(r, "doc", None)
        ]
        self.out["after_delete_titles"] = titles
        # 侧栏菜单动作切换视图
        w.activate_action("win.sidebar-view", GLib.Variant.new_string("folders"))
        self.out["view_folders"] = sb.shown_view() == "folders"
        w.activate_action("win.sidebar-view", GLib.Variant.new_string("notes"))
        self.out["view_notes"] = sb.shown_view() == "notes"
        GLib.timeout_add(200, self.s6_outline)

    def s6_outline(self) -> None:
        w = self.app.window
        sb = w.sidebar
        page = w._pages.get(self._doc_a)
        w.tabview.set_selected_page(page.tab)
        page.buffer.set_text(
            "# 甲\n\n正文\n\n## 乙 **加粗**\n\n### 丙\n\n```\n# 代码块不是标题\n```\n\n"
            + "\n\n".join(f"填充段落 {i}，用来把页面撑出滚动条。" for i in range(1, 40))
            + "\n\n## 尾部标题\n",
            -1,
        )
        w._refresh_outline_now()
        rows = [r for r in _rows(sb.outline_list) if getattr(r, "heading", None)]
        self.out["outline_texts"] = [r.heading.text for r in rows]
        self.out["outline_levels"] = [r.heading.level for r in rows]
        self.out["outline_count_label"] = sb.outline_count.get_text()

        # 点击第 3 条（### 丙，第 7 行）→ 源码光标应停在那一行
        sb._on_outline_activated(sb.outline_list, rows[2])
        it = page.buffer.get_iter_at_mark(page.buffer.get_insert())
        self.out["jumped_line"] = it.get_line() + 1

        # 非 Markdown 标签：大纲给出说明而不是沿用旧条目
        txt = w.new_tab("txt")
        txt.buffer.set_text("# 看起来像标题\n", -1)
        w._refresh_outline_now()
        self.out["outline_non_md_rows"] = len(
            [r for r in _rows(sb.outline_list) if getattr(r, "heading", None)]
        )
        self.out["outline_hint_non_md"] = sb.outline_hint.get_text()

        w.tabview.set_selected_page(page.tab)
        w._refresh_outline_now()
        self.out["outline_restored"] = len(
            [r for r in _rows(sb.outline_list) if getattr(r, "heading", None)]
        )
        GLib.timeout_add(200, self.s7_preview_jump)

    def s7_preview_jump(self) -> None:
        """纯预览模式点大纲 → 预览 WebView 应滚动到对应标题。"""
        from scratchpad.editor import MODE_PREVIEW

        w = self.app.window
        page = self.page()
        self.out["jump_page_fmt"] = page.format
        w.set_mode(MODE_PREVIEW)
        GLib.timeout_add(2500, self.s7_click_outline)

    def s7_click_outline(self) -> None:
        w = self.app.window
        sb = w.sidebar
        rows = [r for r in _rows(sb.outline_list) if getattr(r, "heading", None)]
        self.out["preview_outline_rows"] = len(rows)
        if not rows:
            self.finish()
            return
        target = rows[-1]  # 最后一个标题（「四、结尾」）
        sb._on_outline_activated(sb.outline_list, target)
        GLib.timeout_add(900, self.s7_check_scroll)

    def s7_check_scroll(self) -> None:
        page = self.page()
        view = page.preview._view if page is not None else None
        if view is None:
            self.out["preview_scrolled"] = "no webview"
            self.finish()
            return

        def on_done(v, result, _data):
            try:
                value = v.evaluate_javascript_finish(result).to_double()
                self.out["preview_scrolled"] = value > 0
                self.out["preview_scroll_y"] = value
            except Exception as exc:  # noqa: BLE001
                self.out["preview_scrolled"] = f"err: {exc}"
            GLib.timeout_add(100, self.s8_sort)

        view.evaluate_javascript("window.scrollY", -1, None, None, None, on_done, None)

    # ------------------------------------------------------------------ 排序

    def s8_sort(self) -> None:
        import time as _time

        from scratchpad.editor import MODE_SOURCE

        w = self.app.window
        sb = w.sidebar
        w.set_mode(MODE_SOURCE)

        # 按 B → A → C 的顺序重命名，制造可预测的 updated_at
        for name in ("sort-B", "sort-A", "sort-C"):
            page = w.new_tab("txt", activate=False)
            page.title = name
            w.store.rename(page.doc_id, name)
            _time.sleep(0.03)

        sb.search_entry.set_text("sort-")
        titles = lambda: [  # noqa: E731
            r.doc.title for r in _rows(sb.notes_list) if getattr(r, "doc", None)
        ]
        sb.sort_drop.set_selected(0)  # 最近更新
        self.out["sort_recent"] = titles()
        sb.sort_drop.set_selected(1)  # 最早更新
        self.out["sort_oldest"] = titles()
        sb.sort_drop.set_selected(2)  # 标题 A→Z
        self.out["sort_title_asc"] = titles()
        sb.sort_drop.set_selected(3)  # 标题 Z→A
        self.out["sort_title_desc"] = titles()
        self.out["sort_meta"] = w.store.get_meta("sidebar_sort")

        # 文件夹视图也应按同一规则排序
        sb.filter_drop.set_selected(0)
        sb.refresh_folders()
        inbox = next(r for r in _rows(sb.folders_list) if getattr(r, "name", None) == "")
        self.out["folder_sorted"] = [
            r.doc.title for r in _rows(inbox.children_list) if getattr(r, "doc", None)
        ][:3]

        sb.search_entry.set_text("")
        sb.sort_drop.set_selected(0)
        GLib.timeout_add(200, self.s9_menu)

    # ------------------------------------------------------------------ 命令菜单

    def s9_menu(self) -> None:
        from scratchpad.command_menu import Command, CommandRow

        w = self.app.window
        sections = w._menu_sections()
        self.out["menu_sections"] = [s.title for s in sections]
        self.out["menu_total"] = sum(len(s.items) for s in sections)
        self.out["menu_accel_ctrl_f"] = w._accel_for("win.find")
        self.out["menu_accel_f9"] = w._accel_for("win.toggle-sidebar")

        menu = w.command_menu
        menu.popup_with_search()
        GLib.timeout_add(600, self.s9_check)

    def s9_check(self) -> None:
        from scratchpad.command_menu import Command, CommandRow

        w = self.app.window
        menu = w.command_menu

        def labels():
            return [r.command.label for r in _rows(menu.listbox) if isinstance(r, CommandRow)]

        self.out["menu_popup_visible"] = menu.get_visible()
        self.out["menu_search_mapped"] = menu.search.get_mapped()
        # 键盘焦点在 popover 自己的 surface 里，has_focus() 对独立 surface 不适用，
        # 这里断言 grab_focus 被接受（真实按键已用 XTEST 单独验证过）
        self.out["menu_search_focusable"] = menu.search.grab_focus()
        self.out["menu_all_rows"] = len(labels())

        menu.search.set_text("pdf")
        self.out["menu_search_pdf"] = labels()
        menu.search.set_text("大纲")
        self.out["menu_search_outline"] = labels()
        menu.search.set_text("保存")
        self.out["menu_search_save"] = labels()
        menu.search.set_text("zzzz-nothing")
        self.out["menu_search_empty"] = labels()
        menu.search.set_text("")

        # 命令派发：走真实 action 链路（新建标签）
        before = w.tabview.get_n_pages()
        menu.emit("command", Command("新建标签", "win.new-tab"))
        self.out["menu_command_worked"] = w.tabview.get_n_pages() == before + 1

        # Ctrl+K action 能打开菜单
        menu.popdown()
        GLib.timeout_add(300, self.s9_ctrl_k)

    def s9_ctrl_k(self) -> None:
        w = self.app.window
        w.activate_action("win.command-menu", None)
        GLib.timeout_add(500, self.s9_finish)

    def s9_finish(self) -> None:
        w = self.app.window
        self.out["ctrl_k_opens_menu"] = w.command_menu.get_visible()
        w.command_menu.popdown()
        self.finish()


if __name__ == "__main__":
    SidebarTest().run()
