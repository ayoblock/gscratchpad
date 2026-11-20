"""PDF 导出。

两条管线：

1. WeasyPrint（默认，系统装有 weasyprint 时）：离屏 WebKit 视图完整渲染
   （KaTeX 公式、Mermaid SVG、图片、表格，全部离线），渲染就绪后提取最终
   DOM HTML，交由 weasyprint 子进程做真分页排版。行按 CSS 分页规则切分
   （标题不孤行、代码块/表格/图片整块不拆），一行文字不会被切成上下两半，
   且文字为矢量、可选中可搜索。

2. 位图快照（回退，weasyprint 缺失时）：取 FULL_DOCUMENT 快照，再用
   Gtk.PrintOperation 的 EXPORT 动作按 A4 页面切片写入 PDF。代价是文字为
   位图且切缝可能落在行中间。

WebKitGTK 6.0 的 WebKit.PrintOperation.print_() 在没有打印机（CUPS 队列）
的环境下无法直接导出到文件，故不采用。
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import GLib, Gtk, WebKit  # noqa: E402

from . import markdown_render, paths  # noqa: E402

# A4 210x297mm，页边距：上下 18mm，左右 16mm
_MARGIN_LR_MM = 16.0
_MARGIN_TB_MM = 18.0
_CONTENT_WIDTH_PX = 672  # (210 - 2*16)mm @96dpi ≈ 672 CSS px
_PRINT_SCALE = 2  # 位图回退管线：2x 渲染，提升 PDF 文字与图形清晰度
_VIEW_WIDTH = _CONTENT_WIDTH_PX * _PRINT_SCALE
_WEASY_TIMEOUT_S = 180

_EXPORTING: list[WebKit.WebView] = []


def export_pdf(text: str, out_path: str, on_done, on_error, parent=None,
               on_fallback=None) -> None:
    """异步导出。on_done(path) / on_error(message) 在主循环回调。

    parent 用于短暂承载导出视图（WebKit 渲染需要视图已被映射）。
    on_fallback(reason) 在 weasyprint 缺失或执行失败而回退位图管线时回调，
    用于向用户提示降级。
    """
    weasy_bin = shutil.which("weasyprint")
    if weasy_bin:
        _export_weasy(text, out_path, weasy_bin, on_done, on_error, parent,
                      on_fallback)
    else:
        if on_fallback is not None:
            on_fallback("未检测到 weasyprint，已改用兼容模式导出（文字为位图）")
        _export_bitmap(text, out_path, on_done, on_error, parent)


# ------------------------------------------------------------------ 公共渲染


def _make_view() -> tuple[WebKit.WebView, WebKit.UserContentManager]:
    settings = WebKit.Settings()
    settings.set_enable_javascript(True)
    settings.set_allow_file_access_from_file_urls(True)
    settings.set_allow_universal_access_from_file_urls(True)
    manager = WebKit.UserContentManager()
    manager.register_script_message_handler("ready")
    view = WebKit.WebView(settings=settings, user_content_manager=manager)
    view.set_size_request(_VIEW_WIDTH, 1123)
    _EXPORTING.append(view)
    return view, manager


def _make_holder(view: WebKit.WebView, parent) -> Gtk.Window:
    holder = Gtk.Window(
        title="正在导出 PDF…",
        transient_for=parent,
        default_width=min(_VIEW_WIDTH + 30, 900),
        default_height=520,
    )
    holder.set_child(Gtk.ScrolledWindow(child=view))
    holder.present()
    return holder


def _load_and_wait(view: WebKit.WebView, manager: WebKit.UserContentManager,
                   html: str, base_uri: str, state: dict, on_ready) -> None:
    """加载 HTML，就绪后回调 on_ready（script message 优先，轮询兜底）。"""

    def start_ready_flow() -> None:
        GLib.timeout_add(400, on_ready)

    def on_ready_msg(_manager, _result) -> None:
        _cancel_poll(state)
        start_ready_flow()

    def poll_ready() -> bool:
        if state["done"]:
            return False
        view.evaluate_javascript(
            "window.__scratchpadReady === true",
            -1, None, None, None, _on_poll_result, None,
        )
        return True

    def _on_poll_result(webview, result, _user) -> None:
        try:
            value = webview.evaluate_javascript_finish(result)
            ready = bool(value and not value.is_undefined() and value.to_boolean())
        except Exception:  # noqa: BLE001
            ready = False
        if ready:
            _cancel_poll(state)
            start_ready_flow()

    def on_load(_view, event) -> None:
        if event == WebKit.LoadEvent.FINISHED and state["poll"] == 0:
            state["poll"] = GLib.timeout_add(300, poll_ready)

    manager.connect("script-message-received::ready", on_ready_msg)
    view.connect("load-changed", on_load)
    view.load_html(html, base_uri)


# ------------------------------------------------------------------ WeasyPrint


def _export_weasy(text: str, out_path: str, weasy_bin: str, on_done, on_error,
                  parent, on_fallback) -> None:
    """真分页管线：渲染 → 提取 DOM → weasyprint 子进程。"""
    html = markdown_render.render_document(
        text, dark=False, print_mode=True, print_scale=1
    )
    base_uri = paths.data_root().as_uri() + "/"
    view, manager = _make_view()
    holder = _make_holder(view, parent)
    state = {"done": False, "poll": 0}

    def fail(message: str, fallback: bool = False) -> None:
        if state["done"]:
            return
        state["done"] = True
        _cancel_poll(state)
        _cleanup(view, holder)
        if fallback and on_fallback is not None:
            on_fallback(f"weasyprint 导出失败，已改用兼容模式：{message}")
            _export_bitmap(text, out_path, on_done, on_error, parent)
        else:
            on_error(message)

    def finish_ok() -> None:
        if state["done"]:
            return
        state["done"] = True
        _cleanup(view, holder)
        on_done(out_path)

    def run_weasy(dom_html: str) -> None:
        def worker():
            err: str | None = None
            try:
                with tempfile.TemporaryDirectory(prefix="gscratchpad-pdf-") as td:
                    src = Path(td) / "document.html"
                    src.write_text(dom_html, encoding="utf-8")
                    proc = subprocess.run(
                        [weasy_bin, str(src), out_path,
                         "--base-url", base_uri],
                        capture_output=True, timeout=_WEASY_TIMEOUT_S,
                    )
                    if proc.returncode != 0:
                        detail = proc.stderr.decode(errors="replace").strip()
                        raise RuntimeError(detail[-200:] if detail else
                                           f"退出码 {proc.returncode}")
                    if not Path(out_path).exists():
                        raise RuntimeError("weasyprint 未生成输出文件")
            except Exception as exc:  # noqa: BLE001
                err = str(exc)

            def done():
                if err is None:
                    finish_ok()
                else:
                    fail(err, fallback=True)

            GLib.idle_add(done)

        threading.Thread(target=worker, daemon=True).start()

    def grab_dom() -> bool:
        """渲染就绪：提取最终 DOM（KaTeX 已转 HTML、Mermaid 已转内联 SVG）。"""
        if state["done"]:
            return False

        def on_dom(v, result, _user) -> None:
            if state["done"]:
                return
            try:
                dom = v.evaluate_javascript_finish(result).to_string()
                if not dom:
                    raise RuntimeError("DOM 提取为空")
            except Exception as exc:  # noqa: BLE001
                fail(str(exc))
                return
            run_weasy(dom)

        view.evaluate_javascript(
            "document.documentElement.outerHTML",
            -1, None, None, None, on_dom, None,
        )
        return False

    _load_and_wait(view, manager, html, base_uri, state, grab_dom)


# ------------------------------------------------------------------ 位图回退


def _export_bitmap(text: str, out_path: str, on_done, on_error, parent) -> None:
    html = markdown_render.render_document(
        text, dark=False, print_mode=True, print_scale=_PRINT_SCALE
    )
    view, manager = _make_view()
    holder = _make_holder(view, parent)

    base_uri = paths.data_root().as_uri() + "/"
    state = {"done": False, "poll": 0}

    def fail(message: str) -> None:
        if state["done"]:
            return
        state["done"] = True
        _cancel_poll(state)
        _cleanup(view, holder)
        on_error(message)

    def finish_ok() -> None:
        if state["done"]:
            return
        state["done"] = True
        _cancel_poll(state)
        _cleanup(view, holder)
        on_done(out_path)

    def start_snapshot() -> None:
        if state["done"]:
            return
        view.get_snapshot(
            WebKit.SnapshotRegion.FULL_DOCUMENT,
            0,
            None,
            _on_snapshot,
            (state, fail, finish_ok, out_path),
        )

    def _on_snapshot(_view, result, payload) -> None:
        state_, fail_, finish_, out = payload
        if state_["done"]:
            return
        try:
            texture = _view.get_snapshot_finish(result)
            import os as _os
            if _os.environ.get("SCRATCHPAD_DEBUG_PDF"):
                print(f"DEBUG view={_view.get_width()}x{_view.get_height()} tex={texture.get_width()}x{texture.get_height()}", file=sys.stderr)
            if texture is None:
                raise RuntimeError("快照为空")
            _write_pdf(texture, out)
        except Exception as exc:  # noqa: BLE001
            fail_(str(exc))
            return
        finish_()

    _load_and_wait(view, manager, html, base_uri, state, start_snapshot)


def _cancel_poll(state: dict) -> None:
    poll = state.get("poll")
    if poll:
        GLib.source_remove(poll)
        state["poll"] = 0


def _write_pdf(texture, out_path: str) -> None:
    tex_w = float(texture.get_width())
    tex_h = float(texture.get_height())
    if tex_w <= 0 or tex_h <= 0:
        raise RuntimeError("快照尺寸无效")

    setup = Gtk.PageSetup()
    paper = Gtk.PaperSize.new(Gtk.PAPER_NAME_A4)
    setup.set_paper_size_and_default_margins(paper)
    setup.set_left_margin(_MARGIN_LR_MM, Gtk.Unit.MM)
    setup.set_right_margin(_MARGIN_LR_MM, Gtk.Unit.MM)
    setup.set_top_margin(_MARGIN_TB_MM, Gtk.Unit.MM)
    setup.set_bottom_margin(_MARGIN_TB_MM, Gtk.Unit.MM)

    content_w_pt = setup.get_page_width(Gtk.Unit.POINTS)
    content_h_pt = setup.get_page_height(Gtk.Unit.POINTS)

    ds = tex_w / _CONTENT_WIDTH_PX  # device scale（HiDPI 下为 2）
    css_px_per_pt = _CONTENT_WIDTH_PX / content_w_pt
    page_h_tex_px = content_h_pt * css_px_per_pt * ds
    n_pages = max(1, int(math.ceil(tex_h / page_h_tex_px)))

    snapshot = Gtk.Snapshot.new()
    texture.snapshot(snapshot, tex_w, tex_h)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("无法生成渲染节点")

    op = Gtk.PrintOperation()
    op.set_property("export-filename", out_path)
    op.set_default_page_setup(setup)

    def on_begin(_op, _ctx) -> None:
        _op.set_n_pages(n_pages)

    def on_draw(_op, ctx, page_nr: int) -> None:
        cr = ctx.get_cairo_context()
        cr.save()
        cr.rectangle(0, 0, content_w_pt, content_h_pt)
        cr.clip()
        k = content_w_pt / tex_w
        cr.scale(k, k)
        cr.translate(0.0, -page_nr * page_h_tex_px)
        node.draw(cr)
        cr.restore()

    op.connect("begin-print", on_begin)
    op.connect("draw-page", on_draw)
    result = op.run(Gtk.PrintOperationAction.EXPORT, None)
    if result in (Gtk.PrintOperationResult.ERROR, Gtk.PrintOperationResult.CANCEL):
        raise RuntimeError(f"打印任务失败（result={result}）")


def _cleanup(view: WebKit.WebView, holder: Gtk.Window | None = None) -> None:
    if view in _EXPORTING:
        _EXPORTING.remove(view)
    if holder is not None:
        holder.destroy()
