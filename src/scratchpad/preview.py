"""WebKit 预览面板。

一个标签页对应一个 PreviewPane，WebView 延迟创建（只有真正用到预览时才占用进程），
并在预览不可见（切到源码模式、切到别的标签、窗口最小化）超过 IDLE_RELEASE_SECONDS
后主动销毁，释放 WebKitWebProcess 占用的内存；再次需要预览时按需重建。
渲染完全离线：KaTeX / Mermaid 均为本地文件，且按内容需要加载。
"""

from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Adw, GLib, GObject, Gtk, WebKit  # noqa: E402

from . import markdown_render, paths  # noqa: E402


def _idle_seconds() -> int:
    """空闲回收阈值（秒）。环境变量仅用于测试与调试。"""
    try:
        return max(1, int(os.environ.get("GSCRATCHPAD_PREVIEW_IDLE", "90")))
    except ValueError:
        return 90


class PreviewPane(Gtk.Box):
    """Markdown 预览视图。"""

    __gsignals__ = {
        "rendered": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._view: WebKit.WebView | None = None
        self._scroll = 0.0
        self._last_html: str | None = None
        self._last_base: str | None = None
        self._dark = False
        self._src_uri = (paths.data_root().as_uri() + "/")
        self._release_source: int | None = None
        self._pending_heading: int | None = None
        self._ready = False  # 页面脚本就绪前，大纲滚动先挂起

        self._placeholder = Gtk.Label(
            label="预览将在此处显示", css_classes=["dim-label"], vexpand=True, hexpand=True
        )
        self.append(self._placeholder)

        # 预览不可见时启动倒计时；重新可见则取消（若已回收则重新载入上次内容）
        self.connect("unmap", lambda *_: self._arm_release())
        self.connect("map", lambda *_: self._on_map())

    # ------------------------------------------------------------------ 内部

    def _ensure_view(self) -> WebKit.WebView:
        if self._view is not None:
            return self._view

        settings = WebKit.Settings()
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        settings.set_enable_developer_extras(False)
        settings.set_enable_webaudio(False)
        # 注意：不要设置 hardware_acceleration_policy=NEVER。
        # 实测 WebKitGTK 2.52 + 强制软件渲染会导致 WebView 屏幕完全不绘制（空白），
        # 保持默认策略才能正常显示；离线快照（PDF 导出）不受影响。

        manager = WebKit.UserContentManager()
        manager.register_script_message_handler("ready")
        manager.connect("script-message-received::ready", self._on_ready)

        view = WebKit.WebView(user_content_manager=manager)
        view.set_settings(settings)
        view.set_hexpand(True)
        view.set_vexpand(True)
        view.connect("decide-policy", self._on_decide_policy)
        view.connect("load-changed", self._on_load_changed)

        self._placeholder.set_visible(False)
        self.append(view)
        self._view = view
        return view

    def _on_decide_policy(self, _view, decision, decision_type) -> bool:
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            if action.is_user_gesture():
                uri = action.get_request().get_uri()
                if uri.startswith(("http://", "https://", "mailto:")):
                    Gtk.UriLauncher.new(uri).launch(self.get_root(), None, None, None)
                    return True
                if uri.startswith("file://"):
                    return True
        return False

    def _on_load_changed(self, view, event) -> None:
        if event == WebKit.LoadEvent.FINISHED and self._scroll > 0:
            self._restore_scroll()

    def _restore_scroll(self) -> None:
        if self._view is None:
            return
        self._view.evaluate_javascript(
            f"window.scrollTo(0, {self._scroll});", -1, None, None, None, None, None
        )

    def _on_ready(self, _manager, _result) -> None:
        self._ready = True
        self._restore_scroll()
        self._apply_pending_heading()
        self.emit("rendered")

    def scroll_to_heading(self, index: int) -> None:
        """滚动到第 index 个标题（侧栏大纲点击）。页面未就绪时挂起，ready 后执行。"""
        self._pending_heading = index
        if not self._ready:
            self.keep_alive()
            return
        self._apply_pending_heading()

    def _apply_pending_heading(self) -> None:
        if self._pending_heading is None or self._view is None or not self._ready:
            return
        index = self._pending_heading
        self._pending_heading = None
        self._view.evaluate_javascript(
            "window.gscratchpadScrollToHeading && "
            f"window.gscratchpadScrollToHeading({index});",
            -1, None, None, None, None, None,
        )

    # ------------------------------------------------------------ 内存回收

    def _on_map(self) -> None:
        self.keep_alive()

    def keep_alive(self) -> None:
        """预览重新可见：取消回收倒计时；若已被回收则重建视图并载入上次内容。"""
        self._disarm_release()
        if self._view is None and self._last_html is not None and self.get_mapped():
            view = self._ensure_view()
            self._ready = False
            view.load_html(self._last_html, self._last_base or self._src_uri)

    def schedule_release(self) -> None:
        """预览不再可见：开始空闲倒计时（外部显式调用，如切换标签）。"""
        self._arm_release()

    def _arm_release(self) -> None:
        """预览不可见时开始倒计时，到点销毁 WebView（进程随之退出）。"""
        if self._view is None or self._release_source is not None:
            return
        self._release_source = GLib.timeout_add_seconds(
            _idle_seconds(), self._on_release_timeout
        )

    def _disarm_release(self) -> None:
        if self._release_source is not None:
            GLib.source_remove(self._release_source)
            self._release_source = None

    def _on_release_timeout(self) -> bool:
        self._release_source = None
        self.release_view()
        return False

    def release_view(self) -> None:
        """销毁 WebView，释放 WebKitWebProcess；下次预览时按需重建。"""
        self._disarm_release()
        view = self._view
        if view is None:
            return
        self._view = None
        try:
            view.stop_loading()
        except Exception:  # noqa: BLE001 - 已销毁的视图无需处理
            pass
        try:
            self.remove(view)
        except Exception:  # noqa: BLE001
            pass
        self._placeholder.set_visible(True)

    @property
    def has_view(self) -> bool:
        return self._view is not None

    def release_pending(self) -> bool:
        """是否已进入空闲回收倒计时（供测试断言）。"""
        return self._release_source is not None

    # ------------------------------------------------------------------ 对外

    def set_dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark

    @property
    def dark(self) -> bool:
        return self._dark

    def render(self, text: str, fmt: str, *, force: bool = False,
               base_uri: str | None = None) -> None:
        """渲染文本。fmt='txt' 纯文本；fmt='html' 直接载入原文；其余按 Markdown。"""
        if fmt == "html":
            # 用户自己写的完整 HTML：原文载入，不做任何加工
            html = text
        elif fmt == "txt":
            body = f"<pre style='white-space:pre-wrap;font-family:inherit'>{_escape(text)}</pre>"
            html = markdown_render.wrap_plain(body, dark=self._dark)
        else:
            html = markdown_render.render_document(text, dark=self._dark)

        self._last_html = html
        self._last_base = base_uri or self._src_uri

        if not self.get_mapped():
            # 面板当前不可见（标签切走了 / 已切到源码模式）：只缓存内容，
            # 不创建也不刷新 WebView；重新可见时由 map/keep_alive 载入。
            # 这样后台标签的延迟刷新不会把刚回收的进程又拉起来。
            if self._view is not None:
                self._arm_release()
            return

        self._disarm_release()
        view = self._ensure_view()
        # 记录滚动位置，避免每次重新加载跳回顶部；新页面 ready 前大纲滚动先挂起
        self._ready = False
        view.evaluate_javascript(
            "window.scrollY", -1, None, None, None, self._on_scroll_read, None
        )
        view.load_html(html, self._last_base)

    def _on_scroll_read(self, view, result, _data) -> None:
        try:
            value = view.evaluate_javascript_finish(result)
            if value is not None and not value.is_undefined() and not value.is_null():
                self._scroll = float(value.to_double())
        except GLib.Error:
            self._scroll = 0.0

    def scroll_to_top(self) -> None:
        self._scroll = 0.0
        self._restore_scroll()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
