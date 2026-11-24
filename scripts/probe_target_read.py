"""验证各 target 在同进程 read_async 下是否真能读到数据。"""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

SAMPLE = "中文测试 abc 二房"
mode = sys.argv[1]
win = Gtk.Window(title="probe")
win.present()
clip = Gdk.Display.get_default().get_clipboard()

if mode == "union_no_plain":
    data = GLib.Bytes.new(SAMPLE.encode("utf-8"))
    clip.set_content(
        Gdk.ContentProvider.new_union(
            [
                Gdk.ContentProvider.new_for_bytes("UTF8_STRING", data),
                Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", data),
            ]
        )
    )
else:
    data = GLib.Bytes.new(SAMPLE.encode("utf-8"))
    clip.set_content(
        Gdk.ContentProvider.new_union(
            [
                Gdk.ContentProvider.new_for_bytes("text/plain", data),
                Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", data),
                Gdk.ContentProvider.new_for_bytes("UTF8_STRING", data),
            ]
        )
    )

print(f"[{mode}] formats:", sorted(clip.get_formats().get_mime_types()), flush=True)
TARGETS = ["text/plain", "STRING", "UTF8_STRING", "text/plain;charset=utf-8"]
loop = GLib.MainLoop()
idx = 0


def next_target() -> None:
    global idx
    if idx >= len(TARGETS):
        loop.quit()
        return
    target = TARGETS[idx]
    idx += 1
    clip.read_async([target], 0, None, lambda cb, res: done(target, cb, res))


def done(target: str, cb, res) -> None:
    try:
        stream, mime = cb.read_finish(res)
        buf = stream.read(4096)
        raw = bytes(buf.get_data()) if hasattr(buf, "get_data") else b""
        print(f"  {target}: mime={mime} raw={raw[:60]!r}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  {target}: ERROR {exc}", flush=True)
    GLib.idle_add(next_target)


GLib.timeout_add(400, next_target)
loop.run()
