"""段落遮罩：paragraph_bounds（纯函数）单元测试。

段落规则：空行分隔；标题行（# 开头）自成一段；围栏代码块（``` / ~~~）
整块算一段（含开合围栏行）；其余按连续非空行聚段。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))
os.environ.setdefault(
    "GI_TYPELIB_PATH",
    os.pathsep.join(
        [str(PROJECT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
    ),
)

from scratchpad.editor import paragraph_bounds  # noqa: E402


class ParagraphBoundsTest(unittest.TestCase):
    def test_two_paragraphs_blank_separated(self):
        lines = ["a1", "a2", "", "b1"]
        self.assertEqual(paragraph_bounds(lines, 0), (0, 2))
        self.assertEqual(paragraph_bounds(lines, 1), (0, 2))
        self.assertEqual(paragraph_bounds(lines, 3), (3, 4))

    def test_blank_line_is_own_paragraph(self):
        lines = ["a", "", "b"]
        self.assertEqual(paragraph_bounds(lines, 1), (1, 2))

    def test_heading_standalone(self):
        lines = ["前一段", "## 标题", "后一段"]
        self.assertEqual(paragraph_bounds(lines, 1), (1, 2))
        self.assertEqual(paragraph_bounds(lines, 0), (0, 1))
        self.assertEqual(paragraph_bounds(lines, 2), (2, 3))

    def test_fence_block_whole(self):
        lines = [
            "intro",
            "```python",
            "print(1)",
            "print(2)",
            "```",
            "outro",
        ]
        self.assertEqual(paragraph_bounds(lines, 2), (1, 5))
        self.assertEqual(paragraph_bounds(lines, 4), (1, 5))
        self.assertEqual(paragraph_bounds(lines, 0), (0, 1))
        self.assertEqual(paragraph_bounds(lines, 5), (5, 6))

    def test_tilde_fence(self):
        lines = ["~~~", "x", "~~~", "y"]
        self.assertEqual(paragraph_bounds(lines, 1), (0, 3))

    def test_unclosed_fence_runs_to_end(self):
        lines = ["a", "```", "x", "y"]
        self.assertEqual(paragraph_bounds(lines, 3), (1, 4))

    def test_clamp_out_of_range(self):
        lines = ["a", "", "b"]
        self.assertEqual(paragraph_bounds(lines, 99), (2, 3))
        self.assertEqual(paragraph_bounds(lines, -5), (0, 1))

    def test_empty_document(self):
        self.assertEqual(paragraph_bounds([], 0), (0, 0))

    def test_indented_lines_group_together(self):
        lines = ["- 项 1", "  续行", "", "- 项 2"]
        self.assertEqual(paragraph_bounds(lines, 1), (0, 2))

    def test_consecutive_headings(self):
        lines = ["# A", "# B", "text"]
        self.assertEqual(paragraph_bounds(lines, 0), (0, 1))
        self.assertEqual(paragraph_bounds(lines, 1), (1, 2))
        self.assertEqual(paragraph_bounds(lines, 2), (2, 3))

    def test_trailing_paragraph_to_document_end(self):
        lines = ["", "x", "y"]
        self.assertEqual(paragraph_bounds(lines, 2), (1, 3))


if __name__ == "__main__":
    unittest.main()
