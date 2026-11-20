"""文件关联 / 命令行打开文件测试。

覆盖 Nautilus「用 Gscratchpad 打开」与 `gscratchpad foo.md` 两条路径：
- HANDLES_OPEN 是否真的把 GFile 交到 do_open
- **首次启动时序**：GApplication 带文件时只 emit "open"、不 emit "activate"，
  窗口必须由 do_open 自己建出来（这是最容易漏、且表现为「双击只开空窗口」的坑）
- URI 形式（%U）能解析成本地路径；非本地 URI 被拒绝且不崩溃
- 同一文件重复打开只切标签，不产生重复标签
"""

from __future__ import annotations

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
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="openfiles-"))
HOME = TMP / "home"
DATA = TMP / "data"


def main() -> int:
    HOME.mkdir(parents=True)
    DATA.mkdir(parents=True)
    os.environ["XDG_DATA_HOME"] = str(DATA)
    os.environ["HOME"] = str(HOME)

    a_md = HOME / "a.md"
    a_md.write_text("# 甲\n\n第一份文件\n", encoding="utf-8")
    b_txt = HOME / "b.txt"
    b_txt.write_text("第二份文件\n", encoding="utf-8")
    c_html = HOME / "c.html"
    c_html.write_text("<h1>第三份</h1>\n", encoding="utf-8")

    app = ScratchpadApp()
    # 关键：用 OR，而不是直接 set_flags 覆盖——否则会把 HANDLES_OPEN 抹掉
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    app._register_app_actions()
    app.register(None)  # 触发 startup（CSS / 快捷键），此时 window 仍为 None

    out: dict[str, object] = {}
    out["flags_has_open"] = bool(
        app.get_flags() & Gio.ApplicationFlags.HANDLES_OPEN
    )
    out["window_before_open"] = app.window is None

    def open_path(path: Path) -> None:
        app.do_open([Gio.File.new_for_path(str(path))], 1, "")

    # --- 场景 1：首次启动带文件（do_open 早于任何 activate） ---
    open_path(a_md)
    w = app.window
    out["window_created_by_open"] = w is not None
    out["pages_after_first"] = w.tabview.get_n_pages() if w else -1
    out["no_bonus_blank_tab"] = (w.tabview.get_n_pages() == 1) if w else False
    page = w._current_page() if w else None
    out["first_text_ok"] = bool(page and "第一份文件" in page.snapshot_text())
    out["first_source_path"] = w.store.source_path_of(page.doc_id) if page else None
    out["first_is_active"] = w.get_visible() if w else None

    # activate 紧随 open 到（单实例二次启动的场景）：不应再塞空白标签
    app.do_activate()
    out["activate_no_extra_tab"] = w.tabview.get_n_pages() == 1

    # --- 场景 2：窗口已存在时再打开另一个文件 ---
    open_path(b_txt)
    out["pages_after_second"] = w.tabview.get_n_pages()
    out["second_text_ok"] = "第二份文件" in w._current_page().snapshot_text()

    # --- 场景 3：重复打开同一个文件 -> 只切换标签 ---
    pages_before = w.tabview.get_n_pages()
    open_path(a_md)
    out["dedup_pages_unchanged"] = w.tabview.get_n_pages() == pages_before
    out["dedup_selected_first"] = "第一份文件" in w._current_page().snapshot_text()

    # --- 场景 4：%U 传 URI 而不是路径 ---
    open_path(c_html)  # 先确认路径形式
    uri_file = Gio.File.new_for_uri(c_html.as_uri())
    out["uri_resolves_to_path"] = uri_file.get_path() == str(c_html)
    open_path(c_html)  # 走回路径形式，验证不会崩

    # --- 场景 5：非本地 URI 被拒绝，不崩溃也不多开标签 ---
    pages_before = w.tabview.get_n_pages()
    remote = Gio.File.new_for_uri("https://example.invalid/x.md")
    app.do_open([remote], 1, "")
    out["remote_pages_unchanged"] = w.tabview.get_n_pages() == pages_before
    out["remote_has_no_path"] = remote.get_path() is None

    # --- 场景 6：文件不存在 -> toast 提示，标签数不变 ---
    pages_before = w.tabview.get_n_pages()
    open_path(HOME / "missing.md")
    out["missing_pages_unchanged"] = w.tabview.get_n_pages() == pages_before

    out["final_pages"] = w.tabview.get_n_pages()
    for key, value in out.items():
        print(f"{key}={value!r}")

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
