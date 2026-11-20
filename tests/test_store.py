"""持久化层单元测试。运行：/usr/bin/python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))

from scratchpad.store import Document, Store, replace  # noqa: E402


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sp-unit-"))
        self.store = Store(self.root)
        self.store.open()

    def tearDown(self) -> None:
        self.store.close()

    def test_create_and_restore(self) -> None:
        doc = self.store.create_document("txt", "标题")
        self.store.submit_save(replace(doc, content="hello", revision=doc.revision + 1), wait=True)
        self.store.close()
        store2 = Store(self.root)
        store2.open()
        docs = store2.open_documents()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].content, "hello")
        self.assertEqual(docs[0].title, "标题")
        store2.close()

    def test_revision_monotonic(self) -> None:
        doc = self.store.create_document("txt")
        old = replace(doc, content="old", revision=1)
        new = replace(doc, content="new", revision=2)
        self.store.submit_save(new, wait=True)
        self.store.submit_save(old, wait=True)  # 晚到的旧快照必须被丢弃
        self.assertEqual(self.store.get(doc.id).content, "new")

    def test_close_keeps_document(self) -> None:
        doc = self.store.create_document("txt")
        self.store.submit_save(replace(doc, content="内容", revision=2), wait=True)
        self.store.set_state(doc.id, "closed")
        self.assertEqual(self.store.open_documents(), [])
        self.assertEqual(len(self.store.all_documents()), 1)
        self.assertEqual(self.store.get(doc.id).state, "closed")

    def test_reorder(self) -> None:
        a = self.store.create_document("txt")
        b = self.store.create_document("md")
        c = self.store.create_document("txt")
        self.store.reorder([c.id, a.id, b.id], wait=True)
        order = [d.id for d in self.store.open_documents()]
        self.assertEqual(order, [c.id, a.id, b.id])

    def test_format_switch_mirrors(self) -> None:
        doc = self.store.create_document("txt")
        self.store.submit_save(replace(doc, content="x", format="md", revision=2), wait=True)
        notes = list((self.root / "notes").iterdir())
        self.assertEqual([p.suffix for p in notes], [".md"])

    def test_journal_recovery(self) -> None:
        """模拟崩溃：journal 已写入但 SQLite 提交未完成。"""
        doc = self.store.create_document("txt")
        self.store.submit_save(replace(doc, content="v1", revision=2), wait=True)
        journal = self.root / "recovery" / f"{doc.id}.json"
        journal.write_text(
            json.dumps({"id": doc.id, "revision": 5, "content": "v5-recovered", "ts": 0}),
            encoding="utf-8",
        )
        self.store.close()
        store2 = Store(self.root)
        notes = store2.open()
        self.assertTrue(any("还原" in n for n in notes))
        self.assertEqual(store2.get(doc.id).content, "v5-recovered")
        self.assertFalse(journal.exists())
        store2.close()

    def test_word_count_mixed(self) -> None:
        doc = Document(id="x", title="t", format="txt", content="hello 世界 foo")
        self.assertEqual(doc.char_count, 12)
        self.assertEqual(doc.word_count, 4)  # hello, 世, 界, foo

    def test_delete_document(self) -> None:
        doc = self.store.create_document("md")
        self.store.submit_save(replace(doc, content="![](assets/x/p.png)", revision=2), wait=True)
        asset_dir = self.root / "assets" / doc.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "p.png").write_bytes(b"png")
        self.store.delete_document(doc.id)
        self.assertIsNone(self.store.get(doc.id))
        self.assertFalse(asset_dir.exists())
        self.assertFalse((self.root / "notes" / f"{doc.id}.md").exists())


if __name__ == "__main__":
    unittest.main()
