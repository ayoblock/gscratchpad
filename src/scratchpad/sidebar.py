"""左侧边栏：笔记列表（最近 / 未关闭 / 按格式）、文件夹、本机磁盘树（限定 $HOME）。

设计要点：

1. 侧栏只读数据库的“视图”，所有写操作（改文件夹、重命名、删除）都回调给主窗口，
   由主窗口统一走 store 的工作线程，避免两处各自写库。
2. 磁盘树严格限制在 `$HOME` 内：根节点固定为主目录，`reveal()` 拒绝主目录之外的路径，
   避免误把整个文件系统当树来浏览。
3. 磁盘树懒加载：只有展开某个目录时才枚举它（单层），并且限制条目数，
   主目录下成千上万个文件也不会卡住 UI。
4. 「自动定位」复用同一套 `reveal()`：手动打开文件、拖放打开、目录搜索跳转、
   另存为之后都会调用，逐级展开父目录并选中目标文件。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

VIEW_NOTES = "notes"
VIEW_FOLDERS = "folders"
VIEW_DISK = "disk"
VIEW_OUTLINE = "outline"

FILTER_RECENT = "recent"
FILTER_OPEN = "open"
FILTER_FORMAT = "format"

FILTER_LABELS = (
    (FILTER_RECENT, "最近更新"),
    (FILTER_OPEN, "未关闭"),
    (FILTER_FORMAT, "按格式"),
)

SORT_UPDATED_DESC = "updated_desc"
SORT_LABELS = (
    (SORT_UPDATED_DESC, "最近更新"),
    ("updated_asc", "最早更新"),
    ("title_asc", "标题 A→Z"),
    ("title_desc", "标题 Z→A"),
)
SORT_DEFAULT = SORT_UPDATED_DESC

FORMAT_NAMES = {"txt": "纯文本 TXT", "md": "Markdown", "html": "网页 HTML"}
FORMAT_ICONS = {
    "txt": "text-x-generic-symbolic",
    "md": "text-markdown-symbolic",
    "html": "text-html-symbolic",
}

DISK_SORT_DEFAULT = "name_asc"
DISK_SORT_LABELS = (
    ("name_asc", "名称 A→Z"),
    ("name_desc", "名称 Z→A"),
    ("mtime_desc", "最近修改"),
    ("type_asc", "按类型"),
)

MAX_ENTRIES_PER_DIR = 400
DISK_TEXT_SUFFIXES = {
    ".txt", ".text", ".md", ".markdown", ".mkd", ".html", ".htm", ".log",
    ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".py", ".js", ".ts", ".css", ".xml", ".sh", ".c", ".h", ".cpp", ".rs",
    ".go", ".java", ".sql", ".rst", ".org", ".tex", ".bib", ".plist",
}
DISK_SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", ".git", "site-packages"}

def _human_time(ts: float) -> str:
    if ts <= 0:
        return ""
    delta = max(0.0, time.time() - ts)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    if delta < 86400 * 7:
        return f"{int(delta // 86400)} 天前"
    return time.strftime("%m-%d", time.localtime(ts))


def _collate_key(text: str):
    """标题排序键：跟随系统 locale（zh_CN 下中文按拼音，否则退化为 UTF-8 码位）。"""
    try:
        return GLib.utf8_collate_key(text or "", -1)
    except Exception:  # noqa: BLE001
        return (text or "").encode("utf-8")


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("名称不能为空")
    if len(name) > 60:
        raise ValueError("名称过长（最多 60 字）")
    if "/" in name or "\\" in name:
        raise ValueError("名称不能包含斜杠")
    return name


class Sidebar(Gtk.Box):
    """侧边栏主体。持有一个主窗口引用，用于打开/重命名/删除等写操作。"""

    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, width_request=250)
        self.window = window
        self.store = window.store
        self.set_css_classes(["gscratchpad-sidebar"])

        self._filter = FILTER_RECENT
        self._query = ""
        self._sort = self.store.get_meta("sidebar_sort", SORT_DEFAULT) or SORT_DEFAULT
        if self._sort not in {key for key, _ in SORT_LABELS}:
            self._sort = SORT_DEFAULT
        self._expanded_folders: set[str] = set()
        self._notes_rows: list[Gtk.ListBoxRow] = []
        self._outline_headings: list = []

        # 磁盘树状态
        self._disk_root: Path = Path(os.environ.get("HOME") or Path.home()).resolve()
        self._dir_rows: dict[str, "DiskDirRow"] = {}
        self._file_rows: dict[str, "DiskFileRow"] = {}
        self._disk_ready = False
        self._disk_sort = self.store.get_meta("disk_sort", DISK_SORT_DEFAULT) or DISK_SORT_DEFAULT
        if self._disk_sort not in {key for key, _ in DISK_SORT_LABELS}:
            self._disk_sort = DISK_SORT_DEFAULT

        self._build()

    # ------------------------------------------------------------------ 构建

    def _build(self) -> None:
        top = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=6,
            margin_end=6,
            margin_top=6,
            margin_bottom=2,
        )
        self.stack = Adw.ViewStack()
        self.switcher = Adw.ViewSwitcher(
            stack=self.stack,
            policy=Adw.ViewSwitcherPolicy.NARROW,
            hexpand=True,
        )
        self.switcher.set_halign(Gtk.Align.CENTER)
        top.append(self.switcher)
        self.append(top)

        self.stack.set_vexpand(True)
        self.stack.add_titled_with_icon(self._build_notes_page(), VIEW_NOTES, "笔记", "view-list-symbolic")
        self.stack.add_titled_with_icon(self._build_folders_page(), VIEW_FOLDERS, "文件夹", "folder-symbolic")
        self.stack.add_titled_with_icon(self._build_disk_page(), VIEW_DISK, "磁盘", "drive-harddisk-symbolic")
        self.stack.add_titled_with_icon(
            self._build_outline_page(), VIEW_OUTLINE, "大纲", "view-list-bullet-symbolic"
        )
        self.stack.set_visible_child_name(VIEW_NOTES)
        # 磁盘树是懒加载的：只有真正切到这一页才扫 $HOME，但必须在这一刻扫，
        # 否则用户从 ViewSwitcher 点进来只会看到一张空列表。
        self.stack.connect("notify::visible-child-name", self._on_view_changed)
        self.append(self.stack)

    # ---- 笔记页

    def _build_notes_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            margin_start=8,
            margin_end=8,
            margin_top=6,
            margin_bottom=6,
        )
        self.filter_drop = Gtk.DropDown.new_from_strings([label for _, label in FILTER_LABELS])
        self.filter_drop.set_tooltip_text("笔记视图：最近更新 / 仅未关闭 / 按格式分组")
        self.filter_drop.set_hexpand(True)
        self.filter_drop.connect("notify::selected", self._on_filter_changed)
        selector_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        selector_row.append(self.filter_drop)

        self.sort_drop = Gtk.DropDown.new_from_strings([label for _, label in SORT_LABELS])
        self.sort_drop.set_tooltip_text("排序：最近更新 / 最早更新 / 标题 A→Z / 标题 Z→A")
        self.sort_drop.set_hexpand(True)
        self.sort_drop.set_selected(
            next((i for i, (key, _) in enumerate(SORT_LABELS) if key == self._sort), 0)
        )
        self.sort_drop.connect("notify::selected", self._on_sort_changed)
        selector_row.append(self.sort_drop)
        bar.append(selector_row)

        self.search_entry = Gtk.SearchEntry(placeholder_text="筛选标题…")
        self.search_entry.connect("changed", self._on_search_changed)
        bar.append(self.search_entry)
        page.append(bar)

        self.notes_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.notes_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.notes_list.connect("row-activated", self._on_note_row_activated)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.notes_list)
        page.append(scroller)
        return page

    # ---- 文件夹页

    def _build_folders_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=10,
            margin_end=6,
            margin_top=6,
            margin_bottom=6,
        )
        title = Gtk.Label(label="文件夹", xalign=0, hexpand=True, css_classes=["dim-label"])
        bar.append(title)
        new_btn = Gtk.Button(
            icon_name="folder-new-symbolic",
            tooltip_text="新建文件夹",
            css_classes=["flat"],
        )
        new_btn.connect("clicked", lambda *_: self.prompt_new_folder())
        bar.append(new_btn)
        page.append(bar)

        self.folders_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.folders_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.folders_list)
        page.append(scroller)
        return page

    # ---- 磁盘页

    def _build_disk_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=10,
            margin_end=6,
            margin_top=6,
            margin_bottom=6,
        )
        icon = Gtk.Image(icon_name="user-home-symbolic", css_classes=["dim-label"])
        bar.append(icon)
        self.disk_label = Gtk.Label(
            label="~", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.START
        )
        self.disk_label.set_tooltip_text(str(self._disk_root))
        bar.append(self.disk_label)

        home_btn = Gtk.Button(icon_name="go-home-symbolic", tooltip_text="回到主目录", css_classes=["flat"])
        home_btn.connect("clicked", lambda *_: self.reset_disk_view())
        bar.append(home_btn)

        self.disk_sort_btn = Gtk.MenuButton(
            icon_name="view-sort-descending-symbolic",
            tooltip_text="排序方式",
            css_classes=["flat"],
        )
        self.disk_sort_popover = Gtk.Popover()
        self.disk_sort_popover.connect("show", self._fill_disk_sort_popover)
        self.disk_sort_btn.set_popover(self.disk_sort_popover)
        bar.append(self.disk_sort_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="重新读取磁盘目录", css_classes=["flat"])
        refresh_btn.connect("clicked", lambda *_: self.reload_disk())
        bar.append(refresh_btn)
        page.append(bar)

        # 用普通 Gtk.Box 而不是 Gtk.ListBox：ListBox 的点击手势在 CAPTURE 阶段
        # 会无条件 claim 事件，嵌套在目录行里的文件行根本收不到鼠标点击
        # （表现就是「点不开、右键没菜单」，而键盘激活却正常）。
        self.disk_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["disk-tree"])
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.disk_list)
        page.append(scroller)

        hint = Gtk.Label(
            label=f"仅显示 {self._disk_root} 内的文件夹与文本文件",
            xalign=0,
            wrap=True,
            margin_start=12,
            margin_end=12,
            margin_bottom=8,
            css_classes=["dim-label", "caption"],
        )
        page.append(hint)
        return page

    # ---- 大纲页

    def _build_outline_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=12,
            margin_end=6,
            margin_top=6,
            margin_bottom=6,
        )
        icon = Gtk.Image(icon_name="view-list-bullet-symbolic", css_classes=["dim-label"])
        bar.append(icon)
        self.outline_count = Gtk.Label(label="大纲", xalign=0, hexpand=True, css_classes=["dim-label"])
        bar.append(self.outline_count)
        page.append(bar)

        self.outline_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.outline_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.outline_list.connect("row-activated", self._on_outline_activated)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.outline_list)
        page.append(scroller)

        self.outline_hint = Gtk.Label(
            label="点击标题可跳转到对应位置",
            xalign=0,
            wrap=True,
            margin_start=12,
            margin_end=12,
            margin_bottom=8,
            css_classes=["dim-label", "caption"],
        )
        page.append(self.outline_hint)
        return page

    def set_outline(self, headings: list, *, fmt: str = "md") -> None:
        """用当前标签的标题列表重建大纲；非 Markdown 或没有标题时给出说明。"""
        self._outline_headings = list(headings)
        while (child := self.outline_list.get_first_child()) is not None:
            self.outline_list.remove(child)

        if fmt != "md":
            self.outline_count.set_text("大纲")
            self.outline_hint.set_text("大纲只对 Markdown 文档生效")
            self.outline_list.append(self._placeholder_row("当前标签不是 Markdown 文档"))
            return
        if not headings:
            self.outline_count.set_text("大纲")
            self.outline_hint.set_text("用 # 一级 / ## 二级 这样的写法添加标题")
            self.outline_list.append(self._placeholder_row("这篇笔记还没有标题"))
            return

        self.outline_count.set_text(f"大纲 · {len(headings)}")
        self.outline_hint.set_text("点击标题可跳转到对应位置")
        base = min(h.level for h in headings)
        for heading in headings:
            self.outline_list.append(OutlineRow(heading, base))

    def _on_outline_activated(self, _list, row) -> None:
        heading = getattr(row, "heading", None)
        if heading is None:
            return
        self.window.goto_outline_heading(heading)

    # ------------------------------------------------------------------ 笔记列表

    def _on_filter_changed(self, drop, _param) -> None:
        index = drop.get_selected()
        if 0 <= index < len(FILTER_LABELS):
            self._filter = FILTER_LABELS[index][0]
        self.refresh_notes()

    def _on_search_changed(self, entry) -> None:
        self._query = entry.get_text().strip().lower()
        self.refresh_notes()

    def _on_sort_changed(self, drop, _param) -> None:
        index = drop.get_selected()
        if 0 <= index < len(SORT_LABELS):
            self._sort = SORT_LABELS[index][0]
        self.store.set_meta("sidebar_sort", self._sort)
        self.refresh_notes()
        self.refresh_folders()

    def _sort_docs(self, docs: list) -> list:
        """按当前排序方式重排文档（标题排序走 GLib 的 locale 规则，中文按拼音）。"""
        mode = self._sort
        if mode == "updated_asc":
            return sorted(docs, key=lambda d: (d.updated_at, d.sort_index))
        if mode == "title_asc":
            return sorted(docs, key=lambda d: _collate_key(d.title))
        if mode == "title_desc":
            return sorted(docs, key=lambda d: _collate_key(d.title), reverse=True)
        return sorted(docs, key=lambda d: (-d.updated_at, d.sort_index))

    def refresh_notes(self) -> None:
        """按当前筛选条件重建笔记列表（会保留滚动位置）。"""
        scroller = self.notes_list.get_parent()
        adj = scroller.get_vadjustment() if isinstance(scroller, Gtk.ScrolledWindow) else None
        keep = adj.get_value() if adj is not None else 0.0

        while (child := self.notes_list.get_first_child()) is not None:
            self.notes_list.remove(child)
        self._notes_rows.clear()

        if self._filter == FILTER_RECENT:
            # 「最近」视图默认截断 80 条；按标题排序时放宽，避免只排了前 80 条
            limit = 80 if self._sort == SORT_UPDATED_DESC else 500
            docs = self.store.recent_documents(limit)
            self._append_flat(self._sort_docs(docs))
        elif self._filter == FILTER_OPEN:
            docs = self.store.open_documents_by_recent()
            self._append_flat(self._sort_docs(docs))
        else:
            grouped = self.store.documents_grouped_by_format()
            if not grouped:
                self._append_empty("还没有任何笔记")
            for fmt, docs in grouped.items():
                docs = self._sort_docs([d for d in docs if self._matches(d)])
                if not docs:
                    continue
                self.notes_list.append(
                    self._make_header(f"{FORMAT_NAMES.get(fmt, fmt.upper())} · {len(docs)}")
                )
                for doc in docs:
                    row = NoteRow(self, doc)
                    self.notes_list.append(row)
                    self._notes_rows.append(row)

        if adj is not None:
            GLib.idle_add(lambda: (adj.set_value(keep), False)[1])

    def _append_flat(self, docs: list) -> None:
        visible = [d for d in docs if self._matches(d)]
        if not visible:
            self._append_empty("没有匹配的笔记")
            return
        for doc in visible:
            row = NoteRow(self, doc)
            self.notes_list.append(row)
            self._notes_rows.append(row)

    def _matches(self, doc) -> bool:
        if not self._query:
            return True
        return self._query in (doc.title or "").lower()

    def _make_header(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        label = Gtk.Label(
            label=text,
            xalign=0,
            margin_start=12,
            margin_top=10,
            margin_bottom=2,
            css_classes=["dim-label", "caption-heading"],
        )
        row.set_child(label)
        return row

    def _append_empty(self, text: str) -> None:
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        label = Gtk.Label(
            label=text,
            xalign=0,
            margin_start=12,
            margin_top=12,
            css_classes=["dim-label"],
        )
        row.set_child(label)
        self.notes_list.append(row)

    def _on_note_row_activated(self, _list, row) -> None:
        doc_id = getattr(row, "doc_id", None)
        if doc_id:
            self.window.open_document(doc_id)
            self.window.hide_sidebar_after_pick()

    # ------------------------------------------------------------------ 文件夹

    def refresh_folders(self) -> None:
        while (child := self.folders_list.get_first_child()) is not None:
            self.folders_list.remove(child)
        by_folder = self.store.documents_by_folder()
        names = [""] + self.store.folders()
        # 清理已被删除的展开状态
        self._expanded_folders &= set(names)
        for name in names:
            row = FolderRow(self, name, self._sort_docs(by_folder.get(name, [])))
            self.folders_list.append(row)

    def prompt_new_folder(self) -> None:
        entry = Gtk.Entry(placeholder_text="文件夹名称", activates_default=True)
        dialog = Adw.AlertDialog(heading="新建文件夹", body="把相关笔记归到一起（只在应用内分类，不动磁盘）")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "创建")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_new_folder_response, entry)
        dialog.present(self.window)

    def _on_new_folder_response(self, _dialog, response, entry) -> None:
        if response != "ok":
            return
        try:
            name = _clean_name(entry.get_text())
            self.store.create_folder(name)
        except ValueError as exc:
            self.window.toast_overlay.add_toast(Adw.Toast(title=str(exc), timeout=4))
            return
        self._expanded_folders.add(name)
        self.refresh_folders()
        self.refresh_notes()
        self.window.toast_overlay.add_toast(Adw.Toast(title=f"已创建文件夹「{name}」", timeout=3))

    def rename_folder_prompt(self, old: str) -> None:
        entry = Gtk.Entry(text=old, activates_default=True)
        dialog = Adw.AlertDialog(heading="重命名文件夹")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "确定")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_rename_folder_response, entry, old)
        dialog.present(self.window)

    def _on_rename_folder_response(self, _dialog, response, entry, old) -> None:
        if response != "ok":
            return
        try:
            new = _clean_name(entry.get_text())
        except ValueError as exc:
            self.window.toast_overlay.add_toast(Adw.Toast(title=str(exc), timeout=4))
            return
        if new == old:
            return
        self.store.rename_folder(old, new)
        self._expanded_folders.discard(old)
        self._expanded_folders.add(new)
        self.refresh_folders()
        self.refresh_notes()

    def delete_folder_prompt(self, name: str) -> None:
        dialog = Adw.AlertDialog(
            heading=f"删除文件夹「{name}」？",
            body="文件夹内的笔记不会被删除，会回到「未归档」。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "删除文件夹")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_folder_response, name)
        dialog.present(self.window)

    def _on_delete_folder_response(self, _dialog, response, name) -> None:
        if response != "delete":
            return
        self.store.delete_folder(name)
        self._expanded_folders.discard(name)
        self.refresh_folders()
        self.refresh_notes()

    def move_document(self, doc_id: str, folder: str) -> None:
        """把笔记放进某个文件夹（folder 为空字符串表示移出到「未归档」）。"""
        self.store.set_folder(doc_id, folder)
        self.refresh_folders()
        self.refresh_notes()
        target = f"「{folder}」" if folder else "「未归档」"
        self.window.toast_overlay.add_toast(
            Adw.Toast(title=f"已移动到{target}", timeout=3)
        )

    # ------------------------------------------------------------------ 笔记右键菜单

    def show_note_menu(self, row: "NoteRow", x: float, y: float) -> None:
        doc = row.doc
        popover = Gtk.Popover()
        popover.set_parent(row)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6)

        def add_button(label: str, callback, *, destructive: bool = False) -> None:
            button = Gtk.Button(label=label)
            button.set_css_classes(["flat"])
            if destructive:
                button.add_css_class("destructive-action")
            button.connect(
                "clicked",
                lambda *_: (popover.popdown(), callback()),
            )
            box.append(button)

        add_button(
            "打开",
            lambda: (
                self.window.open_document(doc.id),
                self.window.hide_sidebar_after_pick(),
            ),
        )
        add_button("重命名…", lambda: self.window.rename_document_by_id(doc.id))
        add_button("移动到文件夹…", lambda: self.prompt_move(doc.id))
        if doc.folder:
            add_button("移出文件夹", lambda: self.move_document(doc.id, ""))
        add_button("永久删除…", lambda: self.window.delete_document_by_id(doc.id), destructive=True)

        popover.set_child(box)
        popover.popup()

    def prompt_move(self, doc_id: str) -> None:
        """列出所有文件夹让用户挑选（含「未归档」与新建）。"""
        folders = self.store.folders()
        labels = ["未归档"] + folders + ["＋ 新建文件夹…"]
        dropdown = Gtk.DropDown.new_from_strings(labels)
        current = self.store.doc_folder_of(doc_id)
        if current in folders:
            dropdown.set_selected(folders.index(current) + 1)

        entry = Gtk.Entry(placeholder_text="新建文件夹名称（选最后一项时填写）")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(dropdown)
        box.append(entry)

        dialog = Adw.AlertDialog(heading="移动到文件夹")
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "移动")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_move_response, dropdown, entry, doc_id)
        dialog.present(self.window)

    def _on_move_response(self, _dialog, response, dropdown, entry, doc_id) -> None:
        if response != "ok":
            return
        index = dropdown.get_selected()
        folders = self.store.folders()
        if index == 0:
            target = ""
        elif 1 <= index <= len(folders):
            target = folders[index - 1]
        else:
            try:
                target = _clean_name(entry.get_text())
            except ValueError as exc:
                self.window.toast_overlay.add_toast(Adw.Toast(title=str(exc), timeout=4))
                return
            self.store.create_folder(target)
        self._expanded_folders.add(target)
        self.move_document(doc_id, target)

    # ------------------------------------------------------------------ 磁盘树

    def reset_disk_view(self) -> None:
        self._disk_ready = False
        self._dir_rows.clear()
        self._file_rows.clear()
        while (child := self.disk_list.get_first_child()) is not None:
            self.disk_list.remove(child)
        self.disk_label.set_text("~")
        # 必须重新扫根：reload_disk() 只刷新「已展开」的目录，此刻 _dir_rows 刚被清空，
        # 调它等于什么也不做（此前「回到主目录」按钮会把列表清空就是这个原因）。
        self._ensure_disk_root()

    def reload_disk(self) -> None:
        """重新枚举已展开的目录（内容可能被外部程序改动）。"""
        for path, row in list(self._dir_rows.items()):
            if row.get_expanded():
                row.clear_children()
                row.ensure_children()

    # ---- 磁盘排序

    def _fill_disk_sort_popover(self, *_args) -> None:
        """每次弹出时重建，保证勾选状态与当前值一致。"""
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6
        )
        for key, label in DISK_SORT_LABELS:
            button = Gtk.Button(css_classes=["flat"])
            inner = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_start=4, margin_end=10
            )
            check = Gtk.Image(icon_name="object-select-symbolic", pixel_size=14)
            check.set_visible(key == self._disk_sort)
            inner.append(check)
            inner.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            button.set_child(inner)
            button.connect("clicked", lambda *_a, k=key: self.set_disk_sort(k))
            box.append(button)
        self.disk_sort_popover.set_child(box)

    def set_disk_sort(self, key: str) -> None:
        self.disk_sort_popover.popdown()
        if key not in {k for k, _ in DISK_SORT_LABELS} or key == self._disk_sort:
            return
        self._disk_sort = key
        self.store.set_meta("disk_sort", key, wait=True)
        self._rebuild_disk_keep_expanded()

    def _rebuild_disk_keep_expanded(self) -> None:
        """改排序后重建树，并把原先展开的目录逐级展开回来。"""
        expanded = sorted(
            (Path(p) for p, row in self._dir_rows.items() if row.get_expanded()),
            key=lambda p: len(p.parts),
        )
        label = self.disk_label.get_text()
        self.reset_disk_view()
        for path in expanded:
            self._expand_to(path)
        if label and label != "~":
            self.disk_label.set_text(label)

    def _expand_to(self, path: Path) -> None:
        try:
            rel = path.relative_to(self._disk_root)
        except ValueError:
            return
        current = self._disk_root
        for part in rel.parts:
            current = current / part
            row = self._dir_rows.get(str(current))
            if row is None:
                return
            row.set_expanded(True)

    def _sort_entries(
        self, dirs: list[Path], files: list[Path]
    ) -> tuple[list[Path], list[Path]]:
        """按当前排序方式排列同层条目；文件夹始终排在文件之前。"""
        mode = self._disk_sort

        def name_key(path: Path):
            return _collate_key(path.name.lower())

        def mtime_key(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        if mode == "name_desc":
            key, reverse = name_key, True
        elif mode == "mtime_desc":
            key, reverse = mtime_key, True
        elif mode == "type_asc":
            key, reverse = lambda p: (p.suffix.lower(), name_key(p)), False
        else:
            key, reverse = name_key, False
        return (
            sorted(dirs, key=key, reverse=reverse),
            sorted(files, key=key, reverse=reverse),
        )

    # ---- 磁盘右键菜单

    def show_disk_file_menu(self, row: "DiskFileRow", x: float, y: float) -> None:
        self._show_path_menu(row, row.path, x, y, file=True)

    def show_disk_dir_menu(self, row: "DiskDirRow", x: float, y: float) -> None:
        self._show_path_menu(row, row.path, x, y, file=False)
    def _show_path_menu(self, anchor, path: Path, x: float, y: float, *, file: bool) -> None:
        popover = Gtk.Popover()
        popover.set_parent(anchor)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6
        )

        def add_button(label: str, callback) -> None:
            button = Gtk.Button(label=label, css_classes=["flat"])
            button.connect("clicked", lambda *_: (popover.popdown(), callback()))
            box.append(button)

        if file:
            add_button(
                "打开",
                lambda: (
                    self.window.open_path_at_line(path, 1),
                    self.window.hide_sidebar_after_pick(),
                ),
            )
        add_button("在文件管理器中显示", lambda: self._show_in_file_manager(path))
        add_button("复制路径", lambda: self._copy_to_clipboard(str(path)))
        add_button("复制文件名", lambda: self._copy_to_clipboard(path.name))

        popover.set_child(box)
        popover.connect("closed", lambda _p: setattr(self, "_active_path_menu", None))
        self._active_path_menu = popover
        popover.popup()

    def _show_in_file_manager(self, path: Path) -> None:
        target = path if path.is_dir() else path.parent
        try:
            Gio.AppInfo.launch_default_for_uri(target.as_uri(), None)
        except GLib.Error as exc:
            self.window.toast_overlay.add_toast(
                Adw.Toast(title=f"无法打开文件管理器：{exc.message}", timeout=4)
            )

    def _copy_to_clipboard(self, text: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(text)
        self.window.toast_overlay.add_toast(Adw.Toast(title="已复制", timeout=2))

    def _on_view_changed(self, stack, _param) -> None:
        if stack.get_visible_child_name() == VIEW_DISK:
            self._ensure_disk_root()

    def _ensure_disk_root(self) -> None:
        if self._disk_ready:
            return
        self._disk_ready = True
        self.disk_label.set_text("~")
        rows = self._scan_dir(self._disk_root, depth=0)
        if not rows:
            rows = [self._placeholder_row("主目录下没有可显示的文件夹或文本文件")]
        for row in rows:
            self.disk_list.append(row)

    def _placeholder_row(self, text: str) -> Gtk.Widget:
        return Gtk.Label(
            label=text,
            xalign=0,
            wrap=True,
            margin_start=12,
            margin_end=12,
            margin_top=6,
            margin_bottom=6,
            css_classes=["dim-label", "caption"],
        )

    def _scan_dir(
        self, directory: Path, *, depth: int, collect: list[str] | None = None
    ) -> list[Gtk.Widget]:
        rows: list[Gtk.Widget] = []
        dirs: list[Path] = []
        files: list[Path] = []
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if name in DISK_SKIP_DIRS:
                                continue
                            dirs.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            if Path(name).suffix.lower() in DISK_TEXT_SUFFIXES:
                                files.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError as exc:
            return [self._placeholder_row(f"无法读取：{exc.strerror or exc}")]

        dirs, files = self._sort_entries(dirs, files)
        total = len(dirs) + len(files)
        shown = 0
        for path in dirs:
            if shown >= MAX_ENTRIES_PER_DIR:
                break
            row = DiskDirRow(self, path, depth)
            key = str(path)
            self._dir_rows[key] = row
            if collect is not None:
                collect.append(key)
            rows.append(row)
            shown += 1
        for path in files:
            if shown >= MAX_ENTRIES_PER_DIR:
                break
            row = DiskFileRow(self, path, depth)
            key = str(path)
            self._file_rows[key] = row
            if collect is not None:
                collect.append(key)
            rows.append(row)
            shown += 1
        if total > shown:
            rows.append(
                Gtk.Label(
                    label=f"… 另有 {total - shown} 项未显示",
                    xalign=0,
                    margin_start=12 + 16 * depth,
                    margin_top=4,
                    margin_bottom=4,
                    css_classes=["dim-label", "caption"],
                )
            )
        return rows

    def reveal_local_path(self, path: Path | str) -> bool:
        """展开父目录链并选中目标文件；不在 $HOME 内则只切换视图、返回 False。"""
        try:
            target = Path(path).expanduser().resolve()
        except OSError:
            return False

        self.stack.set_visible_child_name(VIEW_DISK)
        self._ensure_disk_root()

        try:
            rel = target.relative_to(self._disk_root)
        except ValueError:
            self.disk_label.set_text(str(target.parent))
            self.disk_label.set_tooltip_text(str(target))
            return False

        # 逐级展开父目录
        accumulated = self._disk_root
        for part in rel.parent.parts:
            accumulated = accumulated / part
            row = self._dir_rows.get(str(accumulated))
            if row is None:
                # 目录没被列出（例如被条目上限截断）：退化为只显示路径提示
                self.disk_label.set_text(str(target.parent))
                return False
            row.set_expanded(True)

        row = self._file_rows.get(str(target))
        self.disk_label.set_text(str(target.parent).replace(str(self._disk_root), "~", 1))
        self.disk_label.set_tooltip_text(str(target))
        if row is None:
            return False
        row.highlight()  # 没用 ListBox，选中态自己画
        row.grab_focus()  # GTK4 中聚焦即会滚动到可见区域
        return True

    # ------------------------------------------------------------------ 其它

    def refresh(self) -> None:
        self.refresh_notes()
        self.refresh_folders()

    def shown_view(self) -> str:
        return self.stack.get_visible_child_name() or VIEW_NOTES

    def show_view(self, name: str) -> None:
        if name in (VIEW_NOTES, VIEW_FOLDERS, VIEW_DISK, VIEW_OUTLINE):
            self.stack.set_visible_child_name(name)
            if name == VIEW_DISK:
                self._ensure_disk_root()


# ====================================================================== 行组件


class NoteRow(Gtk.ListBoxRow):
    """笔记条目：可点击打开、可拖到文件夹、右键出菜单。"""

    def __init__(self, sidebar: Sidebar, doc) -> None:
        super().__init__()
        self.sidebar = sidebar
        self.doc = doc
        self.doc_id = doc.id

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=10,
            margin_end=8,
            margin_top=5,
            margin_bottom=5,
        )
        icon = Gtk.Image(icon_name=FORMAT_ICONS.get(doc.format, "text-x-generic-symbolic"))
        icon.set_pixel_size(16)
        box.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True)
        title = Gtk.Label(
            label=doc.title or "未命名",
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=24,
        )
        text.append(title)
        meta_bits = [doc.format.upper()]
        if doc.folder:
            meta_bits.append(doc.folder)
        if doc.state == "closed":
            meta_bits.append("已关闭")
        meta_bits.append(_human_time(doc.updated_at))
        subtitle = Gtk.Label(
            label=" · ".join(bit for bit in meta_bits if bit),
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
            css_classes=["dim-label", "caption"],
        )
        text.append(subtitle)
        box.append(text)
        self.set_child(box)
        self.set_tooltip_text(doc.title or "未命名")

        self.add_controller(self._make_drag_source())
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_secondary_click)
        self.add_controller(click)

    def _make_drag_source(self) -> Gtk.DragSource:
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare)
        return source

    def _on_drag_prepare(self, _source, _x, _y):
        # 拖拽载荷就是文档 id（G_TYPE_STRING），接受方是文件夹行
        return Gdk.ContentProvider.new_for_value(self.doc_id)

    def _on_secondary_click(self, _gesture, _n, x, y) -> None:
        self.sidebar.show_note_menu(self, x, y)


class FolderRow(Gtk.ListBoxRow):
    """文件夹行：可展开、可接收拖入的笔记、可重命名/删除。"""

    def __init__(self, sidebar: Sidebar, name: str, docs: list) -> None:
        super().__init__()
        self.sidebar = sidebar
        self.name = name
        self._docs = docs
        self.set_activatable(False)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=6,
            margin_end=4,
            margin_top=3,
            margin_bottom=3,
        )

        self.toggle = Gtk.Button(css_classes=["flat"], width_request=24)
        self.toggle.set_icon_name("pan-end-symbolic")
        self.toggle.set_tooltip_text("展开 / 收起")
        self.toggle.connect("clicked", lambda *_: self.set_expanded(not self.get_expanded()))
        header.append(self.toggle)

        icon = Gtk.Image(icon_name="folder-symbolic", css_classes=["dim-label"])
        icon.set_pixel_size(16)
        header.append(icon)

        label = Gtk.Label(
            label=name or "未归档",
            xalign=0,
            hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
        )
        header.append(label)

        count = Gtk.Label(label=str(len(docs)), css_classes=["dim-label", "caption"])
        header.append(count)

        if name:
            menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic", css_classes=["flat"])
            menu_btn.set_tooltip_text("文件夹操作")
            menu_btn.set_popover(self._build_menu())
            header.append(menu_btn)

        outer.append(header)

        self.children_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.children_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.children_list.set_margin_start(16)
        self.children_list.connect("row-activated", self._on_child_activated)
        # 注意：不要用 Gtk.Revealer——它收起时不收缩布局（实测行高不变），
        # 直接用 visible 控制即可
        self.children_list.set_visible(False)
        outer.append(self.children_list)
        self.set_child(outer)

        # 接收笔记拖入
        self._attach_drop()

        for doc in docs:
            self.children_list.append(NoteRow(sidebar, doc))
        if not docs:
            empty = Gtk.ListBoxRow(selectable=False, activatable=False)
            empty.set_child(
                Gtk.Label(
                    label="（空）", xalign=0, margin_start=10, css_classes=["dim-label", "caption"]
                )
            )
            self.children_list.append(empty)

        expanded = name in sidebar._expanded_folders
        self.children_list.set_visible(expanded)
        self.toggle.set_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic")

    def _build_menu(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6)

        def add(label: str, callback, *, destructive: bool = False) -> None:
            button = Gtk.Button(label=label)
            button.set_css_classes(["flat"])
            if destructive:
                button.add_css_class("destructive-action")
            button.connect("clicked", lambda *_: (popover.popdown(), callback()))
            box.append(button)

        add("重命名…", lambda: self.sidebar.rename_folder_prompt(self.name))
        add("删除文件夹…", lambda: self.sidebar.delete_folder_prompt(self.name), destructive=True)
        popover.set_child(box)
        return popover

    def _attach_drop(self) -> None:
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

    def _on_drop(self, _target, value, _x, _y) -> bool:
        doc_id = str(value or "").strip()
        if not doc_id:
            return False
        self.sidebar._expanded_folders.add(self.name)
        self.sidebar.move_document(doc_id, self.name)
        return True

    def _on_child_activated(self, _list, row) -> None:
        doc_id = getattr(row, "doc_id", None)
        if doc_id:
            self.sidebar.window.open_document(doc_id)
            self.sidebar.window.hide_sidebar_after_pick()

    def get_expanded(self) -> bool:
        return self.children_list.get_visible()

    def set_expanded(self, expanded: bool) -> None:
        self.children_list.set_visible(expanded)
        self.toggle.set_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic")
        if expanded:
            self.sidebar._expanded_folders.add(self.name)
        else:
            self.sidebar._expanded_folders.discard(self.name)


class DiskDirRow(Gtk.Box):
    """磁盘目录行：标题按钮 + 懒加载的子项容器。

    注意这里刻意不用 Gtk.ListBoxRow / 嵌套 ListBox：ListBox 的点击手势在
    CAPTURE 阶段会无条件 claim 事件，行内子控件的鼠标事件全被吞掉
    （表现为「点文件没反应、右键没菜单」，但键盘激活正常）。
    """

    def __init__(self, sidebar: Sidebar, path: Path, depth: int) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar = sidebar
        self.path = path
        self.depth = depth
        self._loaded = False
        self._child_keys: list[str] = []

        self.header = Gtk.Button(css_classes=["flat", "disk-row"], halign=Gtk.Align.FILL)
        inner = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=4 + 14 * depth,
            margin_end=6,
            margin_top=1,
            margin_bottom=1,
        )
        self.toggle = Gtk.Image(icon_name="pan-end-symbolic", pixel_size=12)
        inner.append(self.toggle)
        icon = Gtk.Image(icon_name="folder-symbolic", css_classes=["dim-label"])
        icon.set_pixel_size(16)
        inner.append(icon)
        inner.append(
            Gtk.Label(
                label=path.name or str(path),
                xalign=0,
                hexpand=True,
                ellipsize=Pango.EllipsizeMode.END,
            )
        )
        self.header.set_child(inner)
        self.header.set_tooltip_text(str(path))
        self.header.connect("clicked", lambda *_: self.set_expanded(not self.get_expanded()))
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", self._on_right_click)
        self.header.add_controller(right)
        self.append(self.header)

        self.children_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.children_list.set_visible(False)
        self.append(self.children_list)

    def _on_right_click(self, _gesture, _n_press: int, x: float, y: float) -> None:
        self.sidebar.show_disk_dir_menu(self, x, y)

    def ensure_children(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        rows = self.sidebar._scan_dir(self.path, depth=self.depth + 1, collect=self._child_keys)
        if not rows:
            rows = [self.sidebar._placeholder_row("空文件夹")]
        for row in rows:
            self.children_list.append(row)

    def clear_children(self) -> None:
        # 行被移除后必须同时注销映射，否则 reveal() 会拿到已脱离控件树的旧行
        for key in self._child_keys:
            self.sidebar._dir_rows.pop(key, None)
            self.sidebar._file_rows.pop(key, None)
        self._child_keys.clear()
        while (child := self.children_list.get_first_child()) is not None:
            self.children_list.remove(child)
        self._loaded = False

    def get_expanded(self) -> bool:
        return self.children_list.get_visible()

    def set_expanded(self, expanded: bool) -> None:
        if expanded:
            self.ensure_children()
        self.children_list.set_visible(expanded)
        self.toggle.set_from_icon_name(
            "pan-down-symbolic" if expanded else "pan-end-symbolic"
        )


class DiskFileRow(Gtk.Button):
    """磁盘文件行：单击即作为标签打开，右键出菜单。"""

    def __init__(self, sidebar: Sidebar, path: Path, depth: int) -> None:
        super().__init__(css_classes=["flat", "disk-row"], halign=Gtk.Align.FILL)
        self.sidebar = sidebar
        self.path = path
        self.file_path = path
        self._last_open = 0.0

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=4 + 14 * depth + 20,
            margin_end=6,
            margin_top=1,
            margin_bottom=1,
        )
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown", ".mkd"}:
            icon_name = "text-markdown-symbolic"
        elif suffix in {".html", ".htm"}:
            icon_name = "text-html-symbolic"
        else:
            icon_name = "text-x-generic-symbolic"
        icon = Gtk.Image(icon_name=icon_name, css_classes=["dim-label"])
        icon.set_pixel_size(16)
        box.append(icon)
        box.append(
            Gtk.Label(
                label=path.name,
                xalign=0,
                hexpand=True,
                ellipsize=Pango.EllipsizeMode.END,
            )
        )
        self.set_child(box)
        self.set_tooltip_text(str(path))
        self.connect("clicked", lambda *_: self.open())

        # 右键自己收：Button 内置手势只吃左键，这里能正常拿到右键
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", self._on_right_click)
        self.add_controller(right)

    def _on_right_click(self, gesture, _n_press: int, x: float, y: float) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.sidebar.show_disk_file_menu(self, x, y)

    def highlight(self) -> None:
        """被「自动定位」选中时短暂高亮，代替 ListBox 的选中态。"""
        self.add_css_class("disk-row-current")

        def clear() -> bool:
            self.remove_css_class("disk-row-current")
            return False

        GLib.timeout_add(1400, clear)

    def open(self) -> None:
        # 双击的第二击会再来一次；去重避免已打开的文件被 goto_line(1) 拽回顶部。
        now = time.monotonic()
        if now - self._last_open < 0.4:
            return
        self._last_open = now
        self.sidebar.window.open_path_at_line(self.path, 1)
        self.sidebar.window.hide_sidebar_after_pick()


class OutlineRow(Gtk.ListBoxRow):
    """大纲条目：按标题层级缩进，点击跳转到正文对应位置。"""

    def __init__(self, heading, base_level: int) -> None:
        super().__init__()
        self.heading = heading
        depth = max(0, min(heading.level - base_level, 5))

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=10 + 14 * depth,
            margin_end=8,
            margin_top=4,
            margin_bottom=4,
        )
        dot = Gtk.Label(
            label="●" if heading.level <= 2 else "○",
            css_classes=["dim-label", "caption"],
        )
        box.append(dot)

        label = Gtk.Label(
            label=heading.text,
            xalign=0,
            hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=26,
            wrap=False,
        )
        if heading.level <= 2:
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
            label.set_attributes(attrs)
        elif heading.level >= 4:
            label.add_css_class("dim-label")
        box.append(label)
        self.set_child(box)
        self.set_tooltip_text(f"第 {heading.line} 行 · {heading.text}")
