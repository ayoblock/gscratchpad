"""应用入口与快捷键绑定。"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import paths  # noqa: E402
from .capture import CaptureError, capture_document, run_capture_cli  # noqa: E402
from .keymap import ACCELS  # noqa: E402
from .store import Store  # noqa: E402
from .window import ScratchpadWindow  # noqa: E402

_APP_CSS = """
.scratchpad-editor {
  font-family: "Source Code Pro", "JetBrains Mono", "DejaVu Sans Mono", monospace;
  font-size: 11pt;
}
.scratchpad-tabbar { padding: 0 4px; }
tabbox > .tab-close-button { margin: 0; }
window {
  background: @window_bg_color;
}

/* 悬浮侧边栏：圆角卡片 + 阴影，浮在正文之上，开关时不改变编辑区宽度 */
.sidebar-float {
  background: @sidebar_bg_color;
  border: 1px solid alpha(@window_fg_color, 0.12);
  border-radius: 16px;
  box-shadow: 0 6px 20px alpha(black, 0.20), 0 1px 3px alpha(black, 0.14);
}
.gscratchpad-sidebar {
  padding: 4px 2px 2px 2px;
}
.sidebar-float list.navigation-sidebar {
  background: transparent;
}
/* 磁盘树：普通 Box 里的行（不用 ListBox，见 sidebar.py 里的说明） */
.disk-tree {
  padding: 2px 4px;
}
.disk-row {
  min-height: 26px;
  padding: 0 2px;
  border-radius: 8px;
}
.disk-row:hover {
  background: alpha(@window_fg_color, 0.07);
}
.disk-row-current {
  background: alpha(@accent_bg_color, 0.24);
}
/* 目录搜索结果：同样是普通 Box 行（双击打开、右键菜单） */
.hit-results {
  padding: 2px 4px 8px 4px;
}
.hit-row {
  min-height: 26px;
  padding: 1px 6px;
  border-radius: 8px;
}
.hit-row:hover {
  background: alpha(@window_fg_color, 0.07);
}
.hit-row-current {
  background: alpha(@accent_bg_color, 0.24);
}
.hit-file-head {
  min-height: 28px;
}
"""

ACCELS = ACCELS  # 兼容旧引用；真正的表在 keymap.py（避免与 window.py 循环导入）


class ScratchpadApp(Adw.Application):
    def __init__(self) -> None:
        # HANDLES_OPEN：让文件管理器（Nautilus 双击 / 右键打开方式）与我们自己的
        # 命令行都能把文件交给应用。没有这个 flag，GApplication 会直接丢弃文件参数
        # （只打一行 "This application can not open files."，桌面启动时看不见）。
        # HANDLES_COMMAND_LINE：外部 CLI 捕获（capture v1）经 org.freedesktop.
        # Application.CommandLine 转发到主实例、带真实退出码（见 capture.py）。
        # 两者叠加时文件参数由 do_command_line 自行分派（get_files → open）。
        super().__init__(
            application_id=paths.APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN
            | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.store: Store | None = None
        self.window: ScratchpadWindow | None = None

        for name in (
            "capture-title",
            "capture-book",
            "capture-page",
            "capture-key",
            "capture-mode",
            "capture-text",
        ):
            self.add_main_option(
                name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "", ""
            )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(_APP_CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

    def _ensure_store(self) -> Store:
        """建库（幂等）。捕获通道不开窗也要落库，所以与 _ensure_window 解耦。"""
        if self.store is None:
            self.store = Store()
            recovery_notes = self.store.open()
            for note in recovery_notes:
                print(note, file=sys.stderr)
        return self.store

    def _ensure_window(self) -> ScratchpadWindow:
        """建好主窗口（幂等）。首次启动带文件时 do_open 先于 do_activate，
        那时窗口还不存在——所以建窗口的逻辑必须能被两边复用。"""
        if self.window is not None:
            return self.window

        self._ensure_store()

        self.window = ScratchpadWindow(self, self.store)
        self.window.restore_session()
        return self.window

    def do_activate(self) -> None:
        window = self._ensure_window()
        window.ensure_placeholder_tab()
        window.present()

    def do_open(self, files, n_files: int, _hint: str) -> None:
        """处理命令行 / 文件管理器传来的文件（HANDLES_OPEN）。

        - 首次启动：GApplication 只 emit "open"、不会 emit "activate"，
          所以这里要自己把窗口建出来
        - 已运行时：主实例收到本信号，开成新标签并前置窗口
        - %U 传进来的是 URI 形式，GFile 会自动解析成本地路径
        """
        local_paths: list[str] = []
        remote_uris: list[str] = []
        for gfile in files or []:
            path = gfile.get_path()
            if path:
                local_paths.append(path)
            elif gfile.get_uri():
                remote_uris.append(gfile.get_uri())

        window = self._ensure_window()
        window.present()
        if local_paths:
            window.open_file_paths(local_paths)
        for uri in remote_uris:
            # 只支持本地文件：open_file_paths 走的是 Path 语义
            print(f"gscratchpad: 跳过非本地文件 {uri}", file=sys.stderr)
            window.toast_overlay.add_toast(
                Adw.Toast(title=f"只能打开本机文件：{uri}", timeout=5)
            )
        # 文件全都打不开（路径无效 / 非本地）时，别留下一个空窗口
        window.ensure_placeholder_tab()

    def do_shutdown(self) -> None:
        if self.store is not None:
            try:
                self.store.flush()
                self.store.close()
            except Exception:  # noqa: BLE001
                pass
        Adw.Application.do_shutdown(self)

    # ---------------------------------------------------------- 捕获接口（capture v1）

    def do_command_line(self, command_line) -> int:  # noqa: ANN001
        """命令行入口。

        - 带 --capture-* / "-"：转发通道的捕获（run_capture_cli 自身不再转发）
        - 否则维持既有行为：文件参数走 open（do_open），无参则激活窗口

        注意：本机 PyGObject 未绑定 GApplicationCommandLine.get_files，
        文件参数从 get_arguments 自行计算（跳过选项与 "-"）。
        """
        args = list(command_line.get_arguments())
        if any(a == "-" or a.startswith("--capture-") for a in args[1:]):
            code = run_capture_cli(
                args[1:],
                allow_forward=False,
                stderr=sys.stderr,
                store_factory=self._ensure_store,
                close_store=False,
            )
            command_line.set_exit_status(code)
            return code

        files = [
            Gio.File.new_for_commandline_arg(a)
            for a in args[1:]
            if not a.startswith("-")
        ]
        if files:
            # HANDLES_COMMAND_LINE 下文件分派归本方法，仍走 do_open 语义
            self.do_open(files, len(files), "")
        else:
            self.activate()
        return 0

    def _on_capture_action(self, _action, parameter) -> None:  # noqa: ANN001
        """app.capture action：(ssssss) text,title,book,page,key,mode。"""
        try:
            text, title, book, page, key, mode = parameter.unpack()
        except (GLib.Error, TypeError, ValueError) as exc:
            print(f"gscratchpad: capture 参数无效：{exc}", file=sys.stderr)
            return
        try:
            self._ensure_store()
            doc_id, doc_title, created = capture_document(
                self.store,
                text=text,
                title=title,
                book=book,
                page=page,
                key=key,
                mode=mode,
            )
        except CaptureError as exc:
            # action 无返回值通道：失败只能 toast（窗口存在时）+ stderr
            if self.window is not None:
                self.window.toast_overlay.add_toast(
                    Adw.Toast(title=f"捕获失败：{exc}", timeout=6)
                )
            print(f"gscratchpad: capture 失败（exit {exc.code}）：{exc}", file=sys.stderr)
            return
        if self.window is not None:
            self.window.on_captured(doc_id, doc_title, created)

    def _register_app_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *_: self._show_about())
        self.add_action(about)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        capture_action = Gio.SimpleAction.new(
            "capture", GLib.VariantType.new("(ssssss)")
        )
        capture_action.connect("activate", self._on_capture_action)
        self.add_action(capture_action)

    def _show_about(self) -> None:
        dialog = Adw.AboutDialog(
            application_name="Gscratchpad",
            application_icon=paths.APP_ID,
            developer_name="Gscratchpad contributors",
            version=paths.APP_VERSION,
            website="https://example.invalid/gscratchpad",
            issue_url="https://example.invalid/gscratchpad/issues",
            copyright="© 2026 Gscratchpad contributors",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.add_acknowledgement_section("技术栈", ["GTK4", "libadwaita", "GtkSourceView 5", "WebKitGTK 6.0", "SQLite"])
        # 便于确认「当前运行的到底是哪份代码」——排查快捷键等问题时很有用
        dialog.add_acknowledgement_section("运行位置", [str(Path(__file__).resolve().parent)])
        dialog.present(self.window)


def main() -> int:
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"gscratchpad {paths.APP_VERSION}（{Path(__file__).resolve().parent}）")
        return 0
    # CLI 捕获在进入 GApplication 之前拦截：未运行时本地直落（不建窗不常驻），
    # 已运行时经 org.freedesktop.Application.CommandLine 转发并带回真实退出码。
    if any(a == "-" or a.startswith("--capture-") for a in sys.argv[1:]):
        return run_capture_cli(sys.argv[1:])
    app = ScratchpadApp()
    app._register_app_actions()
    return app.run(sys.argv or ["gscratchpad"])


if __name__ == "__main__":
    sys.exit(main())
