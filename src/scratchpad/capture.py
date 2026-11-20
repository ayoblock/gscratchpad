"""外部应用捕获接口（capture v1）。

供其它应用（如 Lectula 阅读器）把笔记写入本程序。纯写方向：无读取/更新/删除接口。

调用通道（语义等价）：
- D-Bus action ``capture``，参数 GVariant ``(ssssss)``，
  字段依次为 text, title, book, page, key, mode。
  注意动作名**不带** ``app.`` 前缀：``org.gtk.Actions`` 总线接口导出的动作名
  是裸名 ``capture``（``app.capture`` 是进程内 ``activate_action`` 的写法）；
- 命令行 ``gscratchpad --capture-title <s> ... (- | --capture-text <s>)``。

契约 v1.1（勿破坏）：
- key 全局唯一，调用方必须自带命名空间前缀（如 ``lectula:<book-id>``）；
- 文档身份由 key 决定：同 key 的 create 幂等返回既有文档；
  book/title 仅首次建档生效，后续调用传入的新值忽略；
- book/page 传裸内容：book 不带 ``《》``（引用行的书名号由本程序添加）；
- append 永不覆盖既有内容，块分隔符为行首独立一行 ``---``（永久约定）；
- 正文上限 1MB，禁止 NUL 字符；mode 缺省为 append；
- CLI 退出码：0 成功 / 1 参数错误 / 2 服务不可达 / 3 校验失败 / 4 落盘异常；
- CLI ``-``（stdin）在实例运行时同样可用：调用方先读完 stdin，
  转发前改写为 ``--capture-text``（实例侧永远不需要 stdin）。
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from typing import Callable

from . import paths
from .store import Store

MAX_TEXT_BYTES = 1024 * 1024
MODES = ("create", "append")
_KEY_MAX = 256
_TITLE_MAX = 200

EXIT_OK = 0
EXIT_ARGS = 1
EXIT_UNAVAILABLE = 2
EXIT_INVALID = 3
EXIT_STORE = 4

_CAPTURE_OPTIONS = (
    "--capture-title",
    "--capture-book",
    "--capture-page",
    "--capture-key",
    "--capture-mode",
    "--capture-text",
)


class CaptureError(Exception):
    """捕获失败。code 即 CLI 退出码：1 参数错误、3 校验失败、4 落盘异常。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ext_key(key: str) -> str:
    return f"ext:{key}"


def _timestamp(now: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(now))


def _block(book: str, page: str, stamp: str, text: str) -> str:
    """追加块的引用行 + 正文，以换行结尾。引用行只由非空字段组成。"""
    parts: list[str] = []
    if book:
        parts.append(f"《{book}》")
    if page:
        parts.append(page)
    parts.append(stamp)
    body = text.rstrip("\n")
    return "> " + " · ".join(parts) + "\n\n" + body + "\n"


def validate(
    text: str,
    mode: str,
    key: str = "",
    title: str = "",
) -> None:
    """契约校验。mode 错误算参数错误（1），内容问题算校验失败（3）。"""
    if not isinstance(text, str):
        raise CaptureError(EXIT_INVALID, "正文必须是字符串")
    if mode not in MODES:
        raise CaptureError(EXIT_ARGS, f"mode 必须是 create/append，收到 {mode!r}")
    if "\x00" in text:
        raise CaptureError(EXIT_INVALID, "正文包含 NUL 字符")
    if not text.strip():
        raise CaptureError(EXIT_INVALID, "正文为空")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise CaptureError(EXIT_INVALID, "正文超过 1MB 上限")
    key = key or ""
    if len(key) > _KEY_MAX:
        raise CaptureError(EXIT_INVALID, f"key 超过 {_KEY_MAX} 字符")
    if any(ch.isspace() for ch in key):
        raise CaptureError(EXIT_INVALID, "key 不得包含空白字符")
    if len((title or "").strip()) > _TITLE_MAX:
        raise CaptureError(EXIT_INVALID, f"title 超过 {_TITLE_MAX} 字符")


def capture_document(
    store: Store,
    *,
    text: str,
    title: str = "",
    book: str = "",
    page: str = "",
    key: str = "",
    mode: str = "append",
    now: float | None = None,
) -> tuple[str, str, bool]:
    """执行捕获，返回 (doc_id, doc_title, created)。

    key 命中既有文档且 mode=create → 幂等返回，不写内容；
    key 命中且 mode=append → 在文末追加（行首 --- 分隔）；
    无 key / key 无锚点 → 建新文档（append 的首块不带 ---）。
    """
    validate(text, mode, key=key, title=title)
    title = (title or "").strip()[:_TITLE_MAX]
    book = (book or "").strip()
    page = (page or "").strip()
    key = (key or "").strip()
    now = time.time() if now is None else now
    stamp = _timestamp(now)

    doc = None
    if key:
        mapped = store.get_meta(_ext_key(key))
        if mapped:
            doc = store.get(mapped)  # meta 可能指向已删除文档

    created = False
    if doc is not None and mode == "create":
        # 幂等：文档身份由 key 决定，book/title 新值忽略
        return doc.id, doc.title, False

    if doc is None:
        if not title:
            title = f"《{book}》笔记" if book else f"速记 {stamp[5:]}"
        doc = store.create_document("md", title)
        created = True
        body = _block(book, page, stamp, text)
    else:
        head = doc.content
        if head and not head.endswith("\n"):
            head += "\n"
        body = head + "\n---\n" + _block(book, page, stamp, text)

    new_rev = doc.revision + 1
    store.submit_save(
        replace(doc, content=body, revision=new_rev, updated_at=now), wait=True
    )
    after = store.get(doc.id)
    if after is None or after.revision < new_rev:
        raise CaptureError(EXIT_STORE, "落盘失败：revision 未推进（可能被并发保存合并）")

    if key:
        store.set_meta(_ext_key(key), doc.id, wait=True)
    return doc.id, after.title, created


def _parse_cli(argv: list[str], stderr) -> dict | None:
    """解析 --capture-* 参数。返回 None 表示参数错误（已打印原因）。"""
    values: dict[str, str] = {"mode": "append"}
    dash_stdin = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-":
            dash_stdin = True
            i += 1
            continue
        if not arg.startswith("--capture-"):
            print(f"gscratchpad: 未知参数 {arg!r}", file=stderr)
            return None
        name, sep, inline = arg[len("--capture-") :].partition("=")
        if sep:
            values[name] = inline
            i += 1
            continue
        if name not in ("title", "book", "page", "key", "mode", "text"):
            print(f"gscratchpad: 未知参数 {arg!r}", file=stderr)
            return None
        if i + 1 >= len(argv):
            print(f"gscratchpad: {arg} 缺少取值", file=stderr)
            return None
        values[name] = argv[i + 1]
        i += 2
    values["_dash_stdin"] = dash_stdin
    return values


def _bus_name() -> str:
    return paths.APP_ID


def _bus_path() -> str:
    return "/" + paths.APP_ID.replace(".", "/")


def _forward_via_dbus(argv: list[str], stderr) -> int | None:
    """转发给运行中的主实例（org.freedesktop.Application.CommandLine）。

    返回 None 表示总线名无人持有（未运行）→ 调用方走本地落库。
    转发失败（旧版本在跑 / D-Bus 异常）→ 返回 EXIT_UNAVAILABLE，
    绝不回退本地直写：那会绕开正在运行的实例、写出另一份数据。
    """
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except Exception as exc:  # noqa: BLE001
        print(f"gscratchpad: D-Bus 不可用，无法转发：{exc}", file=stderr)
        return EXIT_UNAVAILABLE

    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        owned = connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (_bus_name(),)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        if not owned.unpack()[0]:
            return None
        # org.gtk.Application.CommandLine: (o path, aay arguments, a{sv} platform) -> (i)
        # 本机 gio 导出的 CommandLine 在 org.gtk.Application 上；
        # org.freedesktop.Application 只有 Activate/Open/ActivateAction。
        # 注意：aay 元素是「带 NUL 终止符的 bytestring」——必须用
        # new_bytestring（不带 NUL 时服务端 ^aay 解出越界垃圾串）；
        # arguments 需含 argv[0] 程序名占位，与 gio 客户端行为一致。
        arg_vars = [
            GLib.Variant.new_bytestring(a.encode("utf-8"))
            for a in ["gscratchpad", *argv]
        ]
        result = connection.call_sync(
            _bus_name(),
            _bus_path(),
            "org.gtk.Application",
            "CommandLine",
            GLib.Variant("(oaaya{sv})", ("/", arg_vars, {})),
            GLib.VariantType("(i)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return int(result.unpack()[0])
    except GLib.Error as exc:  # noqa: F821
        print(f"gscratchpad: 转发到运行中的实例失败：{exc}", file=stderr)
        return EXIT_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001
        print(f"gscratchpad: 转发失败：{exc}", file=stderr)
        return EXIT_UNAVAILABLE


def run_capture_cli(
    argv: list[str],
    *,
    stdin=None,
    stdout=sys.stdout,
    stderr=sys.stderr,
    allow_forward: bool = True,
    store_factory: Callable[[], Store] | None = None,
    close_store: bool = True,
) -> int:
    """CLI 捕获入口，返回退出码。

    store_factory 供测试/主实例注入既有 Store；close_store=False 时
    调用方负责关闭（主实例复用自己的写线程，绝不能关）。
    allow_forward=False 供主实例自身（do_command_line）调用，避免自转发。
    """
    parsed = _parse_cli(argv, stderr)
    if parsed is None:
        return EXIT_ARGS

    text = parsed.get("text")
    if text is None:
        if parsed["_dash_stdin"]:
            # stdin 必须在调用方侧读完（含转发场景）：实例侧进程没有可靠的
            # stdin，转发的也是文本参数而非文件描述符
            data = (stdin or sys.stdin.buffer).read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                print(f"gscratchpad: 正文不是有效 UTF-8：{exc}", file=stderr)
                return EXIT_INVALID
        elif stdin is None and not allow_forward:
            # 防御分支：外来客户端直发 `-` 到实例 CommandLine（自身不会构造）
            print("gscratchpad: 实例侧转发通道无 stdin，请使用 --capture-text", file=stderr)
            return EXIT_ARGS
        else:
            print("gscratchpad: 缺少正文来源（--capture-text <s> 或 - 读 stdin）", file=stderr)
            return EXIT_ARGS

    mode = parsed.get("mode", "append")
    try:
        validate(text, mode, key=parsed.get("key", ""), title=parsed.get("title", ""))
    except CaptureError as exc:
        print(f"gscratchpad: {exc}", file=stderr)
        return exc.code

    if allow_forward:
        # stdin 已在调用方读尽：转发时把 `-` 改写为 --capture-text，
        # 实例侧只收文本参数（回执缺陷修复：原先实例收 `-` 无 stdin，
        # exit 1 的原因写在实例进程 stderr，调用方管道里看不到）
        forward_argv = [a for a in argv if a != "-"]
        if parsed["_dash_stdin"] and "text" not in parsed:
            forward_argv += ["--capture-text", text]
        forwarded = _forward_via_dbus(forward_argv, stderr)
        if forwarded is not None:
            return forwarded
        # 无人持有总线名 → 本地直落（此时没有实例在跑，写真实数据目录是期望行为）

    try:
        if store_factory is not None:
            store = store_factory()
        else:
            from . import paths

            store = Store(paths.data_root())
        store.open()
    except Exception as exc:  # noqa: BLE001
        print(f"gscratchpad: 数据目录不可用：{exc}", file=stderr)
        return EXIT_UNAVAILABLE

    try:
        capture_document(
            store,
            text=text,
            title=parsed.get("title", ""),
            book=parsed.get("book", ""),
            page=parsed.get("page", ""),
            key=parsed.get("key", ""),
            mode=mode,
        )
    except CaptureError as exc:
        print(f"gscratchpad: {exc}", file=stderr)
        return exc.code
    finally:
        if close_store:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass
    return EXIT_OK
