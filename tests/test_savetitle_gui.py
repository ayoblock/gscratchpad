"""保存后标签改名 + 头部新建标签按钮 端到端测试。

用法：/usr/bin/python3 tests/test_savetitle_gui.py
输出 JSON（ensure_ascii=False），全部断言为 true 即通过。独立 APP_ID + 临时
XDG_DATA_HOME；走真实动作路径（activate_action / 真实 _write_doc_to_file）。

场景：
1. 头部三个模式按钮右侧存在新建标签按钮，点击后标签数 +1；
2. 新标签保存到磁盘（首次关联，link=True）后，标签名与库内标题同步为文件名 stem；
3. 已关联文件写入（link=False，即 Ctrl+S 路径）不覆盖用户自定义标题。
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

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-savetitle-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")


class SaveTitleTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}
        self.page = None
        self.target = TMP / "我的笔记.md"

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(60000, self.app.quit)
        self.app.run(["savetitle-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, default=str), flush=True)
        self.app.quit()

    def s0_setup(self) -> bool:
        w = self.app.window
        doc = w.store.create_document("md")
        self.page = w.add_tab(replace(doc, content="# 标题\n\n正文\n"))
        w.tabview.set_selected_page(self.page.tab)

        btn = getattr(w, "new_tab_button", None)
        self.out["new_tab_button_exists"] = btn is not None
        # 位置：紧贴三态模式按钮组右侧（前一个兄弟必须是 mode_box）
        self.out["new_tab_button_after_mode_box"] = (
            btn is not None and btn.get_prev_sibling() is w.mode_box
        )
        before = w.tabview.get_n_pages()
        if btn is not None:
            btn.emit("clicked")
        self.out["new_tab_button_adds_tab"] = w.tabview.get_n_pages() == before + 1
        w.tabview.set_selected_page(self.page.tab)
        self.s1_save_renames()
        return False

    def s1_save_renames(self) -> bool:
        """首次保存到磁盘（link=True）→ 标签名/库内标题同步为文件名 stem。"""
        w = self.app.window
        page = self.page
        self.out["title_before_save"] = page.title
        w._write_doc_to_file(page, self.target, link=True)
        self.out["file_written"] = self.target.exists()
        self.out["tab_title_after_save"] = page.tab.get_title()
        self.out["page_title_after_save"] = page.title
        doc = w.store.get(page.doc_id)
        self.out["store_title_after_save"] = doc.title if doc else None
        self.out["title_synced_to_stem"] = (
            page.tab.get_title() == "我的笔记" and page.title == "我的笔记" and doc is not None
            and doc.title == "我的笔记"
        )
        self.out["source_path_linked"] = w.store.source_path_of(page.doc_id) == str(
            self.target.resolve()
        )
        self.out["tooltip_has_path"] = str(self.target.resolve()) in (
            page.tab.get_tooltip() or ""
        )
        self.s2_no_overwrite_custom_title()
        return False

    def s2_no_overwrite_custom_title(self) -> bool:
        """已关联文件再写入（link=False，Ctrl+S 路径）不覆盖用户自定义标题。"""
        w = self.app.window
        page = self.page
        w.store.rename(page.doc_id, "自定义标题", wait=True)
        page.title = "自定义标题"
        page.tab.set_title("自定义标题")
        page.buffer.set_text("# 标题\n\n正文已改\n")
        w._write_doc_to_file(page, self.target, link=False)
        self.out["tab_title_after_plain_save"] = page.tab.get_title()
        self.out["custom_title_kept"] = page.tab.get_title() == "自定义标题"
        self.out["file_content_updated"] = "正文已改" in self.target.read_text(encoding="utf-8")
        self.finish()
        return False


if __name__ == "__main__":
    SaveTitleTest().run()
