"""capture v1 端到端测试：真实 GApplication 实例 + D-Bus action + CLI 转发。

运行：GI_TYPELIB_PATH=vendor/gir/local:/usr/lib/x86_64-linux-gnu/girepository-1.0 \\
      /usr/bin/python3 -m unittest tests.test_capture_e2e -v

实例与 CLI 子进程使用独立 APP_ID（test.io.gscratchpad.Capture）与独立
XDG_DATA_HOME，绝不触碰真实数据目录。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

APP_ID = "test.io.gscratchpad.Capture"
BUS_PATH = "/" + APP_ID.replace(".", "/")
_env = {
    **os.environ,
    "PYTHONPATH": f"{PROJECT / 'src'}:{PROJECT / 'vendor'}",
}

_LAUNCHER = f"""
import sys
sys.path.insert(0, {str(PROJECT / 'src')!r})
sys.path.insert(0, {str(PROJECT / 'vendor')!r})
from scratchpad import paths
paths.APP_ID = {APP_ID!r}
from scratchpad.application import main
sys.exit(main())
"""

_CLI_LAUNCHER = f"""
import sys
sys.path.insert(0, {str(PROJECT / 'src')!r})
sys.path.insert(0, {str(PROJECT / 'vendor')!r})
from scratchpad import paths
paths.APP_ID = {APP_ID!r}
from scratchpad.capture import run_capture_cli
sys.exit(run_capture_cli(sys.argv[1:]))
"""


class CaptureE2ETestCase(unittest.TestCase):
    proc: subprocess.Popen | None = None
    tmp: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="sp-capture-e2e-"))
        env = {**_env, "XDG_DATA_HOME": str(cls.tmp)}
        cls.proc = subprocess.Popen(
            [sys.executable, "-c", _LAUNCHER],
            env=env,
            cwd=str(PROJECT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cls._wait_name_owned()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc is not None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        # 实例可能还握着 DB，稍等释放
        time.sleep(0.5)

    @classmethod
    def _wait_name_owned(cls) -> None:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        deadline = time.time() + 15.0
        while time.time() < deadline:
            result = connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameHasOwner",
                GLib.Variant("(s)", (APP_ID,)),
                GLib.VariantType("(b)"),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            if result.unpack()[0]:
                return
            if cls.proc.poll() is not None:
                out, err = cls.proc.communicate()
                raise AssertionError(
                    f"实例提前退出（code {cls.proc.returncode}）：{err.decode()[:500]}"
                )
            time.sleep(0.15)
        raise AssertionError("15s 内实例未注册 D-Bus 名")

    # ---- 工具 ----

    def _call(self, interface: str, method: str, params: GLib.Variant,
              reply: str | None = None, timeout: int = -1) -> GLib.Variant:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return connection.call_sync(
            APP_ID, BUS_PATH, interface, method, params,
            GLib.VariantType(reply) if reply else None,
            Gio.DBusCallFlags.NONE, timeout, None,
        )

    def _activate_capture(self, text, title="", book="", page="",
                          key="", mode="append") -> None:
        parameter = GLib.Variant("(ssssss)", (text, title, book, page, key, mode))
        self._call(
            "org.gtk.Actions", "Activate",
            GLib.Variant("(sava{sv})", ("capture", [parameter], {})),
            timeout=10000,
        )

    def _db(self) -> sqlite3.Connection:
        db = self.tmp / "gscratchpad" / "gscratchpad.db"
        self.assertTrue(db.is_file(), f"DB 未生成：{db}")
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _poll_meta(self, key: str, timeout: float = 5.0) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            conn = self._db()
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key=?", (key,)
                ).fetchone()
                if row:
                    return row["value"]
            finally:
                conn.close()
            time.sleep(0.1)
        return None

    # ---- 用例 ----

    def test_describe_all_exposes_capture(self) -> None:
        # DescribeAll 返回 a{s(bgav)} 字典（本机 gio 实测，非文档旧式 a(savbg)）；
        # call_sync 的 reply_type 必须是含全部出参的元组类型
        result = self._call(
            "org.gtk.Actions", "DescribeAll", None, reply="(a{s(bgav)})"
        )
        names = result.unpack()[0].keys()
        self.assertIn("capture", names)

    def test_dbus_capture_create_and_idempotent(self) -> None:
        self._activate_capture("e2e 第一条", book="e2e 书", page="p.1",
                               key="lectula:e2e1", mode="append")
        doc_id = self._poll_meta("ext:lectula:e2e1")
        self.assertIsNotNone(doc_id, "capture 后 meta 未出现")
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["title"], "《e2e 书》笔记")
            self.assertEqual(row["format"], "md")
            self.assertIn("> 《e2e 书》 · p.1 ·", row["content"])
            self.assertIn("e2e 第一条", row["content"])
            mirror = self.tmp / "gscratchpad" / "notes" / f"{doc_id}.md"
            self.assertTrue(mirror.is_file())
        finally:
            conn.close()
        # 幂等：同 key create 不新建
        before = self._poll_meta("ext:lectula:e2e1")
        self._activate_capture("不应出现", key="lectula:e2e1", mode="create")
        after = self._poll_meta("ext:lectula:e2e1")
        self.assertEqual(before, after)
        conn = self._db()
        try:
            content = conn.execute(
                "SELECT content FROM documents WHERE id=?", (doc_id,)
            ).fetchone()["content"]
            self.assertNotIn("不应出现", content)
        finally:
            conn.close()

    def test_dbus_capture_append_format(self) -> None:
        self._activate_capture("首块", book="追加书", key="lectula:e2e2", mode="append")
        doc_id = self._poll_meta("ext:lectula:e2e2")
        self.assertIsNotNone(doc_id)
        self._activate_capture("次块", book="追加书", page="p.9",
                               key="lectula:e2e2", mode="append")
        conn = self._db()
        try:
            content = conn.execute(
                "SELECT content FROM documents WHERE id=?", (doc_id,)
            ).fetchone()["content"]
        finally:
            conn.close()
        self.assertIn("首块", content)
        self.assertRegex(content, r"\n---\n> 《追加书》 · p\.9 · \d{4}-\d{2}-\d{2} \d{2}:\d{2}\n\n次块\n")

    def test_dbus_capture_invalid_text_no_doc(self) -> None:
        before = self._count_docs()
        # 超限文本（1MB+1）：action 无返回值通道，失败只 toast/stderr，不得落库。
        # 注：D-Bus 协议的 s 类型禁止内嵌 NUL，NUL 拒绝路径由 CLI/stdin 单测覆盖。
        self._activate_capture("x" * (1024 * 1024 + 1),
                               key="lectula:invalid", mode="append")
        time.sleep(0.5)
        self.assertIsNone(self._poll_meta("ext:lectula:invalid", timeout=1.0))
        self.assertEqual(self._count_docs(), before)

    def _count_docs(self) -> int:
        conn = self._db()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        finally:
            conn.close()

    def test_cli_forward_exit0_and_exit3(self) -> None:
        env = {**_env, "XDG_DATA_HOME": str(self.tmp)}
        # 转发成功：exit 0，落到运行中实例的数据目录
        result = subprocess.run(
            [sys.executable, "-c", _CLI_LAUNCHER,
             "--capture-text", "CLI 转发正文", "--capture-key", "lectula:cli1"],
            env=env, cwd=str(PROJECT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        doc_id = self._poll_meta("ext:lectula:cli1")
        self.assertIsNotNone(doc_id)
        # 回执缺陷回归：实例在跑时 stdin `-` 必须成功（v1.6.0 会静默 exit 1）
        result = subprocess.run(
            [sys.executable, "-c", _CLI_LAUNCHER, "-", "--capture-key", "lectula:cli2"],
            input="stdin 转发正文".encode("utf-8"),
            env=env, cwd=str(PROJECT), capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        doc_id = self._poll_meta("ext:lectula:cli2")
        self.assertIsNotNone(doc_id)
        conn = self._db()
        try:
            content = conn.execute(
                "SELECT content FROM documents WHERE id=?", (doc_id,)
            ).fetchone()["content"]
        finally:
            conn.close()
        self.assertIn("stdin 转发正文", content)
        # 校验失败：本地预检直接退出 3，不触碰实例（NUL 经 stdin 传入，argv 不能含 \x00）
        result = subprocess.run(
            [sys.executable, "-c", _CLI_LAUNCHER, "-"],
            input=b"bad\x00text",
            env=env, cwd=str(PROJECT), capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        # 未知参数：exit 1
        result = subprocess.run(
            [sys.executable, "-c", _CLI_LAUNCHER, "--capture-wat", "x"],
            env=env, cwd=str(PROJECT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 1, result.stderr)


if __name__ == "__main__":
    unittest.main()
