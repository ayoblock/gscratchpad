"""片段与自动补全的设置界面。

两块内容：

1. 「片段」页：自定义文本片段（名称 + 可选快捷键 + 模板），增删改、按键录制、
   实时预览；底部可恢复被改绑核心动作的默认快捷键。
2. 「自动补全」页：内置触发词参考表（Bash / Markdown / HTML / Python / JS / CSS / SQL），
   只读，用来查“输入什么再按 Tab”。
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from . import snippets  # noqa: E402

_MODIFIER_KEYS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock",
    "ISO_Level3_Shift",
}


def _short(text: str, limit: int = 60) -> str:
    text = text.replace("\n", "⏎").replace("\t", "→")
    return text if len(text) <= limit else text[:limit] + "…"


class SnippetEditor(Adw.Dialog):
    """新建 / 编辑一条片段。"""

    def __init__(self, window, snippet: snippets.Snippet | None = None) -> None:
        super().__init__()
        self.window = window
        self.snippet = snippet
        self._accel = snippet.accel if snippet else ""
        self._recording = False

        self.set_title("编辑片段" if snippet else "新建片段")
        self.set_content_width(600)
        self.set_content_height(620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        cancel = Gtk.Button(label="取消")
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label="保存", css_classes=["suggested-action"])
        save.connect("clicked", lambda *_: self._commit())
        header.pack_start(cancel)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.set_margin_top(4)

        info = Adw.PreferencesGroup(title="基本信息")
        self.name_row = Adw.EntryRow(title="名称（命令菜单里显示）")
        self.name_row.set_text(snippet.name if snippet else "")
        info.add(self.name_row)

        self.accel_row = Adw.ActionRow(title="快捷键", subtitle="未绑定")
        self.record_button = Gtk.Button(label="录制")
        self.record_button.add_css_class("flat")
        self.record_button.connect("clicked", lambda *_: self._start_record())
        clear_button = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="清除快捷键")
        clear_button.add_css_class("flat")
        clear_button.connect("clicked", lambda *_: self._set_accel(""))
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        box.append(self.record_button)
        box.append(clear_button)
        self.accel_row.add_suffix(box)
        info.add(self.accel_row)
        page.add(info)

        template_group = Adw.PreferencesGroup(
            title="模板",
            description=(
                "{{cursor}} 光标落点 · {{date}} {{time}} {{title}} 变量 · "
                "支持 \\n \\t \\r \\\\ 转义"
            ),
        )
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_monospace(True)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.get_buffer().set_text(snippet.template if snippet else "")
        self.text_view.get_buffer().connect("changed", lambda *_: self._refresh_preview())
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(200)
        scroller.set_has_frame(True)
        scroller.set_child(self.text_view)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.set_margin_top(6)
        holder.append(scroller)
        template_group.add(holder)
        page.add(template_group)

        preview_group = Adw.PreferencesGroup(title="预览")
        self.preview_label = Gtk.Label(
            xalign=0, wrap=True, selectable=True, css_classes=["monospace", "dim-label"]
        )
        self.preview_label.set_use_markup(False)
        preview_group.add(self.preview_label)
        page.add(preview_group)

        toolbar.set_content(page)
        self.set_child(toolbar)

        ctrl = Gtk.EventControllerKey()
        ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctrl.connect("key-pressed", self._on_record_key)
        self.add_controller(ctrl)

        self._set_accel(self._accel)
        self._refresh_preview()
        GLib.idle_add(self._focus_name)

    # ------------------------------------------------------------------ 内部

    def _focus_name(self) -> bool:
        self.name_row.grab_focus()
        return False

    def _template_text(self) -> str:
        buf = self.text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _refresh_preview(self) -> None:
        rendered = snippets.render(self._template_text(), title="示例标题")
        if not rendered.text:
            self.preview_label.set_text("（空模板）")
            return
        shown = rendered.text[:1] + rendered.text[1:]
        mark = "▏"
        cut = rendered.cursor
        self.preview_label.set_text(
            f"{shown[:cut]}{mark}{shown[cut:]}" + ("\n（光标在末尾）" if cut == len(shown) else "")
        )

    def _set_accel(self, accel: str) -> None:
        self._accel = accel
        if accel:
            self.accel_row.set_subtitle(snippets.pretty_accel(accel) or accel)
        else:
            self.accel_row.set_subtitle("未绑定")

    def _start_record(self) -> None:
        self._recording = True
        self.record_button.set_label("按下组合键…")
        self.record_button.add_css_class("accent")
        self.accel_row.set_subtitle("录制中：按 Esc 取消")

    def _stop_record(self) -> None:
        self._recording = False
        self.record_button.set_label("录制")
        self.record_button.remove_css_class("accent")
        self._set_accel(self._accel)

    def _on_record_key(self, _ctrl, keyval, _code, state) -> bool:
        if not self._recording:
            return False
        if keyval == Gdk.KEY_Escape:
            self._stop_record()
            return True
        name = Gdk.keyval_name(keyval) or ""
        if name in _MODIFIER_KEYS:
            return True  # 只按了修饰键：继续等真正的键
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if not mods:
            is_function = name.startswith("F") and name[1:].isdigit()
            if not is_function:
                self.accel_row.set_subtitle("需要 Ctrl / Alt / Shift 组合，或 F1–F12")
                return True
        if not Gtk.accelerator_valid(keyval, mods):
            self.accel_row.set_subtitle("这个组合不可用，换一个")
            return True
        accel = snippets.normalize_accel(Gtk.accelerator_name(keyval, mods))
        if not accel:
            self.accel_row.set_subtitle("这个组合不可用，换一个")
            return True
        self._accel = accel
        self._stop_record()
        return True

    # ------------------------------------------------------------------ 保存

    def _commit(self) -> None:
        name = self.name_row.get_text().strip()
        if not name:
            self.name_row.add_css_class("error")
            self.name_row.set_tooltip_text("名称不能为空")
            return
        template = self._template_text()
        if not template.strip():
            self.accel_row.set_subtitle("模板不能为空")
            return
        if self._accel:
            owner = self.window.accel_owner(self._accel, exclude=self.snippet.id if self.snippet else "")
            if owner is not None:
                self._ask_rebind(*owner)
                return
        self._apply(name, template)

    def _ask_rebind(self, action: str, label: str) -> None:
        dialog = Adw.AlertDialog(
            heading="快捷键已被占用",
            body=(
                f"{snippets.pretty_accel(self._accel)} 当前用于「{label}」。\n"
                "改绑会把这组键从原动作上移除（原动作仍可从菜单触发）。"
            ),
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("rebind", "仍然改绑")
        dialog.set_response_appearance("rebind", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_dialog, response) -> None:
            if response == "rebind":
                self.window.release_accel(action)
                self._apply(self.name_row.get_text().strip(), self._template_text())

        dialog.connect("response", on_response)
        dialog.present(self)

    def _apply(self, name: str, template: str) -> None:
        if self.snippet is None:
            snippet = snippets.Snippet(name=name, template=template, accel=self._accel)
            self.window.snippets.append(snippet)
        else:
            self.snippet.name = name
            self.snippet.template = template
            self.snippet.accel = self._accel
        self.window.save_snippets()
        self.close()


class SnippetsDialog(Adw.PreferencesDialog):
    """片段管理 + 触发词参考。"""

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self._rows: list[Adw.ActionRow] = []
        self.set_title("片段与自动补全")

        page = Adw.PreferencesPage(title="片段", icon_name="accessories-text-editor-symbolic")
        self.group = Adw.PreferencesGroup(
            title="自定义片段",
            description="绑定快捷键后，在编辑区按下即插入；未绑定时可从命令菜单（Ctrl+K）搜索。",
        )
        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="新建片段")
        add_button.add_css_class("flat")
        add_button.connect("clicked", lambda *_: self._edit(None))
        self.group.set_header_suffix(add_button)
        page.add(self.group)

        accel_group = Adw.PreferencesGroup(title="快捷键")
        self.restore_row = Adw.ActionRow(
            title="恢复默认快捷键", subtitle="把被片段改绑占用的核心快捷键还原"
        )
        restore_button = Gtk.Button(label="恢复")
        restore_button.add_css_class("flat")
        restore_button.connect("clicked", lambda *_: self._restore())
        self.restore_row.add_suffix(restore_button)
        accel_group.add(self.restore_row)
        page.add(accel_group)
        self.add(page)

        self.add(self._build_trigger_page())
        self._rebuild()

    # ------------------------------------------------------------------ 片段列表

    def _build_trigger_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="自动补全", icon_name="tools-check-spelling-symbolic"
        )
        intro = Adw.PreferencesGroup(
            title="触发词 + Tab",
            description="在对应语言的文件里输入触发词后按 Tab 即可展开；未命中时 Tab 仍是普通缩进。",
        )
        page.add(intro)
        group = Adw.PreferencesGroup()
        for lang, lang_name in snippets.TRIGGER_LANG_NAMES.items():
            rows = snippets.trigger_rows(lang)
            if not rows:
                continue
            expander = Adw.ExpanderRow(title=lang_name, subtitle=f"{len(rows)} 个触发词")
            for trigger, summary in rows:
                # 模板里有 <div> / & / $1：Adw.ActionRow 的 subtitle 默认按标记解析，
                # 必须先转义再做行，否则 Pango 解析失败（日志里一串 Gtk-WARNING）
                row = Adw.ActionRow(
                    title=trigger,
                    subtitle=GLib.markup_escape_text(_short(summary, 72)),
                    css_classes=["property"],
                )
                expander.add_row(row)
            group.add(expander)
        page.add(group)
        return page

    def _rebuild(self) -> None:
        for row in self._rows:
            self.group.remove(row)
        self._rows.clear()
        for snippet in self.window.snippets:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(snippet.name),
                subtitle=snippets.pretty_accel(snippet.accel) or "未绑定快捷键",
            )
            edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="编辑")
            edit.add_css_class("flat")
            edit.connect("clicked", lambda _b, s=snippet: self._edit(s))
            delete = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="删除")
            delete.add_css_class("flat")
            delete.connect("clicked", lambda _b, s=snippet: self._delete(s))
            row.add_suffix(edit)
            row.add_suffix(delete)
            self.group.add(row)
            self._rows.append(row)
        if not self.window.snippets:
            empty = Adw.ActionRow(title="还没有片段", subtitle="点右上角 + 新建一条")
            empty.set_activatable(False)
            self.group.add(empty)
            self._rows.append(empty)
        count = self.window.overridden_accel_count()
        self.restore_row.set_subtitle(
            f"已改绑 {count} 组核心快捷键" if count else "没有核心快捷键被占用"
        )

    def _edit(self, snippet: snippets.Snippet | None) -> None:
        dialog = SnippetEditor(self.window, snippet)
        dialog.connect("closed", lambda *_: self._rebuild())
        dialog.present(self)
        self.window._snippet_editor = dialog  # 防 GC

    def _delete(self, snippet: snippets.Snippet) -> None:
        dialog = Adw.AlertDialog(
            heading="删除片段",
            body=f"确定删除「{snippet.name}」？绑定的快捷键会一并解除。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "删除")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, response) -> None:
            if response != "delete":
                return
            self.window.snippets = [s for s in self.window.snippets if s.id != snippet.id]
            self.window.save_snippets()
            self._rebuild()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _restore(self) -> None:
        self.window.restore_default_accels()
        self._rebuild()
