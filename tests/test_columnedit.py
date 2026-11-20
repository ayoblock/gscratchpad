"""columnedit 纯函数测试（不依赖 GTK，任意解释器可跑）。

用法：PYTHONPATH=src python3 -m unittest tests.test_columnedit
或 PYTHONPATH=src:tests python3 -m unittest test_columnedit
"""

from __future__ import annotations

import unittest

from scratchpad import columnedit


class ColumnEditTest(unittest.TestCase):
    # ---------------------------------------------------------------- 前缀/后缀
    def test_prefix_applies_to_every_line_including_empty(self):
        self.assertEqual(
            columnedit.transform("prefix", "a\n\nb", "- "),
            "- a\n- \n- b",
        )

    def test_suffix_applies_to_every_line(self):
        self.assertEqual(
            columnedit.transform("suffix", "a\nb", ";"),
            "a;\nb;",
        )

    def test_empty_arg_is_noop(self):
        self.assertEqual(columnedit.transform("prefix", "a\nb", ""), "a\nb")
        self.assertEqual(columnedit.transform("suffix", "a\nb", ""), "a\nb")

    def test_prefix_with_unicode_arg(self):
        self.assertEqual(columnedit.transform("prefix", "中文\nenglish", "→ "), "→ 中文\n→ english")

    def test_input_list_not_mutated(self):
        lines = ["b", "a"]
        columnedit.sort_lines(lines)
        self.assertEqual(lines, ["b", "a"])

    # ---------------------------------------------------------------- 排序
    def test_sort_ascending(self):
        self.assertEqual(columnedit.transform("sort", "b\na\nc"), "a\nb\nc")

    def test_sort_stable_for_equal_keys(self):
        # sorted 是稳定排序：相同键保持原相对顺序
        self.assertEqual(columnedit.sort_lines(["2 b", "1 a", "2 a"]), ["1 a", "2 a", "2 b"])

    def test_sort_unicode_code_point_order(self):
        # 明确约定：按 Unicode 码点，不做本地化排序（「中」U+4E2D < 「英」U+82F1）
        self.assertEqual(columnedit.transform("sort", "英\n中"), "中\n英")

    def test_sort_single_line_noop(self):
        self.assertEqual(columnedit.transform("sort", "only"), "only")

    # ---------------------------------------------------------------- 去重
    def test_dedup_keeps_first_occurrence(self):
        self.assertEqual(
            columnedit.transform("dedup", "x\ny\nx\nz\ny"),
            "x\ny\nz",
        )

    def test_dedup_exact_match_only(self):
        # 前后空白视为不同行
        self.assertEqual(columnedit.transform("dedup", "x\n x \nx"), "x\n x ")

    def test_dedup_unicode_lines(self):
        self.assertEqual(columnedit.transform("dedup", "甲\n乙\n甲"), "甲\n乙")

    def test_dedup_all_unique_noop(self):
        self.assertEqual(columnedit.transform("dedup", "a\nb\nc"), "a\nb\nc")

    # ---------------------------------------------------------------- 边界
    def test_single_line_roundtrip(self):
        self.assertEqual(columnedit.transform("prefix", "solo", "#"), "#solo")

    def test_unknown_op_noop(self):
        self.assertEqual(columnedit.transform("reverse", "a\nb"), "a\nb")

    def test_trailing_empty_segment_preserved(self):
        # 块以 "行\n空" 形式传入（末段是空行）时，空行同样参与变换
        self.assertEqual(columnedit.transform("prefix", "a\n", "> "), "> a\n> ")
        self.assertEqual(columnedit.transform("dedup", "a\na\n"), "a\n")


if __name__ == "__main__":
    unittest.main()
