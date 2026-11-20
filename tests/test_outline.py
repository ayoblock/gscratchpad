"""Markdown 大纲解析单元测试（纯逻辑，不需要 GUI）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

from scratchpad import markdown_render as mr  # noqa: E402
from scratchpad.outline import Heading, parse_headings, plain_text  # noqa: E402


class OutlineTestCase(unittest.TestCase):
    def test_atx_levels_and_lines(self) -> None:
        text = "# 一\n\n正文\n\n## 二\n\n###### 六\n"
        heads = parse_headings(text)
        self.assertEqual([h.level for h in heads], [1, 2, 6])
        self.assertEqual([h.line for h in heads], [1, 5, 7])
        self.assertEqual([h.index for h in heads], [0, 1, 2])
        self.assertEqual(heads[0].text, "一")

    def test_requires_space_after_hash(self) -> None:
        # CommonMark：#hashtag 不是标题，渲染器同样不会当标题
        self.assertEqual(parse_headings("#hashtag\n\n# 真标题")[0].text, "真标题")

    def test_fenced_code_ignored(self) -> None:
        text = "# 真\n\n```bash\n# 注释\n```\n\n~~~\n## 也不算\n~~~\n\n## 尾\n"
        self.assertEqual([h.text for h in parse_headings(text)], ["真", "尾"])

    def test_unclosed_fence_swallows_rest(self) -> None:
        self.assertEqual(parse_headings("# A\n\n```\n# B\n"), [Heading(0, 1, "A", 1)])

    def test_indented_code_ignored(self) -> None:
        text = "# A\n\n    # 缩进代码\n\n## B\n"
        self.assertEqual([h.text for h in parse_headings(text)], ["A", "B"])

    def test_html_comment_ignored(self) -> None:
        text = "<!--\n# 注释里的\n-->\n\n# 真标题\n"
        self.assertEqual([h.text for h in parse_headings(text)], ["真标题"])

    def test_setext(self) -> None:
        text = "一级\n===\n\n二级\n---\n"
        heads = parse_headings(text)
        self.assertEqual([(h.level, h.text, h.line) for h in heads], [(1, "一级", 1), (2, "二级", 4)])

    def test_setext_needs_paragraph_above(self) -> None:
        # 空行后的 --- 是分隔线；列表项不能被当成 setext 标题
        self.assertEqual(parse_headings("正文\n\n---\n\n- 项\n---\n"), [])
        self.assertEqual(parse_headings("- 项\n---\n"), [])

    def test_trailing_hashes_stripped(self) -> None:
        self.assertEqual(parse_headings("## 标题 ##")[0].text, "标题")
        self.assertEqual(parse_headings("# C#")[0].text, "C#")

    def test_inline_markup_removed(self) -> None:
        text = "# **粗体** 与 `code` 与 [链接](https://x.y) 与 ![图](a.png)"
        self.assertEqual(parse_headings(text)[0].text, "粗体 与 code 与 链接 与 图")
        self.assertEqual(plain_text("~~删~~ _斜_"), "删 斜")

    def test_empty_heading_placeholder(self) -> None:
        self.assertEqual(parse_headings("#\n")[0].text, "（无标题）")

    def test_empty_text(self) -> None:
        self.assertEqual(parse_headings(""), [])
        self.assertEqual(parse_headings("\n\n"), [])

    def test_matches_rendered_heading_count(self) -> None:
        """大纲条目数必须与渲染出的 h1..h6 数量一致，否则预览滚动会错位。"""
        text = (
            "# 一\n\n正文\n\n```py\n# 不是标题\n```\n\n## 二 ##\n\n### 三\n\n"
            "Setext\n------\n\n> # 引用里的标题\n\n- 列表\n\n#### 四\n"
        )
        heads = parse_headings(text)
        body = mr.render_body(text)
        self.assertEqual(body.count("<h1"), sum(1 for h in heads if h.level == 1))
        self.assertEqual(body.count("<h2"), sum(1 for h in heads if h.level == 2))
        self.assertEqual(len(heads), sum(body.count(f"<h{i}") for i in range(1, 7)))

    def test_render_marks_heading_order(self) -> None:
        body = mr.render_body("# A\n\n## B\n")
        self.assertIn('data-h="0"', body)
        self.assertIn('data-h="1"', body)
        self.assertLess(body.index('data-h="0"'), body.index('data-h="1"'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
