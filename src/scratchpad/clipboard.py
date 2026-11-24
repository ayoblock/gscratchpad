"""剪贴板写入的统一入口：所有复制动作都显式提供 UTF8_STRING 目标。

GTK4 的 ``Gdk.Clipboard.set(str)``（以及内置的 ``GtkTextBuffer.copy_clipboard()``）
只提供裸 ``text/plain`` 与 ``text/plain;charset=utf-8``。部分消费方（如 GNOME Shell
的剪贴板查看器）把裸 ``text/plain`` 按 Latin-1 解读，中文 UTF-8 字节会显示成
``\\E4\\BA\\8C`` 这类反斜杠转义。因此在保留兼容目标的前提下，显式把
``UTF8_STRING`` 放在最前，让支持它的消费方按 UTF-8 读取，逐字节保真。

本机 GTK 4.22 的 PyGObject 不暴露 ``Gdk.Clipboard.set_text()``（GIR 标为
``introspectable="0"``），故使用 ``set_content()`` + ``new_for_bytes()`` 实现
同等语义。
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib  # noqa: E402

# 三个目标都提供，顺序刻意把 UTF8_STRING 放最前：
# - UTF8_STRING / text/plain;charset=utf-8：按 UTF-8 读取的正确入口；
# - 裸 text/plain 必须提供：GtkTextView、GNOME Shell 等大量消费者只请求它。
#   仅提供前两个时，X11 后端虽会自动声明 text/plain，但实际无数据可传输，
#   消费者请求即报「没有相容格式」，表现为复制完全失效（v1.16.1 回归）。
# 注意：不能靠「拿掉 text/plain」规避 Latin-1 误读——那会直接让复制不可用。
_TARGETS = ("UTF8_STRING", "text/plain;charset=utf-8", "text/plain")


def set_clipboard_utf8(text: str, display: Gdk.Display | None = None) -> bool:
    """把 text 以显式 UTF-8 目标写入剪贴板；无 display 时返回 False。"""
    return set_clipboard_encoded(text, "utf-8", display)


def set_clipboard_encoded(text: str, encoding: str, display: Gdk.Display | None = None) -> bool:
    """按指定编码把 text 写入剪贴板（用于「复制为其它编码」菜单）。

    同时提供带 charset 的 MIME（让认识该 charset 的消费方正确解码）与裸
    text/plain（原始字节，兼容只认它的消费方）。utf-8 走本模块的默认三目标
    路径，保证 Ctrl+C 等默认复制行为不变。
    """
    if display is None:
        display = Gdk.Display.get_default()
    if display is None:
        return False
    if encoding.lower() in ("utf-8", "utf8"):
        data = GLib.Bytes.new(text.encode("utf-8"))
        providers = [Gdk.ContentProvider.new_for_bytes(t, data) for t in _TARGETS]
    else:
        data = GLib.Bytes.new(text.encode(encoding))
        providers = [
            Gdk.ContentProvider.new_for_bytes(
                f"text/plain;charset={encoding.lower()}", data
            ),
            Gdk.ContentProvider.new_for_bytes("text/plain", data),
        ]
    display.get_clipboard().set_content(Gdk.ContentProvider.new_union(providers))
    return True
