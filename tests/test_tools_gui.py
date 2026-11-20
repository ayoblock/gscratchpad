"""工具类功能端到端测试：行号 / 折叠 / HTML 渲染 / 格式化 / 简繁降级。

用法：/usr/bin/python3 tests/test_tools_gui.py
输出 JSON（ensure_ascii=False），全部通过时每个断言键为 true。
使用临时 XDG_DATA_HOME，不触碰真实数据目录。
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

_local_gir = str(PROJECT / "vendor" / "gir" / "local")
_system_gir = "/usr/lib/x86_64-linux-gnu/girepository-1.0"
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join([_local_gir, _system_gir])

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

import shutil  # noqa: E402

from gi.repository import Adw, Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

TMP = tempfile.mkdtemp(prefix="gscratchpad-tools-test-")
os.environ["XDG_DATA_HOME"] = TMP

MD_SRC = "# H1\n\npara1\n\n## H2\n\npara2\n\n# Tail\n"
JSON_SRC = '{"b":1,"a":[1,2]}'


class ToolsTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        # 用户可能正开着 gscratchpad：单实例会让测试进程直接退出（window 恒为 None）
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict = {}
        self.step = 0

    # ------------------------------------------------------------------ 步骤

    def s0_line_numbers_and_folding(self) -> None:
        self.app.do_activate()
        w = self.app.window
        page = w.new_tab()
        self.out["line_numbers"] = page.view.get_show_line_numbers()
        page.buffer.set_text(MD_SRC)
        page._folding.set_language("markdown")
        # 可折叠：# H1（行0）、## H2（行4）；# Tail 后无内容
        self.out["md_foldable"] = sorted(page._folding._foldable) == [0, 4]
        page._folding.fold_at(0)
        self.out["fold_hides_lines"] = page.buffer.get_line_count() < MD_SRC.count("\n") + 1
        self.out["snapshot_always_full"] = page.snapshot_text() == MD_SRC
        page._folding.unfold_all()
        self.out["unfold_restores"] = page.buffer.get_text(
            page.buffer.get_start_iter(), page.buffer.get_end_iter(), True
        ) == MD_SRC

    def s1_html_preview(self) -> None:
        w = self.app.window
        page = w._current_page()
        w.activate_action("win.set-format", GLib.Variant.new_string("html"))
        self.out["fmt_switched"] = page.format == "html"
        page.buffer.set_text("<h1>你好 HTML</h1><p>段落</p>")
        w.activate_action("win.view-mode", GLib.Variant.new_string("preview"))

    def s2_check_html_dom(self) -> bool:
        page = self.app.window._current_page()
        view = page.preview._view
        self._dom_tries = 0

        def done(v, result, _d):
            try:
                val = v.evaluate_javascript_finish(result)
                text = val.to_string() if val else ""
            except GLib.Error:
                text = ""
            if text == "你好 HTML":
                self.out["html_rendered"] = True
                GLib.timeout_add(100, self.next)
                return False
            self._dom_tries += 1
            if self._dom_tries < 8:  # load_html 异步，未就绪则重试
                view.evaluate_javascript(
                    "document.body.querySelector('h1') ? "
                    "document.body.querySelector('h1').textContent : 'NO-H1'",
                    -1, None, None, None, done, None,
                )
                return False
            self.out["html_rendered"] = f"got: {text!r}"
            GLib.timeout_add(100, self.next)
            return False

        view.evaluate_javascript(
            "document.body.querySelector('h1') ? "
            "document.body.querySelector('h1').textContent : 'NO-H1'",
            -1, None, None, None, done, None,
        )
        return True  # 自行调度后续步骤

    def s3_format_json(self) -> None:
        w = self.app.window
        page = w._current_page()
        w.activate_action("win.view-mode", GLib.Variant.new_string("source"))
        page.buffer.set_text(JSON_SRC)
        w.activate_action("win.format-doc", None)

    def s4_check_formatted_and_s2t(self) -> None:
        w = self.app.window
        page = w._current_page()
        text = page.snapshot_text()
        self.out["json_formatted"] = '"b": 1' in text and "\n  " in text
        # 简繁转换用含简体中文的内容（纯 ASCII 转换后不变，无法断言）
        self._before_s2t = "简体中文测试，汉字与標點。"
        page.buffer.set_text(self._before_s2t)
        w.activate_action("win.convert-s2t", None)
        self.out["opencc_installed"] = bool(shutil.which("opencc"))

    def s5_check_s2t_and_find_and_save(self) -> bool:
        w = self.app.window
        page = w._current_page()
        # opencc 转换是异步子进程，轮询等待结果（最多 2 秒）
        deadline = time.time() + 2.0

        def poll() -> bool:
            text = page.snapshot_text()
            if shutil.which("opencc"):
                if text != self._before_s2t or time.time() > deadline:
                    self.out["s2t_path"] = text != self._before_s2t
                else:
                    return True  # 继续等待
            else:
                self.out["s2t_missing_noop"] = text == self._before_s2t
            self._s5_rest(page)
            return False

        GLib.timeout_add(120, poll)
        return True  # 自行调度后续步骤

    def _s5_rest(self, page) -> None:
        w = self.app.window
        page.hide_search()
        w.activate_action("win.find", None)
        self.out["find_search_mode"] = page.search_bar.get_search_mode()

        def verify_visible() -> bool:
            # 关键：断言真实布局高度，而不是 reveal_child 这类"内部状态"。
            # SearchBar 的 search_mode 为 False 时高度恒为 0，界面其实什么都没显示。
            self.out["find_bar_height"] = page.search_bar.get_height()
            self.out["find_entry_mapped"] = page.search_entry.get_mapped()
            self._s5_finish(page)
            return False

        GLib.timeout_add(350, verify_visible)

    def _s5_finish(self, page) -> None:
        page.hide_search()
        out_path = Path(TMP) / "doc.html"
        w = self.app.window
        w._write_doc_to_file(page, out_path, link=True)
        self.out["html_file_saved"] = out_path.exists()
        self.out["html_lang_highlight"] = (
            page.buffer.get_language().get_id() if page.buffer.get_language() else None
        ) == "html"
        self.finish()

    def next(self) -> bool:
        """推进到下一步。步骤函数返回 True 表示自行调度后续步骤。"""
        names = [self.s0_line_numbers_and_folding, self.s1_html_preview,
                 self.s2_check_html_dom, self.s3_format_json,
                 self.s4_check_formatted_and_s2t, self.s5_check_s2t_and_find_and_save]
        if self.step >= len(names):
            self.finish()
            return False
        print(f"[step {self.step}] enter", flush=True)
        try:
            handled = names[self.step]()
        except Exception as exc:  # noqa: BLE001
            print(f"[step {self.step}] EXC: {exc}", flush=True)
            self.out[f"step{self.step}_error"] = str(exc)
            self.finish()
            return False
        print(f"[step {self.step}] done", flush=True)
        self.step += 1
        if not handled:
            GLib.timeout_add(150, self.next)
        return False

    def run(self) -> None:
        print("[run] scheduling", flush=True)
        GLib.idle_add(self.next)
        GLib.timeout_add(30000, self.app.quit)
        print("[run] entering main loop", flush=True)
        self.app.run(["gscratchpad-tools-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, indent=1), flush=True)
        self.app.quit()


if __name__ == "__main__":
    ToolsTest().run()
