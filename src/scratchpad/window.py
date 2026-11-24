"""主窗口：多标签管理、自动保存调度、模式切换、状态栏。"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import assets, columnedit, keymap, paths, snippets  # noqa: E402
from . import backupzip  # noqa: E402
from .cloud import (  # noqa: E402
    BACKUP_INTERVAL_DEFAULT,
    CHANGE_DEBOUNCE,
    STARTUP_DELAY,
    SYNC_INTERVAL_DEFAULT,
    CloudManager,
)
from .command_menu import Command, CommandMenu, CommandSection, format_accel  # noqa: E402
from .editor import MODE_PREVIEW, MODE_SOURCE, MODE_SPLIT, EditorPage  # noqa: E402

# 设置宽度循环顺序：关闭 → 85% → 75% → 50% → 关闭（Ctrl+Shift+M）
# （内部标识沿用 writing_* 命名与 meta key，避免偏好迁移；源码/预览两区同时生效）
WRITING_CYCLE = ("off", "85", "75", "50")
# 打字机模式光标行位置候选（视口百分比，50=居中，33≈SoloMD 的 1/3 处）
TYPEWRITER_ALIGNS = ("25", "33", "50", "66", "75")
from .outline import parse_headings  # noqa: E402
from .sidebar import Sidebar  # noqa: E402
from .store import Document, SaveState, Store  # noqa: E402

AUTOSAVE_DELAY_MS = 300
_KEYDEBUG = bool(os.environ.get("GSCRATCHPAD_KEYDEBUG"))
FORMAT_ICON = {
    "txt": "text-x-generic-symbolic",
    "md": "text-markdown-symbolic",
    "html": "text-html-symbolic",
}

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".avif",
}
MD_EXTS = {".md", ".markdown", ".mkd"}
HTML_EXTS = {".html", ".htm"}
TEXT_EXTS = {
    ".txt", ".text", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".py", ".js", ".ts", ".css", ".html", ".htm", ".xml",
    ".sh", ".c", ".h", ".cpp", ".rs", ".go", ".java", ".sql", ".rst", ".org",
    ".tex", ".bib", ".plist",
}

# 快捷键说明对话框的内容：(分组名, ((加速键, 说明), …))；加速键为空表示只列说明
SHORTCUTS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "标签页",
        (
            ("<Control>N", "新建标签"),
            ("<Control>O", "打开本机文件（可多选）"),
            ("<Control>S", "保存到本机文件（未关联时另存为）"),
            ("<Control>W", "关闭当前标签（保留文档）"),
            ("<Control>Tab", "下一个标签"),
            ("<Control><Shift>Tab", "上一个标签"),
            ("", "Ctrl+1 … Ctrl+9：切换到指定标签"),
        ),
    ),
    (
        "编辑",
        (
            ("<Control>Z", "撤销"),
            ("<Control><Shift>Z", "重做"),
            ("<Control>F", "查找"),
            ("<Control>H", "替换"),
            ("<Control><Shift>F", "在目录中搜索"),
            ("<Control><Shift>H", "目录批量替换"),
            ("<Control><Shift>P", "切换源码 / 预览"),
            ("<Control><Shift>M", "设置宽度：关闭 → 85% → 75% → 50% 循环"),
            ("<Control><Shift>T", "打字机模式：光标行固定于视口百分比处（开 / 关）"),
            ("<Control><Shift>I", "格式化排版（JSON / XML / HTML / Python / Bash）"),
            ("", "列编辑：菜单「工具」（每行加前缀 / 后缀、行排序、去重）"),
            ("<Control><Shift>K", "按列提取（按分隔符或字符宽度只保留一列）"),
            ("<Control>K", "命令菜单（菜单 + 命令搜索）"),
            ("<Control><Shift>E", "片段与自动补全设置"),
            ("F9", "显示 / 隐藏侧边栏"),
            ("", "输入触发词后按 Tab 展开片段（Bash / Markdown / HTML 等）"),
            ("", "自定义片段快捷键在「片段与自动补全」里录制"),
            ("", "简体 ↔ 繁体（菜单「工具」，需系统安装 opencc）"),
        ),
    ),
)


def _human_size(size: float) -> str:
    """字节数 → 便于阅读的字符串（B/KB/MB/GB，一位小数）。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _read_text_file(path: Path) -> str:
    """读取文本文件：utf-8 → gb18030 → latin-1 逐级降级；含 NUL 视为二进制。"""
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError("二进制文件，不支持作为文本打开")
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _cloud_time(raw: str) -> str:
    """meta 里的执行时间戳 → 本地时间短串；空/无效返回占位。"""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(raw)))
    except (TypeError, ValueError):
        return "—"


class ScratchpadWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, store: Store) -> None:
        super().__init__(application=application)
        self.store = store
        self.set_title("Gscratchpad")
        self.set_default_size(1000, 700)
        self.mode = MODE_SOURCE
        # 写作模式：'off' 或 '50' / '75' / '85'（启动时从 meta 恢复）
        self._writing_mode = "off"
        self._writing_action: Gio.SimpleAction | None = None
        self._timers: dict[str, int] = {}
        self._pages: dict[str, EditorPage] = {}
        self._closing = False
        self._file_save_banner_until = 0.0
        self._sidebar_timer: int | None = None
        self._suppress_sidebar_persist = False
        self._outline_timer: int | None = None
        self._outline_sig: tuple | None = None
        self._closed_docs: list = []
        self._folder_dialog = None  # 目录搜索/替换对话框（防 GC）
        self.snippets: list[snippets.Snippet] = []
        self._snippet_actions: list[str] = []
        self._snippets_dialog = None
        self._snippet_editor = None
        # 云备份 / 云同步（sync v1）：管理器 + 定时器；墓碑由 store 删除事件驱动
        self.cloud = CloudManager(self.store)
        self._cloud_debounce_timer: int | None = None
        self.cloud.on_status = self._on_cloud_status
        # 保存状态回调在写线程内触发 → 转投主循环，再操作 GLib 定时器
        self.store.on_save_state(lambda _s: GLib.idle_add(self._cloud_touch))

        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", self._on_theme_changed)

        self._build_ui()
        self._build_actions()
        self._init_snippets()
        self._apply_color_scheme(self.store.get_meta("color_scheme", "default"), persist=False)
        self._restore_geometry()

        # 云调度定时器：启动延迟 / 同步周期 / 备份周期（回调内部检查开关与配置）
        GLib.timeout_add_seconds(int(STARTUP_DELAY), self._on_cloud_startup_tick)
        GLib.timeout_add_seconds(int(SYNC_INTERVAL_DEFAULT), self._on_cloud_sync_tick)
        GLib.timeout_add_seconds(int(BACKUP_INTERVAL_DEFAULT), self._on_cloud_backup_tick)

        # Ctrl+F / Ctrl+H 三重保险：
        # 1) 窗口 capture 阶段直接调 show_search，不经过 action muxer；
        # 2) 窗口级 ShortcutController（GLOBAL），与 accel 同源但独立于焦点控件；
        # 3) 标题栏放大镜按钮 + 菜单项，鼠标也能到达同一功能。
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_window_key)
        self.add_controller(key_ctrl)

        sc = Gtk.ShortcutController()
        sc.set_scope(Gtk.ShortcutScope.GLOBAL)
        sc.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control>f"),
                action=Gtk.NamedAction.new("win.find"),
            )
        )
        sc.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control>h"),
                action=Gtk.NamedAction.new("win.replace"),
            )
        )
        sc.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control><Shift>f"),
                action=Gtk.NamedAction.new("win.fs-search"),
            )
        )
        sc.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control><Shift>h"),
                action=Gtk.NamedAction.new("win.fs-replace"),
            )
        )
        sc.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<Control>k"),
                action=Gtk.NamedAction.new("win.command-menu"),
            )
        )
        self.add_controller(sc)

        self.store.on_save_state(self._on_save_state)

        self.connect("close-request", self._on_close_request)

    def _on_window_key(self, _ctrl, keyval, _code, state) -> bool:
        if _KEYDEBUG:
            print(f"[keys] keyval={keyval:#x} state={int(state):#x}", file=sys.stderr, flush=True)
        if keyval == Gdk.KEY_Escape and not (
            state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK)
        ):
            # 查找栏打开时 Esc 归 SearchBar（先关查找再谈侧栏），避免抢走它的关闭
            page = self._current_page()
            if page is not None and page.search_bar.get_search_mode():
                return False
            if self.sidebar_visible():
                self.hide_sidebar()
                return True
            return False
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        if keyval in (Gdk.KEY_c, Gdk.KEY_C):
            # Ctrl+C：窗口 CAPTURE 阶段抢在 GtkTextView 内置 text.copy-clipboard
            # 之前，改走显式 UTF8_STRING，避免中文被消费方按 Latin-1 转成 \\XX。
            # 仅拦截「焦点在编辑器且有选区」；无选区或焦点在搜索框等处交还内置行为。
            page = self._current_page()
            if page is not None and page.view.has_focus() and page.buffer.get_has_selection():
                page.copy_as_utf8_text()
                return True
            return False
        if keyval in (Gdk.KEY_f, Gdk.KEY_F):
            page = self._current_page()
            if page is not None:
                page.show_search(False)
                return True
        elif keyval in (Gdk.KEY_h, Gdk.KEY_H):
            page = self._current_page()
            if page is not None:
                page.show_search(True)
                return True
        return False

    # ================================================================== UI 构建

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Gscratchpad", subtitle="")
        header.set_title_widget(title)
        self._header = header

        # 编辑模式切换（三态按钮组）
        self.mode_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=0, css_classes=["linked"]
        )
        self._mode_buttons: dict[str, Gtk.ToggleButton] = {}
        for mode, icon, tooltip in (
            (MODE_SOURCE, "document-edit-symbolic", "源码编辑"),
            (MODE_SPLIT, "view-dual-symbolic", "分屏预览"),
            (MODE_PREVIEW, "eye-symbolic", "实时预览"),
        ):
            btn = Gtk.ToggleButton(
                icon_name=icon, tooltip_text=tooltip, active=(mode == MODE_SOURCE)
            )
            btn.connect("toggled", self._on_mode_toggled, mode)
            self.mode_box.append(btn)
            self._mode_buttons[mode] = btn

        # 写作模式：同一 linked 组内的下拉按钮（位于三态模式按钮之后、新建标签之前）
        self.writing_button = Gtk.MenuButton(
            icon_name="format-justify-center-symbolic",
            tooltip_text="设置宽度：源码与预览居中排版，Ctrl+Shift+M 循环切换",
        )
        writing_menu = Gio.Menu()
        for label, value in (
            ("关闭（满宽）", "off"),
            ("居中 85%", "85"),
            ("居中 75%", "75"),
            ("居中 50%", "50"),
        ):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(
                "win.writing-mode", GLib.Variant.new_string(value)
            )
            writing_menu.append_item(item)
        self.writing_button.set_menu_model(writing_menu)
        self.mode_box.append(self.writing_button)

        # 打字机模式：写作模式右侧同风格下拉（跟随滚动 / 段落遮罩 / 光标行位置）
        self.typewriter_button = Gtk.MenuButton(
            icon_name="input-keyboard-symbolic",
            tooltip_text="打字机模式：光标行固定跟随 + 段落遮罩（Ctrl+Shift+T 开关跟随）",
        )
        tw_menu = Gio.Menu()
        tw_menu.append("跟随滚动（光标行固定）", "win.typewriter-mode")
        tw_menu.append("遮罩其它段落", "win.paragraph-dim")
        align_menu = Gio.Menu()
        for label, value in (
            ("视口 25%（偏上）", "25"),
            ("视口 33%（约 1/3 处）", "33"),
            ("视口 50%（居中）", "50"),
            ("视口 66%", "66"),
            ("视口 75%（偏下）", "75"),
        ):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(
                "win.typewriter-align", GLib.Variant.new_string(value)
            )
            align_menu.append_item(item)
        tw_menu.append_submenu("光标行位置", align_menu)
        self.typewriter_button.set_menu_model(tw_menu)
        self.mode_box.append(self.typewriter_button)

        # 侧边栏开关与三态模式按钮放在一起（同一组控件里）
        self.sidebar_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic",
            tooltip_text="显示 / 隐藏侧边栏（F9）",
            # 每次启动一律收起侧边栏，不记忆上次的展开状态；
            # 用户可在应用内用 F9 / 头部按钮随时展开。
            active=False,
        )
        self.sidebar_button.connect("toggled", self._on_sidebar_toggled)
        header_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_start.append(self.sidebar_button)
        header_start.append(self.mode_box)
        # 新建标签：紧贴三态模式按钮右侧，鼠标可达（键盘 Ctrl+N 仍有效）
        self.new_tab_button = Gtk.Button(
            icon_name="tab-new-symbolic", tooltip_text="新建标签（Ctrl+N）"
        )
        self.new_tab_button.connect(
            "clicked", lambda *_: self.activate_action("win.new-tab", None)
        )
        header_start.append(self.new_tab_button)
        # 撤销 / 重做按钮：灵敏度随缓冲区 can-undo / can-redo 属性自动同步
        self.undo_button = Gtk.Button(
            icon_name="edit-undo-symbolic", tooltip_text="撤销（Ctrl+Z）"
        )
        self.undo_button.connect("clicked", lambda *_: self.activate_action("win.undo", None))
        self.redo_button = Gtk.Button(
            icon_name="edit-redo-symbolic", tooltip_text="重做（Ctrl+Shift+Z）"
        )
        self.redo_button.connect("clicked", lambda *_: self.activate_action("win.redo", None))
        self.undo_button.set_sensitive(False)
        self.redo_button.set_sensitive(False)
        header_start.append(self.undo_button)
        header_start.append(self.redo_button)
        header.pack_start(header_start)

        # 命令菜单：分组 + 顶部搜索框（Ctrl+K 直接打开搜索）
        self.command_menu = CommandMenu(self._menu_sections, self._accel_for)
        self.command_menu.connect("command", self._on_command)
        self.menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text="菜单与命令搜索（Ctrl+K）",
            primary=True,
            popover=self.command_menu,
        )
        header.pack_end(self.menu_button)

        # 鼠标可达的查找入口：键盘快捷键被环境吞掉时仍能使用
        self.find_button = Gtk.Button(
            icon_name="edit-find-symbolic", tooltip_text="查找（Ctrl+F）"
        )
        self.find_button.connect("clicked", lambda *_: self.activate_action("win.find", None))
        header.pack_end(self.find_button)

        # 立即同步入口（位于主题与查找之间）：触发 win.cloud-sync-now，
        # 最近一次同步状态写入 tooltip，鼠标可达、无需开命令菜单
        self.sync_button = Gtk.Button(
            icon_name="emblem-synchronizing-symbolic", tooltip_text="立即同步（WebDAV）"
        )
        self.sync_button.connect(
            "clicked", lambda *_: self.activate_action("win.cloud-sync-now", None)
        )
        header.pack_end(self.sync_button)

        # 日间 / 夜间主题切换（持久化到 meta，重启后保持）
        self.theme_button = Gtk.Button(
            icon_name="weather-clear-night-symbolic", tooltip_text="切换到夜间主题"
        )
        self.theme_button.connect("clicked", lambda *_: self.toggle_theme())
        header.pack_end(self.theme_button)

        root.append(header)

        # 标签栏
        self.tabview = Adw.TabView()
        self.tabbar = Adw.TabBar(view=self.tabview, autohide=False)
        self.tabbar.set_css_classes(["scratchpad-tabbar"])

        self.tabview.connect("close-page", self._on_close_page)
        self.tabview.connect("notify::selected-page", self._on_selected_page)
        self.tabview.connect("page-reordered", lambda *_: self._persist_order())

        # 悬浮侧边栏：覆盖在编辑区之上，不挤压正文宽度（显示/隐藏时文字不重排）
        self.sidebar = Sidebar(self)
        self.sidebar.set_size_request(310, -1)
        self.sidebar_frame = Gtk.Box()
        self.sidebar_frame.set_css_classes(["sidebar-float"])
        self.sidebar_frame.set_margin_top(10)
        self.sidebar_frame.set_margin_bottom(10)
        self.sidebar_frame.set_margin_start(10)
        self.sidebar_frame.set_margin_end(12)
        self.sidebar_frame.append(self.sidebar)

        self.sidebar_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
            transition_duration=180,
        )
        self.sidebar_revealer.set_child(self.sidebar_frame)
        self.sidebar_revealer.set_halign(Gtk.Align.START)
        self.sidebar_revealer.set_valign(Gtk.Align.FILL)
        self.sidebar_revealer.set_overflow(Gtk.Overflow.VISIBLE)
        self.sidebar_revealer.set_reveal_child(self.sidebar_button.get_active())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.tabbar)
        content.append(self.tabview)
        self.overlay = Gtk.Overlay()
        self.overlay.set_child(content)
        self.overlay.add_overlay(self.sidebar_revealer)
        root.append(self.overlay)

        # 状态栏
        root.append(self._build_statusbar())

        self._rebuild_recent_menu()
        self.sidebar.refresh()

    def _build_statusbar(self) -> Gtk.Box:
        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            css_classes=["toolbar"], margin_start=12, margin_end=12,
            margin_top=4, margin_bottom=4,
        )
        self.stats_label = Gtk.Label(label="字符 0 · 词 0", css_classes=["dim-label"])
        bar.append(self.stats_label)

        self.format_button = Gtk.MenuButton(label="TXT", tooltip_text="切换文档格式")
        self.format_button.set_menu_model(self._build_format_menu())
        bar.append(self.format_button)

        self.save_icon = Gtk.Image(icon_name="object-select-symbolic", css_classes=["dim-label"])
        self.save_label = Gtk.Label(label="已保存", css_classes=["dim-label"])
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        bar.append(self.save_icon)
        bar.append(self.save_label)
        return bar

    def _build_format_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("纯文本 (TXT)", "win.set-format::txt")
        section.append("Markdown (MD)", "win.set-format::md")
        section.append("网页 (HTML)", "win.set-format::html")
        menu.append_section("文档格式", section)
        return menu

    # ================================================================== 命令菜单

    def _menu_sections(self) -> list[CommandSection]:
        """5 个语义分组，组内高频项在前；每次打开菜单现算（含已关闭文档）。"""
        sections = [
            CommandSection(
                "文档",
                [
                    Command("新建标签", "win.new-tab", keywords="new tab 新建 笔记"),
                    Command("打开本机文件…", "win.open-file", keywords="open 打开 文件"),
                    Command("保存到本机文件", "win.save-file", keywords="save 保存 写入"),
                    Command("重命名标签", "win.rename-tab", keywords="rename 改名"),
                    Command("插入图片…", "win.insert-image", keywords="image 图片 插图"),
                    Command("导出为 PDF…", "win.export-pdf", keywords="pdf 导出 打印 export"),
                ],
            ),
            CommandSection(
                "编辑",
                [
                    Command("撤销", "win.undo", keywords="undo 撤销"),
                    Command("重做", "win.redo", keywords="redo 重做"),
                    Command("查找…", "win.find", keywords="find search 搜索 查找"),
                    Command("查找与替换…", "win.replace", keywords="replace 替换"),
                    Command("关闭标签", "win.close-tab", keywords="close 关闭"),
                    Command("永久删除当前文档…", "win.delete-doc", keywords="delete 删除"),
                    Command("下一个标签页", "win.next-tab", keywords="tab 标签 切换"),
                    Command("上一个标签页", "win.prev-tab", keywords="tab 标签 切换"),
                ],
            ),
            CommandSection(
                "视图",
                [
                    Command("显示 / 隐藏侧边栏", "win.toggle-sidebar", keywords="sidebar 侧栏"),
                    Command("侧栏：笔记列表", "win.sidebar-view", "notes", keywords="notes 笔记"),
                    Command("侧栏：文件夹", "win.sidebar-view", "folders", keywords="folder 文件夹"),
                    Command("侧栏：本机磁盘", "win.sidebar-view", "disk", keywords="disk 磁盘 文件树"),
                    Command("侧栏：Markdown 大纲", "win.sidebar-view", "outline", keywords="outline 大纲 目录"),
                    Command(
                        "侧栏：选中笔记后自动隐藏（当前：%s）"
                        % ("开" if self.store.get_meta("sidebar_autohide", "1") == "1" else "关"),
                        "win.toggle-sidebar-autohide",
                        keywords="sidebar 侧栏 自动隐藏 autohide 收起",
                    ),
                    Command("源码编辑模式", "win.view-mode", MODE_SOURCE, keywords="source 源码"),
                    Command("分屏预览模式", "win.view-mode", MODE_SPLIT, keywords="split 分屏"),
                    Command("实时预览模式", "win.view-mode", MODE_PREVIEW, keywords="preview 预览"),
                    Command(
                        "设置宽度：关闭（满宽）",
                        "win.writing-mode",
                        "off",
                        keywords="writing 写作 专注 居中 满宽 关闭 宽度 width",
                    ),
                    Command(
                        "设置宽度：居中 85%",
                        "win.writing-mode",
                        "85",
                        keywords="writing 写作 专注 居中 85 宽度 width",
                    ),
                    Command(
                        "设置宽度：居中 75%",
                        "win.writing-mode",
                        "75",
                        keywords="writing 写作 专注 居中 75 宽度 width",
                    ),
                    Command(
                        "设置宽度：居中 50%",
                        "win.writing-mode",
                        "50",
                        keywords="writing 写作 专注 居中 50 宽度 width",
                    ),
                    Command(
                        "打字机模式：光标行固定跟随（开 / 关）",
                        "win.toggle-typewriter",
                        keywords="typewriter 打字机 滚动 跟随 居中 固定",
                    ),
                    Command(
                        "段落遮罩：非当前段落褪色退后（开 / 关）",
                        "win.paragraph-dim",
                        keywords="typewriter 打字机 遮罩 褪色 虚化 专注 dim",
                    ),
                    Command(
                        "打字机光标行位置：居中",
                        "win.typewriter-align",
                        "50",
                        keywords="typewriter 打字机 位置 居中 50",
                    ),
                    Command("切换日间 / 夜间主题", "win.toggle-theme", keywords="theme 主题 日间 夜间 深色 暗色"),
                ],
            ),
            CommandSection(
                "工具",
                [
                    Command("列编辑：每行加前缀…", "win.line-prefix", keywords="column 列 前缀 prefix"),
                    Command("列编辑：每行加后缀…", "win.line-suffix", keywords="column 列 后缀 suffix"),
                    Command("列编辑：行排序（A→Z）", "win.sort-lines", keywords="column 列 排序 sort"),
                    Command("列编辑：去除重复行", "win.dedup-lines", keywords="column 列 去重 dedup 重复"),
                    Command(
                        "列编辑：按列提取（保留一列）…",
                        "win.column-take",
                        keywords="column 列 提取 切分 分隔符 宽度 take",
                    ),
                    Command("格式化排版", "win.format-doc", keywords="format 格式化 排版"),
                    Command("简体 → 繁体", "win.convert-s2t", keywords="convert 简繁 繁体"),
                    Command("繁体 → 简体", "win.convert-t2s", keywords="convert 简繁 简体"),
                    Command("在目录中搜索…", "win.fs-search", keywords="search 目录 搜索 files"),
                    Command("目录批量替换…", "win.fs-replace", keywords="replace 目录 替换 files"),
                    Command("折叠当前区块", "win.fold-current", keywords="fold 折叠"),
                    Command("展开全部折叠", "win.unfold-all", keywords="unfold 展开"),
                    Command("片段与自动补全…", "win.manage-snippets", keywords="snippet 片段 补全 快捷键"),
                    Command("清除已关闭的笔记…", "win.purge-closed", keywords="purge 清除 已关闭 回收 清理 历史"),
                    Command("清理孤儿文件并压缩数据库…", "win.maintenance", keywords="maintenance 清理 孤儿 vacuum 压缩 数据库 空间"),
                    Command("云同步设置…", "win.cloud-sync-settings", keywords="webdav cloud sync 同步 云 备份 设置"),
                    Command("立即同步", "win.cloud-sync-now", keywords="webdav cloud sync 同步 云 now"),
                    Command("立即备份", "win.cloud-backup-now", keywords="webdav cloud backup 备份 云 now"),
                    Command("导入备份 zip…", "win.cloud-import-backup", keywords="import 导入 备份 恢复 zip"),
                    Command("从云端恢复…", "win.cloud-restore", keywords="webdav cloud restore 恢复 云端 备份 zip"),
                ],
            ),
        ]

        if self._closed_docs:
            sections.append(
                CommandSection(
                    "已关闭的文档",
                    [
                        Command(
                            (d.title[:32] + "…") if len(d.title) > 32 else d.title or "未命名",
                            "win.reopen-doc",
                            d.id,
                            keywords="reopen 重开 已关闭",
                        )
                        for d in self._closed_docs
                    ],
                )
            )

        if self.snippets:
            sections.append(
                CommandSection(
                    "片段",
                    [
                        Command(
                            s.name,
                            f"win.snippet-{s.id}",
                            keywords=f"snippet 片段 {s.accel}",
                        )
                        for s in self.snippets
                    ],
                )
            )

        sections.append(
            CommandSection(
                "其他",
                [
                    Command("键盘快捷键", "win.shortcuts", keywords="shortcut 快捷键 帮助"),
                    Command("关于 Gscratchpad", "app.about", keywords="about 关于 版本"),
                    Command("退出", "app.quit", keywords="quit 退出 关闭应用"),
                ],
            )
        )
        return sections

    def _accel_for(self, action: str) -> str:
        app = self.get_application()
        if app is None:
            return ""
        accels = app.get_accels_for_action(action)
        return format_accel(accels[0]) if accels else ""

    def _on_command(self, _menu, command: Command) -> None:
        target = GLib.Variant.new_string(command.target) if command.target else None
        if command.action.startswith("app."):
            app = self.get_application()
            if app is not None:
                app.activate_action(command.action[4:], target)
            return
        self.activate_action(command.action, target)

    def open_command_menu(self) -> None:
        """Ctrl+K：直接弹出命令搜索。"""
        self.command_menu.popup_with_search()

    def _rebuild_recent_menu(self) -> None:
        """刷新「已关闭的文档」缓存；命令菜单每次打开都会重读，无需重建模型。"""
        closed = [d for d in self.store.all_documents() if d.state == "closed"]
        closed.sort(key=lambda d: d.updated_at, reverse=True)
        self._closed_docs = closed[:10]

    # ================================================================== 动作

    def _build_actions(self) -> None:
        def add(name, callback, param_type=None):
            action = Gio.SimpleAction.new(name, param_type)
            action.connect("activate", callback)
            self.add_action(action)
            return action

        add("new-tab", lambda *_: self.new_tab())
        add("open-file", lambda *_: self.open_file())
        add("save-file", lambda *_: self.save_active_to_file())
        add("close-tab", lambda *_: self.close_current_tab())
        add("rename-tab", lambda *_: self.rename_current())
        add("insert-image", lambda *_: self.choose_image())
        add("export-pdf", lambda *_: self.export_pdf())
        add("toggle-sidebar", lambda *_: self.toggle_sidebar())
        add(
            "sidebar-view",
            lambda _a, value: self.show_sidebar_view(value.get_string()),
            GLib.VariantType.new("s"),
        )
        add("find", lambda *_: self._current_page() and self._current_page().show_search(False))
        add("replace", lambda *_: self._current_page() and self._current_page().show_search(True))
        add(
            "copy-as-encoding",
            lambda _a, value: (
                self._current_page().copy_as_encoded(value.get_string())
                if self._current_page() is not None
                else None
            ),
            GLib.VariantType.new("s"),
        )
        add("fs-search", lambda *_: self.open_folder_search())
        add("fs-replace", lambda *_: self.open_folder_replace())
        add("save-now", lambda *_: self.save_active_now())
        add("delete-doc", lambda *_: self.delete_current_document())
        add("purge-closed", lambda *_: self.purge_closed_documents())
        add("maintenance", lambda *_: self.run_maintenance())
        add("cloud-sync-settings", lambda *_: self.show_cloud_settings())
        add("cloud-sync-now", lambda *_: self.cloud.sync_async())
        add("cloud-backup-now", lambda *_: self.cloud.backup_async())
        add("cloud-import-backup", lambda *_: self.show_cloud_import())
        add("cloud-restore", lambda *_: self.show_cloud_restore())
        add("toggle-sidebar-autohide", lambda *_: self.toggle_sidebar_autohide())
        add("shortcuts", lambda *_: self.show_shortcuts())
        add("manage-snippets", lambda *_: self.manage_snippets())
        add("toggle-theme", lambda *_: self.toggle_theme())
        add("command-menu", lambda *_: self.open_command_menu())
        add("next-tab", lambda *_: self.step_tab(1))
        add("prev-tab", lambda *_: self.step_tab(-1))
        add("toggle-mode", lambda *_: self.toggle_source_preview())
        add("reopen-doc", self._on_reopen_doc, GLib.VariantType.new("s"))
        add("set-format", self._on_set_format, GLib.VariantType.new("s"))
        add("format-doc", lambda *_: self.format_current_doc())
        add("convert-s2t", lambda *_: self.convert_current_doc("s2t"))
        add("convert-t2s", lambda *_: self.convert_current_doc("t2s"))
        add("fold-current", lambda *_: self.fold_current_block())
        add("unfold-all", lambda *_: self.unfold_all_blocks())
        add("undo", lambda *_: self.undo_current(redo=False))
        add("redo", lambda *_: self.undo_current(redo=True))
        add("line-prefix", lambda *_: self.prompt_line_arg("prefix"))
        add("line-suffix", lambda *_: self.prompt_line_arg("suffix"))
        add("sort-lines", lambda *_: self.run_line_op("sort"))
        add("dedup-lines", lambda *_: self.run_line_op("dedup"))
        add("column-take", lambda *_: self.prompt_column_op())

        mode_action = Gio.SimpleAction.new_stateful(
            "view-mode", GLib.VariantType.new("s"), GLib.Variant.new_string(MODE_SOURCE)
        )

        def on_mode(action, value):
            self.set_mode(value.get_string())

        mode_action.connect("activate", on_mode)
        self.add_action(mode_action)

        # 写作模式（stateful 字符串：off / 50 / 75 / 85，菜单项自动显示选中态）
        saved = self.store.get_meta("writing_width", "off") or "off"
        if saved not in WRITING_CYCLE:
            saved = "off"
        self._writing_mode = saved
        writing_action = Gio.SimpleAction.new_stateful(
            "writing-mode", GLib.VariantType.new("s"), GLib.Variant.new_string(saved)
        )
        writing_action.connect("activate", self._on_writing_mode)
        self.add_action(writing_action)
        self._writing_action = writing_action
        add("cycle-writing-mode", lambda *_: self.cycle_writing_mode())

        # 打字机模式（stateful bool：光标行固定于视口百分比处跟随滚动）
        saved_tw = (self.store.get_meta("typewriter", "0") or "0") == "1"
        typewriter_action = Gio.SimpleAction.new_stateful(
            "typewriter-mode", None, GLib.Variant.new_boolean(saved_tw)
        )
        typewriter_action.connect("activate", self._on_typewriter_mode)
        self.add_action(typewriter_action)
        self._typewriter_action = typewriter_action
        add(
            "toggle-typewriter",
            lambda *_: self.set_typewriter(not self._typewriter()),
        )

        # 段落遮罩（可独立于跟随滚动；stateful bool）
        saved_dim = (self.store.get_meta("paragraph_dim", "0") or "0") == "1"
        dim_action = Gio.SimpleAction.new_stateful(
            "paragraph-dim", None, GLib.Variant.new_boolean(saved_dim)
        )
        dim_action.connect("activate", self._on_paragraph_dim)
        self.add_action(dim_action)
        self._dim_action = dim_action

        # 光标行位置（stateful 字符串：视口百分比）
        saved_align = self.store.get_meta("typewriter_align", "33") or "33"
        if saved_align not in TYPEWRITER_ALIGNS:
            saved_align = "33"
        align_action = Gio.SimpleAction.new_stateful(
            "typewriter-align",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(saved_align),
        )
        align_action.connect("activate", self._on_typewriter_align)
        self.add_action(align_action)
        self._align_action = align_action

        for index in range(1, 10):
            add(
                f"goto-{index}",
                lambda _a, _v, i=index: self.goto_tab(i - 1),
            )

    # ================================================================== 片段

    def _init_snippets(self) -> None:
        """启动时载入片段，并回放“被改绑的核心快捷键”记录。"""
        self.snippets = snippets.loads(self.store.get_meta(snippets.META_KEY))
        self._apply_accel_overrides()
        self._rebuild_snippet_actions()

    def _apply_accel_overrides(self) -> None:
        raw = self.store.get_meta(snippets.OVERRIDES_KEY)
        app = self.get_application()
        if app is None or not raw:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        for action, accels in data.items():
            if isinstance(accels, list):
                app.set_accels_for_action(action, [str(a) for a in accels])

    def _save_accel_overrides(self) -> None:
        app = self.get_application()
        if app is None:
            return
        data: dict[str, list[str]] = {}
        for action, defaults in keymap.ACCELS.items():
            live = list(app.get_accels_for_action(action))
            if {snippets.canonical_accel(a) for a in live} != {
                snippets.canonical_accel(a) for a in defaults
            }:
                data[action] = live
        self.store.set_meta(
            snippets.OVERRIDES_KEY, json.dumps(data, ensure_ascii=False), wait=True
        )

    def _rebuild_snippet_actions(self) -> None:
        """按当前片段列表重建 `win.snippet-<id>` 动作与加速键。"""
        app = self.get_application()
        for full in self._snippet_actions:
            if app is not None:
                app.set_accels_for_action(full, [])
            self.remove_action(full.split(".", 1)[1])
        self._snippet_actions.clear()
        for snippet in self.snippets:
            name = f"snippet-{snippet.id}"
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._on_snippet_activate, snippet.id)
            self.add_action(action)
            full = f"win.{name}"
            self._snippet_actions.append(full)
            if app is not None:
                app.set_accels_for_action(full, [snippet.accel] if snippet.accel else [])

    def save_snippets(self) -> None:
        self.store.set_meta(snippets.META_KEY, snippets.dumps(self.snippets), wait=True)
        self._rebuild_snippet_actions()

    def accel_owner(self, accel: str, *, exclude: str = "") -> tuple[str, str] | None:
        """accel 已被占用时返回 (动作名, 人话说明)。`exclude` 用于忽略正在编辑的片段。"""
        target = snippets.canonical_accel(accel)
        if not target:
            return None
        for snippet in self.snippets:
            if snippet.id == exclude or not snippet.accel:
                continue
            if snippets.canonical_accel(snippet.accel) == target:
                return (f"win.snippet-{snippet.id}", f"片段「{snippet.name}」")
        app = self.get_application()
        if app is None:
            return None
        for action in keymap.ACCELS:
            live = app.get_accels_for_action(action)
            if any(snippets.canonical_accel(a) == target for a in live):
                return (action, keymap.label_for(action))
        return None

    def release_accel(self, action: str) -> None:
        """把某个动作占用的加速键全部解除（片段被覆盖或用户选择改绑时调用）。"""
        app = self.get_application()
        if app is None:
            return
        if action.startswith("win.snippet-"):
            sid = action.split("win.snippet-", 1)[1]
            for snippet in self.snippets:
                if snippet.id == sid:
                    snippet.accel = ""
            self.save_snippets()
            return
        app.set_accels_for_action(action, [])
        self._save_accel_overrides()

    def overridden_accel_count(self) -> int:
        raw = self.store.get_meta(snippets.OVERRIDES_KEY)
        if not raw:
            return 0
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return 0
        if not isinstance(data, dict):
            return 0
        return sum(1 for value in data.values() if not value)

    def restore_default_accels(self) -> None:
        """还原核心快捷键；与默认键冲突的片段快捷键会被解除（片段仍可用菜单触发）。"""
        app = self.get_application()
        if app is None:
            return
        self.store.set_meta(snippets.OVERRIDES_KEY, "", wait=True)
        for action, defaults in keymap.ACCELS.items():
            app.set_accels_for_action(action, defaults)
        changed = False
        for snippet in self.snippets:
            if snippet.accel and self.accel_owner(snippet.accel, exclude=snippet.id):
                snippet.accel = ""
                changed = True
        if changed:
            self.save_snippets()
        else:
            self._rebuild_snippet_actions()

    def manage_snippets(self) -> None:
        from .snippets_ui import SnippetsDialog

        dialog = SnippetsDialog(self)
        dialog.connect("closed", lambda *_: setattr(self, "_snippets_dialog", None))
        dialog.present(self)
        self._snippets_dialog = dialog

    def _on_snippet_activate(self, _action, _param, snippet_id: str) -> None:
        self.insert_snippet_by_id(snippet_id)

    def insert_snippet_by_id(self, snippet_id: str) -> None:
        page = self._current_page()
        snippet = next((s for s in self.snippets if s.id == snippet_id), None)
        if page is None or snippet is None:
            return
        if not page.view.has_focus():
            # 焦点在搜索框 / 侧栏时不插入，避免“按了快捷键却不知道写进哪里”
            self.toast_overlay.add_toast(Adw.Toast(title="片段只在编辑区内插入：先点一下正文"))
            return
        page.insert_snippet(snippet.template)

    # ================================================================== 标签页

    def _current_page(self) -> EditorPage | None:
        tab = self.tabview.get_selected_page()
        return tab.get_child() if tab is not None else None

    def _configure_page_for_source(self, page: EditorPage) -> None:
        """已关联本机文件的文档：按扩展名设置语法高亮与预览 base_uri。"""
        linked = self.store.source_path_of(page.doc_id)
        if linked:
            page.set_language_for_path(linked)
            page.set_base_uri(linked)

    def add_tab(self, doc: Document, *, activate: bool = True) -> EditorPage:
        page = EditorPage()
        page.load_document(doc.id, doc.title, doc.format, doc.content, doc.revision)
        self._configure_page_for_source(page)
        page.set_mode(self._doc_mode_of(doc.id), initial=True)
        page.set_scheme(Adw.StyleManager.get_default().get_dark())
        page.set_writing_width(self._writing_pct())
        self._apply_typewriter_state(page)
        self._restore_cursor(page)
        page.connect("edited", self._on_page_edited, page)
        page.connect("stats-changed", self._on_page_stats, page)
        page.connect("request-toast", self._on_page_request_toast, page)
        page.buffer.connect("notify::can-undo", self._on_undo_state_changed, page)
        page.buffer.connect("notify::can-redo", self._on_undo_state_changed, page)
        self._pages[doc.id] = page

        tab = self.tabview.append(page)
        tab.set_title(doc.title or "未命名")
        tab.set_tooltip(doc.title or "未命名")
        tab.set_icon(Gio.ThemedIcon.new(FORMAT_ICON.get(doc.format, "text-x-generic-symbolic")))
        page.tab = tab

        if activate:
            self.tabview.set_selected_page(tab)
        self._schedule_sidebar_refresh()
        return page

    def new_tab(self, fmt: str = "txt", activate: bool = True) -> EditorPage:
        doc = self.store.create_document(fmt)
        return self.add_tab(doc, activate=activate)

    def close_current_tab(self) -> None:
        tab = self.tabview.get_selected_page()
        if tab is not None:
            self.tabview.close_page(tab)

    def _on_close_page(self, _view, tab) -> bool:
        """关闭标签 = 关闭视图；先确保内容已持久化，再把文档标记为已关闭。"""
        page = tab.get_child()
        if page is None:
            return False
        self._cancel_timer(page.doc_id)
        if self.store.get(page.doc_id) is None:
            # 文档已被永久删除：不再回写，避免"文档不存在"的错误提示
            self._pages.pop(page.doc_id, None)
            self._schedule_sidebar_refresh()
            return False
        self._save_page(page, wait=True)
        self._save_cursor(page)
        self.store.set_state(page.doc_id, "closed")
        self._pages.pop(page.doc_id, None)
        self._schedule_sidebar_refresh()
        GLib.idle_add(lambda *_: (self._persist_order(), False)[1] if not self._closing else False)
        # 关闭后若没有标签，补一个空白标签，保持“打开即可输入”的体验
        if self.tabview.get_n_pages() <= 1:
            GLib.idle_add(self._ensure_tab_after_close, tab)
        return False

    def _ensure_tab_after_close(self, closing_tab) -> bool:
        if self.tabview.get_n_pages() == 0:
            self.new_tab()
        return False

    def ensure_placeholder_tab(self) -> None:
        """没有任何标签时补一个空白标签，保证「打开即可输入」。

        首次启动带文件（文件管理器关联打开）时，do_open 会自己建标签，
        此时不该再塞一个空白标签进去，所以这个兜底由调用方在打开之后再决定。
        """
        if self.tabview.get_n_pages() == 0:
            self.new_tab()

    def _on_selected_page(self, _view, _param) -> None:
        tab = self.tabview.get_selected_page()
        if tab is None:
            return
        page = tab.get_child()
        if page is not None:
            previous = getattr(self, "_active_doc_id", None)
            if previous and previous != page.doc_id:
                self._save_cursor(self._pages.get(previous))
            self._active_doc_id = page.doc_id
            self.store.set_meta("active_doc", page.doc_id)
            # 切换标签：窗口模式跟随该文档自己的模式（各页模式独立）
            if page.mode != self.mode:
                self.mode = page.mode
                for name, button in self._mode_buttons.items():
                    blocked = button.handler_block_by_func(self._on_mode_toggled)
                    button.set_active(name == page.mode)
                    button.handler_unblock_by_func(self._on_mode_toggled)
            self._update_stats(page)
            self._update_format_button(page)
            self._sync_undo_buttons(page)
            self.save_label.set_tooltip_text(
                self.store.source_path_of(page.doc_id) or None
            )
            # 未选中的标签页不再需要预览进程：进入倒计时；选中的恢复/重建
            for index in range(self.tabview.get_n_pages()):
                other = self.tabview.get_nth_page(index).get_child()
                if other is None:
                    continue
                if other is page:
                    other.preview.keep_alive()
                else:
                    other.preview.schedule_release()
            page.view.grab_focus()
        self._schedule_outline_refresh(80)

    def goto_tab(self, index: int) -> None:
        pages = self.tabview.get_n_pages()
        if 0 <= index < pages:
            self.tabview.set_selected_page(self.tabview.get_nth_page(index))

    def step_tab(self, delta: int) -> None:
        n = self.tabview.get_n_pages()
        if n == 0:
            return
        current = self.tabview.get_page_position(self.tabview.get_selected_page())
        self.goto_tab((current + delta) % n)

    def _persist_order(self) -> None:
        ids = []
        for i in range(self.tabview.get_n_pages()):
            page = self.tabview.get_nth_page(i).get_child()
            if page is not None:
                ids.append(page.doc_id)
        self.store.reorder(ids)

    def rename_current(self) -> None:
        page = self._current_page()
        if page is None:
            return
        entry = Gtk.Entry(text=page.title, activates_default=True)
        dialog = Adw.AlertDialog(body="为标签页设置一个名称", heading="重命名")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "确定")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_rename_response, page, entry)
        dialog.present(self)

    def _on_rename_response(self, dialog, response, page, entry) -> None:
        if response != "ok":
            return
        title = entry.get_text().strip() or "未命名"
        page.title = title
        page.tab.set_title(title)
        self.store.rename(page.doc_id, title)
        self._save_page(page, wait=False)
        self._rebuild_recent_menu()
        self._schedule_sidebar_refresh()

    # ================================================================== 保存

    def _on_page_request_toast(self, _page, text: str, _page_data) -> None:
        """编辑器工具的 toast 提示通道（如「已在选区内替换 N 处」）。"""
        self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=4))

    def _on_page_edited(self, _page, page) -> None:
        self._cancel_timer(page.doc_id)
        source = GLib.timeout_add(AUTOSAVE_DELAY_MS, self._autosave_tick, page)
        self._timers[page.doc_id] = source
        self._set_save_ui("saving", "自动保存中…")
        if page is self._current_page():
            self._schedule_outline_refresh()

    def _cancel_timer(self, doc_id: str) -> None:
        source = self._timers.pop(doc_id, None)
        if source is not None:
            GLib.source_remove(source)

    def _autosave_tick(self, page) -> bool:
        self._timers.pop(page.doc_id, None)
        if page.doc_id in self._pages:
            self._save_page(page)
            # 顺带记录光标：进程被强杀时也能回到接近原来的位置（不阻塞 UI）
            self._save_cursor(page, wait=False)
        return False

    def _build_snapshot(self, page: EditorPage) -> Document:
        base = self.store.get(page.doc_id)
        if base is None:
            raise RuntimeError(f"文档不存在：{page.doc_id}")
        return replace(
            base,
            content=page.snapshot_text(),
            title=page.title,
            format=page.format,
            revision=base.revision + 1,
        )

    def _save_page(self, page: EditorPage, *, wait: bool = False) -> None:
        try:
            doc = self._build_snapshot(page)
        except RuntimeError as exc:
            self._set_save_ui("error", str(exc))
            return
        page.revision = doc.revision
        self.store.submit_save(doc, wait=wait)

    def save_active_now(self) -> None:
        page = self._current_page()
        if page is not None:
            self._save_page(page, wait=True)

    # ---- 编辑进度（光标行号，重新打开后回到原位）

    @staticmethod
    def _cursor_key(doc_id: str) -> str:
        return f"cursor:{doc_id}"

    @staticmethod
    def _mode_key(doc_id: str) -> str:
        """每文档模式持久化 key：重开应用恢复该文档关闭时的模式。"""
        return f"mode:{doc_id}"

    def _doc_mode_of(self, doc_id: str) -> str:
        saved = self.store.get_meta(self._mode_key(doc_id), self.mode)
        return saved if saved in (MODE_SOURCE, MODE_SPLIT, MODE_PREVIEW) else self.mode

    def _save_doc_mode(self, page: EditorPage | None) -> None:
        if page is None or not page.doc_id:
            return
        self.store.set_meta(self._mode_key(page.doc_id), page.mode)

    def _save_cursor(self, page: EditorPage | None, *, wait: bool = True) -> None:
        if page is None or not page.doc_id:
            return
        line, column = page.cursor_position()
        self.store.set_meta(self._cursor_key(page.doc_id), f"{line}:{column}", wait=wait)

    def _restore_cursor(self, page: EditorPage) -> None:
        raw = self.store.get_meta(self._cursor_key(page.doc_id))
        if not raw:
            return
        line_text, _sep, column_text = raw.partition(":")
        try:
            line = int(line_text)
            column = int(column_text) if column_text else 0
        except ValueError:
            return
        page.place_cursor_at(line, column)

    def _on_save_state(self, state: SaveState) -> None:
        GLib.idle_add(self._on_save_state_main, state)

    def _on_save_state_main(self, state: SaveState) -> bool:
        if self._closing:
            return False
        if state.status == "error":
            self._set_save_ui("error", state.message)
            toast = Adw.Toast(title=f"自动保存失败：{state.message}", timeout=0)
            self.toast_overlay.add_toast(toast)
        elif state.status == "saved":
            # 刚写入本机文件时，保留文件保存提示，不被自动保存状态覆盖
            if time.time() < self._file_save_banner_until:
                return False
            self._set_save_ui("saved", f"已自动保存 {time.strftime('%H:%M:%S', time.localtime(state.timestamp))}")
            # 内容变化会改变 updated_at，让侧栏「最近」顺序跟上（合并重建，避免每键一刷）
            self._schedule_sidebar_refresh(1200)
        return False

    # ================================================================== 状态栏

    def _on_page_stats(self, _page, page) -> None:
        if self.tabview.get_selected_page() is page.tab:
            self._update_stats(page)

    def _update_stats(self, page: EditorPage) -> None:
        chars, words = page.stats()
        self.stats_label.set_text(f"字符 {chars} · 词 {words}")

    def _update_format_button(self, page: EditorPage) -> None:
        self.format_button.set_label(page.format.upper())

    def _set_save_ui(self, status: str, message: str) -> None:
        icons = {
            "saved": "object-select-symbolic",
            "saving": "view-refresh-symbolic",
            "error": "dialog-error-symbolic",
        }
        self.save_icon.set_from_icon_name(icons.get(status, "object-select-symbolic"))
        self.save_label.set_text(message)
        self.save_icon.set_css_classes(["dim-label"] if status != "error" else ["error"])

    # ================================================================== 模式

    def _on_mode_toggled(self, button, mode: str) -> None:
        if button.get_active():
            self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        for name, button in self._mode_buttons.items():
            handler_blocked = button.handler_block_by_func(self._on_mode_toggled)
            button.set_active(name == mode)
            button.handler_unblock_by_func(self._on_mode_toggled)
        self.store.set_meta("view_mode", mode)
        page = self._current_page()
        if page is not None:
            page.set_mode(mode)
            page.view.grab_focus()
            self._save_doc_mode(page)

    def toggle_source_preview(self) -> None:
        self.set_mode(MODE_PREVIEW if self.mode != MODE_PREVIEW else MODE_SOURCE)

    # ---- 写作模式

    def _on_writing_mode(self, action, value) -> None:
        text = value.get_string()
        action.set_state(GLib.Variant.new_string(text if text in WRITING_CYCLE else "off"))
        self.set_writing_mode(text)

    def set_writing_mode(self, text: str, *, persist: bool = True) -> None:
        if text not in WRITING_CYCLE:
            text = "off"
        self._writing_mode = text
        pct = 0 if text == "off" else int(text)
        for page in self._pages.values():
            page.set_writing_width(pct)
        if self._writing_action is not None:
            self._writing_action.set_state(GLib.Variant.new_string(text))
        if persist:
            self.store.set_meta("writing_width", text)

    def cycle_writing_mode(self) -> None:
        try:
            index = WRITING_CYCLE.index(self._writing_mode)
        except ValueError:
            index = 0
        self.set_writing_mode(WRITING_CYCLE[(index + 1) % len(WRITING_CYCLE)])

    def _writing_pct(self) -> int:
        return 0 if self._writing_mode == "off" else int(self._writing_mode)

    # ---- 打字机模式

    def _on_typewriter_mode(self, _action, _value) -> None:
        self.set_typewriter(not self._typewriter())

    def _typewriter(self) -> bool:
        return self._typewriter_action.get_state().get_boolean()

    def set_typewriter(self, on: bool, *, persist: bool = True) -> None:
        """开关打字机模式：应用到所有标签页并持久化（与写作模式同一接线方式）。"""
        self._typewriter_action.set_state(GLib.Variant.new_boolean(bool(on)))
        for page in self._pages.values():
            page.set_typewriter(bool(on))
        if persist:
            # 开关切换频率极低，阻塞落盘换取重启后状态确定
            self.store.set_meta("typewriter", "1" if on else "0", wait=True)

    # ---- 段落遮罩 / 光标行位置

    def _on_paragraph_dim(self, _action, _value) -> None:
        self.set_paragraph_dim(not self._paragraph_dim())

    def _paragraph_dim(self) -> bool:
        return self._dim_action.get_state().get_boolean()

    def set_paragraph_dim(self, on: bool, *, persist: bool = True) -> None:
        """开关段落遮罩：应用到所有标签页并持久化。"""
        self._dim_action.set_state(GLib.Variant.new_boolean(bool(on)))
        for page in self._pages.values():
            page.set_paragraph_dim(bool(on))
        if persist:
            self.store.set_meta("paragraph_dim", "1" if on else "0", wait=True)

    def _on_typewriter_align(self, _action, value) -> None:
        self.set_typewriter_align(value.get_string())

    def set_typewriter_align(self, pct: str, *, persist: bool = True) -> None:
        """设置光标行在视口的目标位置（百分比字符串）。"""
        if pct not in TYPEWRITER_ALIGNS:
            pct = "33"
        self._align_action.set_state(GLib.Variant.new_string(pct))
        try:
            n = int(pct)
        except ValueError:
            n = 33
        for page in self._pages.values():
            page.set_typewriter_align(n)
        if persist:
            self.store.set_meta("typewriter_align", pct, wait=True)

    def _apply_typewriter_state(self, page: EditorPage) -> None:
        """建页时一次性应用打字机三项状态（跟随 / 位置 / 遮罩）。"""
        page.set_typewriter(self._typewriter())
        page.set_typewriter_align(int(self._align_action.get_state().get_string()))
        page.set_paragraph_dim(self._paragraph_dim())

    def _on_theme_changed(self, manager, _param) -> None:
        dark = manager.get_dark()
        for page in self._pages.values():
            page.set_scheme(dark)
        if getattr(self, "theme_button", None) is not None:
            self._update_theme_button()

    # ---- 日间 / 夜间主题

    def _apply_color_scheme(self, scheme: str, *, persist: bool = True) -> None:
        mapping = {
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
            "default": Adw.ColorScheme.DEFAULT,
        }
        key = scheme if scheme in mapping else "default"
        self._color_scheme = key
        Adw.StyleManager.get_default().set_color_scheme(mapping[key])
        if persist:
            self.store.set_meta("color_scheme", key, wait=True)
        if getattr(self, "theme_button", None) is not None:
            self._update_theme_button()

    def _update_theme_button(self) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        self.theme_button.set_icon_name(
            "display-brightness-symbolic" if dark else "weather-clear-night-symbolic"
        )
        self.theme_button.set_tooltip_text("切换到日间主题" if dark else "切换到夜间主题")

    def toggle_theme(self) -> None:
        """在日间与夜间之间切换；结果写入 meta，下次启动沿用。"""
        dark = Adw.StyleManager.get_default().get_dark()
        self._apply_color_scheme("light" if dark else "dark")

    # ================================================================== 侧边栏

    def _on_sidebar_toggled(self, button) -> None:
        self.set_sidebar_visible(
            button.get_active(), persist=not self._suppress_sidebar_persist
        )

    def set_sidebar_visible(self, visible: bool, *, persist: bool = True) -> None:
        """显示/隐藏悬浮侧栏（不改变编辑区宽度，只做滑入淡出）。"""
        self.sidebar_revealer.set_reveal_child(bool(visible))
        if visible:
            self._schedule_outline_refresh(0)
        if persist:
            self.store.set_meta("sidebar_visible", "1" if visible else "0", wait=True)

    def sidebar_visible(self) -> bool:
        return self.sidebar_revealer.get_reveal_child()

    def toggle_sidebar(self) -> None:
        self.sidebar_button.set_active(not self.sidebar_button.get_active())

    def hide_sidebar(self) -> None:
        """收起侧栏，但不改写偏好值（sidebar_visible 保持原值）。

        自动隐藏属于一次性动作；侧栏启动状态固定为收起，不读取该偏好。
        """
        if not self.sidebar_visible() and not self.sidebar_button.get_active():
            return
        self._suppress_sidebar_persist = True
        try:
            self.sidebar_button.set_active(False)
        finally:
            self._suppress_sidebar_persist = False
        self.set_sidebar_visible(False, persist=False)

    def hide_sidebar_after_pick(self) -> None:
        """侧栏内选中条目（笔记 / 文件 / 文件夹内文档）后的自动收起。"""
        if self.store.get_meta("sidebar_autohide", "1") != "1":
            return
        self.hide_sidebar()

    def show_sidebar_view(self, name: str) -> None:
        if not self.sidebar_button.get_active():
            self.sidebar_button.set_active(True)
        self.sidebar.show_view(name)

    def _schedule_sidebar_refresh(self, delay: int = 250) -> None:
        """侧栏内容变化较频繁（自动保存会改 updated_at），合并成一次重建。"""
        if getattr(self, "sidebar", None) is None:
            return
        source = getattr(self, "_sidebar_timer", None)
        if source is not None:
            GLib.source_remove(source)
        self._sidebar_timer = GLib.timeout_add(delay, self._refresh_sidebar_now)

    def _refresh_sidebar_now(self) -> bool:
        self._sidebar_timer = None
        if getattr(self, "sidebar", None) is None:
            return False
        self.sidebar.refresh()
        return False

    # ---- Markdown 大纲

    def _schedule_outline_refresh(self, delay: int = 400) -> None:
        """编辑/切换标签后合并重建大纲，避免每次按键都解析全文。"""
        if getattr(self, "sidebar", None) is None:
            return
        if self._outline_timer is not None:
            GLib.source_remove(self._outline_timer)
        self._outline_timer = GLib.timeout_add(delay, self._refresh_outline_now)

    def _refresh_outline_now(self) -> bool:
        self._outline_timer = None
        if getattr(self, "sidebar", None) is None:
            return False
        page = self._current_page()
        if page is None:
            self._outline_sig = ()
            self.sidebar.set_outline([], fmt="")
            return False
        if page.format != "md":
            if self._outline_sig != ("", page.format):
                self._outline_sig = ("", page.format)
                self.sidebar.set_outline([], fmt=page.format)
            return False
        headings = parse_headings(page.snapshot_text())
        sig = tuple((h.level, h.text, h.line) for h in headings)
        if sig == self._outline_sig:
            return False
        self._outline_sig = sig
        self.sidebar.set_outline(headings, fmt="md")
        return False

    def goto_outline_heading(self, heading) -> None:
        """大纲点击：源码/分屏 → 定位到行；纯预览 → 滚动到对应标题。"""
        page = self._current_page()
        if page is None:
            return
        if self.mode == MODE_PREVIEW and page.format == "md":
            page.preview.scroll_to_heading(heading.index)
        else:
            page.goto_line(heading.line)

    # ================================================================== 格式

    def _on_set_format(self, _action, value) -> None:
        page = self._current_page()
        if page is None:
            return
        fmt = value.get_string()
        if fmt == page.format:
            return
        page.set_format(fmt)
        page.tab.set_icon(Gio.ThemedIcon.new(FORMAT_ICON.get(fmt, "text-x-generic-symbolic")))
        self._update_format_button(page)
        self._save_page(page, wait=False)
        self._rebuild_recent_menu()
        self._schedule_sidebar_refresh()
        self._outline_sig = None
        self._schedule_outline_refresh(80)

    # ================================================================== 工具：格式化 / 简繁转换

    def _replace_page_text(self, page: EditorPage, text: str) -> None:
        """整篇替换（折叠先全部展开，保证 mark 一致；替换可撤销）。"""
        page._folding.unfold_all()
        page.buffer.begin_user_action()
        start, end = page.buffer.get_bounds()
        page.buffer.delete(start, end)
        page.buffer.insert_at_cursor(text, len(text.encode()))
        page.buffer.end_user_action()

    def _run_tool_async(self, page: EditorPage, label: str, work, on_done) -> None:
        """工作线程执行 → 主线程回调。work(text)->str 抛异常返回提示。"""
        from . import formatter  # noqa: F401  (确保导入失败尽早暴露)

        text = page.snapshot_text()
        self._set_save_ui("saving", f"{label}…")

        def worker():
            result, err = None, None
            try:
                result = work(text)
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
            def done():
                self._set_save_ui("saved", "已保存")
                if err is not None:
                    self.toast_overlay.add_toast(Adw.Toast(title=f"{label}失败：{err}", timeout=0))
                    return False
                if self._pages.get(page.doc_id) is not page:
                    return False  # 页面已关闭
                on_done(page, result)
                return False
            GLib.idle_add(done)

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _selection_bounds(self, page: EditorPage):
        """当前选区 (start_iter, end_iter)；无选区返回 None。

        GTK4 的 get_selection_bounds：无选区返回空元组，有选区返回 (start, end)
        二元组（布尔返回值不进 PyGObject 结果）。
        """
        sel = page.buffer.get_selection_bounds()
        if len(sel) == 2:
            start, end = sel
        else:
            return None
        if not start.equal(end):
            return start, end
        return None

    def _replace_region(self, page: EditorPage, marks: tuple, text: str) -> None:
        """按标记对定点替换（先展开折叠保证 mark 一致由调用方负责）。

        单一 user action（一步撤销），完成后重新选中替换结果，然后移除标记。
        """
        buf = page.buffer
        m_start, m_end = marks
        buf.begin_user_action()
        s = buf.get_iter_at_mark(m_start)
        e = buf.get_iter_at_mark(m_end)
        if not s.equal(e):
            buf.delete(s, e)
        buf.insert_at_cursor(text, len(text.encode()))
        buf.end_user_action()
        s2 = buf.get_iter_at_mark(m_start)
        e2 = s2.copy()
        e2.forward_chars(len(text))
        buf.select_range(s2, e2)
        buf.delete_mark(m_start)
        buf.delete_mark(m_end)

    def _run_tool_async_region(self, page: EditorPage, label: str, work, on_done) -> None:
        """选区感知的异步工具通道。

        有选区：只把选中文本交给 work()，完成后用左右重力标记对定点替换、
        重新选中结果（其余正文零扰动，撤销只回退这一段）；
        无选区：整篇走 _run_tool_async（on_done 收到 region=None）。
        on_done(page, result, region)，region 非 None 时为 (m_start, m_end)。
        """
        sel = self._selection_bounds(page)
        if sel is None:
            self._run_tool_async(page, label, work, lambda p, r: on_done(p, r, None))
            return

        start, end = sel
        text = start.get_slice(end)
        buf = page.buffer
        # 左重力起标 + 右重力止标：期间缓冲区如有任何插入，区间随文本移动
        m_start = buf.create_mark(None, start, True)
        m_end = buf.create_mark(None, end, False)
        self._set_save_ui("saving", f"{label}…")

        def worker():
            result, err = None, None
            try:
                result = work(text)
            except Exception as exc:  # noqa: BLE001
                err = str(exc)

            def done():
                if self._pages.get(page.doc_id) is not page:
                    return False  # 页面已关闭，缓冲区（含标记）随之销毁
                self._set_save_ui("saved", "已保存")
                if err is not None:
                    buf.delete_mark(m_start)
                    buf.delete_mark(m_end)
                    self.toast_overlay.add_toast(Adw.Toast(title=f"{label}失败：{err}", timeout=0))
                    return False
                page._folding.unfold_all()  # 折叠是物理移除，不展开替换会错位
                on_done(page, result, (m_start, m_end))
                return False

            GLib.idle_add(done)

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def fold_current_block(self) -> None:
        """菜单入口：折叠光标所在区块（不依赖 gutter 点击）。"""
        page = self._current_page()
        if page is None:
            return
        line = page.buffer.get_iter_at_mark(page.buffer.get_insert()).get_line()
        folded = page._folding.toggle_fold(line)
        if not folded:
            self.toast_overlay.add_toast(Adw.Toast(title="光标处没有可折叠的区块", timeout=3))

    def unfold_all_blocks(self) -> None:
        page = self._current_page()
        if page is not None:
            page._folding.unfold_all()

    # ================================================================== 撤销 / 重做与列编辑

    def undo_current(self, *, redo: bool = False) -> None:
        page = self._current_page()
        if page is None:
            return
        if redo:
            if page.buffer.get_property("can-redo"):
                page.buffer.redo()
        elif page.buffer.get_property("can-undo"):
            page.buffer.undo()
        self._sync_undo_buttons(page)
        page.view.grab_focus()

    def _on_undo_state_changed(self, _buffer, _pspec, page) -> None:
        if page is self._current_page():
            self._sync_undo_buttons(page)

    def _sync_undo_buttons(self, page: EditorPage | None = None) -> None:
        page = page if page is not None else self._current_page()
        if page is None:
            self.undo_button.set_sensitive(False)
            self.redo_button.set_sensitive(False)
            return
        self.undo_button.set_sensitive(bool(page.buffer.get_property("can-undo")))
        self.redo_button.set_sensitive(bool(page.buffer.get_property("can-redo")))

    def run_line_op(self, op: str, arg: str = "") -> None:
        """列编辑入口：作用于当前选区（无选区时前缀/后缀作用于光标行）。"""
        page = self._current_page()
        if page is None:
            return
        # apply_line_op 改动缓冲区后走 edited 信号 → 自动保存/大纲刷新，无需在此重复
        if page.apply_line_op(op, arg):
            return
        hint = {
            "sort": "排序需要先选中两行以上",
            "dedup": "去重需要先选中两行以上",
        }.get(op)
        self.toast_overlay.add_toast(Adw.Toast(title=hint or "内容没有变化", timeout=3))

    def prompt_column_op(self) -> Adw.AlertDialog | None:
        """按列提取对话框：分隔符 / 字符宽度两种依据，带实时预览。

        未命中的行由 columnedit 原样保留，对话框里预先告知会保留多少行，
        避免用户以为内容被吞掉。返回对话框对象便于测试取到预览内容。
        """
        page = self._current_page()
        if page is None:
            return None
        span = page.selection_span()
        line_count = span[1] - span[0] + 1
        source_text = page.block_text(span)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_size_request(480, -1)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        btn_sep = Gtk.CheckButton(label="按分隔符")
        btn_width = Gtk.CheckButton(label="按字符宽度")
        btn_width.set_group(btn_sep)
        btn_sep.set_active(True)
        mode_row.append(btn_sep)
        mode_row.append(btn_width)
        box.append(mode_row)

        sep_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sep_entry = Gtk.Entry(text="：", hexpand=True, placeholder_text="如 ： 或 ：|:")
        sep_entry.set_activates_default(True)
        idx_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        idx_spin.set_value(1)
        sep_row.append(Gtk.Label(label="分隔符"))
        sep_row.append(sep_entry)
        sep_row.append(Gtk.Label(label="保留第"))
        sep_row.append(idx_spin)
        sep_row.append(Gtk.Label(label="段"))
        box.append(sep_row)

        width_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        width_spin = Gtk.SpinButton.new_with_range(1, 999, 1)
        width_spin.set_value(4)
        width_row.append(Gtk.Label(label="保留前"))
        width_row.append(width_spin)
        width_row.append(Gtk.Label(label="个字符（其余删掉）"))
        box.append(width_row)

        preview = Gtk.Label(xalign=0.0, wrap=True, selectable=False)
        preview.add_css_class("monospace")
        preview.add_css_class("dim-label")
        box.append(preview)

        def current_mode() -> str:
            return "sep" if btn_sep.get_active() else "width"

        def current_args() -> dict:
            return {
                "sep": sep_entry.get_text(),
                "index": int(idx_spin.get_value()),
                "width": int(width_spin.get_value()),
            }

        def refresh(*_args) -> None:
            mode = current_mode()
            sep_row.set_visible(mode == "sep")
            width_row.set_visible(mode == "width")
            new, miss = columnedit.take_column(source_text, mode, **current_args())
            src = source_text.split("\n")
            dst = new.split("\n")
            shown = []
            for i in range(min(3, len(src))):
                before = src[i] if len(src[i]) <= 26 else src[i][:26] + "…"
                after = dst[i] if len(dst[i]) <= 26 else dst[i][:26] + "…"
                shown.append(f"{before}\n  → {after}")
            head = f"预览（共 {line_count} 行）："
            tail = f"\n共 {miss} 行未命中，将原样保留" if miss else ""
            preview.set_text(head + "\n" + "\n".join(shown) + tail)

        def on_response(_dialog, response: str) -> None:
            if response != "ok":
                return
            changed, miss = page.apply_column_op(current_mode(), **current_args())
            if not changed:
                self.toast_overlay.add_toast(Adw.Toast(title="内容没有变化", timeout=3))
                return
            title = "已按列提取"
            if miss:
                title += f"（{miss} 行未命中，已原样保留）"
            self.toast_overlay.add_toast(Adw.Toast(title=title, timeout=3))

        dialog = Adw.AlertDialog(
            heading="按列提取",
            body=f"对选区覆盖的 {line_count} 行只保留其中一列，其余内容删除",
        )
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "替换选区")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", on_response)
        sep_entry.connect("changed", refresh)
        idx_spin.connect("value-changed", refresh)
        width_spin.connect("value-changed", refresh)
        btn_sep.connect("toggled", refresh)
        refresh()
        dialog.present(self)
        return dialog

    def prompt_line_arg(self, kind: str) -> None:
        """前缀 / 后缀输入对话框：确定后对选区各行施加。"""
        label = "前缀" if kind == "prefix" else "后缀"
        entry = Gtk.Entry(placeholder_text=f"要加在每行的{label}，留空则不修改", activates_default=True)
        dialog = Adw.AlertDialog(
            heading=f"添加{label}",
            body=f"对选中区域（无选区时为光标所在行）的每一行{'开头' if kind == 'prefix' else '末尾'}追加内容",
        )
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "确定")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_line_arg_response, kind, entry)
        dialog.present(self)

    def _on_line_arg_response(self, dialog, response, kind: str, entry: Gtk.Entry) -> None:
        if response != "ok":
            return
        self.run_line_op(kind, entry.get_text())

    def format_current_doc(self) -> None:
        page = self._current_page()
        if page is None:
            return
        from . import formatter

        sel = self._selection_bounds(page)
        selected_text = sel[0].get_slice(sel[1]) if sel is not None else None

        kind = None
        linked = self.store.source_path_of(page.doc_id)
        if linked:
            kind = formatter.format_kind_for_ext(Path(linked).suffix)
        if selected_text is not None:
            # 只排版选中代码块：优先按选区内容嗅探语言（块可以是与文档不同的语言），
            # 嗅探不出再回退关联扩展名
            sniffed = formatter.sniff_kind(selected_text)
            if sniffed:
                kind = sniffed
        elif kind is None:
            kind = formatter.sniff_kind(page.snapshot_text())
        if kind is None:
            self.toast_overlay.add_toast(Adw.Toast(
                title="无法识别可格式化的语言（支持 JSON / XML / HTML / Python / Bash，"
                      "需关联本机文件或内容可自动识别）", timeout=5))
            return

        def work(text):
            return formatter.format_text(text, kind)

        def done(p, result, region):
            if region is None:
                self._replace_page_text(p, result)
            else:
                self._replace_region(p, region, result)
            self._save_page(p)
            self.toast_overlay.add_toast(Adw.Toast(title=f"已按 {kind.upper()} 排版", timeout=4))

        self._run_tool_async_region(page, f"正在排版（{kind.upper()}）", work, done)

    def convert_current_doc(self, mode: str) -> None:
        page = self._current_page()
        if page is None:
            return
        import shutil

        opencc = shutil.which("opencc")
        if not opencc:
            self.toast_overlay.add_toast(Adw.Toast(
                title="未检测到 opencc，无法转换；请安装：sudo apt install opencc", timeout=0))
            return
        target = "繁体" if mode == "s2t" else "简体"

        def work(text):
            import subprocess

            proc = subprocess.run(
                [opencc, "-c", mode], input=text.encode(), capture_output=True, timeout=60
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="replace").strip()[:120])
            return proc.stdout.decode()

        def done(p, result, region):
            if region is None:
                self._replace_page_text(p, result)
            else:
                self._replace_region(p, region, result)
            self._save_page(p)
            self.toast_overlay.add_toast(Adw.Toast(title=f"已转换为{target}", timeout=4))

        self._run_tool_async_region(page, f"正在转换为{target}", work, done)

    # ================================================================== 本机文件：打开 / 保存 / 拖放

    def _build_open_filters(self) -> Gio.ListStore:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        md_filter = Gtk.FileFilter(name="Markdown")
        for pattern in ("*.md", "*.markdown", "*.mkd"):
            md_filter.add_pattern(pattern)
        md_filter.add_mime_type("text/markdown")
        txt_filter = Gtk.FileFilter(name="文本文件")
        txt_filter.add_pattern("*.txt")
        txt_filter.add_mime_type("text/plain")
        all_filter = Gtk.FileFilter(name="所有文件")
        all_filter.add_pattern("*")
        filters.append(md_filter)
        filters.append(txt_filter)
        filters.append(all_filter)
        return filters

    def open_file(self) -> None:
        """Ctrl+O：文件选择器打开一个或多个本机文件，各占一个新标签。"""
        dialog = Gtk.FileDialog(title="打开文件", modal=True)
        dialog.set_filters(self._build_open_filters())
        dialog.open_multiple(self, None, self._on_files_chosen, None)

    def _on_files_chosen(self, dialog, result, _data) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        if files is None:
            return
        paths = [f.get_path() for f in files if f.get_path()]
        if paths:
            self.handle_dropped_files(paths)

    def open_file_paths(self, paths_list: list[str]) -> None:
        """把本机文本文件作为新标签打开（同一路径已打开则切换到既有标签）。"""
        opened = 0
        last_opened: Path | None = None
        for raw in paths_list:
            path = Path(raw).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            # 已作为标签打开过 → 直接切换
            existing = self._find_page_by_source(str(resolved))
            if existing is not None:
                self.tabview.set_selected_page(existing.tab)
                last_opened = resolved
                continue
            try:
                text = _read_text_file(resolved)
            except (OSError, ValueError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(title=f"无法打开 {resolved.name}：{exc}", timeout=5)
                )
                continue
            fmt = "md" if resolved.suffix.lower() in MD_EXTS else (
                "html" if resolved.suffix.lower() in HTML_EXTS else "txt"
            )
            title = resolved.stem or resolved.name
            try:
                doc = self.store.create_document(fmt, title=title)
            except RuntimeError as exc:
                self.toast_overlay.add_toast(Adw.Toast(title=f"创建文档失败：{exc}", timeout=5))
                continue
            saved = replace(doc, content=text, revision=doc.revision + 1)
            self.store.submit_save(saved, wait=True)
            self.store.set_source_path(doc.id, str(resolved))
            page = self.add_tab(saved, activate=True)
            page.revision = saved.revision
            page.set_language_for_path(str(resolved))
            page.set_base_uri(str(resolved))
            self._update_source_tooltip(page)
            last_opened = resolved
            opened += 1
        if opened:
            self._rebuild_recent_menu()
        if last_opened is not None and getattr(self, "sidebar", None) is not None:
            # 手动打开/拖放打开：磁盘树自动定位到该文件所在目录
            self.sidebar.reveal_local_path(last_opened)

    def _find_page_by_source(self, source: str) -> EditorPage | None:
        for page in self._pages.values():
            linked = self.store.source_path_of(page.doc_id)
            if linked == source:
                return page
        return None

    # ================================================================== 目录搜索 / 批量替换

    def open_folder_search(self) -> None:
        """Ctrl+Shift+F：在用户指定的真实目录中搜索。"""
        from .fssearch_ui import FolderSearchDialog

        # 必须持有引用：Adw.Dialog 在 Python 侧没有强引用时可能被 GC 掉
        self._folder_dialog = FolderSearchDialog(self)
        self._folder_dialog.present(self)

    def open_folder_replace(self) -> None:
        """Ctrl+Shift+H：在用户指定的真实目录中批量替换。"""
        from .fssearch_ui import FolderReplaceDialog

        self._folder_dialog = FolderReplaceDialog(self)
        self._folder_dialog.present(self)

    def open_folder_replace_for(
        self,
        *,
        folder: Path | str | None = None,
        find_text: str = "",
        options: dict | None = None,
        only_file: Path | str | None = None,
    ):
        """从「在目录中搜索」的结果行进入替换：带目录、查找内容与选项。

        `only_file` 给出时，预览完成后只勾选该文件（其余文件列出来但不勾选），
        避免「我只是想改这一个文件」变成整目录批量改写。
        """
        from .fssearch_ui import FolderReplaceDialog

        dialog = FolderReplaceDialog(
            self, find_text=find_text, folder=folder, options=options, only_file=only_file
        )
        self._folder_dialog = dialog
        dialog.present(self)
        return dialog

    def open_path_at_line(
        self, path: Path | str, line: int, column: int = 0, length: int = 0
    ) -> None:
        """打开文件（已打开则切换）并把光标定位到指定行，可选中命中文本。"""
        target = Path(path)
        self.open_file_paths([str(target)])
        try:
            resolved = str(target.resolve())
        except OSError:
            resolved = str(target)
        page = self._find_page_by_source(resolved)
        if page is None:
            return
        self.tabview.set_selected_page(page.tab)
        page.goto_line(line, column, length)

    def reload_source_tabs(
        self, paths_changed: list[Path], previous: dict[str, str] | None = None
    ) -> tuple[int, int]:
        """磁盘文件被外部改写后，刷新已打开且内容未变的标签。

        `previous` 是「替换前该文件的完整内容」。只有当前编辑内容与它完全一致时才刷新，
        否则说明用户在应用内改过（自动保存只写库、不写源文件），刷新会丢掉这些修改。
        返回 (已刷新数, 因内容已变化而跳过的数量)。
        """
        changed = {str(Path(p)) for p in paths_changed}
        previous = previous or {}
        reloaded = 0
        skipped = 0
        for page in list(self._pages.values()):
            src = self.store.source_path_of(page.doc_id)
            if not src or src not in changed:
                continue
            before = previous.get(src)
            if before is None or page.snapshot_text() != before:
                skipped += 1
                continue
            try:
                text = _read_text_file(Path(src))
            except (OSError, ValueError):
                continue
            self._replace_page_text(page, text)
            page.dirty = False
            page.revision += 1
            self._save_page(page, wait=False)
            reloaded += 1
        if skipped:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=f"{skipped} 个标签在应用内有未保存的修改，未自动刷新，请手动核对",
                    timeout=8,
                )
            )
        return reloaded, skipped

    def save_active_to_file(self) -> None:
        """Ctrl+S：已关联文件 → 原子写回该文件；未关联 → 弹出另存为。"""
        page = self._current_page()
        if page is None:
            return
        linked = self.store.source_path_of(page.doc_id)
        if linked:
            self._write_doc_to_file(page, Path(linked))
        else:
            self.save_active_as()

    def save_active_as(self) -> None:
        page = self._current_page()
        if page is None:
            return
        ext = {"md": "md", "html": "html"}.get(page.format, "txt")
        dialog = Gtk.FileDialog(
            title="保存到本机文件", modal=True, initial_name=f"{page.title}.{ext}"
        )
        dialog.save(self, None, self._on_save_as_target, (page,))

    def _on_save_as_target(self, dialog, result, data) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            self._write_doc_to_file(data[0], Path(path), link=True)

    def _write_doc_to_file(self, page: EditorPage, path: Path, *, link: bool = False) -> None:
        """内容先落内部库（自动保存机制不受影响），再原子写到本机文件。"""
        self._save_page(page, wait=True)
        from .store import _atomic_write

        try:
            _atomic_write(path, page.snapshot_text().encode("utf-8"), mode=0o644)
        except OSError as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=f"保存失败：{exc}", timeout=0)
            )
            self._set_save_ui("error", f"写入 {path.name} 失败")
            return
        if link:
            self.store.set_source_path(page.doc_id, str(path.resolve()))
            page.set_language_for_path(str(path))
            page.set_base_uri(str(path))
            # 首次关联文件 / 另存到新路径：标签名同步为文件名，命名规则与「打开文件」一致（stem 优先）
            new_title = path.stem or path.name
            if new_title and new_title != page.title:
                page.title = new_title
                page.tab.set_title(new_title)
                self.store.rename(page.doc_id, new_title)
                self._rebuild_recent_menu()
                self._schedule_sidebar_refresh()
            self._update_source_tooltip(page)
            if getattr(self, "sidebar", None) is not None:
                self.sidebar.reveal_local_path(path)
        basename = path.name
        self._file_save_banner_until = time.time() + 3.0
        self._set_save_ui("saved", f"已保存到 {basename}")
        self.save_label.set_tooltip_text(str(path))
        self.toast_overlay.add_toast(Adw.Toast(title=f"已保存到 {path}", timeout=5))

    def _update_source_tooltip(self, page: EditorPage) -> None:
        linked = self.store.source_path_of(page.doc_id)
        page.tab.set_tooltip(f"{page.title}\n{linked}" if linked else page.title)

    def handle_dropped_files(self, paths_list: list[str]) -> None:
        """拖放入口：图片插入引用；文本/Markdown 打开为新标签；二进制提示。"""
        images: list[str] = []
        docs: list[str] = []
        for raw in paths_list:
            suffix = Path(raw).suffix.lower()
            if suffix in IMAGE_EXTS:
                images.append(raw)
            elif suffix in MD_EXTS or suffix in TEXT_EXTS:
                docs.append(raw)
            else:
                # 无扩展名/未知扩展名：探测是否为文本
                try:
                    head = Path(raw).read_bytes()[:4096]
                except OSError as exc:
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=f"无法读取 {Path(raw).name}：{exc}", timeout=5)
                    )
                    continue
                if b"\x00" not in head:
                    docs.append(raw)
                else:
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=f"不支持打开二进制文件 {Path(raw).name}", timeout=5)
                    )
        if images:
            self.import_images(images)
        if docs:
            self.open_file_paths(docs)

    # ================================================================== 图片

    def import_images(self, paths_list: list) -> None:
        """选择器 / 拖放入口。

        文档已关联本机文件时，直接写相对路径引用（如 `![](../024907.png)`），
        不复制图片——文件留在原位，便于与同目录的 Markdown 一起移动或版本管理。
        未关联文件（还没保存到磁盘）时没有可用的基准目录，退回到应用资源目录导入。
        """
        page = self._current_page()
        if page is None:
            return
        linked = self.store.source_path_of(page.doc_id)
        imported: list[tuple[str, str]] = []
        for path in paths_list:
            rel = ""
            name = ""
            if linked:
                ref = assets.relative_image_ref(linked, path)
                if ref is not None:
                    rel, name = ref
            if not rel:
                try:
                    rel, name = assets.import_image(page.doc_id, path)
                except (OSError, ValueError) as exc:
                    self.toast_overlay.add_toast(Adw.Toast(title=f"导入图片失败：{exc}"))
                    continue
            imported.append((rel, name))
        if not imported:
            return
        page.buffer.begin_user_action()
        for rel, _name in imported:
            if page.format == "md":
                text = f"![]({rel})\n"
            else:
                text = f"{rel}\n"
            page.buffer.insert_at_cursor(text)
        page.buffer.end_user_action()
        self._save_page(page)

    def choose_image(self) -> None:
        dialog = Gtk.FileDialog(title="插入图片")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        image_filter = Gtk.FileFilter(name="图片文件")
        image_filter.add_mime_type("image/*")
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_image_chosen, None)

    def _on_image_chosen(self, dialog, result, _data) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            self.import_images([path])

    # ================================================================== PDF

    def export_pdf(self) -> None:
        page = self._current_page()
        if page is None:
            return
        if page.format != "md":
            self.toast_overlay.add_toast(Adw.Toast(title="仅 Markdown 文档支持 PDF 导出"))
            return
        from . import pdfexport

        suggested = page.title or "未命名"
        dialog = Gtk.FileDialog(title="导出 PDF", initial_name=f"{suggested}.pdf")
        dialog.save(self, None, self._on_pdf_target, (page,))

    def _on_pdf_target(self, dialog, result, data) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        page = data[0]
        out_path = file.get_path()
        self._set_save_ui("saving", f"正在导出 PDF…")
        from . import pdfexport

        pdfexport.export_pdf(
            page.snapshot_text(),
            out_path,
            on_done=lambda p: GLib.idle_add(self._pdf_done, p),
            on_error=lambda msg: GLib.idle_add(self._pdf_error, msg),
            parent=self,
            on_fallback=lambda reason: GLib.idle_add(
                self._pdf_fallback_notice, reason),
        )

    def _pdf_fallback_notice(self, reason: str) -> bool:
        self.toast_overlay.add_toast(Adw.Toast(title=reason, timeout=6))
        return False

    def _pdf_done(self, path: str) -> bool:
        self._set_save_ui("saved", "已保存")
        self.toast_overlay.add_toast(Adw.Toast(title=f"已导出：{path}", timeout=5))
        return False

    def _pdf_error(self, message: str) -> bool:
        self._set_save_ui("saved", "已保存")
        self.toast_overlay.add_toast(Adw.Toast(title=f"PDF 导出失败：{message}", timeout=0))
        return False

    # ================================================================== 已关闭/删除

    def _on_reopen_doc(self, _action, value) -> None:
        self.open_document(value.get_string())

    def on_captured(self, doc_id: str, doc_title: str, created: bool) -> None:
        """外部捕获（app.capture）落库后的窗口侧反馈。

        窗口开着时：toast + 刷新侧栏；目标文档恰在本窗口打开且无未保存修改，
        则就地重载把追加内容显示出来（不切换标签）；有未保存修改则只提示核对，
        避免覆盖用户输入。
        """
        page = self._pages.get(doc_id)
        if page is not None:
            doc = self.store.get(doc_id)
            if doc is None:
                pass
            elif page.dirty:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=f"「{doc_title}」正在编辑：外部追加已入库，请核对",
                        timeout=6,
                    )
                )
            else:
                page.load_document(doc.id, doc.title, doc.format, doc.content, doc.revision)
                if page.tab is not None:
                    page.tab.set_title(doc.title or "未命名")
                    page.tab.set_tooltip(doc.title or "未命名")
        verb = "新建" if created else "已追加到"
        self.toast_overlay.add_toast(
            Adw.Toast(title=f"{verb}笔记「{doc_title}」", timeout=4)
        )
        self._schedule_sidebar_refresh()

    def open_document(self, doc_id: str) -> EditorPage | None:
        """打开文档：已在本窗口打开则切换标签；已关闭则从库里重新开一个标签。"""
        for page in self._pages.values():
            if page.doc_id == doc_id:
                if page.tab is not None:
                    self.tabview.set_selected_page(page.tab)
                return page
        doc = self.store.get(doc_id)
        if doc is None:
            self.toast_overlay.add_toast(
                Adw.Toast(title="该笔记已不存在（可能被删除）", timeout=4)
            )
            return None
        self.store.set_state(doc_id, "open")
        index = min(self.tabview.get_n_pages(), doc.sort_index)
        page = EditorPage()
        page.load_document(doc.id, doc.title, doc.format, doc.content, doc.revision)
        self._configure_page_for_source(page)
        page.set_mode(self._doc_mode_of(doc.id), initial=True)
        page.set_scheme(Adw.StyleManager.get_default().get_dark())
        page.set_writing_width(self._writing_pct())
        self._apply_typewriter_state(page)
        self._restore_cursor(page)
        page.connect("edited", self._on_page_edited, page)
        page.connect("stats-changed", self._on_page_stats, page)
        page.connect("request-toast", self._on_page_request_toast, page)
        page.buffer.connect("notify::can-undo", self._on_undo_state_changed, page)
        page.buffer.connect("notify::can-redo", self._on_undo_state_changed, page)
        self._pages[doc.id] = page
        tab = self.tabview.insert(page, index)
        tab.set_title(doc.title or "未命名")
        tab.set_tooltip(doc.title or "未命名")
        tab.set_icon(Gio.ThemedIcon.new(FORMAT_ICON.get(doc.format, "text-x-generic-symbolic")))
        page.tab = tab
        self.tabview.set_selected_page(tab)
        self._persist_order()
        self._schedule_sidebar_refresh()
        return page

    def rename_document_by_id(self, doc_id: str) -> None:
        doc = self.store.get(doc_id)
        if doc is None:
            return
        entry = Gtk.Entry(text=doc.title, activates_default=True)
        dialog = Adw.AlertDialog(heading="重命名", body="为笔记设置一个名称")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", "确定")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect("response", self._on_rename_by_id, doc_id, entry)
        dialog.present(self)

    def _on_rename_by_id(self, _dialog, response, doc_id, entry) -> None:
        if response != "ok":
            return
        title = entry.get_text().strip() or "未命名"
        self.store.rename(doc_id, title)
        page = self._pages.get(doc_id)
        if page is not None:
            page.title = title
            if page.tab is not None:
                page.tab.set_title(title)
            self._save_page(page, wait=False)
        self._schedule_sidebar_refresh()

    def delete_document_by_id(self, doc_id: str) -> None:
        doc = self.store.get(doc_id)
        if doc is None:
            return
        dialog = Adw.AlertDialog(
            heading="永久删除？",
            body=f"将永久删除「{doc.title}」及其内容与图片资源。此操作不可撤销。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "永久删除")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_by_id, doc_id)
        dialog.present(self)

    def _on_delete_by_id(self, _dialog, response, doc_id) -> None:
        if response != "delete":
            return
        self._delete_document_now(doc_id)

    def _delete_document_now(self, doc_id: str) -> None:
        page = self._pages.pop(doc_id, None)
        self._cancel_timer(doc_id)
        assets.remove_assets(doc_id)
        self.store.delete_document(doc_id)
        if page is not None and page.tab is not None:
            self.tabview.close_page(page.tab)
        self._rebuild_recent_menu()
        self._schedule_sidebar_refresh()

    def delete_current_document(self) -> None:
        page = self._current_page()
        if page is None:
            return
        dialog = Adw.AlertDialog(
            heading="永久删除？",
            body=f"将永久删除「{page.title}」及其内容与图片资源。此操作不可撤销。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "永久删除")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_confirmed, page)
        dialog.present(self)

    def _on_delete_confirmed(self, dialog, response, page) -> None:
        if response != "delete":
            return
        self._delete_document_now(page.doc_id)

    # ================================================================== 云同步设置与备份导入

    def show_cloud_settings(self) -> None:
        """WebDAV / 自动备份 / 同步设置（Adw.PreferencesWindow，即改即存）。"""
        win = Adw.PreferencesWindow(transient_for=self, modal=True)
        win.set_title("云同步设置")
        win.set_default_size(620, 520)
        self._cloud_dialog = win  # 防 GC

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="WebDAV 服务器",
            description="与 Android 端「云备份」可共用同一地址；同步按设备目录隔离，互不覆盖。",
        )
        url_row = Adw.EntryRow(title="服务器地址（目录级）")
        url_row.set_text(self.cloud.config_url())
        user_row = Adw.EntryRow(title="用户名（地址含 user@ 时可留空）")
        user_row.set_text(self.store.get_meta("webdav_user", "") or "")
        pass_row = Adw.PasswordEntryRow(title="密码")
        pass_row.set_text(self.cloud.config_password())
        group.add(url_row)
        group.add(user_row)
        group.add(pass_row)
        page.add(group)

        toggles = Adw.PreferencesGroup(title="自动任务")
        backup_switch = Adw.SwitchRow(
            title="自动备份",
            subtitle="每 30 分钟与关闭时上传整包快照 gscratchpad-cloud-设备ID.zip（内容无变化时跳过）",
        )
        backup_switch.set_active(CloudManager.autobackup_enabled(self.store))
        sync_switch = Adw.SwitchRow(
            title="自动同步",
            subtitle="每 5 分钟、启动后与内容变更防抖后双向同步；冲突败者保全到 recovery/",
        )
        sync_switch.set_active(CloudManager.autosync_enabled(self.store))
        toggles.add(backup_switch)
        toggles.add(sync_switch)
        page.add(toggles)

        status_group = Adw.PreferencesGroup(title="手动操作与状态")
        sync_now_row = Adw.ActionRow(title="立即同步")
        sync_now_row.add_suffix(self._cloud_button("同步", lambda: self.cloud.sync_async()))
        backup_now_row = Adw.ActionRow(title="立即备份")
        backup_now_row.add_suffix(self._cloud_button("备份", lambda: self.cloud.backup_async()))
        import_row = Adw.ActionRow(title="导入备份 zip（合并导入，不覆盖本地较新内容）")
        import_row.add_suffix(self._cloud_button("选择…", self.show_cloud_import))
        restore_row = Adw.ActionRow(title="从云端恢复", subtitle="列出远端各设备备份 zip 后选择下载")
        restore_row.add_suffix(self._cloud_button("选择…", self.show_cloud_restore))
        last_sync = self.store.get_meta("cloud_sync_at", "")
        last_backup = self.store.get_meta("cloud_backup_at", "")
        status_row = Adw.ActionRow(
            title="上次执行",
            subtitle=(
                f"同步 {_cloud_time(last_sync)} · 备份 {_cloud_time(last_backup)}"
                if (last_sync or last_backup)
                else "尚未执行"
            ),
        )
        for row in (sync_now_row, backup_now_row, import_row, restore_row, status_row):
            status_group.add(row)
        page.add(status_group)
        win.add(page)

        def apply_url_user(*_a) -> None:
            try:
                self.cloud.save_config(
                    url_row.get_text(),
                    user_row.get_text(),
                    "",  # 密码单独在关闭时保存
                    remember_in_meta=False,
                )
            except Exception as exc:  # noqa: BLE001
                self.toast_overlay.add_toast(Adw.Toast(title=f"地址无效：{exc}", timeout=4))

        url_row.connect("changed", self._cloud_row_debounced(apply_url_user))
        user_row.connect("changed", self._cloud_row_debounced(apply_url_user))
        backup_switch.connect(
            "notify::active",
            lambda *_: self.cloud.set_enabled(autobackup=backup_switch.get_active()),
        )
        sync_switch.connect(
            "notify::active",
            lambda *_: self.cloud.set_enabled(autosync=sync_switch.get_active()),
        )

        def on_close(_w) -> bool:
            password = pass_row.get_text()
            self.cloud.save_config(
                url_row.get_text(),
                user_row.get_text(),
                password,
                remember_in_meta=True,
            )
            return False

        win.connect("close-request", on_close)
        win.present()
        self._cloud_dialog_built = True  # 测试断言：对话框构建完整走完

    @staticmethod
    def _cloud_row_debounced(callback, delay_ms: int = 600):
        state = {"id": None}

        def inner(*_a) -> None:
            if state["id"] is not None:
                GLib.source_remove(state["id"])
            state["id"] = GLib.timeout_add(delay_ms, lambda: (callback(), False)[1])

        return inner

    @staticmethod
    def _cloud_button(label: str, handler) -> Gtk.Button:
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["flat"])
        button.connect("clicked", lambda *_: handler())
        return button

    def show_cloud_import(self) -> None:
        """选择备份 zip → 后台合并导入（不覆盖本地较新内容）。"""
        dialog = Gtk.FileDialog(title="选择备份 zip")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("备份包 (*.zip)")
        file_filter.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_cloud_import_chosen, None)

    def _on_cloud_import_chosen(self, dialog, result, _data) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None or not file.get_path():
            return
        self._import_backup_zip(Path(file.get_path()))

    def show_cloud_restore(self) -> None:
        """列远端备份 zip → 选择后下载并合并导入（新格式按设备区分 + 旧名兼容）。"""
        import threading as _threading

        def worker() -> None:
            try:
                backups = self.cloud.list_remote_backups()
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_cloud_status, f"列云端备份失败：{exc}")
                return
            GLib.idle_add(self._show_cloud_restore_dialog, backups)

        _threading.Thread(target=worker, name="gsp-cloud-list", daemon=True).start()

    def _show_cloud_restore_dialog(self, backups) -> None:
        if not backups:
            self._on_cloud_status("云端没有可恢复的备份 zip")
            return
        dialog = Gtk.Dialog(title="从云端恢复", transient_for=self, modal=True)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("下载并恢复", Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.append(
            Gtk.Label(label="选择远端备份 zip（合并导入，不覆盖本地较新内容）")
        )
        labels = [
            f"{item.name}  ·  {item.size // 1024 if item.size >= 0 else '?'} KB  ·  {item.modified}"
            for item in backups
        ]
        dropdown = Gtk.DropDown(model=Gtk.StringList.new(labels))
        content.append(dropdown)
        dialog.show()

        def on_response(_dlg, response) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                index = dropdown.get_selected()
                if 0 <= index < len(backups):
                    self._download_and_import(backups[index].name)
            dialog.destroy()

        dialog.connect("response", on_response)

    def _download_and_import(self, name: str) -> None:
        import os
        import tempfile
        import threading as _threading

        fd, raw = tempfile.mkstemp(prefix="gs-cloud-restore-", suffix=".zip")
        os.close(fd)
        target = Path(raw)

        def worker() -> None:
            try:
                size = self.cloud.download_backup(name, target)
                GLib.idle_add(self._on_cloud_status, f"已下载 {name}（{size} B），开始导入")
                self._import_backup_zip(target, cleanup=True)
            except Exception as exc:  # noqa: BLE001
                target.unlink(missing_ok=True)
                GLib.idle_add(self._on_cloud_status, f"下载云端备份失败：{exc}")

        _threading.Thread(target=worker, name="gsp-cloud-download", daemon=True).start()

    def _import_backup_zip(self, zip_path: Path, cleanup: bool = False) -> None:
        assets_dir = paths.data_root() / "assets"

        def worker() -> None:
            try:
                report, items = backupzip.import_backup_zip(zip_path, assets_dir=assets_dir)
                if report.errors:
                    self._on_cloud_status(f"导入失败：{report.errors[0]}")
                    return
                local_revs = self.store.local_revisions()
                applied = skipped = metas = 0
                folders: list[tuple[str, float]] = []
                for item in items:
                    if "meta_key" in item:
                        self.store.set_meta(item["meta_key"], item["meta_value"])
                        metas += 1
                        continue
                    local_rev = local_revs.get(item["id"])
                    if local_rev is not None and local_rev >= int(item["revision"]):
                        skipped += 1
                        continue
                    self.store.apply_remote(item)
                    if item.get("folder"):
                        folders.append((item["folder"], float(item.get("created_at", 0.0))))
                    applied += 1
                self.store.merge_folders(folders)
                self._on_cloud_status(
                    f"导入完成：应用 {applied}，冲突跳过 {skipped}，"
                    f"资源 {report.assets_imported}，meta {metas}"
                )
            except Exception as exc:  # noqa: BLE001
                self._on_cloud_status(f"导入失败：{exc}")
            finally:
                if cleanup:
                    zip_path.unlink(missing_ok=True)

        import threading as _threading

        _threading.Thread(target=worker, name="gsp-import", daemon=True).start()

    # ================================================================== 清理与维护

    def toggle_sidebar_autohide(self) -> None:
        enabled = self.store.get_meta("sidebar_autohide", "1") == "1"
        self.store.set_meta("sidebar_autohide", "0" if enabled else "1", wait=True)
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=f"选中笔记后自动隐藏侧栏：{'已关闭' if enabled else '已开启'}",
                timeout=3,
            )
        )

    def purge_closed_documents(self) -> None:
        """批量永久删除 state='closed' 的笔记（先确认，再走写线程单事务）。"""
        docs = self.store.closed_documents()
        if not docs:
            self.toast_overlay.add_toast(Adw.Toast(title="没有已关闭的笔记", timeout=3))
            return
        targets = [d for d in docs if d.id not in self._pages]
        if not targets:
            self.toast_overlay.add_toast(
                Adw.Toast(title="已关闭的笔记都在标签中打开，未删除", timeout=4)
            )
            return
        total = sum(len(d.content.encode("utf-8")) for d in targets)
        body = (
            f"将永久删除 {len(targets)} 篇已关闭笔记（正文约 {_human_size(total)}）"
            "及其图片资源。\n\n"
            "已关闭笔记可从侧栏「最近更新」重新打开，清除后无法恢复；"
            "关联的本机原文件不受影响。"
        )
        dialog = Adw.AlertDialog(heading="清除已关闭的笔记？", body=body)
        dialog.add_response("cancel", "取消")
        dialog.add_response("purge", "永久清除")
        dialog.set_response_appearance("purge", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_purge_closed)
        dialog.present(self)

    def _on_purge_closed(self, _dialog, response) -> None:
        if response != "purge":
            return
        report = self.store.purge_closed_documents(keep_ids=set(self._pages))
        self._rebuild_recent_menu()
        self._schedule_sidebar_refresh(0)
        title = f"已清除 {report.purged_docs} 篇已关闭笔记"
        if report.errors:
            title += f"（{len(report.errors)} 项文件未删除）"
        self.toast_overlay.add_toast(Adw.Toast(title=title, timeout=5))

    def run_maintenance(self) -> None:
        """清理孤儿文件 + VACUUM。先扫描出计数与体积，确认后才动数据目录。"""
        scan = self.store.scan_orphans()
        items: list[str] = []
        if scan.orphan_notes:
            items.append(
                f"镜像文件 {scan.orphan_notes} 个（{_human_size(scan.orphan_notes_bytes)}）"
            )
        if scan.orphan_assets:
            items.append(
                f"图片资源 {scan.orphan_assets} 个（{_human_size(scan.orphan_assets_bytes)}）"
            )
        if scan.orphan_journals:
            items.append(f"恢复日志 {scan.orphan_journals} 个")
        if scan.stale_meta:
            items.append(f"失效映射 {scan.stale_meta} 条")
        reclaimable = scan.db_free_bytes >= 256 * 1024
        if not items and not reclaimable:
            self.toast_overlay.add_toast(
                Adw.Toast(title="数据目录已无需要清理的内容", timeout=3)
            )
            return

        lines: list[str] = []
        if items:
            lines.append("将删除本应用数据目录内无对应笔记的文件：")
            lines.extend(f"· {text}" for text in items)
        if reclaimable:
            lines.append(f"\n数据库可回收约 {_human_size(scan.db_free_bytes)} 空闲页。")
        lines.append(
            "\n只处理 notes/、assets/、recovery/ 三个目录，不触碰你关联的本机原文件。"
        )
        dialog = Adw.AlertDialog(heading="清理孤儿文件并压缩数据库？", body="\n".join(lines))
        dialog.add_response("cancel", "取消")
        dialog.add_response("run", "开始清理")
        dialog.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("run")
        dialog.connect("response", self._on_maintenance_confirmed)
        dialog.present(self)

    def _on_maintenance_confirmed(self, _dialog, response) -> None:
        if response != "run":
            return
        report = self.store.maintain(vacuum=True)
        self._rebuild_recent_menu()
        self._schedule_sidebar_refresh(0)
        if report.total_orphans:
            title = (
                f"已清理 {report.total_orphans} 个孤儿文件"
                f"（{_human_size(report.orphan_bytes)}）"
            )
        elif report.vacuumed:
            title = "数据库已压缩"
        else:
            title = "没有需要清理的内容"
        if report.vacuumed:
            title += (
                f"；数据库 {_human_size(report.db_bytes_before)} → "
                f"{_human_size(report.db_bytes_after)}"
            )
        if report.errors:
            title += f"；{len(report.errors)} 项未完成"
        self.toast_overlay.add_toast(Adw.Toast(title=title, timeout=6))

    # ================================================================== 快捷键说明

    def show_shortcuts(self) -> None:
        """用代码构建快捷键对话框。

        旧实现用 Gtk.Builder + XML 字符串，libadwaita 1.9 删掉了
        `AdwShortcutsSection.section-name` 与 `max-height` 两个属性，Builder 报
        「Invalid property」后走 g_error 直接终止进程——菜单点「键盘快捷键」就退出。
        代码构建不存在这个失效模式，且加速键可逐个校验。
        """
        dialog = Adw.ShortcutsDialog()
        for section_name, items in SHORTCUTS:
            section = Adw.ShortcutsSection(title=section_name)
            for accelerator, title in items:
                item = Adw.ShortcutsItem(title=title)
                if accelerator:
                    ok, _key, _mods = Gtk.accelerator_parse(accelerator)
                    if ok:
                        item.set_accelerator(accelerator)
                section.add(item)
            dialog.add(section)
        self._shortcuts_dialog = dialog  # 保持引用，避免被 GC 后窗口消失
        dialog.present(self)

    # ================================================================== 生命周期

    def _restore_geometry(self) -> None:
        width = self.store.get_meta("window_w")
        height = self.store.get_meta("window_h")
        if width and height:
            try:
                self.set_default_size(int(width), int(height))
            except ValueError:
                pass
        if self.store.get_meta("maximized") == "1":
            self.maximize()

    def restore_session(self) -> list[str]:
        """启动恢复：返回恢复说明。"""
        docs = self.store.open_documents()
        notes: list[str] = []
        if not docs:
            # 不在这里急着建空白标签：若是「双击文件」启动，do_open 会马上
            # 打开文件，先建空白标签就会多出一个空页面
            self.set_mode(self.store.get_meta("view_mode", MODE_SOURCE))
            return notes
        for doc in docs:
            self.add_tab(doc, activate=False)
        active = self.store.get_meta("active_doc")
        selected = False
        for i in range(self.tabview.get_n_pages()):
            page = self.tabview.get_nth_page(i).get_child()
            if page is not None and page.doc_id == active:
                self.tabview.set_selected_page(self.tabview.get_nth_page(i))
                selected = True
                break
        if not selected:
            self.tabview.set_selected_page(self.tabview.get_nth_page(0))
        # 每文档模式：各页已在 add_tab 时按 mode:<doc_id> 恢复；
        # 窗口模式 / 按钮跟随当前选中文档，不再用全局 view_mode 覆盖全部页。
        tab = self.tabview.get_selected_page()
        page = tab.get_child() if tab is not None else None
        if page is not None:
            self.set_mode(page.mode)
        # 启动恢复时窗口尚未显示，grab_focus 无效 → 重开后打字没反应（需切
        # 一次模式才激活）。窗口首次显示后再补一次焦点。
        self._focus_after_map = True
        self.connect("map", self._on_map_focus_restore)
        return notes

    def _on_map_focus_restore(self, *_args) -> None:
        if not getattr(self, "_focus_after_map", False):
            return
        self._focus_after_map = False
        GLib.idle_add(self._focus_current_view)

    def _focus_current_view(self) -> bool:
        if self._closing:
            return False
        page = self._current_page()
        if page is not None and self.mode != MODE_PREVIEW:
            page.view.grab_focus()
        return False

    def _persist_session(self) -> None:
        width, height = self.get_default_size()
        self.store.set_meta("window_w", str(width))
        self.store.set_meta("window_h", str(height))
        self.store.set_meta("maximized", "1" if self.is_maximized() else "0")
        page = self._current_page()
        if page is not None:
            self.store.set_meta("active_doc", page.doc_id)
        for item in self._pages.values():
            self._save_cursor(item)
            self._save_doc_mode(item)

    def _on_close_request(self, _window) -> bool:
        if self._closing:
            return False
        self._closing = True
        # 退出前同步落盘：不询问、不丢内容
        for page in list(self._pages.values()):
            self._cancel_timer(page.doc_id)
            if page.dirty:
                self._save_page(page, wait=True)
        self._persist_session()
        self.store.flush()
        if self.cloud is not None:
            # 关闭前推送（规约 §9）：同步 + 备份，阻塞式尽力而为
            self.cloud.close_flush()
        self.store.close()
        return False  # 允许关闭

    # ------------------------------------------------------------------ 云备份 / 云同步

    def _on_cloud_status(self, text: str) -> None:
        """云任务状态回调（工作线程内触发）→ 主线程 toast + 标题栏同步按钮 tooltip。"""
        def show() -> bool:
            self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=5))
            if getattr(self, "sync_button", None) is not None:
                self.sync_button.set_tooltip_text(f"同步：{text}")
            return False
        GLib.idle_add(show)

    def _cloud_touch(self) -> None:
        """内容保存后防抖触发同步（主线程内调用）。"""
        if self._closing or not CloudManager.autosync_enabled(self.store):
            return
        if self._cloud_debounce_timer is not None:
            GLib.source_remove(self._cloud_debounce_timer)
        self._cloud_debounce_timer = GLib.timeout_add_seconds(
            int(CHANGE_DEBOUNCE), self._on_cloud_debounce_fire
        )

    def _on_cloud_debounce_fire(self) -> bool:
        self._cloud_debounce_timer = None
        if (
            not self._closing
            and CloudManager.autosync_enabled(self.store)
            and self.cloud.config_url()
        ):
            self.cloud.sync_async()
        return False

    def _on_cloud_startup_tick(self) -> bool:
        if (
            not self._closing
            and CloudManager.autosync_enabled(self.store)
            and self.cloud.config_url()
        ):
            self.cloud.sync_async()
        return False

    def _on_cloud_sync_tick(self) -> bool:
        if (
            not self._closing
            and CloudManager.autosync_enabled(self.store)
            and self.cloud.config_url()
        ):
            self.cloud.sync_async()
        return True

    def _on_cloud_backup_tick(self) -> bool:
        if (
            not self._closing
            and CloudManager.autobackup_enabled(self.store)
            and self.cloud.config_url()
        ):
            self.cloud.backup_async()
        return True


