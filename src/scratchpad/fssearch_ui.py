"""目录搜索 / 批量替换 对话框。

数据源是用户显式选择的真实目录（不碰应用自己的数据库），行为对齐
`search_md.py` / `replace_md.py`，并补上图形界面必需的安全措施：
预览后再执行、按文件勾选、自动备份、已打开标签同步刷新。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .clipboard import set_clipboard_utf8  # noqa: E402
from . import fssearch, paths  # noqa: E402

DISPLAY_LIMIT = 400          # 结果列表最多渲染多少行（防止界面卡顿）
PER_FILE_HITS = 50           # 单个文件最多展示多少条命中


def _markup(snippet: str, pattern: str, case_sensitive: bool, regex: bool) -> str:
    """把命中片段包成 <b>，其余部分转义。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    source = pattern if regex else re.escape(pattern)
    try:
        rx = re.compile(source, flags)
    except re.error:
        return GLib.markup_escape_text(snippet)
    parts: list[str] = []
    pos = 0
    for m in rx.finditer(snippet):
        if m.start() == m.end():
            break
        parts.append(GLib.markup_escape_text(snippet[pos:m.start()]))
        parts.append("<b>" + GLib.markup_escape_text(m.group(0)) + "</b>")
        pos = m.end()
    parts.append(GLib.markup_escape_text(snippet[pos:]))
    return "".join(parts)


def _switch(label: str, active: bool) -> tuple[Gtk.Box, Gtk.Switch]:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(Gtk.Label(label=label))
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    box.append(sw)
    return box, sw


class _FolderDialog(Adw.Dialog):
    """公共部分：文件夹选择 + 三个选项开关。"""

    def __init__(self, window, title: str, *, case_default: bool = False) -> None:
        super().__init__()
        self.window = window
        self.set_title(title)
        self.can_close = True
        self.set_content_width(860)
        self.set_content_height(680)
        self._folder: Path | None = None

        self.toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title=title, subtitle="搜索与替换只作用于所选目录")
        )
        self.toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(12)
        body.set_margin_bottom(12)
        body.set_margin_start(14)
        body.set_margin_end(14)

        # ---- 目录选择
        folder_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.folder_button = Gtk.Button(label="选择文件夹…", icon_name="folder-open-symbolic")
        self.folder_button.connect("clicked", lambda *_: self._pick_folder())
        folder_row.append(self.folder_button)
        self.folder_label = Gtk.Label(
            label="尚未选择目录",
            hexpand=True,
            halign=Gtk.Align.START,
            ellipsize=Pango.EllipsizeMode.END,
            css_classes=["dim-label"],
        )
        folder_row.append(self.folder_label)
        body.append(folder_row)

        # ---- 选项
        opts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        recursive_box, self.recursive_switch = _switch("递归子目录", True)
        case_box, self.case_switch = _switch("区分大小写", case_default)
        regex_box, self.regex_switch = _switch("正则表达式", False)
        for widget in (recursive_box, case_box, regex_box):
            opts.append(widget)
        body.append(opts)

        self.body = body
        self.toolbar.set_content(body)
        self.set_child(self.toolbar)

        # 上次目录延迟到子类字段就绪后再恢复（见 _restore_last_folder）
        try:
            self._saved_root = window.store.get_meta("fs_root")
        except Exception:  # noqa: BLE001
            self._saved_root = None

    def _restore_last_folder(self) -> None:
        saved = self._saved_root
        if saved and Path(saved).is_dir():
            self._set_folder(Path(saved), remember=False)

    # ------------------------------------------------------------------ 目录

    def _pick_folder(self) -> None:
        dialog = Gtk.FileDialog(title="选择要搜索的文件夹", modal=True)
        if self._folder is not None:
            try:
                dialog.set_initial_folder(Gio.File.new_for_path(str(self._folder)))
            except Exception:  # noqa: BLE001
                pass
        dialog.select_folder(self.window, None, self._on_folder_chosen, None)

    def _on_folder_chosen(self, dialog, result, _data) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if gfile is None or not gfile.get_path():
            return
        self._set_folder(Path(gfile.get_path()))

    def _set_folder(self, path: Path, *, remember: bool = True) -> None:
        self._folder = path
        self.folder_label.set_text(str(path))
        self.folder_label.set_tooltip_text(str(path))
        if remember:
            try:
                self.window.store.set_meta("fs_root", str(path))
            except Exception:  # noqa: BLE001
                pass
        self._on_folder_changed()

    def _on_folder_changed(self) -> None:
        pass

    # ------------------------------------------------------------------ 工具

    def _options(self) -> dict:
        return {
            "recursive": self.recursive_switch.get_active(),
            "case_sensitive": self.case_switch.get_active(),
            "regex": self.regex_switch.get_active(),
        }

    def _add_to_body(self, widget) -> None:
        self.body.append(widget)



class _HitRow(Gtk.Box):
    """一条搜索结果。

    交互与「磁盘」页一致：**不用 Gtk.ListBox**——它在 CAPTURE 阶段无条件 claim
    鼠标序列，行内的手势收不到事件。这里用普通 Box 叠手势控制器：

    - 单击：选中（高亮当前行），不跳走，方便上下浏览、复制片段
    - 双击 / 回车：打开文件并定位到关键词（选中命中文本）
    - 右键：菜单，含「替换此内容…」
    """

    def __init__(self, dialog: "FolderSearchDialog", file_hits, hit: fssearch.Hit,
                 label: Gtk.Label) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.dialog = dialog
        self.path = file_hits.path
        self.rel = file_hits.rel
        self.line_no = hit.line_no
        self.hit = hit
        self._menu: Gtk.Popover | None = None
        self.add_css_class("hit-row")
        self.set_margin_start(24)
        self.set_focusable(True)
        self.append(
            Gtk.Label(
                label=str(hit.line_no), width_chars=5, xalign=1,
                css_classes=["dim-label", "monospace"],
            )
        )
        self.append(label)

        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_press)
        self.add_controller(click)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", self._on_right_press)
        self.add_controller(right)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # ------------------------------------------------------------------ 行为

    def open_target(self) -> None:
        self.dialog.open_hit(self.path, self.hit)

    def replace_target(self) -> None:
        self.dialog.replace_in_file(self.path)

    def _on_press(self, _gesture, n_press: int, _x: float, _y: float) -> None:
        if n_press >= 2:
            self.open_target()
        else:
            self.dialog.focus_hit_row(self)

    def _on_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            self.open_target()
            return True
        return False

    def _on_right_press(self, _gesture, _n_press: int, x: float, y: float) -> None:
        self.show_menu(x, y)

    def show_menu(self, x: float = 0, y: float = 0) -> Gtk.Popover:
        popover = Gtk.Popover()
        popover.set_parent(self)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6
        )

        def add(label: str, callback) -> None:
            button = Gtk.Button(label=label, css_classes=["flat"])
            button.connect("clicked", lambda *_: (popover.popdown(), callback()))
            box.append(button)

        add("打开并定位到此行", self.open_target)
        add("替换此内容…", self.replace_target)
        add("在文件管理器中显示", self._show_in_file_manager)
        add("复制文件路径", self._copy_path)
        popover.set_child(box)
        popover.connect("closed", lambda _p: setattr(self, "_menu", None))
        self._menu = popover
        popover.popup()
        return popover

    def menu_labels(self) -> list[str]:
        """右键菜单的条目文本（测试与无障碍检查用）。"""
        popover = self.show_menu()
        box = popover.get_child()
        labels: list[str] = []
        child = box.get_first_child() if box is not None else None
        while child is not None:
            labels.append(child.get_label() if isinstance(child, Gtk.Button) else "")
            child = child.get_next_sibling()
        popover.popdown()
        return labels

    def _show_in_file_manager(self) -> None:
        target = self.path if self.path.is_dir() else self.path.parent
        try:
            Gio.AppInfo.launch_default_for_uri(target.as_uri(), None)
        except GLib.Error as exc:
            self.dialog.status.set_text(f"无法打开文件管理器：{exc.message}")

    def _copy_path(self) -> None:
        set_clipboard_utf8(str(self.path))


class FolderSearchDialog(_FolderDialog):
    """在选定目录中搜索关键词；双击结果打开并定位，右键可转入替换。"""

    def __init__(self, window) -> None:
        super().__init__(window, "在目录中搜索")
        self._generation = 0
        self._timer: int | None = None
        self._outcome: fssearch.SearchOutcome | None = None
        self._current_row: _HitRow | None = None
        self.replace_dialog = None  # 「替换此内容…」打开的对话框（防 GC）

        self.entry = Gtk.SearchEntry(
            placeholder_text=r"要搜索的关键词…（支持 \n \t \r \\）", hexpand=True
        )
        self.entry.connect("search-changed", lambda *_: self._schedule())
        self.entry.connect("activate", lambda *_: self._run_now())
        self._add_to_body(self.entry)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status = Gtk.Label(
            label="选择目录并输入关键词", hexpand=True, xalign=0,
            ellipsize=Pango.EllipsizeMode.END, css_classes=["dim-label"],
        )
        status_row.append(self.status)
        status_row.append(
            Gtk.Label(
                label="双击打开并定位 · 右键替换此内容",
                css_classes=["dim-label", "caption"],
            )
        )
        self._add_to_body(status_row)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_has_frame(True)
        # 普通 Box 承载结果行（原因见 _HitRow 的注释）
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.results.add_css_class("hit-results")
        scroller.set_child(self.results)
        self._add_to_body(scroller)

        self.spinner = Gtk.Spinner(visible=False)
        self._add_to_body(self.spinner)
        self._restore_last_folder()

    # ------------------------------------------------------------------ 搜索

    def _on_folder_changed(self) -> None:
        self._generation += 1  # 让进行中的搜索作废
        if self.entry.get_text().strip():
            self._schedule()

    def _schedule(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(280, self._run_now)

    def _run_now(self) -> bool:
        self._timer = None
        raw = self.entry.get_text()
        if self._folder is None:
            self.status.set_text("请先选择一个文件夹")
            return False
        if not raw:
            self._clear()
            self.status.set_text("输入关键词开始搜索")
            return False

        self._generation += 1
        generation = self._generation
        opts = self._options()
        pattern = raw if opts["regex"] else fssearch.unescape(raw)
        root = self._folder
        self.spinner.start()
        self.spinner.set_visible(True)
        self.status.set_text("搜索中…")

        def worker() -> None:
            try:
                outcome = fssearch.search(
                    root, pattern,
                    recursive=opts["recursive"],
                    case_sensitive=opts["case_sensitive"],
                    regex=opts["regex"],
                    should_stop=lambda: generation != self._generation,
                )
                err = None
            except Exception as exc:  # noqa: BLE001
                outcome, err = None, str(exc)
            GLib.idle_add(lambda: self._on_result(generation, outcome, err, pattern))

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _on_result(self, generation: int, outcome, err, pattern: str) -> bool:
        if generation != self._generation:
            return False
        self.spinner.stop()
        self.spinner.set_visible(False)
        if err is not None:
            self.status.set_text(f"搜索失败：{err}")
            return False
        self._outcome = outcome
        self._render(outcome, pattern)
        return False

    def _clear(self) -> None:
        self._current_row = None
        while (child := self.results.get_first_child()) is not None:
            self.results.remove(child)

    def _build_file_head(self, file_hits: fssearch.FileHits) -> Gtk.Widget:
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.add_css_class("hit-file-head")
        head.set_margin_top(8)
        head.set_margin_bottom(2)
        head.append(Gtk.Image(icon_name="text-x-generic-symbolic"))
        head.append(
            Gtk.Label(
                label=file_hits.rel, xalign=0, hexpand=True,
                ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"],
            )
        )
        head.append(Gtk.Label(label=f"{file_hits.count} 处", css_classes=["dim-label"]))
        # 整文件替换入口（等价于右键菜单的「替换此内容…」，只是范围是该文件全部命中）
        replace = Gtk.Button(
            icon_name="edit-find-replace-symbolic",
            css_classes=["flat"],
            valign=Gtk.Align.CENTER,
            tooltip_text=f"在「{file_hits.rel}」中替换…",
        )
        replace.connect("clicked", lambda *_a, p=file_hits.path: self.replace_in_file(p))
        head.append(replace)
        return head

    def _hit_label(self, hit: fssearch.Hit, pattern: str, opts: dict) -> Gtk.Label:
        if hit.excerpt:
            # 跨行命中：excerpt 里已把换行渲染成 ⏎，不再做高亮（避免标记错位）
            return Gtk.Label(
                label=hit.excerpt, xalign=0, hexpand=True,
                ellipsize=Pango.EllipsizeMode.END,
            )
        snippet = fssearch.preview_snippet(
            hit.line_text, pattern, opts["case_sensitive"], opts["regex"]
        )
        return Gtk.Label(
            label=_markup(snippet, pattern, opts["case_sensitive"], opts["regex"]),
            use_markup=True, xalign=0, hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
        )

    def _render(self, outcome: fssearch.SearchOutcome, pattern: str) -> None:
        self._clear()
        if outcome.total_hits == 0:
            self.status.set_text(
                f"扫描 {outcome.scanned} 个文件，没有命中"
                + (f"（跳过 {outcome.skipped} 个不可读/二进制文件）" if outcome.skipped else "")
            )
            return
        opts = self._options()
        shown = 0
        for file_hits in outcome.files:
            self.results.append(self._build_file_head(file_hits))
            for hit in file_hits.hits[:PER_FILE_HITS]:
                if shown >= DISPLAY_LIMIT:
                    break
                self.results.append(
                    _HitRow(self, file_hits, hit, self._hit_label(hit, pattern, opts))
                )
                shown += 1
            if shown >= DISPLAY_LIMIT:
                break

        note = f"，仅显示前 {shown} 条" if outcome.truncated or shown < outcome.total_hits else ""
        self.status.set_text(
            f"扫描 {outcome.scanned} 个文件：{outcome.matched_files} 个文件命中 "
            f"{outcome.total_hits} 处{note}"
            + (f"（跳过 {outcome.skipped} 个）" if outcome.skipped else "")
        )

    # ------------------------------------------------------------------ 跳转 / 替换

    def focus_hit_row(self, row: _HitRow) -> None:
        """单击只做选中：给当前行着高亮，不打开文件。"""
        if self._current_row is row:
            return
        if self._current_row is not None:
            self._current_row.remove_css_class("hit-row-current")
        self._current_row = row
        row.add_css_class("hit-row-current")

    def open_hit(self, path: Path, hit: fssearch.Hit) -> None:
        self.close()
        line, column, length = hit.line_no, hit.column, hit.length
        GLib.idle_add(
            lambda: (self.window.open_path_at_line(path, line, column, length), False)[1]
        )

    def replace_in_file(self, path: Path | None = None) -> None:
        """把当前目录、查找内容与选项带进「目录批量替换」，默认只勾选 `path`。"""
        raw = self.entry.get_text()
        folder = self._folder
        opts = self._options()
        window = self.window

        def open_it() -> bool:
            self.replace_dialog = window.open_folder_replace_for(
                folder=folder, find_text=raw, options=opts, only_file=path
            )
            return False

        self.close()
        GLib.idle_add(open_it)


class FolderReplaceDialog(_FolderDialog):
    """在选定目录中批量替换，先预览再执行，自动备份。

    可以带参打开（从搜索结果右键「替换此内容…」）：
    `find_text` 预填查找内容，`folder` 预选目录，`options` 沿用搜索的三个开关，
    `only_file` 让预览后**只勾选**这一个文件。
    """

    def __init__(
        self,
        window,
        *,
        find_text: str = "",
        folder: Path | str | None = None,
        options: dict | None = None,
        only_file: Path | str | None = None,
    ) -> None:
        super().__init__(window, "目录批量替换", case_default=True)
        self._plan: fssearch.Plan | None = None
        self._rows: list[tuple[Gtk.CheckButton, fssearch.FilePlan]] = []
        self._busy = False
        self._only_file = Path(only_file) if only_file is not None else None

        if options:
            self.recursive_switch.set_active(bool(options.get("recursive", True)))
            self.case_switch.set_active(bool(options.get("case_sensitive", True)))
            self.regex_switch.set_active(bool(options.get("regex", False)))

        entries = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.find_entry = Gtk.Entry(
            placeholder_text=r"查找内容（支持 \n \t \r \\）", hexpand=True
        )
        self.replace_entry = Gtk.Entry(
            placeholder_text=r"替换为（支持 \n \t \r \\）", hexpand=True
        )
        entries.append(Gtk.Label(label="查找"))
        entries.append(self.find_entry)
        entries.append(Gtk.Label(label="替换"))
        entries.append(self.replace_entry)
        self._add_to_body(entries)
        self.find_entry.connect("changed", lambda *_: self._invalidate())

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preview_button = Gtk.Button(label="预览替换")
        self.preview_button.connect("clicked", lambda *_: self._start_preview())
        self.apply_button = Gtk.Button(label="执行替换", css_classes=["destructive-action"])
        self.apply_button.set_sensitive(False)
        self.apply_button.connect("clicked", lambda *_: self._confirm_apply())
        self.select_all_button = Gtk.Button(label="全选")
        self.select_all_button.connect("clicked", lambda *_: self._set_all(True))
        actions.append(self.preview_button)
        actions.append(self.select_all_button)
        actions.append(self.apply_button)
        self._add_to_body(actions)

        # 任何会影响结果的输入变化都必须作废旧预览——否则「改完替换内容直接点执行」
        # 会拿旧计划落盘（旧计划里的替换串可能是空的，等于把命中处删掉）。
        self.replace_entry.connect("changed", lambda *_: self._invalidate())
        for switch in (self.recursive_switch, self.case_switch, self.regex_switch):
            switch.connect("notify::active", lambda *_: self._invalidate())

        self.status = Gtk.Label(
            label="选择目录，输入查找与替换内容，先点「预览替换」",
            halign=Gtk.Align.START, wrap=True, css_classes=["dim-label"],
        )
        self._add_to_body(self.status)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_has_frame(True)
        self.listbox = Gtk.ListBox(css_classes=["boxed-list"])
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self.listbox)
        self._add_to_body(scroller)

        self.spinner = Gtk.Spinner(visible=False)
        self._add_to_body(self.spinner)

        if folder is not None:
            self._set_folder(Path(folder), remember=False)
        if find_text:
            self.find_entry.set_text(find_text)
            self.find_entry.set_position(-1)
        self._restore_last_folder()
        if find_text and folder is not None and self._only_file is not None:
            # 从搜索结果进来：立刻预览一次，并把勾选收敛到目标文件
            self.status.set_text(f"正在检查「{self._only_file.name}」…（预览后只勾选该文件）")
            GLib.idle_add(self._auto_preview)

    def _auto_preview(self) -> bool:
        self._start_preview()
        return False

    # ------------------------------------------------------------------ 预览

    def _invalidate(self) -> None:
        self._plan = None
        button = getattr(self, "apply_button", None)
        if button is not None:
            button.set_sensitive(False)
        if getattr(self, "status", None) is not None and self._rows:
            self.status.set_text("输入已改动，请重新点「预览替换」后再执行")

    def _on_folder_changed(self) -> None:
        self._invalidate()

    def _start_preview(self) -> None:
        if self._busy:
            return
        if self._folder is None:
            self.status.set_text("请先选择一个文件夹")
            return
        raw = self.find_entry.get_text()
        if not raw:
            self.status.set_text("查找内容不能为空")
            return
        opts = self._options()
        pattern = raw if opts["regex"] else fssearch.unescape(raw)
        replacement = self.replace_entry.get_text()
        if not opts["regex"]:
            replacement = fssearch.unescape(replacement)
        root = self._folder
        self._set_busy(True, "正在扫描…")

        def worker() -> None:
            try:
                plan = fssearch.plan_replace(
                    root, pattern, replacement,
                    recursive=opts["recursive"],
                    case_sensitive=opts["case_sensitive"],
                    regex=opts["regex"],
                )
                err = None
            except Exception as exc:  # noqa: BLE001
                plan, err = None, str(exc)
            GLib.idle_add(lambda: self._on_plan(plan, err))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.preview_button.set_sensitive(not busy)
        self.apply_button.set_sensitive(not busy and bool(self._plan and self._plan.changed_files))
        if message:
            self.status.set_text(message)

    def _on_plan(self, plan, err) -> bool:
        self._set_busy(False)
        if err is not None:
            self.status.set_text(f"预览失败：{err}")
            return False
        self._plan = plan
        self._rows.clear()
        while (child := self.listbox.get_first_child()) is not None:
            self.listbox.remove(child)

        if not plan.changed_files:
            self.status.set_text(f"扫描 {plan.scanned} 个文件，没有可替换的内容")
            self.apply_button.set_sensitive(False)
            return False

        for item in plan.changed_files:
            row = Gtk.ListBoxRow(activatable=False, selectable=False)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            check = Gtk.CheckButton(active=True)
            box.append(check)
            box.append(
                Gtk.Label(
                    label=item.rel, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                    tooltip_text=str(item.path),
                )
            )
            box.append(Gtk.Label(label=f"{item.count} 处", css_classes=["dim-label"]))
            row.set_child(box)
            self.listbox.append(row)
            self._rows.append((check, item))

        for item in plan.files:
            if item.error:
                row = Gtk.ListBoxRow(activatable=False, selectable=False)
                label = Gtk.Label(
                    label=f"{item.rel}：{item.error}", xalign=0, wrap=True,
                    css_classes=["dim-label", "error"],
                )
                row.set_child(label)
                self.listbox.append(row)

        note_only = ""
        if self._only_file is not None:
            note_only = self._select_only_file()
        if not self.replace_entry.get_text():
            note_only += "；替换内容为空，执行会删除命中的文本"

        self.status.set_text(
            f"扫描 {plan.scanned} 个文件：将修改 {len(plan.changed_files)} 个文件，"
            f"共 {plan.total_replacements} 处（执行前自动备份）"
            + (f"；{plan.skipped} 个文件被跳过" if plan.skipped else "")
            + note_only
        )
        self.apply_button.set_sensitive(True)
        return False

    def _select_only_file(self) -> str:
        """只勾选从搜索结果进来的那个文件，返回给状态行追加的说明。"""
        target = self._only_file
        try:
            target_key = target.resolve()
        except OSError:
            target_key = target
        checked = 0
        for check, item in self._rows:
            try:
                same = item.path.resolve() == target_key
            except OSError:
                same = item.path == target
            check.set_active(same)
            checked += int(same)
        if checked:
            return f"；已只勾选「{target.name}」，其它文件需手动勾选"
        return f"；「{target.name}」中没有命中，未勾选任何文件"

    def _set_all(self, active: bool) -> None:
        for check, _item in self._rows:
            check.set_active(active)

    # ------------------------------------------------------------------ 执行

    def _selected_paths(self) -> list[Path]:
        return [item.path for check, item in self._rows if check.get_active()]

    def _confirm_apply(self) -> None:
        plan = self._plan
        if plan is None:
            return
        selected = self._selected_paths()
        if not selected:
            self.status.set_text("没有勾选任何文件")
            return
        count = sum(item.count for _c, item in self._rows if item.path in set(selected))
        dialog = Adw.AlertDialog(
            heading="确认替换？",
            body=(
                f"将修改 {len(selected)} 个文件，共 {count} 处。\n"
                "原文件会自动备份，误操作可从备份目录恢复。"
            ),
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("apply", "执行替换")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: self._apply(selected) if r == "apply" else None)
        dialog.present(self)

    def _apply(self, selected: list[Path]) -> None:
        plan = self._plan
        if plan is None or self._busy:
            return
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        backup = paths.data_root() / "replace-backups" / stamp
        chosen = set(selected)
        # 记录替换前内容，供窗口判断标签是否被用户在应用内改过
        before = {str(item.path): item.old_text for item in plan.files if item.path in chosen}
        self._set_busy(True, "正在写入…")

        def worker() -> None:
            try:
                result = fssearch.apply_plan(plan, backup, only=selected)
                err = None
            except Exception as exc:  # noqa: BLE001
                result, err = None, str(exc)
            GLib.idle_add(lambda: self._on_applied(result, err, backup, before))

        threading.Thread(target=worker, daemon=True).start()

    def _on_applied(self, result, err, backup: Path, before: dict[str, str]) -> bool:
        self._set_busy(False)
        if err is not None:
            self.status.set_text(f"替换失败：{err}")
            return False
        reloaded, skipped = self.window.reload_source_tabs(result.changed, before)
        parts = [f"已修改 {len(result.changed)} 个文件，共 {result.replacements} 处"]
        parts.append(f"备份：{backup}")
        if reloaded:
            parts.append(f"已刷新 {reloaded} 个打开的标签")
        if skipped:
            parts.append(f"{skipped} 个标签有未保存修改，未自动刷新")
        if result.errors:
            parts.append("；".join(result.errors[:3]))
        self.status.set_text("\n".join(parts))
        self.apply_button.set_sensitive(False)
        self._plan = None
        self.window.toast_overlay.add_toast(
            Adw.Toast(title=f"替换完成：{len(result.changed)} 个文件 / {result.replacements} 处", timeout=6)
        )
        return False
