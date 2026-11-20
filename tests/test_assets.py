"""图片相对引用计算（assets.relative_image_ref）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scratchpad import assets  # noqa: E402


class RelativeImageRefTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def test_same_directory(self) -> None:
        doc = self.touch("notes/a.md")
        img = self.touch("notes/pic.png")
        self.assertEqual(assets.relative_image_ref(doc, img), ("pic.png", "pic"))

    def test_parent_directory(self) -> None:
        doc = self.touch("notes/2026/a.md")
        img = self.touch("notes/024907.png")
        self.assertEqual(assets.relative_image_ref(doc, img), ("../024907.png", "024907"))

    def test_subdirectory(self) -> None:
        doc = self.touch("notes/a.md")
        img = self.touch("notes/img/pic.png")
        self.assertEqual(assets.relative_image_ref(doc, img), ("img/pic.png", "pic"))

    def test_spaces_and_parentheses_encoded(self) -> None:
        doc = self.touch("d/a.md")
        img = self.touch("d/图 1 (2).png")
        self.assertEqual(assets.relative_image_ref(doc, img)[0], "图%201%20%282%29.png")

    def test_missing_image_returns_none(self) -> None:
        doc = self.touch("d/a.md")
        self.assertIsNone(assets.relative_image_ref(doc, self.root / "d" / "none.png"))

    def test_doc_path_without_existing_file(self) -> None:
        """文档尚未落盘也要能算出相对路径（只用到它的目录）。"""
        img = self.touch("d/pic.png")
        self.assertEqual(
            assets.relative_image_ref(self.root / "d" / "new.md", img)[0], "pic.png"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
