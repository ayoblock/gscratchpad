"""批量清除与数据目录维护的单元测试。

运行：GI_TYPELIB_PATH=vendor/gir/local:/usr/lib/x86_64-linux-gnu/girepository-1.0 \
      /usr/bin/python3 -m unittest tests.test_maintenance -v

全部使用临时数据目录，不触碰真实数据。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))

from scratchpad.store import Store, replace  # noqa: E402


class MaintenanceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sp-maint-"))
        self.store = Store(self.root)
        self.store.open()
        self.notes = self.root / "notes"
        self.assets = self.root / "assets"
        self.recovery = self.root / "recovery"

    def tearDown(self) -> None:
        self.store.close()

    # ---- 工具 ----

    def _doc(self, fmt: str = "md", title: str = "标题", text: str = "") -> str:
        doc = self.store.create_document(fmt, title)
        if text:
            self.store.submit_save(
                replace(doc, content=text, revision=doc.revision + 1), wait=True
            )
        return doc.id

    def _close(self, doc_id: str) -> None:
        self.store.set_state(doc_id, "closed")

    def _freelist(self) -> int:
        return int(self.store._query_one("PRAGMA freelist_count")[0])

    # ---- 批量清除 ----

    def test_purge_only_closed_and_cleans_files(self) -> None:
        keep = self._doc("md", "保留", "保留内容")
        gone = self._doc("md", "关闭的", "关闭内容" * 100)
        self._close(gone)
        (self.assets / gone).mkdir(parents=True, exist_ok=True)
        (self.assets / gone / "a.png").write_bytes(b"x" * 2048)
        self.store.set_meta(f"cursor:{gone}", "3:5", wait=True)
        self.store.set_meta(f"source_path:{gone}", "/tmp/x.md", wait=True)
        self.store.set_meta("ext:lectula:book1", gone, wait=True)

        report = self.store.purge_closed_documents()

        self.assertEqual(report.purged_docs, 1)
        self.assertGreater(report.purged_bytes, 0)
        self.assertIsNotNone(self.store.get(keep))
        self.assertIsNone(self.store.get(gone))
        self.assertTrue((self.notes / f"{keep}.md").is_file())
        self.assertFalse((self.notes / f"{gone}.md").exists())
        self.assertFalse((self.assets / gone).exists())
        self.assertIsNone(self.store.get_meta(f"cursor:{gone}"))
        self.assertIsNone(self.store.get_meta(f"source_path:{gone}"))
        self.assertIsNone(self.store.get_meta("ext:lectula:book1"))
        self.assertEqual(report.errors, [])

    def test_purge_keep_ids_skips_open_page(self) -> None:
        closed = self._doc("txt", "关闭", "x")
        self._close(closed)
        report = self.store.purge_closed_documents(keep_ids={closed})
        self.assertEqual(report.purged_docs, 0)
        self.assertIsNotNone(self.store.get(closed))

    def test_purge_noop_when_no_closed(self) -> None:
        self._doc("md", "开着", "y")
        report = self.store.purge_closed_documents()
        self.assertEqual(report.purged_docs, 0)
        self.assertEqual(report.errors, [])

    # ---- 孤儿扫描 ----

    def test_scan_counts_orphans_and_stale_meta(self) -> None:
        live = self._doc("md", "有效", "z")
        (self.notes / "deadbeefdeadbeefdeadbeefdeadbeef.md").write_text("孤儿", encoding="utf-8")
        (self.assets / "deadbeefdeadbeefdeadbeefdeadbeef").mkdir()
        (self.assets / "deadbeefdeadbeefdeadbeefdeadbeef" / "p.png").write_bytes(b"p" * 500)
        (self.recovery / "deadbeefdeadbeefdeadbeefdeadbeef.json").write_text("{}", encoding="utf-8")
        self.store.set_meta("ext:lectula:ghost", "not-a-doc", wait=True)
        self.store.set_meta("cursor:not-a-doc", "1:1", wait=True)
        self.store.set_meta("sidebar_visible", "1", wait=True)

        scan = self.store.scan_orphans()

        self.assertEqual(scan.orphan_notes, 1)
        self.assertGreaterEqual(scan.orphan_notes_bytes, 0)
        self.assertEqual(scan.orphan_assets, 1)
        self.assertGreater(scan.orphan_assets_bytes, 0)
        self.assertEqual(scan.orphan_journals, 1)
        self.assertEqual(scan.stale_meta, 2)
        self.assertTrue((self.notes / f"{live}.md").is_file())

    def test_scan_ignores_fresh_tmp_and_counts_stale_tmp(self) -> None:
        fresh = self.notes / "abc.def.txt.tmp"
        fresh.write_text("正在写", encoding="utf-8")
        stale = self.notes / "def.ghi.md.tmp"
        stale.write_text("残留", encoding="utf-8")
        os.utime(stale, (0, 0))

        scan = self.store.scan_orphans()
        self.assertEqual(scan.orphan_notes, 1)  # 只算过期 tmp

    # ---- 清理执行 ----

    def test_maintain_removes_orphans_keeps_live(self) -> None:
        live = self._doc("md", "有效", "内容")
        (self.notes / "deadbeef.md").write_text("孤儿", encoding="utf-8")
        (self.assets / "deadbeef").mkdir()
        (self.assets / live).mkdir()
        (self.assets / live / "keep.png").write_bytes(b"k" * 100)
        (self.recovery / "deadbeef.json").write_text("{}", encoding="utf-8")

        report = self.store.maintain(vacuum=False)

        self.assertEqual(report.orphan_notes, 1)
        self.assertEqual(report.orphan_assets, 1)
        self.assertEqual(report.orphan_journals, 1)
        self.assertFalse((self.notes / "deadbeef.md").exists())
        self.assertFalse((self.assets / "deadbeef").exists())
        self.assertFalse((self.recovery / "deadbeef.json").exists())
        self.assertTrue((self.notes / f"{live}.md").is_file())
        self.assertTrue((self.assets / live / "keep.png").is_file())

    def test_maintain_does_not_follow_symlinks(self) -> None:
        outside = self.root.parent / f"outside-{os.getpid()}.txt"
        outside.write_text("用户文件", encoding="utf-8")
        link = self.notes / "deadbeef.md"
        link.symlink_to(outside)
        outside_dir = self.root.parent / f"outside-dir-{os.getpid()}"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "u.png").write_bytes(b"u")
        dir_link = self.assets / "deadbeef"
        dir_link.symlink_to(outside_dir, target_is_directory=True)

        report = self.store.maintain(vacuum=False)

        self.assertTrue(outside.is_file(), "符号链接目标不得被删除")
        self.assertEqual(outside.read_text(encoding="utf-8"), "用户文件")
        self.assertTrue((outside_dir / "u.png").is_file())
        self.assertFalse(link.is_symlink())
        self.assertFalse(dir_link.is_symlink())
        self.assertEqual(report.errors, [])
        outside.unlink()
        (outside_dir / "u.png").unlink()
        outside_dir.rmdir()

    def test_maintain_ignores_unknown_paths_outside_data_dir(self) -> None:
        (self.root / "notes-backup.md").write_text("不该动", encoding="utf-8")
        self.store.maintain(vacuum=False)
        self.assertTrue((self.root / "notes-backup.md").is_file())

    def test_vacuum_reclaims_free_pages(self) -> None:
        big = self._doc("md", "大文档", "x" * (512 * 1024))
        self.store.delete_document(big)
        self.assertGreater(self._freelist(), 0)

        report = self.store.maintain(vacuum=True)

        self.assertTrue(report.vacuumed)
        self.assertEqual(self._freelist(), 0)
        self.assertLessEqual(report.db_bytes_after, report.db_bytes_before)


if __name__ == "__main__":
    unittest.main()
