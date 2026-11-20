"""v1.4.3 新特性端到端测试：主题切换 / 快捷键对话框 / 光标进度 / 图片相对引用。

用法：/usr/bin/python3 tests/test_features_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。使用临时 XDG_DATA_HOME。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import replace
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

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from scratchpad import assets  # noqa: E402
from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.editor import EditorPage  # noqa: E402
from scratchpad.window import SHORTCUTS  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-features-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")
DOCS = TMP / "docs"
(DOCS / "sub").mkdir(parents=True, exist_ok=True)
PNG = DOCS / "024907.png"
PNG.write_bytes(b"\x89PNG\r\n\x1a\n")
PNG2 = DOCS / "sub" / "图 1 (2).png"
PNG2.write_bytes(b"\x89PNG\r\n\x1a\n")
TEXT40 = "\n".join(f"line {i}" for i in range(1, 41)) + "\n"


class FeaturesTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.idle_add(self.s0_theme)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["features-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    # ------------------------------------------------------------------ 主题

    def s0_theme(self) -> bool:
        w = self.app.window
        style = Adw.StyleManager.get_default()
        # 先固定到日间，保证断言与系统主题无关
        w._apply_color_scheme("light", persist=True)
        self.out["start_light"] = not style.get_dark()
        self.out["icon_light"] = w.theme_button.get_icon_name() == "weather-clear-night-symbolic"
        w.toggle_theme()
        self.out["toggle_to_dark"] = style.get_dark()
        self.out["meta_dark"] = w.store.get_meta("color_scheme") == "dark"
        self.out["icon_dark"] = w.theme_button.get_icon_name() == "display-brightness-symbolic"
        w.toggle_theme()
        self.out["toggle_back_light"] = not style.get_dark()
        self.out["meta_light"] = w.store.get_meta("color_scheme") == "light"
        self.s1_shortcuts()
        return False

    # ------------------------------------------------------------------ 快捷键

    def s1_shortcuts(self) -> None:
        w = self.app.window
        w.activate_action("win.shortcuts", None)
        dialog = getattr(w, "_shortcuts_dialog", None)
        self.out["shortcuts_dialog"] = isinstance(dialog, Adw.ShortcutsDialog)
        self.out["shortcuts_alive"] = w.get_visible()
        self.out["shortcuts_sections"] = len(SHORTCUTS)
        # 每个加速键都必须能被 GTK 解析：非法字符串在真实对话框里会显示异常
        bad = []
        for _name, items in SHORTCUTS:
            for accel, _title in items:
                if accel:
                    ok, _k, _m = Gtk.accelerator_parse(accel)
                    if not ok:
                        bad.append(accel)
        self.out["shortcut_accels_ok"] = not bad
        self.out["bad_accels"] = bad
        # 矩形列选已按用户指令整体移除：动作、文案、page 侧入口都不许残留，
        # 否则残留的指针控制器会再次劫持 Shift+点击扩展选区等原生行为。
        self.out["no_rect_action"] = all(
            w.lookup_action(n) is None
            for n in ("rect-copy", "rect-cut", "rect-delete")
        )
        self.out["no_rect_shortcut_text"] = not any(
            "矩形" in title for _name, items in SHORTCUTS for _a, title in items
        )
        page = w._current_page()
        self.out["no_rect_page_api"] = page is not None and not any(
            hasattr(page, n)
            for n in ("rect_copy", "rect_delete", "has_rect_selection",
                      "rect_select_by_columns", "_on_rect_press", "_alt_down")
        )
        self.out["shortcut_items"] = sum(len(items) for _n, items in SHORTCUTS)
        if dialog:
            dialog.close()
        self.s2_cursor()
        return None

    # ------------------------------------------------------------------ 光标进度

    def s2_cursor(self) -> None:
        w = self.app.window
        doc = w.store.create_document("txt")
        w.store.set_meta(w._cursor_key(doc.id), "25:3", wait=True)
        page = w.add_tab(replace(doc, content=TEXT40))
        line, column = page.cursor_position()
        self.out["cursor_restored"] = (line, column) == (25, 3)

        # 越界行号自动收敛，不抛异常
        page.place_cursor_at(99999, 999, scroll=False)
        line, column = page.cursor_position()
        self.out["cursor_clamped"] = line == page.buffer.get_line_count()

        # 保存侧：编辑后记录当前行
        page.buffer.set_text(TEXT40)
        page.place_cursor_at(31, 2, scroll=False)
        w._save_cursor(page)
        self.out["cursor_saved"] = w.store.get_meta(w._cursor_key(doc.id)) == "31:2"

        # 切换标签时自动保存上一个标签的光标
        other = w.new_tab("txt")
        page.place_cursor_at(12, 0, scroll=False)
        w.tabview.set_selected_page(page.tab)
        w.tabview.set_selected_page(other.tab)
        self.out["cursor_saved_on_switch"] = w.store.get_meta(w._cursor_key(doc.id)) == "12:0"
        self.s3_images()
        return None

    # ------------------------------------------------------------------ 图片

    def s3_images(self) -> None:
        w = self.app.window
        doc = w.store.create_document("md")
        (DOCS / "sub" / "a.md").write_text("# a\n", encoding="utf-8")
        w.store.set_source_path(doc.id, str(DOCS / "sub" / "a.md"))
        page = w.add_tab(w.store.get(doc.id))
        page.set_language_for_path(str(DOCS / "sub" / "a.md"))
        page.set_base_uri(str(DOCS / "sub" / "a.md"))
        w.tabview.set_selected_page(page.tab)

        # 拖放入口与「插入图片」走同一函数
        w.handle_dropped_files([str(PNG)])
        text = page.snapshot_text()
        self.out["img_relative"] = "![](../024907.png)" in text
        self.out["img_not_copied"] = not (TMP / "data" / "gscratchpad" / "assets" / doc.id).exists()

        # 文件名含空格与括号：URL 编码后才能被解析
        page.buffer.set_text("")
        page.buffer.place_cursor(page.buffer.get_start_iter())
        w.import_images([str(PNG2)])
        self.out["img_encoded"] = "![](图%201%20%282%29.png)" in page.snapshot_text()

        # 未关联本机文件：退回应用资源目录
        loose = w.new_tab("md")
        w.tabview.set_selected_page(loose.tab)
        w.import_images([str(PNG)])
        loose_text = loose.snapshot_text()
        self.out["img_asset_fallback"] = "assets/" in loose_text and loose_text.startswith("![](")
        self.out["relative_helper"] = assets.relative_image_ref(
            DOCS / "sub" / "a.md", PNG
        )[0] == "../024907.png"
        self.finish()
        return None


def Gtk_accelerator_parse(accel: str):
    return Gtk.accelerator_parse(accel)


if __name__ == "__main__":
    FeaturesTest().run()
