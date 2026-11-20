"""PDF 导出端到端测试（修订六）。

场景 1：系统 PATH 含 weasyprint → 走真分页管线。
  验证 PDF 生成、文字矢量可搜索（pdftotext）、页数 > 1。
场景 2：PATH 无 weasyprint → 回退位图管线。
  验证 on_fallback 被调用且仍能产出 PDF。

注意：本机若未安装系统 weasyprint，可在 PATH 前置一个含 weasyprint 可执行
文件的目录（如临时 venv）来覆盖场景 1；两个场景均会自动按当前环境取舍。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))
os.environ.setdefault(
    "GI_TYPELIB_PATH",
    os.pathsep.join([str(PROJECT / "vendor" / "gir" / "local"),
                     "/usr/lib/x86_64-linux-gnu/girepository-1.0"]),
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, GLib, Gtk, WebKit  # noqa: E402

from scratchpad import pdfexport  # noqa: E402

WEASY_LOCAL = "/tmp/wpvenv/bin"  # 本地实验 venv（可选）
DOC_TEXT = (
    "# PDF 导出测试\n\n行内公式 $E = mc^2$ 与块公式：\n\n"
    "$$\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}$$\n\n"
    "| 函数 | 值 |\n|---|---|\n| sin | 0.5 |\n| cos | 0.86 |\n\n"
    "```python\ndef f(x):\n    return x ** 2\n```\n\n"
    "```mermaid\ngraph LR; A-->B;\n```\n\n"
    + "\n\n".join(
        f"这是第 {i} 段长文，需要足够多的汉字填满整行宽度，确保分页缝隙有"
        "机会落在这一行的中间位置，检验是否会把一行文字切成上下两半。"
        for i in range(40)
    )
)


def make_app(tmpdir: Path):
    app = Adw.Application(application_id="test.pdfexport")
    out: dict = {}

    def run_case():
        win = Gtk.Window()
        win.present()
        app.win = win

        def case1():
            out["case1_fallback"] = None
            print("[pdf-test] case1 start", flush=True)
            if not (shutil.which("weasyprint") or
                    (os.path.isdir(WEASY_LOCAL) and
                     os.path.exists(WEASY_LOCAL + "/weasyprint"))):
                out["case1"] = "SKIP (no weasyprint)"
                GLib.timeout_add(50, case2)
                return False
            if os.path.isdir(WEASY_LOCAL):
                os.environ["PATH"] = WEASY_LOCAL + os.pathsep + os.environ["PATH"]
            out_path = str(tmpdir / "weasy.pdf")
            pdfexport.export_pdf(
                DOC_TEXT, out_path,
                on_done=lambda p: (out.__setitem__("case1", "ok"),
                                   out.__setitem__("case1_path", p),
                                   GLib.timeout_add(100, case2)),
                on_error=lambda m: (out.__setitem__("case1", f"ERR: {m}"),
                                    GLib.timeout_add(100, case2)),
                parent=win,
            )
            return False

        def case2():
            print("[pdf-test] case2 start", flush=True)
            # 从 PATH 移除 weasyprint：用清空 PATH 的子模拟不可行（shutil.which 读 os.environ），
            # 这里临时把 PATH 指向不含 weasyprint 的目录
            saved = os.environ["PATH"]
            os.environ["PATH"] = "/usr/bin-nonexist"
            out_path = str(tmpdir / "bitmap.pdf")
            pdfexport.export_pdf(
                DOC_TEXT, out_path,
                on_done=lambda p: (out.__setitem__("case2", "ok"),
                                   out.__setitem__("case2_path", p),
                                   GLib.timeout_add(100, finish)),
                on_error=lambda m: (out.__setitem__("case2", f"ERR: {m}"),
                                    GLib.timeout_add(100, finish)),
                on_fallback=lambda r: out.__setitem__("case2_fallback", r),
                parent=win,
            )
            os.environ["PATH"] = saved
            return False

        def finish():
            try:
                p1 = tmpdir / "weasy.pdf"
                if out.get("case1") == "ok":
                    t = subprocess.run(["pdftotext", str(p1), "-"],
                                       capture_output=True, text=True)
                    txt = t.stdout
                    out["case1_vector"] = "PDF 导出测试" in txt
                    out["case1_pages"] = txt.count("\f")
                p2 = tmpdir / "bitmap.pdf"
                if out.get("case2") == "ok":
                    out["case2_size"] = p2.stat().st_size
            finally:
                app.quit()

        GLib.idle_add(case1)
        GLib.timeout_add(90000, app.quit)

    app.connect("activate", lambda a: (a.hold(), run_case()))
    print("[pdf-test] activating", flush=True)
    app.run([])
    print("[pdf-test] mainloop exited", flush=True)
    return out


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="pdf-test-"))
    out = make_app(tmpdir)
    print(out, flush=True)
    ok = True
    c1 = out.get("case1")
    if c1 == "SKIP (no weasyprint)":
        print("case1 skipped")
    elif c1 == "ok":
        ok &= bool(out.get("case1_vector")) and out.get("case1_pages", 0) >= 2
        print(f"case1 (weasyprint): pages={out.get('case1_pages')} "
              f"vector={out.get('case1_vector')}")
    else:
        ok = False
        print("case1 FAILED:", c1)
    ok &= out.get("case2") == "ok" and bool(out.get("case2_fallback"))
    print("case2 (bitmap fallback):", out.get("case2"),
          "fallback-noticed:", bool(out.get("case2_fallback")))
    print("PDF EXPORT TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
