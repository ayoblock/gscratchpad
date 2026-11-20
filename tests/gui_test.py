"""自动化 GUI 测试驱动。

用法：/usr/bin/python3 tests/gui_test.py <phase> [--kill]
phase:
  write    — 启动应用，写入 3 个标签页并触发自动保存，随后正常退出或 SIGKILL
  verify   — 启动应用，读取恢复出的标签页内容，输出 JSON
  autosave — 写入内容后不显式 flush，验证防抖后自动落盘
  closetab — 关闭标签页，验证文档保留、界面无保存提示、可从菜单恢复
  preview  — 渲染预览并通过 JS 检查公式 / Mermaid 渲染结果
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

# 开发环境：优先使用本地 typelib（WebKit 6.0 / GtkSource 5）
_local_gir = str(PROJECT / "vendor" / "gir" / "local")
_system_gir = "/usr/lib/x86_64-linux-gnu/girepository-1.0"
_existing = os.environ.get("GI_TYPELIB_PATH", "")
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [_local_gir, _system_gir, _existing] if _existing else [_local_gir, _system_gir]
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from scratchpad import paths  # noqa: E402
from scratchpad.application import ScratchpadApp  # noqa: E402

MD_SAMPLE = (
    "# 第二页\n\n公式 $E=mc^2$ 与\n\n$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$\n\n"
    "```mermaid\nflowchart TD\n  A --> B\n```\n\n| a | b |\n| - | - |\n| 1 | 2 |"
)


class Harness:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        # 用户可能正开着 gscratchpad：单实例会让测试进程直接退出（window 恒为 None）
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict = {}
        self.printed = False

    def emit(self) -> None:
        if not self.printed:
            print(json.dumps(self.out, ensure_ascii=False), flush=True)
            self.printed = True

    # ------------------------------------------------------------------ utils

    def w(self):
        return self.app.window

    def pages(self):
        view = self.w().tabview
        return [view.get_nth_page(i).get_child() for i in range(view.get_n_pages())]

    def at(self, seconds: float, func) -> None:
        """在主循环启动后延迟执行；必须在 app.run 之前注册。"""
        GLib.timeout_add(int(seconds * 1000), lambda: (func(), False)[1])

    def finish(self) -> None:
        self.w().close()

    # ------------------------------------------------------------------ phases

    def phase_write(self, kill: bool) -> None:
        def setup() -> None:
            w = self.w()
            pages = self.pages()
            pages[0].buffer.set_text("第一页内容 alpha 123")
            pages[0].title = "首页笔记"
            pages[0].tab.set_title("首页笔记")
            w.store.rename(pages[0].doc_id, "首页笔记")

            w.new_tab("md")
            pages = self.pages()
            pages[1].buffer.set_text(MD_SAMPLE)
            pages[1].title = "数学笔记"
            pages[1].tab.set_title("数学笔记")
            w.store.rename(pages[1].doc_id, "数学笔记")

            w.new_tab("txt")
            pages = self.pages()
            pages[2].buffer.set_text("第三页内容")
            w._persist_order()

            self.out["written"] = [
                {"title": p.title, "fmt": p.format, "text": p.snapshot_text()}
                for p in self.pages()
            ]

        def flush_and_end() -> None:
            if not kill:
                # 正常退出：显式 flush 后关闭
                self.app.store.flush()
                docs = self.app.store.open_documents()
                self.out["docs_on_disk"] = [
                    {"title": d.title, "fmt": d.format, "len": len(d.content), "rev": d.revision}
                    for d in docs
                ]
                self.emit()
                self.finish()
            else:
                # 崩溃模拟：不 flush、不调用任何退出清理，直接 SIGKILL
                self.emit()
                os.kill(os.getpid(), signal.SIGKILL)

        self.at(0.8, setup)
        self.at(2.2, flush_and_end)

    def phase_verify(self) -> None:
        def collect() -> None:
            self.out["restored"] = [
                {"title": p.title, "fmt": p.format, "text": p.snapshot_text()}
                for p in self.pages()
            ]
            self.out["meta_active"] = self.w().store.get_meta("active_doc")
            self.emit()
            self.finish()

        self.at(2.0, collect)

    def phase_autosave(self) -> None:
        def edit() -> None:
            self.pages()[0].buffer.set_text("autosave should hit disk without explicit flush")

        def check() -> None:
            doc = self.app.store.get(self.pages()[0].doc_id)
            self.out = {
                "db_content": doc.content if doc else None,
                "ok": bool(doc and "autosave" in doc.content),
            }
            self.emit()
            self.finish()

        self.at(0.8, edit)
        self.at(1.3, check)

    def phase_closetab(self) -> None:
        def setup() -> None:
            w = self.w()
            pages = self.pages()
            pages[0].buffer.set_text("将被关闭但保留的文档")
            w.new_tab("txt")

        def close_first() -> None:
            self.w().tabview.close_page(self.w().tabview.get_nth_page(0))

        def verify() -> None:
            closed = [d for d in self.app.store.all_documents() if d.state == "closed"]
            self.out = {
                "remaining_tabs": [p.title for p in self.pages()],
                "closed_docs_kept": len(closed),
                "closed_content": [d.content for d in closed if "将被关闭" in d.content],
            }
            self.emit()
            self.finish()

        self.at(0.8, setup)
        self.at(1.2, close_first)
        self.at(1.8, verify)

    def phase_preview(self) -> None:
        def setup() -> None:
            w = self.w()
            page = self.pages()[0]
            page.set_format("md")
            page.buffer.set_text(
                "公式 $a^2+b^2=c^2$\n\n$$\\int_0^1 x dx = \\frac{1}{2}$$\n\n"
                "```mermaid\nflowchart LR\n  X --> Y\n```\n"
            )
            w.set_mode("split")
            page.refresh_preview()

        def check() -> None:
            view = self.pages()[0].preview._view
            js = (
                "JSON.stringify({katex: document.querySelectorAll('.katex').length,"
                " svgs: document.querySelectorAll('.mermaid svg').length})"
            )
            view.evaluate_javascript(js, -1, None, None, None, self._js_done, None)

        self.at(0.8, setup)
        self.at(6.5, check)

    def phase_pdf(self) -> None:
        def setup() -> None:
            page = self.pages()[0]
            page.set_format("md")
            page.buffer.set_text(
                "# PDF 导出测试\n\n中文段落与 $E=mc^2$。\n\n$$\\sum_{i=1}^n i=\\frac{n(n+1)}{2}$$\n\n"
                "```mermaid\nflowchart LR\n  A --> B\n```\n\n| 甲 | 乙 |\n| - | - |\n| 1 | 2 |\n"
            )
            page.refresh_preview()

        def do_export() -> None:
            from scratchpad import pdfexport

            out = os.path.join(os.environ["SCRATCHPAD_DATA_DIR"], "export-test.pdf")
            pdfexport.export_pdf(
                self.pages()[0].snapshot_text(),
                out,
                on_done=lambda p: self._pdf_ok(p),
                on_error=lambda m: self._pdf_fail(m),
            )

        self.at(0.8, setup)
        self.at(3.0, do_export)

    def _pdf_ok(self, path: str) -> None:
        size = os.path.getsize(path)
        header = open(path, "rb").read(8)
        self.out = {"pdf": path, "size": size, "header": header.decode("latin-1")}
        print(json.dumps(self.out, ensure_ascii=False), flush=True)
        self.finish()

    def _pdf_fail(self, msg: str) -> None:
        self.out = {"pdf_error": msg}
        print(json.dumps(self.out, ensure_ascii=False), flush=True)
        self.finish()

    def phase_image(self) -> None:
        def setup() -> None:
            from PIL import Image

            img_path = os.path.join(os.environ["SCRATCHPAD_DATA_DIR"], "input.png")
            Image.new("RGB", (120, 80), (30, 120, 200)).save(img_path)
            page = self.pages()[0]
            page.set_format("md")
            self.w().import_images([img_path])

        def check() -> None:
            page = self.pages()[0]
            text = page.snapshot_text()
            asset_files = []
            from scratchpad import paths

            adir = paths.doc_asset_dir(page.doc_id)
            if adir.is_dir():
                asset_files = [p.name for p in adir.iterdir()]
            self.out = {"text": text, "assets": asset_files}
            w = self.w()
            w.set_mode("split")
            page.refresh_preview()
            self._after = lambda: self._image_dom_check(page)
            GLib.timeout_add(5000, lambda: (self._after(), False)[1])

        self.at(0.8, setup)
        self.at(1.5, check)

    def _image_dom_check(self, page) -> None:
        view = page.preview._view
        js = (
            "JSON.stringify({imgs: document.images.length,"
            " loaded: Array.from(document.images).map(i => i.naturalWidth > 0)})"
        )
        view.evaluate_javascript(js, -1, None, None, None, self._js_done2, None)

    def _js_done2(self, view, result, _data) -> None:
        value = view.evaluate_javascript_finish(result)
        print("IMAGE_DOM", value.to_string() if value else "None", flush=True)
        print(json.dumps(self.out, ensure_ascii=False), flush=True)
        self.finish()

    def _js_done(self, view, result, _data) -> None:
        value = view.evaluate_javascript_finish(result)
        print("PREVIEW_DOM", value.to_string() if value else "None", flush=True)
        self.finish()

    def phase_find(self) -> None:
        def setup() -> None:
            page = self.pages()[0]
            page.buffer.set_text("苹果 香蕉 苹果 橙子 苹果\n第二行 苹果\n第三行")

        def find_next() -> None:
            page = self.pages()[0]
            page.show_search(False)
            page.search_entry.set_text("苹果")

        def jump() -> None:
            page = self.pages()[0]
            positions = []
            for _ in range(4):
                page.find_next()
                s, e = page._selection_iters()
                if s is None:
                    positions.append(None)
                else:
                    positions.append(page.buffer.get_text(s, e, False))
            self.out["selections"] = positions

        def replace_all() -> None:
            page = self.pages()[0]
            page.replace_entry.set_text("水果")
            page.replace_all()
            self.out["after_replace"] = page.snapshot_text()
            print(json.dumps(self.out, ensure_ascii=False), flush=True)
            self.finish()

        self.at(0.8, setup)
        self.at(1.2, find_next)
        self.at(2.0, jump)
        self.at(2.4, replace_all)

    def phase_dark(self) -> None:
        def setup() -> None:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            page = self.pages()[0]
            page.set_format("md")
            page.buffer.set_text("深色预览测试 $x^2$")
            self.w().set_mode("split")
            page.refresh_preview()

        def check() -> None:
            view = self.pages()[0].preview._view
            js = (
                "JSON.stringify({dark: document.body.classList.contains('preview-dark'),"
                " katex: document.querySelectorAll('.katex').length})"
            )
            view.evaluate_javascript(js, -1, None, None, None, self._js_done3, None)

        self.at(0.8, setup)
        self.at(5.5, check)

    def _js_done3(self, view, result, _data) -> None:
        value = view.evaluate_javascript_finish(result)
        print("DARK_DOM", value.to_string() if value else "None", flush=True)
        self.finish()

    # ------------------------------------------------------------ 本机文件

    def phase_openfile(self) -> None:
        """Ctrl+O 逻辑：open_file_paths 打开 txt/md，关联 source_path，内容入库。"""
        workdir = Path(tempfile.mkdtemp(prefix="gsp-open-"))
        txt = workdir / "会议记录.txt"
        md = workdir / "计划.md"
        txt.write_text("来自本机 txt 文件的内容", encoding="utf-8")
        md.write_text("# 本机 MD\n\n正文 **加粗**", encoding="utf-8")

        def run_open() -> None:
            w = self.w()
            w.open_file_paths([str(txt), str(md), str(workdir / "不存在.txt")])
            self.out["n_tabs"] = w.tabview.get_n_pages()
            titles = [w.tabview.get_nth_page(i).get_child().title
                      for i in range(w.tabview.get_n_pages())]
            self.out["titles"] = titles
            self.out["workdir"] = str(workdir)

        def check_state() -> None:
            w = self.w()
            selected = w.tabview.get_selected_page().get_child()
            docs = self.app.store.open_documents()
            self.out["selected_title"] = selected.title
            self.out["selected_text"] = selected.snapshot_text()
            self.out["selected_fmt"] = selected.format
            self.out["linked"] = self.app.store.source_path_of(selected.doc_id)
            self.out["db_docs"] = [
                {"title": d.title, "fmt": d.format, "len": len(d.content)} for d in docs
            ]
            print(json.dumps(self.out, ensure_ascii=False), flush=True)
            self.finish()

        self.at(0.8, run_open)
        self.at(2.0, check_state)

    def phase_savefile(self, workdir_env: str | None = None) -> None:
        """Ctrl+S 逻辑：已关联 → 写回原文件；未关联 → 另存为（直接调内部方法）。"""
        workdir = Path(workdir_env or tempfile.mkdtemp(prefix="gsp-save-"))
        src = workdir / "笔记.md"
        src.write_text("# 原始内容\n", encoding="utf-8")

        def link_and_edit() -> None:
            w = self.w()
            page = w.pages[0] if False else w.tabview.get_selected_page().get_child()
            # 打开本机文件建立关联
            w.open_file_paths([str(src)])
            page = w.tabview.get_selected_page().get_child()
            page.buffer.set_text("# 已修改的内容\n\n新段落")
            self.out["src"] = str(src)
            self.out["workdir"] = str(workdir)

        def save_back() -> None:
            w = self.w()
            w.save_active_to_file()  # 已关联 → 原子写回 src

        def save_as() -> None:
            w = self.w()
            # 未关联文档：直接走内部写入（绕过对话框）
            page = w.tabview.get_selected_page().get_child()
            w._write_doc_to_file(page, workdir / "另存.md", link=True)

        def check() -> None:
            w = self.w()
            page = w.tabview.get_selected_page().get_child()
            self.out["src_content"] = (workdir / "笔记.md").read_text(encoding="utf-8")
            self.out["as_content"] = (workdir / "另存.md").read_text(encoding="utf-8")
            self.out["relinked"] = self.app.store.source_path_of(page.doc_id)
            self.out["status_label"] = w.save_label.get_text()
            print(json.dumps(self.out, ensure_ascii=False), flush=True)
            self.finish()

        self.at(0.8, link_and_edit)
        self.at(1.6, save_back)
        self.at(2.4, save_as)
        self.at(3.6, check)

    def phase_dropfiles(self) -> None:
        """拖放分类：图片 → 插入引用；txt/md → 新标签；二进制 → 提示不打开。"""
        workdir = Path(tempfile.mkdtemp(prefix="gsp-drop-"))
        png = workdir / "pic.png"
        # 1x1 红色 PNG
        png.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080200000090775"
            "3de0000000c4944415408d763f8cfc00000030101"
            "00184dff5d0000000049454e44ae426082"
        ))
        txt = workdir / "拖入.txt"
        txt.write_text("拖进来的文本", encoding="utf-8")
        md = workdir / "拖入.md"
        md.write_text("# 拖进来的 MD", encoding="utf-8")
        binary = workdir / "程序.bin"
        binary.write_bytes(b"MZ\x00\x00binary")

        def run_drop() -> None:
            w = self.w()
            w.handle_dropped_files([str(txt), str(png), str(md), str(binary)])
            self.out["workdir"] = str(workdir)
            self.out["n_tabs"] = w.tabview.get_n_pages()
            self.out["titles"] = [
                w.tabview.get_nth_page(i).get_child().title
                for i in range(w.tabview.get_n_pages())
            ]

        def check_image_ref() -> None:
            w = self.w()
            page0 = w.tabview.get_nth_page(0).get_child()
            self.out["first_tab_text"] = page0.snapshot_text()
            print(json.dumps(self.out, ensure_ascii=False), flush=True)
            self.finish()

        self.at(0.8, run_drop)
        self.at(2.2, check_image_ref)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    phase = sys.argv[1]
    kill = "--kill" in sys.argv
    data_dir = os.environ.get("SCRATCHPAD_DATA_DIR")
    if not data_dir:
        print("需要 SCRATCHPAD_DATA_DIR 环境变量", file=sys.stderr)
        return 2
    os.environ["XDG_DATA_HOME"] = data_dir

    harness = Harness()
    if phase == "write":
        harness.phase_write(kill)
    elif phase == "verify":
        harness.phase_verify()
    elif phase == "autosave":
        harness.phase_autosave()
    elif phase == "closetab":
        harness.phase_closetab()
    elif phase == "preview":
        harness.phase_preview()
    elif phase == "pdf":
        harness.phase_pdf()
    elif phase == "image":
        harness.phase_image()
    elif phase == "find":
        harness.phase_find()
    elif phase == "dark":
        harness.phase_dark()
    elif phase == "openfile":
        harness.phase_openfile()
    elif phase == "savefile":
        harness.phase_savefile()
    elif phase == "dropfiles":
        harness.phase_dropfiles()
    else:
        print(f"未知 phase：{phase}", file=sys.stderr)
        return 2

    harness.app.run(["gui-test"])
    harness.emit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
