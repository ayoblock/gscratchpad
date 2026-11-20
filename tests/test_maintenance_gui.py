"""侧栏自动隐藏 / Esc 关闭 / 批量清除 / 维护 的界面层测试。

运行：GI_TYPELIB_PATH=vendor/gir/local:/usr/lib/x86_64-linux-gnu/girepository-1.0 \
      /usr/bin/python3 tests/test_maintenance_gui.py

输出 JSON（ensure_ascii=False），值须全为 True。使用临时 HOME 与数据目录。
"""

from __future__ import annotations

import json
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
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gdk, Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="maint-gui-"))
HOME = TMP / "home"
DATA = TMP / "data"


class MaintenanceGuiTest:
    def __init__(self) -> None:
        HOME.mkdir(parents=True)
        DATA.mkdir(parents=True)
        os.environ["XDG_DATA_HOME"] = str(DATA)
        os.environ["HOME"] = str(HOME)
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.idle_add(self.s0_autohide)
        GLib.timeout_add(40000, self.app.quit)
        self.app.run(["maint-gui-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False), flush=True)
        self.app.quit()

    # ---- 步骤 ----

    def s0_autohide(self) -> None:
        w = self.app.window
        sb = w.sidebar

        a = w.new_tab("md")
        a.title = "笔记甲"
        w.store.rename(a.doc_id, "笔记甲")
        a.buffer.set_text("# 甲\n", -1)
        w._refresh_sidebar_now()
        self._doc_a = a.doc_id

        w.store.set_meta("sidebar_autohide", "1", wait=True)
        w.sidebar_button.set_active(True)
        self.out["sidebar_open_before"] = w.sidebar_visible()

        row = self._row_for(sb, "笔记甲")
        sb.notes_list.emit("row-activated", row)
        self.out["hidden_after_pick"] = not w.sidebar_visible()
        # 自动隐藏不得把「隐藏」写成用户偏好（否则下次启动侧栏是关的）
        self.out["pref_kept"] = w.store.get_meta("sidebar_visible", "1") == "1"
        GLib.idle_add(self.s1_autohide_off)

    def s1_autohide_off(self) -> None:
        w = self.app.window
        sb = w.sidebar
        w.store.set_meta("sidebar_autohide", "0", wait=True)
        w.sidebar_button.set_active(True)
        row = self._row_for(sb, "笔记甲")
        sb.notes_list.emit("row-activated", row)
        self.out["stays_open_when_off"] = w.sidebar_visible()
        w.store.set_meta("sidebar_autohide", "1", wait=True)
        GLib.idle_add(self.s2_escape)

    def s2_escape(self) -> None:
        w = self.app.window
        page = w._current_page()
        w.sidebar_button.set_active(True)
        handled = w._on_window_key(None, Gdk.KEY_Escape, 0, 0)
        self.out["esc_closes_sidebar"] = handled and not w.sidebar_visible()

        # 查找栏打开时 Esc 归 SearchBar，不得抢走
        w.sidebar_button.set_active(True)
        page.show_search(False)
        passed = w._on_window_key(None, Gdk.KEY_Escape, 0, 0)
        self.out["esc_passed_to_search"] = passed is False and w.sidebar_visible()
        page.hide_search()
        w.hide_sidebar()
        GLib.idle_add(self.s3_toggle_action)

    def s3_toggle_action(self) -> None:
        w = self.app.window
        w.activate_action("win.toggle-sidebar-autohide", None)
        self.out["toggle_off"] = w.store.get_meta("sidebar_autohide") == "0"
        w.activate_action("win.toggle-sidebar-autohide", None)
        self.out["toggle_on"] = w.store.get_meta("sidebar_autohide") == "1"
        GLib.idle_add(self.s4_purge)

    def s4_purge(self) -> None:
        w = self.app.window
        page = w.new_tab("md")
        page.title = "已关闭的"
        w.store.rename(page.doc_id, "已关闭的")
        page.buffer.set_text("# 会被清除\n", -1)
        w._save_page(page, wait=True)
        closed_id = page.doc_id
        w.store.set_state(closed_id, "closed")
        w.tabview.close_page(page.tab)
        assets_dir = DATA / "gscratchpad" / "assets" / closed_id
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "a.png").write_bytes(b"x" * 1024)
        self._closed_id = closed_id

        self.out["closed_listed"] = any(
            d.id == closed_id for d in w.store.closed_documents()
        )
        # 直接走确认后的处理路径（对话框本身是独立 surface，不在本测试里模拟点击）
        w._on_purge_closed(None, "purge")

        self.out["closed_gone"] = w.store.get(closed_id) is None
        self.out["closed_assets_gone"] = not assets_dir.exists()
        self.out["open_doc_kept"] = w.store.get(self._doc_a) is not None
        GLib.idle_add(self.s5_maintenance)

    def s5_maintenance(self) -> None:
        w = self.app.window
        notes = DATA / "gscratchpad" / "notes"
        orphan = notes / "deadbeefdeadbeefdeadbeefdeadbeef.md"
        orphan.write_text("孤儿", encoding="utf-8")
        orphan_assets = DATA / "gscratchpad" / "assets" / "deadbeefdeadbeefdeadbeefdeadbeef"
        orphan_assets.mkdir(parents=True, exist_ok=True)
        (orphan_assets / "p.png").write_bytes(b"p" * 2048)

        live_mirror = notes / f"{self._doc_a}.md"
        self.out["live_mirror_before"] = live_mirror.is_file()

        w._on_maintenance_confirmed(None, "run")

        self.out["orphan_removed"] = not orphan.exists()
        self.out["orphan_assets_removed"] = not orphan_assets.exists()
        self.out["live_mirror_kept"] = live_mirror.is_file()
        GLib.idle_add(self.s6_menu)

    def s6_menu(self) -> None:
        w = self.app.window
        labels = [
            cmd.label
            for section in w._menu_sections()
            for cmd in section.items
        ]
        self.out["menu_purge"] = any("清除已关闭的笔记" in text for text in labels)
        self.out["menu_maintenance"] = any("清理孤儿文件" in text for text in labels)
        self.out["menu_autohide"] = any("自动隐藏" in text for text in labels)
        self.finish()

    # ---- 工具 ----

    @staticmethod
    def _row_for(sidebar, title: str):
        child = sidebar.notes_list.get_first_child()
        while child is not None:
            doc = getattr(child, "doc", None)
            if doc is not None and doc.title == title:
                return child
            child = child.get_next_sibling()
        raise AssertionError(f"侧栏未找到笔记行：{title}")


if __name__ == "__main__":
    MaintenanceGuiTest().run()
