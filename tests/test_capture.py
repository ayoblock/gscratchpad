"""capture v1 纯逻辑单元测试。运行：/usr/bin/python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import io
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))

from scratchpad.capture import (  # noqa: E402
    EXIT_ARGS,
    EXIT_INVALID,
    CaptureError,
    _block,
    capture_document,
    run_capture_cli,
    validate,
)
from scratchpad.store import Store  # noqa: E402


class CaptureLogicTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sp-capture-"))
        self.store = Store(self.root)
        self.store.open()

    def tearDown(self) -> None:
        self.store.close()

    # ---- validate ----

    def test_reject_nul(self) -> None:
        with self.assertRaises(CaptureError) as cm:
            validate("a\x00b", "append")
        self.assertEqual(cm.exception.code, EXIT_INVALID)

    def test_reject_oversize(self) -> None:
        with self.assertRaises(CaptureError) as cm:
            validate("x" * (1024 * 1024 + 1), "append")
        self.assertEqual(cm.exception.code, EXIT_INVALID)

    def test_reject_blank_text(self) -> None:
        with self.assertRaises(CaptureError) as cm:
            validate("   \n", "append")
        self.assertEqual(cm.exception.code, EXIT_INVALID)

    def test_reject_bad_mode(self) -> None:
        with self.assertRaises(CaptureError) as cm:
            validate("hi", "update")
        self.assertEqual(cm.exception.code, EXIT_ARGS)

    def test_reject_key_with_space(self) -> None:
        with self.assertRaises(CaptureError) as cm:
            validate("hi", "append", key="lectula a b")
        self.assertEqual(cm.exception.code, EXIT_INVALID)

    # ---- create / 幂等 ----

    def test_create_defaults(self) -> None:
        now = time.mktime(time.strptime("2026-11-13 03:20", "%Y-%m-%d %H:%M"))
        doc_id, title, created = capture_document(
            self.store, text="第一条", book="三体", page="p.45", key="lectula:b1",
            mode="append", now=now,
        )
        self.assertTrue(created)
        self.assertEqual(title, "《三体》笔记")
        doc = self.store.get(doc_id)
        # 建档首块不带 --- 分隔
        self.assertEqual(
            doc.content,
            "> 《三体》 · p.45 · 2026-11-13 03:20\n\n第一条\n",
        )
        self.assertEqual(doc.format, "md")
        self.assertEqual(self.store.get_meta("ext:lectula:b1"), doc_id)
        # 镜像文件同步
        mirror = self.root / "notes" / f"{doc_id}.md"
        self.assertTrue(mirror.is_file())
        self.assertIn("第一条", mirror.read_text(encoding="utf-8"))

    def test_create_title_fallback_without_book(self) -> None:
        _, title, created = capture_document(
            self.store, text="速记内容", mode="append", now=0.0,
        )
        self.assertTrue(created)
        self.assertTrue(title.startswith("速记 "))
        self.assertNotIn("《", title)

    def test_create_idempotent_same_key(self) -> None:
        now = 0.0
        doc_id1, _, created1 = capture_document(
            self.store, text="first", book="书A", key="lectula:b1", mode="create", now=now,
        )
        self.assertTrue(created1)
        doc_id2, title2, created2 = capture_document(
            self.store, text="second", book="书B", title="新标题",
            key="lectula:b1", mode="create", now=now,
        )
        self.assertFalse(created2)
        self.assertEqual(doc_id1, doc_id2)
        # book/title 新值忽略，内容不变
        self.assertEqual(title2, "《书A》笔记")
        self.assertNotIn("second", self.store.get(doc_id1).content)

    def test_append_adds_separator_and_keeps_content(self) -> None:
        now1 = time.mktime(time.strptime("2026-11-13 03:20", "%Y-%m-%d %H:%M"))
        now2 = time.mktime(time.strptime("2026-11-13 04:00", "%Y-%m-%d %H:%M"))
        doc_id, _, created = capture_document(
            self.store, text="第一段", book="书A", page="p.1",
            key="lectula:b1", mode="append", now=now1,
        )
        self.assertTrue(created)
        capture_document(
            self.store, text="第二段", book="书A", page="p.2",
            key="lectula:b1", mode="append", now=now2,
        )
        content = self.store.get(doc_id).content
        self.assertIn("第一段", content)
        self.assertIn("\n---\n> 《书A》 · p.2 · 2026-11-13 04:00\n\n第二段\n", content)
        # revision 单调
        self.assertGreaterEqual(self.store.get(doc_id).revision, 2)

    def test_append_without_key_creates(self) -> None:
        doc_id, title, created = capture_document(
            self.store, text="临时记录", mode="append", now=0.0,
        )
        self.assertTrue(created)
        self.assertIsNone(self.store.get_meta("ext:"))
        self.assertTrue(title.startswith("速记 "))
        self.assertNotIn("《", title)

    def test_stale_meta_recreates(self) -> None:
        doc_id, _, _ = capture_document(
            self.store, text="a", book="书A", key="lectula:b1", mode="append", now=0.0,
        )
        self.store.delete_document(doc_id)
        doc_id2, _, created = capture_document(
            self.store, text="b", book="书A", key="lectula:b1", mode="append", now=0.0,
        )
        self.assertTrue(created)
        self.assertNotEqual(doc_id, doc_id2)
        self.assertEqual(self.store.get_meta("ext:lectula:b1"), doc_id2)

    def test_block_omits_empty_fields(self) -> None:
        self.assertEqual(
            _block("", "", "2026-01-01 00:00", "hi"),
            "> 2026-01-01 00:00\n\nhi\n",
        )

    # ---- CLI（本地分支，注入临时 Store，禁用转发） ----

    def _cli(self, argv: list[str], stdin: bytes | None = None) -> tuple[int, str]:
        err = io.StringIO()
        code = run_capture_cli(
            argv,
            stdin=io.BytesIO(stdin) if stdin is not None else None,
            stderr=err,
            allow_forward=False,
            store_factory=lambda: Store(self.root),
        )
        return code, err.getvalue()

    def test_cli_text_and_exit0(self) -> None:
        code, err = self._cli(
            ["--capture-text", "来自CLI", "--capture-book", "书A", "--capture-key", "c1"]
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.store.get_meta("ext:c1") is not None, True)

    def test_cli_stdin(self) -> None:
        code, err = self._cli(
            ["-", "--capture-key", "c2"], stdin="stdin 正文".encode("utf-8")
        )
        self.assertEqual(code, 0, err)
        doc_id = self.store.get_meta("ext:c2")
        self.assertIn("stdin 正文", self.store.get(doc_id).content)

    def test_cli_missing_text_source(self) -> None:
        code, _ = self._cli(["--capture-title", "x"])
        self.assertEqual(code, EXIT_ARGS)

    def test_cli_unknown_arg(self) -> None:
        code, _ = self._cli(["--capture-text", "hi", "--capture-wat", "x"])
        self.assertEqual(code, EXIT_ARGS)

    def test_cli_inline_equals_form(self) -> None:
        code, err = self._cli(["--capture-text=equals 正文", "--capture-key=c3"])
        self.assertEqual(code, 0, err)
        doc_id = self.store.get_meta("ext:c3")
        self.assertIn("equals 正文", self.store.get(doc_id).content)

    def test_cli_bad_mode_exit1(self) -> None:
        code, _ = self._cli(["--capture-text", "hi", "--capture-mode", "update"])
        self.assertEqual(code, EXIT_ARGS)

    def test_cli_nul_exit3(self) -> None:
        code, _ = self._cli(["--capture-text", "bad\x00text"])
        self.assertEqual(code, EXIT_INVALID)

    def test_cli_bad_utf8_exit3(self) -> None:
        code, _ = self._cli(["-"], stdin=b"\xff\xfe\xfa")
        self.assertEqual(code, EXIT_INVALID)

    def test_cli_stdin_forward_rewrites_to_text(self) -> None:
        """回执缺陷回归：实例在跑时 `-` 必须成功——调用方读尽 stdin，
        转发 argv 把 `-` 改写为 --capture-text（实例侧不依赖 stdin）。"""
        import scratchpad.capture as cap

        captured: list[list[str]] = []

        def fake_forward(argv, stderr):
            captured.append(list(argv))
            return 0  # 模拟运行中实例返回 0

        orig = cap._forward_via_dbus
        cap._forward_via_dbus = fake_forward
        try:
            err = io.StringIO()
            code = run_capture_cli(
                ["--capture-key", "f1", "-"],
                stdin=io.BytesIO("经转发的 stdin".encode("utf-8")),
                stderr=err,
                store_factory=lambda: Store(self.root),
            )
        finally:
            cap._forward_via_dbus = orig
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(
            captured,
            [["--capture-key", "f1", "--capture-text", "经转发的 stdin"]],
        )
        # 走了转发路径就不得本地落库（否则实例与调用方各写一份）
        self.assertIsNone(self.store.get_meta("ext:f1"))

    def test_cli_oversize_exit3(self) -> None:
        code, _ = self._cli(["--capture-text", "x" * (1024 * 1024 + 1)])
        self.assertEqual(code, EXIT_INVALID)


if __name__ == "__main__":
    unittest.main()
