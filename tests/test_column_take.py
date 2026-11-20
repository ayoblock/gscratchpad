"""columnedit 切列（取一列）纯函数单元测试。

用法：PYTHONPATH=src python3 -m unittest test_column_take（或 tests.test_column_take）

覆盖：分隔符取第 N 段、多候选分隔符、未命中行原样保留、空行豁免、
字符宽截取、边界（宽 0 / 段号 0 / 空分隔符 / 未知模式）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scratchpad import columnedit  # noqa: E402


class TakeColumnSepTest(unittest.TestCase):
    LINES = [
        "- 欧洲：中世纪全身板甲。",
        "- 日本：武士大铠、胴丸。",
        "- 清代：八旗铠甲。",
        "- 宋代：普通札甲作为主体。",
        "- 唐代：明光铠。",
        "- 现代：防弹衣。",
    ]
    EXPECT = ["- 欧洲", "- 日本", "- 清代", "- 宋代", "- 唐代", "- 现代"]

    def test_take_first_segment(self) -> None:
        new, miss = columnedit.take_column(
            "\n".join(self.LINES), "sep", sep="：", index=1
        )
        self.assertEqual(new.split("\n"), self.EXPECT)
        self.assertEqual(miss, 0)

    def test_take_second_segment(self) -> None:
        new, _miss = columnedit.take_column(
            "\n".join(self.LINES), "sep", sep="：", index=2
        )
        self.assertEqual(new.split("\n")[0], "中世纪全身板甲。")

    def test_multi_candidate_sep(self) -> None:
        text = "a:b\nc：d"
        new, miss = columnedit.take_column(text, "sep", sep="：|:", index=2)
        self.assertEqual(new.split("\n"), ["b", "d"])
        self.assertEqual(miss, 0)

    def test_earliest_sep_wins(self) -> None:
        # 半角冒号出现在全角之前，取更靠前的切点
        new, _ = columnedit.take_column("x:y：z", "sep", sep="：|:", index=1)
        self.assertEqual(new, "x")

    def test_missing_sep_keeps_line(self) -> None:
        text = "有：分隔\n没有分隔的一行"
        new, miss = columnedit.take_column(text, "sep", sep="：", index=1)
        self.assertEqual(new.split("\n"), ["有", "没有分隔的一行"])
        self.assertEqual(miss, 1)

    def test_not_enough_segments_keeps_line(self) -> None:
        text = "a：b\nc"
        new, miss = columnedit.take_column(text, "sep", sep="：", index=2)
        self.assertEqual(new.split("\n"), ["b", "c"])
        self.assertEqual(miss, 1)

    def test_blank_lines_exempt(self) -> None:
        text = "a：b\n\nc：d"
        new, miss = columnedit.take_column(text, "sep", sep="：", index=1)
        self.assertEqual(new.split("\n"), ["a", "", "c"])
        self.assertEqual(miss, 0)

    def test_whitespace_only_line_exempt(self) -> None:
        text = "a：b\n   \nc：d"
        new, miss = columnedit.take_column(text, "sep", sep="：", index=1)
        self.assertEqual(new.split("\n")[1], "   ")
        self.assertEqual(miss, 0)

    def test_empty_sep_is_noop(self) -> None:
        text = "a：b"
        new, miss = columnedit.take_column(text, "sep", sep="", index=1)
        self.assertEqual(new, text)
        self.assertEqual(miss, 0)

    def test_index_zero_is_noop(self) -> None:
        text = "a：b"
        new, miss = columnedit.take_column(text, "sep", sep="：", index=0)
        self.assertEqual(new, text)
        self.assertEqual(miss, 0)

    def test_regex_metacharacters_are_literal(self) -> None:
        # 分隔符含正则元字符时必须按字面处理，不能当模式用
        text = "a|b\nc.d\ne*f"
        new, miss = columnedit.take_column(text, "sep", sep="\\|", index=2)
        self.assertEqual(new.split("\n"), ["b", "c.d", "e*f"])
        self.assertEqual(miss, 2)

    def test_multichar_sep(self) -> None:
        text = "标题 —— 正文"
        new, _ = columnedit.take_column(text, "sep", sep=" —— ", index=2)
        self.assertEqual(new, "正文")

    def test_split_seps_drops_empty(self) -> None:
        self.assertEqual(columnedit.split_seps("：|:"), ["：", ":"])
        self.assertEqual(columnedit.split_seps("："), ["："])
        self.assertEqual(columnedit.split_seps("||"), [])

    def test_split_seps_escaped_pipe(self) -> None:
        # 竖线需写成 \| 才能作为字面分隔符
        self.assertEqual(columnedit.split_seps("\\|"), ["|"])
        self.assertEqual(columnedit.split_seps("：|\\|"), ["：", "|"])
        self.assertEqual(columnedit.split_seps(""), [])


class TakeColumnWidthTest(unittest.TestCase):
    def test_width_four_on_user_example(self) -> None:
        lines = [
            "- 欧洲中世纪全身板甲。",
            "- 日本武士大铠、胴丸。",
            "- 清代八旗铠甲。",
            "- 宋代普通札甲作为主体。",
            "- 唐代明光铠。",
            "- 现代防弹衣。",
        ]
        new, miss = columnedit.take_column("\n".join(lines), "width", width=4)
        self.assertEqual(
            new.split("\n"),
            ["- 欧洲", "- 日本", "- 清代", "- 宋代", "- 唐代", "- 现代"],
        )
        self.assertEqual(miss, 0)

    def test_short_line_kept(self) -> None:
        new, miss = columnedit.take_column("abcdefg\nab", "width", width=4)
        self.assertEqual(new.split("\n"), ["abcd", "ab"])
        self.assertEqual(miss, 1)

    def test_zero_width_noop(self) -> None:
        text = "abcdefg"
        new, miss = columnedit.take_column(text, "width", width=0)
        self.assertEqual(new, text)
        self.assertEqual(miss, 0)

    def test_cjk_and_emoji_count_as_one(self) -> None:
        new, _ = columnedit.take_column("中文😀abcd", "width", width=3)
        self.assertEqual(new, "中文😀")

    def test_unknown_mode_noop(self) -> None:
        text = "a：b"
        new, miss = columnedit.take_column(text, "bogus")
        self.assertEqual(new, text)
        self.assertEqual(miss, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
