"""内存优化验证：预览空闲回收 + KaTeX/Mermaid 按需加载。

用法：/usr/bin/python3 tests/test_memory.py
输出 JSON（ensure_ascii=False）。使用临时 XDG_DATA_HOME，不触碰真实数据。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
    [str(PROJECT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
)

TMP = tempfile.mkdtemp(prefix="gscratchpad-mem-test-")
os.environ["XDG_DATA_HOME"] = TMP
os.environ["GSCRATCHPAD_PREVIEW_IDLE"] = "1"  # 1 秒后回收，便于测试

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402

RICH_MD = "# 标题\n\n公式 $E=mc^2$\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
PLAIN_MD = "# 纯文字\n\n没有任何公式或图表。\n"
JS_RICH = (
    "JSON.stringify({katex: !!document.querySelector('.katex'),"
    " svg: !!document.querySelector('.mermaid svg'),"
    " mermaidLoaded: typeof mermaid !== 'undefined'})"
)
JS_PLAIN = "String(typeof mermaid) + '/' + String(typeof katex)"


def webkit_rss_kb() -> int:
    """本进程派生的 WebKit 子进程 RSS 合计（KB）。"""
    total = 0
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            comm = stat.split("(")[1].split(")")[0]
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            if ppid != me or not comm.startswith("WebKit"):
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except (OSError, IndexError, ValueError):
            continue
    return total


class MemoryTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        # 用户可能正开着 gscratchpad：单实例会让测试进程直接退出（window 恒为 None）
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict = {}
        self.step = 0
        self._deadline = 0.0

    # ------------------------------------------------------------------ 工具

    def page(self):
        return self.app.window._current_page()

    def poll_js(self, script: str, ok, on_result, timeout: float = 12.0) -> None:
        """轮询执行 JS，直到 ok(value) 为真或超时。"""
        self._deadline = time.time() + timeout
        page = self.page()

        def tick() -> bool:
            view = page.preview._view
            if view is None:
                if time.time() > self._deadline:
                    on_result(None)
                    return False
                GLib.timeout_add(150, tick)  # 视图按需重建，稍后重试
                return False
            state = {"v": None}

            def done(v, result, _d):
                try:
                    val = v.evaluate_javascript_finish(result)
                    state["v"] = val.to_string() if val else None
                except GLib.Error:
                    state["v"] = None
                if state["v"] is not None and ok(state["v"]):
                    on_result(state["v"])
                    return False
                if time.time() > self._deadline:
                    on_result(state["v"])
                    return False
                GLib.timeout_add(200, tick)
                return False

            view.evaluate_javascript(script, -1, None, None, None, done, None)
            return False

        GLib.timeout_add(150, tick)

    def wait(self, seconds: float, then) -> None:
        GLib.timeout_add(int(seconds * 1000), lambda: (then(), False)[1])

    # ------------------------------------------------------------------ 步骤

    def s0_render_rich(self) -> None:
        w = self.app.window
        page = w.new_tab("md")
        page.buffer.set_text(RICH_MD)
        w.set_mode("preview")
        self.out["rss_before_render_kb"] = webkit_rss_kb()

        def check(value):
            self.out["rich_js"] = value
            self.out["math_rendered"] = bool(value and '"katex":true' in value.replace(" ", ""))
            self.out["mermaid_rendered"] = bool(value and '"svg":true' in value.replace(" ", ""))
            self.out["webkit_rss_with_preview_kb"] = webkit_rss_kb()
            self.next()

        self.poll_js(JS_RICH, lambda v: v is not None and '"svg":true' in v.replace(" ", ""), check)

    def s1_release_on_hide(self) -> None:
        w = self.app.window
        page = self.page()
        self.out["view_before_hide"] = page.preview.has_view
        w.set_mode("source")  # 预览不可见 → 启动回收倒计时

        def after():
            self.out["view_after_idle"] = page.preview.has_view
            self.out["released"] = not page.preview.has_view
            self.out["placeholder_visible"] = page.preview._placeholder.get_visible()
            GLib.timeout_add(2500, self._after_release)

        self.wait(2.6, after)

    def _after_release(self) -> bool:
        self.out["webkit_rss_after_release_kb"] = webkit_rss_kb()
        self.next()
        return False

    def s2_recreate(self) -> None:
        w = self.app.window
        w.set_mode("preview")
        page = self.page()

        def check(value):
            self.out["rerender_js"] = value
            self.out["rerender_ok"] = bool(value and '"svg":true' in value.replace(" ", ""))
            self.out["view_recreated"] = page.preview.has_view
            self.next()

        self.poll_js(JS_RICH, lambda v: v is not None and '"svg":true' in v.replace(" ", ""), check)

    def s3_tab_switch(self) -> None:
        """切到别的标签后回收；切回来必须自动重建并重新渲染。"""
        w = self.app.window
        page1 = self.page()          # 先取原标签，new_tab 之后选中页就是新标签了
        page2 = w.new_tab("md")
        page2.buffer.set_text("# 第二个标签\n\n内容 beta\n")
        w.set_mode("preview")
        self.out["tab2_view"] = page2.preview.has_view

        w.tabview.set_selected_page(page1.tab)

        def check_released():
            self.out["tab2_released_while_away"] = not page2.preview.has_view
            self.out["tab2_mapped"] = page2.preview.get_mapped()
            self.out["tab2_pending"] = page2.preview.release_pending()
            w.tabview.set_selected_page(page2.tab)
            self.wait(1.2, check_back)

        def check_back():
            self.out["tab2_view_on_return"] = page2.preview.has_view

            def value(v):
                self.out["tab2_js"] = v
                self.out["tab2_rerendered"] = bool(v and "第二个标签" in v)
                self.next()

            self.poll_js(
                "document.body.textContent || ''",
                lambda v: v is not None and "第二个标签" in v,
                value,
            )

        self.wait(3.0, check_released)

    def s4_plain_no_libs(self) -> None:
        w = self.app.window
        page = w.new_tab("md")
        page.buffer.set_text(PLAIN_MD)
        w.set_mode("preview")

        def check(value):
            self.out["plain_js"] = value
            self.out["plain_skips_libs"] = value == "undefined/undefined"
            self.finish()

        self.poll_js(JS_PLAIN, lambda v: v is not None and v.startswith("undefined"), check)

    # ------------------------------------------------------------------ 调度

    def next(self) -> bool:
        names = [
            self.s0_render_rich,
            self.s1_release_on_hide,
            self.s2_recreate,
            self.s3_tab_switch,
            self.s4_plain_no_libs,
        ]
        if self.step >= len(names):
            self.finish()
            return False
        print(f"[step {self.step}]", flush=True)
        try:
            names[self.step]()
        except Exception as exc:  # noqa: BLE001
            import traceback

            print(traceback.format_exc(), flush=True)
            self.out[f"step{self.step}_error"] = str(exc)
            self.finish()
            return False
        self.step += 1
        return False

    def run(self) -> None:
        GLib.idle_add(self.next)
        GLib.timeout_add(60000, self.app.quit)
        self.app.run(["gscratchpad-mem-test"])

    def finish(self) -> None:
        print(json.dumps(self.out, ensure_ascii=False, indent=1), flush=True)
        self.app.quit()


if __name__ == "__main__":
    MemoryTest().run()
