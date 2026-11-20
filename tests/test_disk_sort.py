"""磁盘视图：排序 + 点击/右键打开文件的界面测试。

覆盖：
- 四种排序（名称 A→Z / Z→A / 最近修改 / 按类型），文件夹始终在文件之前
- 排序选择持久化到 meta `disk_sort`
- 改排序重建树后，原先展开的目录仍然展开
- 左键单击即打开文件（含双击第二击不把光标拽回顶部）
- 右键只弹菜单、不打开文件
- 菜单里的「复制路径」真的写进剪贴板
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(ROOT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.sidebar import DiskDirRow, DiskFileRow  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="disk-sort-"))
HOME = TMP / "home"
DATA = TMP / "data"


def rows_of(listbox) -> list:
    child = listbox.get_first_child()
    out = []
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def names_of(listbox) -> list[str]:
    out = []
    for row in rows_of(listbox):
        if isinstance(row, (DiskFileRow, DiskDirRow)):
            out.append(row.path.name)
    return out


def fake_gesture(button: int):
    return SimpleNamespace(
        get_current_button=lambda: button,
        set_state=lambda _state: None,
    )


class DiskTest:
    def __init__(self) -> None:
        (HOME / "alpha_dir").mkdir(parents=True)
        (HOME / "zeta_dir").mkdir(parents=True)
        (HOME / "alpha_dir" / "inner.md").write_text("# inner\n", encoding="utf-8")
        now = time.time()
        for name, age in (("A.txt", 3000), ("b.md", 10), ("c.json", 1500)):
            path = HOME / name
            path.write_text("content\n", encoding="utf-8")
            os.utime(path, (now - age, now - age))
        os.environ["XDG_DATA_HOME"] = str(DATA)
        os.environ["HOME"] = str(HOME)
        DATA.mkdir(parents=True)
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.timeout_add(900, self.step1)
        GLib.timeout_add(25000, self.app.quit)
        self.app.run(["disk-test"])

    def step1(self) -> bool:
        w = self.app.window
        if w is None:
            return True
        sb = w.sidebar
        w.sidebar_button.set_active(True)
        sb.show_view("disk")
        sb._ensure_disk_root()

        self.out["default_sort"] = sb._disk_sort
        self.out["name_asc"] = names_of(sb.disk_list)

        sb.set_disk_sort("name_desc")
        self.out["name_desc"] = names_of(sb.disk_list)

        sb.set_disk_sort("mtime_desc")
        files = [n for n in names_of(sb.disk_list) if not n.endswith("_dir")]
        self.out["mtime_files"] = files
        self.out["mtime_dirs_first"] = names_of(sb.disk_list)[:2] == ["zeta_dir", "alpha_dir"] or names_of(sb.disk_list)[:2] == ["alpha_dir", "zeta_dir"]

        sb.set_disk_sort("type_asc")
        self.out["type_files"] = [n for n in names_of(sb.disk_list) if not n.endswith("_dir")]

        self.out["meta_sort"] = w.store.get_meta("disk_sort")

        # 展开子目录后改排序：展开状态要保留
        sb.set_disk_sort("name_asc")
        alpha = next(r for r in rows_of(sb.disk_list) if isinstance(r, DiskDirRow) and r.path.name == "alpha_dir")
        alpha.set_expanded(True)
        self.out["expanded_before"] = alpha.get_expanded()
        sb.set_disk_sort("name_desc")
        alpha2 = sb._dir_rows.get(str(HOME / "alpha_dir"))
        self.out["expanded_after"] = bool(alpha2 and alpha2.get_expanded())
        self.out["child_visible"] = bool(
            alpha2 and [r for r in rows_of(alpha2.children_list) if isinstance(r, DiskFileRow)]
        )

        # 左键单击打开文件
        sb.set_disk_sort("name_asc")
        sb._ensure_disk_root()
        bmd = next(r for r in rows_of(sb.disk_list) if isinstance(r, DiskFileRow) and r.path.name == "b.md")
        pages_before = w.tabview.get_n_pages()
        bmd.emit("clicked")
        self.out["click_opened"] = w.tabview.get_n_pages() == pages_before + 1
        self.out["click_content"] = "content" in (w._current_page().snapshot_text() if w._current_page() else "")

        # 双击第二击（同一行 0.4s 内）应被去重，不新增标签
        bmd.emit("clicked")  # 双击的第二击
        self.out["double_click_dedup"] = w.tabview.get_n_pages() == pages_before + 1

        # 右键：只弹菜单，不打开
        cjson = next(r for r in rows_of(sb.disk_list) if isinstance(r, DiskFileRow) and r.path.name == "c.json")
        pages_now = w.tabview.get_n_pages()
        cjson._on_right_click(fake_gesture(3), 1, 0, 0)
        self.out["right_click_no_open"] = w.tabview.get_n_pages() == pages_now
        popover = getattr(sb, "_active_path_menu", None)
        self.out["menu_visible"] = bool(popover and popover.get_visible())

        # 菜单项文案
        labels: list[str] = []
        if popover is not None:
            box = popover.get_child()
            child = box.get_first_child() if box else None
            while child is not None:
                if isinstance(child, Gtk.Button):
                    labels.append(child.get_label())
                child = child.get_next_sibling()
        self.out["menu_labels"] = labels

        # 复制路径
        sb._copy_to_clipboard(str(cjson.path))
        clip = self.app.get_active_window()
        display = clip.get_display() if clip else None
        if display is not None:
            display.get_clipboard().read_text_async(None, self._on_clip, str(cjson.path))
        else:
            self.finish()
        return False

    def _on_clip(self, clipboard, result, expected) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error as exc:
            text = f"err: {exc.message}"
        self.out["clipboard_ok"] = text == expected
        self.finish()

    def finish(self) -> None:
        for key, value in self.out.items():
            print(f"{key}={value!r}")
        self.app.quit()


if __name__ == "__main__":
    DiskTest().run()
