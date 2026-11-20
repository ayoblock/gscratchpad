"""命令式菜单：分组命令 + 顶部搜索框（菜单栏替代方案）。

设计要点：

1. 单一数据源——菜单结构由 `provider()` 每次打开时现算，动态分组（如「已关闭的文档」）
   不需要额外的 Gio.Menu 同步，也不会出现"菜单里的条目和实际文档对不上"。
2. 搜索框固定在顶部，过滤只重建下方列表，输入焦点不会丢（Gtk.PopoverMenu 换 menu model
   会把自定义子控件一起重建，导致搜索框失焦，所以这里自建 popover）。
3. 快捷键提示由外部 `accel_resolver` 提供（读 Gtk.Application 注册的 accel），
   菜单里看到的就是真正生效的组合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, GObject, Gtk, Pango  # noqa: E402

WIDTH = 340
MAX_LIST_HEIGHT = 470


@dataclass(frozen=True)
class Command:
    """一条可执行命令。target 为字符串参数（如侧栏视图名、文档 id）。"""

    label: str
    action: str
    target: str | None = None
    keywords: str = ""


@dataclass
class CommandSection:
    title: str
    items: list[Command] = field(default_factory=list)


def format_accel(accel: str) -> str:
    """`<Control><Shift>f` → `Ctrl+Shift+F`（只做展示，不影响绑定）。"""
    if not accel:
        return ""
    parts: list[str] = []
    rest = accel
    while rest.startswith("<"):
        end = rest.find(">")
        if end < 0:
            break
        token = rest[1:end]
        rest = rest[end + 1:]
        if token in ("Control", "Primary"):
            parts.append("Ctrl")
        elif token in ("Shift", "Alt", "Super"):
            parts.append(token)
        else:
            parts.append(token)
    if rest:
        parts.append(rest.upper() if len(rest) == 1 else rest)
    return "+".join(parts)


class CommandRow(Gtk.ListBoxRow):
    """一条命令：左侧名称，右侧快捷键。"""

    def __init__(self, command: Command, accel: str) -> None:
        super().__init__()
        self.command = command

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=12,
            margin_end=12,
            margin_top=5,
            margin_bottom=5,
        )
        box.append(
            Gtk.Label(
                label=command.label,
                xalign=0,
                hexpand=True,
                ellipsize=Pango.EllipsizeMode.END,
            )
        )
        if accel:
            box.append(
                Gtk.Label(label=accel, css_classes=["dim-label", "caption"], xalign=1)
            )
        self.set_child(box)


class CommandMenu(Gtk.Popover):
    """搜索式命令菜单。`provider` 返回最新的分组命令列表。"""

    __gsignals__ = {
        "command": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(
        self,
        provider: Callable[[], list[CommandSection]],
        accel_resolver: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(has_arrow=False)
        self._provider = provider
        self._accel_resolver = accel_resolver
        self._building = False

        self.set_size_request(WIDTH, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="搜索命令…")
        # GTK4 里 focusable 默认 False，不显式打开就 grab_focus 不进去
        self.search.set_focusable(True)
        self.search.set_margin_top(8)
        self.search.set_margin_bottom(6)
        self.search.set_margin_start(8)
        self.search.set_margin_end(8)
        self.search.connect("changed", lambda *_: self.rebuild())
        self.search.connect("activate", self._on_entry_activate)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.search.add_controller(key)
        box.append(self.search)

        self.listbox = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(MAX_LIST_HEIGHT)
        scroller.set_child(self.listbox)
        box.append(scroller)

        self.set_child(box)
        self.connect("show", self._on_show)

    # ------------------------------------------------------------------ 展示

    def rebuild(self) -> None:
        """按当前搜索词重建列表（保留搜索框焦点与已选中的同一条命令）。"""
        if self._building:
            return
        self._building = True
        try:
            query = self.search.get_text().strip().lower()
            keep = self._selected_label()
            while (child := self.listbox.get_first_child()) is not None:
                self.listbox.remove(child)

            shown = 0
            select_row: Gtk.ListBoxRow | None = None
            for section in self._provider():
                items = [c for c in section.items if self._matches(c, query)]
                if not items:
                    continue
                header = Gtk.ListBoxRow(selectable=False, activatable=False)
                header.set_child(
                    Gtk.Label(
                        label=section.title,
                        xalign=0,
                        margin_start=12,
                        margin_top=8,
                        margin_bottom=2,
                        css_classes=["dim-label", "caption"],
                    )
                )
                self.listbox.append(header)
                for command in items:
                    row = CommandRow(command, self._resolve_accel(command.action))
                    self.listbox.append(row)
                    shown += 1
                    if keep is not None and command.label == keep:
                        select_row = row

            if shown == 0:
                empty = Gtk.ListBoxRow(selectable=False, activatable=False)
                empty.set_child(
                    Gtk.Label(
                        label=f"没有匹配「{self.search.get_text()}」的命令",
                        xalign=0,
                        wrap=True,
                        margin_start=12,
                        margin_end=12,
                        margin_top=10,
                        margin_bottom=10,
                        css_classes=["dim-label", "caption"],
                    )
                )
                self.listbox.append(empty)

            target = select_row or self._first_row()
            if target is not None:
                self.listbox.select_row(target)
        finally:
            self._building = False

    def _matches(self, command: Command, query: str) -> bool:
        if not query:
            return True
        haystack = f"{command.label} {command.action} {command.keywords}".lower()
        return query in haystack

    def _resolve_accel(self, action: str) -> str:
        if self._accel_resolver is None:
            return ""
        try:
            return self._accel_resolver(action)
        except Exception:  # noqa: BLE001 - 提示信息缺失不应影响菜单
            return ""

    def _first_row(self) -> Gtk.ListBoxRow | None:
        child = self.listbox.get_first_child()
        while child is not None:
            if isinstance(child, CommandRow):
                return child
            child = child.get_next_sibling()
        return None

    def _selected_label(self) -> str | None:
        row = self.listbox.get_selected_row()
        return row.command.label if isinstance(row, CommandRow) else None

    # ------------------------------------------------------------------ 交互

    def _on_row_activated(self, _list, row) -> None:
        if isinstance(row, CommandRow):
            self.emit("command", row.command)
            self.popdown()

    def _on_entry_activate(self, _entry) -> None:
        row = self.listbox.get_selected_row() or self._first_row()
        if isinstance(row, CommandRow):
            self.emit("command", row.command)
            self.popdown()

    def _on_key(self, _ctrl, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.popdown()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            self.listbox.grab_focus()
            row = self._first_row()
            if row is not None:
                self.listbox.select_row(row)
            return True
        return False

    # ------------------------------------------------------------------ 生命周期

    def popup_with_search(self) -> None:
        """供快捷键调用：弹出并把焦点放到搜索框。"""
        self.popup()
        GLib.idle_add(self._focus_search)

    def _on_show(self, _popover) -> None:
        if self.search.get_text():
            # set_text 会触发 changed → rebuild
            self.search.set_text("")
        else:
            self.rebuild()
        GLib.idle_add(self._focus_search)

    def _focus_search(self) -> bool:
        self.search.grab_focus()
        self.search.set_position(-1)
        return False
