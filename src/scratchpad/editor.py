"""编辑器标签页：GtkSource 源码编辑 + 查找替换 + 预览联动。"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")

from gi.repository import Adw, Gdk, GLib, Gio, GObject, Gtk, GtkSource  # noqa: E402

from .preview import PreviewPane  # noqa: E402
from .folding import FoldEngine, FoldGutter  # noqa: E402
from . import columnedit  # noqa: E402
from . import escapecodec  # noqa: E402
from . import snippets  # noqa: E402

MODE_SOURCE = "source"
MODE_SPLIT = "split"
MODE_PREVIEW = "preview"

# 写作模式：可选百分比与最小行宽（小窗口下防止文本被挤成几个字一行）
WRITING_PCTS = (50, 75, 85)
WRITING_MIN_WIDTH = 360


def writing_target_width(viewport_w: int, pct: int) -> int:
    """写作模式目标宽度：视口宽 × 百分比，下限 360 px 且不超过视口（0 = 关闭）。"""
    if pct <= 0 or viewport_w <= 0:
        return 0
    target = max(WRITING_MIN_WIDTH, round(viewport_w * pct / 100))
    return min(target, viewport_w)


def paragraph_bounds(lines: list[str], idx: int) -> tuple[int, int]:
    """光标所在第 idx 行（0 基）所属段落的行区间 [start, end)，0 基左闭右开。

    段落规则：空行分隔；标题行（# 开头）自成一段；围栏代码块（``` / ~~~）
    整块算一段（含开合围栏行）；其余按连续非空行聚段。idx 越界时钳制到首/末行。
    """
    n = len(lines)
    if n == 0:
        return (0, 0)
    idx = max(0, min(idx, n - 1))

    # 逐行标记围栏块归属：进入后直到闭合行（含）都算围栏内
    in_fence = [False] * n
    fence_open = False
    marker = ""
    for i, raw in enumerate(lines):
        s = raw.lstrip()
        if not fence_open and (s.startswith("```") or s.startswith("~~~")):
            fence_open = True
            marker = s[:3]
            in_fence[i] = True
        elif fence_open:
            in_fence[i] = True
            if s.startswith(marker):
                fence_open = False

    if in_fence[idx]:
        start = idx
        while start > 0 and in_fence[start - 1]:
            start -= 1
        end = idx + 1
        while end < n and in_fence[end]:
            end += 1
        return (start, end)

    if not lines[idx].strip():
        return (idx, idx + 1)          # 空行自成一段（只遮罩它自己）

    if lines[idx].lstrip().startswith("#"):
        return (idx, idx + 1)          # 标题行自成一段

    def plain(i: int) -> bool:
        if not lines[i].strip() or in_fence[i]:
            return False
        return not lines[i].lstrip().startswith("#")

    start = idx
    while start > 0 and plain(start - 1):
        start -= 1
    end = idx + 1
    while end < n and plain(end):
        end += 1
    return (start, end)

# 关联本机文件时的扩展名 → GtkSource 语言 id（用于语法高亮与折叠）
LANG_BY_EXT = {
    ".py": "python", ".pyw": "python",
    ".json": "json",
    ".xml": "xml", ".svg": "xml", ".plist": "xml",
    ".html": "html", ".htm": "html",
    ".css": "css", ".js": "js", ".ts": "typescript",
    ".sh": "sh", ".bash": "sh", ".zsh": "sh",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".rs": "rust", ".go": "go",
    ".java": "java", ".sql": "sql", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".md": "markdown", ".markdown": "markdown", ".mkd": "markdown",
    ".csv": "csv", ".log": "", ".tex": "latex",
}


class EditorPage(Gtk.Box):
    """一个标签页对应的完整编辑视图。"""

    __gsignals__ = {
        "edited": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "stats-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # 编辑器工具向窗口 toast 通道发提示（如「已在选区内替换 N 处」）
        "request-toast": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self.doc_id: str = ""
        self.title: str = "未命名"
        self.format: str = "txt"
        self.revision: int = 0
        self.mode: str = MODE_SOURCE
        self.dirty: bool = False
        self._lang_id: str = ""          # 由文件扩展名推断的语言（优先于 format）
        self._base_uri: str = ""         # 关联文件所在目录（HTML 预览相对资源用）

        # ---- 源码编辑器
        self.buffer = GtkSource.Buffer()
        self.buffer.connect("changed", self._on_buffer_changed)
        self.view = GtkSource.View.new_with_buffer(self.buffer)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.view.set_show_line_numbers(True)
        self.view.set_highlight_current_line(False)
        self.view.set_left_margin(18)
        self.view.set_right_margin(18)
        self.view.set_top_margin(14)
        self.view.set_bottom_margin(64)
        self.view.set_css_classes(["scratchpad-editor"])
        self.view.add_controller(self._make_drop_controller())
        # 右键菜单：GTK 内置文本菜单（剪切/复制/粘贴/删除/撤销/重做/全选/表情）
        # 之后追加我们的工具项。extra-menu 只增不减，内置项无法也不必移除。
        self.view.set_extra_menu(self._build_context_menu())

        # Tab 触发词展开：CAPTURE 阶段先看一眼，未命中就把 Tab 原样交还给
        # GtkSource 的默认缩进行为（返回 False 即可，不能吞掉）。
        self._trigger_ctrl = Gtk.EventControllerKey()
        self._trigger_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._trigger_ctrl.connect("key-pressed", self._on_trigger_key)
        self.view.add_controller(self._trigger_ctrl)

        self.source_scroller = Gtk.ScrolledWindow()
        self.source_scroller.set_child(self.view)
        self.source_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # 默认铺满编辑区（写作模式关闭态）。Gtk.ScrolledWindow 的 hexpand 默认是
        # False，不显式打开时宽度会退到最小内容宽，整个编辑器只剩几十像素。
        self.source_scroller.set_hexpand(True)

        # ---- 写作模式：把滚动区收窄并在编辑区居中（宽度按百分比可调）
        # 用「Box（撑满）+ 两侧 hexpand 空白 + 固定宽度子滚动区」实现居中，
        # 而不用 Adw.Clamp 系：实测 Adw.ClampScrollable 对 GtkSource.View 不按
        # maximum-size 拉伸（宽度停在 88 字符自然宽度 792px），Adw.Clamp 会切断
        # 垂直滚动（adjustment 恒为 0）；Gtk.Box 内子控件 halign=CENTER 也不生效
        # （实测 x 恒为 0），只有两侧 hexpand 空白能真正均分剩余空间。
        self._writing_pct = 0
        self._writing_state: tuple[bool, int] | None = None
        self._writing_idle: int | None = None

        # ---- 打字机模式：光标行固定于视口百分比处（滚动跟随）
        self._typewriter = False
        self._typewriter_idle: int | None = None
        self._typewriter_yalign = 33     # 光标行目标位置（视口百分比，50=居中）
        self._tw_retries = 0             # 布局校验未完成时的补滚计数

        # ---- 段落遮罩：当前段落以外的文本叠 TextTag 褪色蒙版（变灰退后）。
        # 用主题前景色降不透明度：亮主题深字变浅、暗主题浅字变暗，都是「向
        # 背景退去」的观感（等效于遮罩，不是真模糊——GTK4 无法对字形做高斯
        # 模糊，评估结论见 TEST_REPORT 修订三十一前评估）。tag 优先级高于
        # 语法高亮，遮罩段落整体褪色是预期行为。颜色在 set_scheme 时按当前
        # 主题重算（构造时 style context 可能还没拿到主题色）。
        self._dim_on = False
        self._dim_idle: int | None = None
        self._dim_sig: tuple[int, int] | None = None
        self._dim_tag = self.buffer.create_tag("paragraph-dim")
        self._refresh_dim_colors()
        self.buffer.connect("notify::cursor-position", self._on_cursor_moved)
        self.source_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, vexpand=True
        )
        self._write_pad_left = Gtk.Box(hexpand=True)
        self._write_pad_right = Gtk.Box(hexpand=True)
        self._write_pad_left.set_visible(False)
        self._write_pad_right.set_visible(False)
        self.source_box.append(self._write_pad_left)
        self.source_box.append(self.source_scroller)
        self.source_box.append(self._write_pad_right)
        self.source_box.connect("notify::width", self._on_source_width_changed)
        self.connect("map", self._on_page_mapped)

        # ---- 查找 / 替换
        self.search_settings = GtkSource.SearchSettings(
            case_sensitive=False, wrap_around=True, regex_enabled=False
        )
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)

        # ---- 折叠（箭头列在行号左侧）
        self._fold_renderer = FoldGutter()
        self._folding = FoldEngine(self.buffer, self.view, self._fold_renderer)
        self._fold_renderer.bind(self._folding)
        self._folding.on_fold_changed = lambda: self.emit("stats-changed")
        self.view.get_gutter(Gtk.TextWindowType.LEFT).insert(self._fold_renderer, 30)

        self._build_search_bar()

        # ---- 预览
        self.preview = PreviewPane()

        # ---- 布局：搜索栏在顶部，下方分屏
        self.append(self.search_bar)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=460, hexpand=True, vexpand=True)
        self.paned.set_start_child(self.source_box)
        self.paned.set_end_child(self.preview)
        self.append(self.paned)
        self._preview_timer: int | None = None
        self.set_mode(MODE_SOURCE, initial=True)

    # ------------------------------------------------------------------ 文档

    def load_document(self, doc_id: str, title: str, fmt: str, content: str, revision: int) -> None:
        self.doc_id = doc_id
        self.title = title
        self.format = fmt
        self.revision = revision
        self.dirty = False
        self.buffer.set_text(content)
        self._folding.reset()
        self._apply_language()

    def snapshot_text(self) -> str:
        """全文（含已折叠内容）——保存/预览/统计/PDF 一律取这里。"""
        return self._folding.expand_text()

    def set_format(self, fmt: str) -> None:
        if fmt != self.format:
            self.format = fmt
            self.dirty = True
            self.emit("edited")
        self._apply_language()
        if self.mode in (MODE_SPLIT, MODE_PREVIEW):
            self.refresh_preview()

    def _apply_language(self) -> None:
        manager = GtkSource.LanguageManager.get_default()
        lang = None
        if self._lang_id:
            lang = manager.get_language(self._lang_id)
        if lang is None and self.format == "md":
            lang = manager.get_language("markdown")
        elif lang is None and self.format == "html":
            lang = manager.get_language("html")
        self.buffer.set_language(lang)
        # 折叠策略与语法高亮保持一致
        self._folding.set_language(self._lang_id or ("markdown" if (lang is not None and self.format == "md") else ""))

    def set_language_for_path(self, path: str) -> None:
        """打开本机文件后按扩展名设置语法高亮（同时影响折叠策略）。"""
        ext = Path(path).suffix.lower()
        self._lang_id = LANG_BY_EXT.get(ext, "")
        self._apply_language()

    def set_base_uri(self, path: str) -> None:
        """关联本机文件后设置预览 base_uri（相对资源解析目录）。"""
        self._base_uri = Path(path).resolve().parent.as_uri() + "/"

    def set_scheme(self, dark: bool) -> None:
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        scheme = scheme_manager.get_scheme("Adwaita-dark" if dark else "Adwaita")
        if scheme is None:
            scheme = scheme_manager.get_scheme("classic")
        if scheme is not None:
            self.buffer.set_style_scheme(scheme)
        self._refresh_dim_colors()
        self.preview.set_dark(dark)
        if self.mode in (MODE_SPLIT, MODE_PREVIEW):
            self.refresh_preview()

    def _refresh_dim_colors(self) -> None:
        """按当前主题重算遮罩颜色（前景 0.32 透明度 + 背景 0.05 极淡雾面）。"""
        dark = Adw.StyleManager.get_default().get_dark()
        ok, fg = self.view.get_style_context().lookup_color("theme_fg_color")
        if not ok:
            fg = Gdk.RGBA()
            fg.parse("#ffffff" if dark else "#000000")
        faded = fg.copy()
        faded.alpha = 0.32
        scrim = fg.copy()
        scrim.alpha = 0.05
        self._dim_tag.set_property("foreground-rgba", faded)
        self._dim_tag.set_property("background-rgba", scrim)

    # ------------------------------------------------------------------ 编辑事件

    def _on_buffer_changed(self, _buffer) -> None:
        if self._dim_on:
            # 文本变了段落边界可能移动（回车分段/删空行并段）：置为待重算
            self._dim_sig = None
            self._schedule_dim()
        if self._folding.mutating:
            # 折叠/展开引起的变动：不标记 dirty、不触发保存；字数按全文重算
            self.emit("stats-changed")
            return
        self.dirty = True
        self.emit("edited")
        self.emit("stats-changed")
        self._schedule_preview_refresh()

    def _schedule_preview_refresh(self, delay_ms: int = 150) -> None:
        """实时预览：输入停止 150ms 后刷新（防抖，避免逐键整页重载）。"""
        if self.mode == MODE_SOURCE:
            return
        if self._preview_timer is not None:
            GLib.source_remove(self._preview_timer)
        self._preview_timer = GLib.timeout_add(delay_ms, self._preview_tick)

    def _preview_tick(self) -> bool:
        self._preview_timer = None
        if self.mode != MODE_SOURCE:
            self.refresh_preview()
        return False

    # ------------------------------------------------------------------ 模式

    def set_mode(self, mode: str, initial: bool = False) -> None:
        self.mode = mode
        if mode == MODE_SOURCE:
            self.source_box.set_visible(True)
            self.preview.set_visible(False)
        elif mode == MODE_PREVIEW:
            self.source_box.set_visible(False)
            self.preview.set_visible(True)
            self.refresh_preview()
        else:  # split
            self.source_box.set_visible(True)
            self.preview.set_visible(True)
            self.refresh_preview()
        if not initial and mode != MODE_PREVIEW:
            self.view.grab_focus()

    # ------------------------------------------------------------------ 写作模式

    def set_writing_width(self, pct: int) -> None:
        """设置写作模式宽度百分比（0 = 关闭，恢复铺满）。"""
        self._writing_pct = max(0, int(pct))
        self._apply_writing_width()

    def _apply_writing_width(self) -> None:
        viewport_w = self.source_box.get_width()
        if viewport_w <= 0:
            # 尚未布局：不缓存无效状态，等 map / 宽度变化时重算
            self._writing_state = None
            return
        target = writing_target_width(viewport_w, self._writing_pct)
        state = (target <= 0, target)
        if state == self._writing_state:
            return
        self._writing_state = state
        on = target > 0
        self._write_pad_left.set_visible(on)
        self._write_pad_right.set_visible(on)
        if not on:
            # 关闭：滚动区铺满编辑区，与原行为一致
            self.source_scroller.set_hexpand(True)
            self.source_scroller.set_size_request(-1, -1)
            return
        self.source_scroller.set_hexpand(False)
        self.source_scroller.set_size_request(target, -1)

    def _on_source_width_changed(self, *_args) -> None:
        """编辑区宽度变化（窗口缩放 / 拖拽分屏）时按比例重算；延迟到 idle 避免布局中重排。"""
        if self._writing_pct <= 0 or self._writing_idle is not None:
            return
        self._writing_idle = GLib.idle_add(self._apply_writing_idle)

    def _on_page_mapped(self, *_args) -> None:
        """页面首次显示：此时才有真实宽度（新标签在未布局时设置会被跳过的补偿）。"""
        if self._writing_pct > 0 and self._writing_idle is None:
            self._writing_idle = GLib.idle_add(self._apply_writing_idle)

    def _apply_writing_idle(self) -> bool:
        self._writing_idle = None
        self._apply_writing_width()
        return False

    # ------------------------------------------------------------------ 打字机模式

    def set_typewriter(self, on: bool) -> None:
        """打字机模式：光标所在行固定在视口 _typewriter_yalign% 处（滚动跟随）。

        用 scroll_to_mark(use_align=True, yalign=...) 而不是 scroll_mark_onscreen：
        后者只保证「可见」不做对齐（写作模式回归实测，底差恰为 bottom-margin）。
        头尾由 API 自动钳制，不会把文档滚出界。
        """
        self._typewriter = bool(on)
        if self._typewriter:
            self._schedule_typewriter()

    def set_typewriter_align(self, pct: int) -> None:
        """光标行目标位置：视口高度的百分比（50 = 居中，33 ≈ SoloMD 的 1/3 处）。"""
        self._typewriter_yalign = min(90, max(10, int(pct)))
        if self._typewriter:
            self._schedule_typewriter()

    def _on_cursor_moved(self, *_args) -> None:
        self._tw_retries = 0
        if self._typewriter:
            self._schedule_typewriter()
        if self._dim_on:
            self._schedule_dim()

    def _schedule_typewriter(self) -> None:
        if self._typewriter_idle is not None:
            return  # 已排队：连续打字合并为一帧（与写作模式同一 idle 短路写法）
        self._typewriter_idle = GLib.idle_add(self._typewriter_tick)

    def _typewriter_tick(self) -> bool:
        self._typewriter_idle = None
        if not self._typewriter or not self.view.get_mapped():
            return False
        if self.buffer.get_has_selection():
            # 拖选抑制：插入点在选区端点，逐次居中会上下抖动
            return False
        if self._folding.mutating:
            # 折叠/展开引起的重排与重选区：跳过本次，避免把上下文滚走
            return False
        target = self._typewriter_yalign / 100.0
        self.view.scroll_to_mark(
            self.buffer.get_insert(), 0.0, True, 0.0, target
        )
        # 远距离跳转或刚换文本时，目标行可能落在尚未校验的布局区：GTK 第一拍
        # 只按「确保可见」滚（探针实测：伪对齐 → 后续校验把视口推离目标行）。
        # 布局校验完成后 y 才真实，补滚对齐直到收敛（上限 3 拍；钳制态会自然停）。
        err = self._typewriter_alignment_error(target)
        if err is not None and err > 2.0 and self._tw_retries < 3:
            self._tw_retries += 1
            self._schedule_typewriter()
        else:
            self._tw_retries = 0
        return False

    def _typewriter_alignment_error(self, target: float) -> float | None:
        """光标行中心与视口 target×page_size 处的距离（px）；无法测量时 None。"""
        adj = self.source_scroller.get_vadjustment()
        ps = adj.get_page_size()
        if ps <= 0:
            return None
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line_y, line_h = self.view.get_line_yrange(it)
        if line_h <= 0:
            return None
        _wx, wy = self.view.buffer_to_window_coords(Gtk.TextWindowType.TEXT, 0, line_y)
        # wy 是视口相对坐标（不含 adj.value），探针实证
        return abs((wy + line_h / 2) - target * ps)

    def set_paragraph_dim(self, on: bool) -> None:
        """段落遮罩开关。与打字机滚动相互独立，可只遮罩不滚动。

        TextTag 随文本移动自动跟随；光标跨段或文本变更时经 idle 重算一次。
        """
        self._dim_on = bool(on)
        self._dim_sig = None
        if self._dim_on:
            self._schedule_dim()
        else:
            self._clear_dim()

    def has_paragraph_dim(self) -> bool:
        return self._dim_on

    def _schedule_dim(self) -> None:
        if self._dim_idle is not None:
            return
        self._dim_idle = GLib.idle_add(self._dim_tick)

    def _dim_tick(self) -> bool:
        self._dim_idle = None
        if not self._dim_on:
            return False
        if self.buffer.get_has_selection():
            # 选区期间暂停刷新，避免遮罩与选区高亮打架（保持上一次状态）
            return False
        if self._folding.mutating:
            return False
        cursor_line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        text = self.buffer.get_text(*self.buffer.get_bounds(), True)
        bounds = paragraph_bounds(text.split("\n"), cursor_line)
        if bounds == self._dim_sig:
            return False
        self._dim_sig = bounds
        self._paint_dim(*bounds)
        return False

    def _paint_dim(self, start: int, end: int) -> None:
        """把遮罩 tag 应用到 [0, start) 与 [end, 文档末尾)，当前段落保持清晰。"""
        buf = self.buffer
        buf.remove_tag(self._dim_tag, *buf.get_bounds())
        if start > 0:
            _ok, it = buf.get_iter_at_line(start)
            buf.apply_tag(self._dim_tag, buf.get_start_iter(), it)
        if end < buf.get_line_count():
            _ok, it = buf.get_iter_at_line(end)
            buf.apply_tag(self._dim_tag, it, buf.get_end_iter())

    def _clear_dim(self) -> None:
        self._dim_sig = None
        self.buffer.remove_tag(self._dim_tag, *self.buffer.get_bounds())

    def refresh_preview(self, force: bool = False) -> None:
        if self.mode == MODE_SOURCE:
            return
        self.preview.render(
            self.snapshot_text(), self.format, force=force,
            base_uri=self._base_uri or None,
        )

    # ------------------------------------------------------------------ 查找替换

    def _build_search_bar(self) -> None:
        # 只用 Gtk.SearchBar 自己的 search-mode 控制展开，不再套 Gtk.Revealer。
        # SearchBar 在 search_mode=False 时子控件高度恒为 0，外层 Revealer 即便
        # reveal_child=True 也只是"打开了一个 0 高度的盒子"，界面毫无变化。
        self._syncing_hide = False
        bar = Gtk.SearchBar()
        self.search_bar = bar
        bar.set_show_close_button(True)
        bar.connect("notify::search-mode-enabled", self._on_search_mode_changed)

        self.search_entry = Gtk.SearchEntry(
            placeholder_text="查找（支持正则）", hexpand=True
        )
        self.search_entry.connect("search-changed", self._on_search_text_changed)
        self.search_entry.connect("activate", lambda *_: self.find_next())
        self.search_entry.connect("stop-search", lambda *_: self.hide_search())

        prev_btn = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="上一个（Shift+Enter）")
        prev_btn.connect("clicked", lambda *_: self.find_prev())
        next_btn = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="下一个（Enter）")
        next_btn.connect("clicked", lambda *_: self.find_next())

        case_toggle = Gtk.CheckButton(label="区分大小写")
        case_toggle.connect("toggled", self._on_case_toggled)
        self.case_toggle = case_toggle
        regex_toggle = Gtk.CheckButton(label="正则")
        regex_toggle.connect("toggled", self._on_regex_toggled)
        self.regex_toggle = regex_toggle
        # 「转义」：把 \n \t \r \\ \xHH \uHHHH 当控制字符。默认关闭——
        # 本应用常用来贴路径/日志，默认解码会把 C:\temp 变成制表符。
        self.escape_toggle = Gtk.CheckButton(
            label="转义",
            tooltip_text="非正则模式下把 \\n \\t \\r \\\\ \\xHH \\uHHHH 当控制字符"
                         "（查找与替换都生效）；正则模式本身已支持这些转义与反向引用",
        )
        self.escape_toggle.connect("toggled", self._on_escape_toggled)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row1.append(self.search_entry)
        row1.append(prev_btn)
        row1.append(next_btn)
        row1.append(case_toggle)
        row1.append(regex_toggle)
        row1.append(self.escape_toggle)

        self.replace_entry = Gtk.Entry(placeholder_text="替换为", hexpand=True)
        replace_btn = Gtk.Button(label="替换")
        replace_btn.connect("clicked", lambda *_: self.replace_current())
        replace_all_btn = Gtk.Button(label="全部替换")
        replace_all_btn.connect("clicked", lambda *_: self.replace_all())
        # 「仅选区」：全部替换只处理完全落在选区内的匹配。打开面板时若为
        # 多行选区则默认勾上（显式开关，不做隐式推断）。
        self.replace_sel_toggle = Gtk.CheckButton(label="仅选区", tooltip_text="全部替换只作用于当前选区")

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row2.append(self.replace_entry)
        row2.append(replace_btn)
        row2.append(replace_all_btn)
        row2.append(self.replace_sel_toggle)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.append(row1)
        inner.append(row2)
        bar.set_child(inner)
        # 把 entry 与 SearchBar 绑定：SearchBar 才知道"输入到哪个框"、
        # 也才不会报 "does not have an entry connected to it"
        bar.connect_entry(self.search_entry)
        # 标准接线：源码视图聚焦时，直接键入即查找、Esc 关闭
        bar.set_key_capture_widget(self.view)

        self.match_label = Gtk.Label(css_classes=["dim-label"])

    def _on_search_mode_changed(self, bar, _pspec) -> None:
        # 用户点关闭按钮 / 按 Esc 时 SearchBar 自己把 search_mode 置 False，
        # 这里同步清理高亮并交还焦点；自身调用 hide_search 时用标志避免递归。
        if not bar.get_search_mode() and not self._syncing_hide:
            self.hide_search()

    def show_search(self, replace: bool = False) -> None:
        self._folding.unfold_all()
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()
        selected = self._selected_text()
        if selected:
            self.search_entry.set_text(selected)
        self.search_entry.select_region(0, -1)
        if replace:
            # 多行选区 → 默认「仅选区」；否则回退整篇语义（显式且可改）
            sels = self._selection_iters()
            if sels[0] is not None and sels[0].get_line() != sels[1].get_line():
                self.replace_sel_toggle.set_active(True)
            else:
                self.replace_sel_toggle.set_active(False)
        GLib.idle_add(lambda: (self.replace_entry.set_visible(replace), False)[1])

    def hide_search(self) -> None:
        if self.search_bar.get_search_mode():
            self._syncing_hide = True
            try:
                self.search_bar.set_search_mode(False)
            finally:
                self._syncing_hide = False
        self.search_settings.set_search_text("")
        self.view.grab_focus()

    def goto_line(self, line_no: int, column: int = 0, length: int = 0) -> None:
        """光标移到指定行（1 基）并滚动到可见——目录搜索的结果跳转用。

        `column` 是行内偏移（0 基），`length` 是命中文本长度；给出后会把关键词
        整段选中，用户一眼就能看到命中的是哪几个字（跨行命中则跨行选中）。
        """
        self._folding.unfold_all()
        last = max(0, self.buffer.get_line_count() - 1)
        index = min(max(0, line_no - 1), last)
        it = self.buffer.get_start_iter()
        it.set_line(index)
        # 列号收敛到行尾：拼错的列号不应该把光标推到下一行
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        offset = max(0, min(column, line_end.get_line_offset()))
        start = it.copy()
        if offset:
            start.forward_chars(offset)
        self.buffer.place_cursor(start)
        if length > 0:
            end = start.copy()
            end.forward_chars(length)
            if end.get_offset() > start.get_offset():
                self.buffer.select_range(start, end)
        self.view.scroll_to_iter(start, 0.15, True, 0.5, 0.5)
        self.view.grab_focus()

    # ------------------------------------------------------------------ 光标位置

    def cursor_position(self) -> tuple[int, int]:
        """当前光标 (行, 列)，行号 1 基——用于退出/切换标签时记住进度。"""
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return it.get_line() + 1, it.get_line_offset()

    def place_cursor_at(self, line_no: int, column: int = 0, *, scroll: bool = True) -> None:
        """恢复光标位置：不抢焦点、不改内容，行号 1 基（越界自动收敛）。"""
        last = max(0, self.buffer.get_line_count() - 1)
        index = min(max(0, line_no - 1), last)
        # GTK 4.22 的 get_iter_at_line() 通过 Python 暴露为 (ok, iter) 元组，
        # 这里统一用 start_iter + set_line 拿到可写的 iter，避免解包差异。
        line_end = self.buffer.get_start_iter()
        line_end.set_line(index)
        line_end.forward_to_line_end()
        target = self.buffer.get_start_iter()
        target.set_line(index)
        target.forward_chars(max(0, min(column, line_end.get_line_offset())))
        self.buffer.place_cursor(target)
        if scroll:
            # 等布局完成再滚动，否则视图尚未分配高度，滚动会被丢弃
            GLib.idle_add(self._scroll_to_cursor_idle)

    def _scroll_to_cursor_idle(self) -> bool:
        self.view.scroll_to_mark(self.buffer.get_insert(), 0.0, True, 0.0, 0.3)
        return False

    def _selected_text(self) -> str:
        start, end = self._selection_iters()
        if start is None:
            return ""
        return self.buffer.get_text(start, end, False)

    def _selection_iters(self):
        """GTK 4.22 起需通过 insert/selection_bound 标记取选区。"""
        buf = self.buffer
        insert = buf.get_iter_at_mark(buf.get_insert())
        bound = buf.get_iter_at_mark(buf.get_selection_bound())
        if insert.get_offset() == bound.get_offset():
            return None, None
        if insert.get_offset() <= bound.get_offset():
            return insert, bound
        return bound, insert

    def _escape_enabled(self) -> bool:
        return self.escape_toggle.get_active()

    def _search_pattern(self) -> str:
        """送进 SearchSettings 的查找串。

        正则模式下不解码：PCRE 本身把 `\\n` 当换行（已实测），再解码会把
        `\\\\n`（字面反斜杠 n）破坏成换行。仅非正则模式需要把转义变成字面字符。
        """
        raw = self.search_entry.get_text()
        if self._escape_enabled() and not self.search_settings.get_regex_enabled():
            return escapecodec.decode(raw)
        return raw

    def _replacement_text(self) -> str:
        """送进 SearchContext.replace()（单个替换）的替换串。

        正则模式：原样交上游。实测 `replace()` 自己会展开 `\\n` `\\t` `\\\\`
        与 `\\1`–`\\9` / `\\0`，此处再解码会二次解释（`\\\\n` 会被错当成换行）。
        非正则模式：上游按字面插入，故由本模块解码（开关打开时）。
        """
        raw = self.replace_entry.get_text()
        if self._escape_enabled() and not self.search_settings.get_regex_enabled():
            return escapecodec.decode(raw)
        return raw

    def _bulk_replacement_text(self) -> str:
        """送进 SearchContext.replace_all()（批量替换）的替换串。

        与单个替换不同：实测 `replace_all()` **只展开 `\\1`–`\\9` / `\\0`，
        不展开 `\\n` `\\t` `\\\\`**（同一库两条路径语义不一致）。因此正则模式下
        也必须先由本模块解码转义；反向引用原样留给上游展开。
        """
        raw = self.replace_entry.get_text()
        if self.search_settings.get_regex_enabled() or self._escape_enabled():
            return escapecodec.decode(raw)
        return raw

    def _on_search_text_changed(self, entry) -> None:
        self.search_settings.set_search_text(self._search_pattern())

    def _on_case_toggled(self, toggle) -> None:
        self.search_settings.set_case_sensitive(toggle.get_active())

    def _on_regex_toggled(self, toggle) -> None:
        self.search_settings.set_regex_enabled(toggle.get_active())
        # 解码条件依赖正则开关（见 _search_pattern），必须重放查找串
        self.search_settings.set_search_text(self._search_pattern())

    def _on_escape_toggled(self, toggle) -> None:
        self.search_settings.set_search_text(self._search_pattern())

    def _select(self, start, end) -> None:
        self.buffer.select_range(start, end)
        self.view.scroll_to_iter(end, 0.0, False, 0.5, 0.5)

    def find_next(self) -> None:
        self._find(forward=True)

    def find_prev(self) -> None:
        self._find(forward=False)

    def _find(self, forward: bool) -> None:
        if not self.search_settings.get_search_text():
            return
        start, end = self._selection_iters()
        anchor = end if (forward and end is not None) else (
            start if (not forward and start is not None) else self.buffer.get_start_iter()
        )
        if forward:
            found, s, e, wrapped = self.search_context.forward(anchor)
        else:
            found, s, e, wrapped = self.search_context.backward(anchor)
        if found:
            self._select(s, e)

    def replace_current(self) -> None:
        start, end = self._selection_iters()
        if start is None:
            self._find(forward=True)
            start, end = self._selection_iters()
            if start is None:
                return
        text = self._replacement_text()
        self.search_context.replace(start, end, text, -1)
        self._find(forward=True)

    def replace_all(self) -> None:
        """全部替换：整篇或仅选区。

        实测（GSV 5.18.0）上游三条路径语义不一致：`replace()` 展开转义与反向
        引用，`replace_all()` 只展开反向引用、不展开转义；而逐处调用 `replace()`
        是二次复杂度（3000 处匹配 22 s，`replace_all()` 仅 0.02 s）。
        故：替换串先由 escapecodec 解码，再整体交给 `replace_all()`；选区替换
        把选区文本搬进临时缓冲区复用同一路径，不逐处 `replace()`。
        """
        text = self._bulk_replacement_text()
        if self.replace_sel_toggle.get_active():
            sels = self._selection_iters()
            if sels[0] is None or sels[0].equal(sels[1]):
                self.emit("request-toast", "「仅选区」需要先选中一段内容")
                return
            n, lo, hi = self._replace_in_bounds(text, sels)
            buf = self.buffer
            if n:
                # 重新选中修改区域，方便连续操作
                buf.select_range(buf.get_iter_at_offset(lo), buf.get_iter_at_offset(hi))
            self.emit("request-toast", f"已在选区内替换 {n} 处")
            return

        n = self._replace_in_document(text)
        self.emit("request-toast", f"整篇替换 {n} 处")

    def _make_context(self, target):
        """在 target 缓冲区上建一个与当前查找设置一致的 SearchContext。"""
        settings = GtkSource.SearchSettings(
            case_sensitive=self.search_settings.get_case_sensitive(),
            wrap_around=False,
            regex_enabled=self.search_settings.get_regex_enabled(),
        )
        settings.set_search_text(self.search_settings.get_search_text())
        return GtkSource.SearchContext.new(target, settings)

    def _replace_in_document(self, text: str) -> int:
        """整篇替换：在脱离视图的临时缓冲区里完成，再一次性写回。

        必须离开视图：`replace_all()` 内部逐处修改缓冲区，每改一次都触发一次
        重高亮，实测 3000 处匹配在已挂载视图的缓冲区上耗时 52 s、在裸缓冲区
        上 0.02 s。写回用单次 set_text（一次 user action = 一步撤销），并恢复
        光标位置。
        """
        buf = self.buffer
        full = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

        tmp = GtkSource.Buffer()
        tmp.set_text(full, -1)
        tmp_context = self._make_context(tmp)
        count = self._count_matches(tmp_context, tmp)
        if not count:
            return 0

        tmp_context.replace_all(text, -1)
        new_text = tmp.get_text(tmp.get_start_iter(), tmp.get_end_iter(), False)
        keep = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        buf.begin_user_action()
        try:
            buf.set_text(new_text, -1)
            buf.place_cursor(buf.get_iter_at_offset(min(keep, buf.get_char_count())))
        finally:
            buf.end_user_action()
        return count

    @staticmethod
    def _count_matches(context, target) -> int:
        """统计匹配处数（只数不改，线性）。零宽匹配前进一格推进，避免原地循环。"""
        pos = target.get_start_iter()
        count = 0
        while True:
            found, start, end, wrapped = context.forward(pos)
            if not found or wrapped:
                break
            count += 1
            if start.get_offset() == end.get_offset():
                if end.get_offset() >= target.get_char_count():
                    break
                pos = target.get_iter_at_offset(end.get_offset() + 1)
            else:
                pos = end
        return count

    def _replace_in_bounds(self, text: str, bounds) -> tuple[int, int, int]:
        """在 bounds 内替换（完全落在范围内才算），返回 (处数, 新起, 新止)。

        选区文本搬进临时缓冲区，用同一套 SearchSettings 跑 `replace_all()`：
        线性、与整篇替换同语义；正则的锚点/环视天然只看选区内部，跨界匹配不会
        命中。整段替换包进单一 user action（一步撤销）。
        """
        buf = self.buffer
        lo, hi = bounds[0].get_offset(), bounds[1].get_offset()
        segment = buf.get_text(bounds[0], bounds[1], False)

        tmp = GtkSource.Buffer()
        tmp.set_text(segment, -1)
        tmp_context = self._make_context(tmp)

        count = self._count_matches(tmp_context, tmp)
        if not count:
            return 0, lo, hi

        tmp_context.replace_all(text, -1)
        new_segment = tmp.get_text(tmp.get_start_iter(), tmp.get_end_iter(), False)
        buf.begin_user_action()
        try:
            buf.delete(bounds[0], bounds[1])
            buf.insert(buf.get_iter_at_offset(lo), new_segment)
        finally:
            buf.end_user_action()
        return count, lo, lo + len(new_segment)

    # ------------------------------------------------------------------ 片段

    def trigger_language(self) -> str:
        """当前文档用于触发词展开的语言 id（无对应表时返回空串）。"""
        if self._lang_id:
            return "js" if self._lang_id == "typescript" else self._lang_id
        if self.format == "md":
            return "markdown"
        if self.format == "html":
            return "html"
        return ""

    def insert_snippet(self, template: str, *, title: str | None = None) -> None:
        """插入一条模板：整段合并为一次撤销，光标按 `{{cursor}}` 落位。"""
        self.buffer.begin_user_action()
        try:
            self._delete_selection()
            self._insert_template(template, title)
        finally:
            self.buffer.end_user_action()
        self.view.grab_focus()

    def _delete_selection(self) -> None:
        start, end = self._selection_iters()
        if start is not None:
            self.buffer.delete(start, end)

    # ------------------------------------------------------------------ 列编辑

    def _selection_lines(self) -> tuple[int, int] | None:
        """选区覆盖的整行范围 [start_line, end_line]（0 基）。

        末行若选区停在行首（offset 0），该行不计入——与主流编辑器一致：
        从上一行行尾拖到下一行行首，不应把下一行整行带上。
        无选区返回 None。
        """
        start, end = self._selection_iters()
        if start is None:
            return None
        start_line = start.get_line()
        end_line = end.get_line()
        if end.get_line_offset() == 0 and end_line > start_line:
            end_line -= 1
        return start_line, end_line

    def _selection_or_cursor_lines(self) -> tuple[int, int]:
        """选区覆盖的整行范围；无选区时退化为光标所在行。"""
        span = self._selection_lines()
        if span is None:
            line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
            return line, line
        return span

    def selection_span(self) -> tuple[int, int]:
        """供窗口层（切列对话框）取当前作用的行范围。"""
        return self._selection_or_cursor_lines()

    def _block_iters(self, span: tuple[int, int]) -> tuple[Gtk.TextIter, Gtk.TextIter]:
        """把行范围展开为整块的起止 iter（终点停在末行行尾，不含换行符）。"""
        start_line, end_line = span
        block_start = self.buffer.get_start_iter()
        block_start.set_line(start_line)
        block_end = block_start.copy()
        block_end.set_line(end_line)
        if not block_end.ends_line():
            block_end.forward_to_line_end()
        return block_start, block_end

    def block_text(self, span: tuple[int, int] | None = None) -> str:
        """取选区覆盖整行的文本（无选区取光标行），供切列对话框预览。

        与执行路径不同，这里**不展开折叠**：预览只是示意，不应改动用户的
        折叠状态；真正执行时 apply_column_op 会先 unfold_all。
        """
        span = span if span is not None else self._selection_or_cursor_lines()
        start, end = self._block_iters(span)
        return self.buffer.get_text(start, end, False)

    def _replace_block(self, span: tuple[int, int], new: str) -> None:
        """整块替换为 new，包进单一 user action（一步撤销），完成后选中新块。"""
        start, end = self._block_iters(span)
        start_offset = start.get_offset()
        self.buffer.begin_user_action()
        try:
            self.buffer.delete(start, end)
            insert_at = self.buffer.get_iter_at_offset(start_offset)
            self.buffer.insert(insert_at, new)
        finally:
            self.buffer.end_user_action()
        new_start = self.buffer.get_iter_at_offset(start_offset)
        new_end = self.buffer.get_iter_at_offset(start_offset + len(new))
        self.buffer.select_range(new_start, new_end)
        self.view.scroll_to_mark(self.buffer.get_insert(), 0.1, True, 0.0, 0.3)

    def apply_column_op(
        self, mode: str, *, sep: str = "：", index: int = 1, width: int = 0
    ) -> tuple[bool, int]:
        """按分隔符或字符宽度只保留一列，返回 (是否改动, 未命中行数)。

        未命中的行由 columnedit 原样保留，这里只负责把计数交给调用方提示用户。
        """
        self._folding.unfold_all()
        span = self._selection_or_cursor_lines()
        old = self.block_text(span)
        new, miss = columnedit.take_column(old, mode, sep=sep, index=index, width=width)
        if new == old:
            return False, miss
        self._replace_block(span, new)
        return True, miss

    def apply_line_op(self, op: str, arg: str = "") -> bool:
        """对选区覆盖的整行施加列编辑操作；无选区时仅作用于光标所在行。

        先展开全部折叠（折叠内容在缓冲区里是物理移除的，选区看不到它），
        整块替换包进单一 user action（一步撤销），完成后重新选中修改后的行。
        返回 False 表示无可做的事（空选区给排序/去重、内容未变），调用方负责提示。
        """
        if op not in columnedit.OPS:
            raise ValueError(f"unknown line op: {op}")
        self._folding.unfold_all()
        span = self._selection_or_cursor_lines()
        start_line, end_line = span
        if op in ("sort", "dedup") and end_line == start_line:
            return False
        old = self.block_text(span)
        new = columnedit.transform(op, old, arg)
        if new == old:
            return False
        self._replace_block(span, new)
        return True


    def _insert_template(self, template: str, title: str | None = None) -> None:
        rendered = snippets.render(
            template, title=self.title if title is None else title
        )
        text, cursor = rendered.text, rendered.cursor
        buf = self.buffer
        # 用字符偏移记录插入点：GTK 的 iter 在缓冲区改动后一律失效，
        # 复制出来的 iter 也会失效（曾导致光标落到 0、并打 “Invalid text buffer iterator”）
        start_offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        buf.insert_at_cursor(text)
        target = buf.get_iter_at_offset(start_offset + cursor)
        buf.place_cursor(target)
        self.view.scroll_to_mark(buf.get_insert(), 0.1, True, 0.0, 0.3)

    def _on_trigger_key(self, _ctrl, keyval, _code, state) -> bool:
        """Tab 触发词展开。未命中一律返回 False，保留 GtkSource 默认缩进。"""
        if keyval != Gdk.KEY_Tab:
            return False
        if state & Gtk.accelerator_get_default_mod_mask():
            return False
        if self.buffer.get_has_selection():
            return False
        lang = self.trigger_language()
        if not lang:
            return False
        insert = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line_start = insert.copy()
        line_start.set_line_offset(0)
        before = self.buffer.get_text(line_start, insert, False)
        match = snippets.match_trigger(before[-32:], lang)
        if match is None:
            return False
        start = insert.copy()
        start.backward_chars(match.length)
        self.buffer.begin_user_action()
        try:
            self.buffer.delete(start, insert)
            self._insert_template(match.template)
        finally:
            self.buffer.end_user_action()
        return True

    # ------------------------------------------------------------------ 图片拖放

    @staticmethod
    def _build_context_menu() -> Gio.Menu:
        """编辑区右键追加菜单（menu model 引用既有 win.* 动作，无需新动作）。

        条目刻意克制：均为选区/光标锚定操作；无选区时排序/去重等动作自身
        已有 toast 提示，不会静默操作。
        """
        col = Gio.Menu()
        col.append("每行加前缀…", "win.line-prefix")
        col.append("每行加后缀…", "win.line-suffix")
        col.append("行排序", "win.sort-lines")
        col.append("去除重复行", "win.dedup-lines")
        col.append("按列提取（保留一列）…", "win.column-take")
        menu = Gio.Menu()
        menu.append_submenu("列编辑", col)
        menu.append("格式化排版", "win.format-doc")
        menu.append("简体 → 繁体", "win.convert-s2t")
        menu.append("繁体 → 简体", "win.convert-t2s")
        menu.append("折叠当前区块", "win.fold-current")
        return menu

    def _make_drop_controller(self) -> Gtk.DropTarget:
        target = Gtk.DropTarget()
        target.set_gtypes([Gdk.FileList])
        target.set_actions(Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop)
        return target

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = value.get_files()
        paths = [f.get_path() for f in files if f.get_path()]
        if not paths:
            return False
        window = self.get_root()
        if window is not None and hasattr(window, "handle_dropped_files"):
            window.handle_dropped_files(paths)
            return True
        return False

    # ------------------------------------------------------------------ 统计

    def stats(self) -> tuple[int, int]:
        text = self.snapshot_text()
        cjk = 0
        latin_chars: list[str] = []
        for ch in text:
            code = ord(ch)
            if 0x3040 <= code <= 0x30FF or 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
                cjk += 1
                latin_chars.append(" ")
            else:
                latin_chars.append(ch)
        words = len("".join(latin_chars).split())
        return len(text), words
