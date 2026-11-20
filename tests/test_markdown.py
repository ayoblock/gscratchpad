"""Markdown 渲染与图片资源单元测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

from scratchpad import assets  # noqa: E402
from scratchpad import markdown_render as mr  # noqa: E402


class MarkdownTestCase(unittest.TestCase):
    def test_headings_bold_italic(self) -> None:
        body = mr.render_body("# 标题\n\n**粗体** *斜体*")
        self.assertIn("<h1", body)
        self.assertIn("<strong>粗体</strong>", body)
        self.assertIn("<em>斜体</em>", body)

    def test_lists(self) -> None:
        body = mr.render_body("1. 甲\n2. 乙\n\n- 无序")
        self.assertIn("<ol>", body)
        self.assertIn("<ul>", body)

    def test_table(self) -> None:
        body = mr.render_body("| a | b |\n| - | - |\n| 1 | 2 |")
        self.assertIn("<table>", body)
        self.assertIn("<td>1</td>", body)

    def test_code_highlight(self) -> None:
        body = mr.render_body("```python\ndef f():\n    return 1\n```")
        self.assertIn("codehilite", body)
        self.assertIn("def", body)

    def test_math_inline_and_display(self) -> None:
        body = mr.render_body("行内 $E=mc^2$ 与 $$\\int_0^1 x$$")
        self.assertIn('data-tex="E=mc^2"', body)
        self.assertIn('data-display="1"', body)

    def test_math_not_eaten_by_markdown(self) -> None:
        body = mr.render_body("$a_1 + b^2$")
        self.assertIn('data-tex="a_1 + b^2"', body)

    def test_math_inside_code_untouched(self) -> None:
        body = mr.render_body("```\n$x^2$\n```")
        self.assertNotIn("data-tex", body)

    def test_mermaid_block(self) -> None:
        body = mr.render_body("```mermaid\nflowchart LR\n  A --> B\n```")
        self.assertIn('<div class="mermaid">', body)
        self.assertIn("flowchart", body)

    def test_html_escaping(self) -> None:
        body = mr.render_body("<script>alert(1)</script>")
        self.assertNotIn("<script", body)
        self.assertNotIn("alert", body)

    def test_dangerous_link_blocked(self) -> None:
        body = mr.render_body('[点我](javascript:alert(1))')
        self.assertNotIn("javascript:", body)

    def test_inline_html_passthrough_safe(self) -> None:
        body = mr.render_body('<span class="x" onclick="evil()">文字</span>')
        self.assertIn('<span class="x">文字</span>', body)

    def test_document_html_has_local_assets(self) -> None:
        html = mr.render_document("公式 $x$")
        self.assertIn("file://", html)
        self.assertIn("katex.min.js", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://cdn", html)

    def test_assets_loaded_only_when_needed(self) -> None:
        """按需加载：没有公式/图表就不引入对应脚本（省内存）。"""
        plain = mr.render_document("普通段落，没有公式")
        self.assertNotIn("katex.min.js", plain)
        self.assertNotIn("mermaid.min.js", plain)
        self.assertIn("messageHandlers.ready", plain)  # 就绪回调必须始终存在

        math = mr.render_document("公式 $E=mc^2$")
        self.assertIn("katex.min.js", math)
        self.assertNotIn("mermaid.min.js", math)

        diagram = mr.render_document("```mermaid\nflowchart TD\n  A --> B\n```")
        self.assertIn("mermaid.min.js", diagram)
        self.assertNotIn("katex.min.js", diagram)

        both = mr.render_document("$x$\n\n```mermaid\ngraph TD;A-->B\n```", print_mode=True)
        self.assertIn("katex.min.js", both)
        self.assertIn("mermaid.min.js", both)

    def test_print_mode_a4(self) -> None:
        html = mr.render_document("# t", print_mode=True)
        self.assertIn("size: A4", html)
        self.assertIn("page-break-inside: avoid", html)


class AssetsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sp-assets-"))
        os.environ["XDG_DATA_HOME"] = str(self.tmp)
        import importlib

        import scratchpad.paths as paths

        importlib.reload(paths)
        globals()["paths"] = paths

    def test_import_and_dedupe(self) -> None:
        import scratchpad.assets as assets_mod

        src = self.tmp / "pic.png"
        src.write_bytes(b"\x89PNG fake")
        rel, name = assets_mod.import_image("doc1", src)
        self.assertTrue(rel.startswith("assets/doc1/"))
        self.assertEqual(name, "pic")
        # 重复导入应去重
        rel2, _ = assets_mod.import_image("doc1", src)
        self.assertEqual(rel, rel2)
        files = assets_mod.list_assets("doc1")
        self.assertEqual(len(files), 1)

    def test_reject_bad_ext(self) -> None:
        import scratchpad.assets as assets_mod

        src = self.tmp / "evil.exe"
        src.write_bytes(b"x")
        with self.assertRaises(ValueError):
            assets_mod.import_image("doc1", src)


if __name__ == "__main__":
    unittest.main()
