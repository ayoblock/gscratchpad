"""片段引擎单元测试：模板渲染 / 转义 / 加速键规范化 / 触发词边界 / 存取容错。"""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scratchpad import snippets  # noqa: E402

NOW = datetime.datetime(2026, 11, 9, 23, 22, 5)


class RenderTest(unittest.TestCase):
    def test_cursor_marker_removed_and_offset(self) -> None:
        out = snippets.render("<!-- {{cursor}} -->")
        self.assertEqual(out.text, "<!--  -->")
        self.assertEqual(out.cursor, 5)

    def test_cursor_defaults_to_end(self) -> None:
        out = snippets.render("abc")
        self.assertEqual((out.text, out.cursor), ("abc", 3))

    def test_only_first_cursor_counts(self) -> None:
        out = snippets.render("a{{cursor}}b{{cursor}}c")
        self.assertEqual(out.text, "abc")
        self.assertEqual(out.cursor, 1)

    def test_escapes(self) -> None:
        out = snippets.render(r"a\nb\tc\r\\d")
        self.assertEqual(out.text, "a\nb\tc\r\\d")

    def test_unknown_escape_kept(self) -> None:
        self.assertEqual(snippets.render(r"\q").text, r"\q")
        self.assertEqual(snippets.render("结尾\\").text, "结尾\\")

    def test_variables(self) -> None:
        out = snippets.render("{{date}} {{time}} {{datetime}} {{title}}", title="笔记", now=NOW)
        self.assertEqual(out.text, "2026-11-09 23:22 2026-11-09 23:22 笔记")

    def test_unknown_placeholder_kept(self) -> None:
        self.assertEqual(snippets.render("{{foo}}").text, "{{foo}}")
        self.assertEqual(snippets.render("{{cursor").text, "{{cursor")

    def test_cursor_offset_counts_expanded_text(self) -> None:
        out = snippets.render("{{date}}{{cursor}}X", now=NOW)
        self.assertEqual(out.cursor, 10)
        self.assertEqual(out.text, "2026-11-09X")

    def test_bash_dollar_signs_survive(self) -> None:
        # GtkSourceView 的 snippet 解析器会吃掉 $1 / \n，这里必须原样保留
        out = snippets.render('printf "%s\\n" $1 ; echo $HOME')
        self.assertEqual(out.text, 'printf "%s\n" $1 ; echo $HOME')

    def test_empty_template(self) -> None:
        self.assertEqual(snippets.render("").cursor, 0)


class AccelTest(unittest.TestCase):
    def test_canonical_matches_between_forms(self) -> None:
        self.assertEqual(
            snippets.canonical_accel("<Control><Shift>P"), snippets.canonical_accel("Ctrl+Shift+P")
        )
        self.assertEqual(
            snippets.canonical_accel("<Shift><Control>p"), snippets.canonical_accel("<Control><Shift>P")
        )

    def test_modifier_order_irrelevant(self) -> None:
        self.assertEqual(
            snippets.canonical_accel("Shift+Ctrl+1"), snippets.canonical_accel("<Control><Shift>1")
        )

    def test_normalize(self) -> None:
        self.assertEqual(snippets.normalize_accel("Ctrl+1"), "<Control>1")
        self.assertEqual(snippets.normalize_accel("ctrl+shift+e"), "<Control><Shift>e")
        self.assertEqual(snippets.normalize_accel("<Control>1"), "<Control>1")

    def test_invalid(self) -> None:
        for bad in ("", "Control", "Ctrl+", "<Control>", "Hyper+X", None):
            self.assertEqual(snippets.normalize_accel(bad), "", bad)

    def test_pretty(self) -> None:
        self.assertEqual(snippets.pretty_accel("<Shift><Control>p"), "Ctrl+Shift+P")
        self.assertEqual(snippets.pretty_accel("F9"), "F9")
        self.assertEqual(snippets.pretty_accel(""), "")

    def test_find_by_accel(self) -> None:
        items = [snippets.Snippet("注释", "<!-- {{cursor}} -->", "Ctrl+1")]
        self.assertIsNotNone(snippets.find_by_accel(items, "<Control>1"))
        self.assertIsNone(snippets.find_by_accel(items, "<Control>2"))


class TriggerTest(unittest.TestCase):
    def test_bash_trigger(self) -> None:
        match = snippets.match_trigger("ife", "sh")
        self.assertIsNotNone(match)
        self.assertEqual(match.length, 3)
        self.assertIn("then", match.template)

    def test_word_boundary(self) -> None:
        self.assertIsNone(snippets.match_trigger("life", "sh"))
        self.assertIsNone(snippets.match_trigger("x_h1", "markdown"))

    def test_boundary_after_space_or_newline(self) -> None:
        self.assertIsNotNone(snippets.match_trigger("  h2", "markdown"))
        self.assertIsNotNone(snippets.match_trigger("第一行\ncode", "markdown"))

    def test_unknown_language(self) -> None:
        self.assertIsNone(snippets.match_trigger("ife", "json"))
        self.assertIsNone(snippets.match_trigger("ife", ""))

    def test_longest_trigger_wins(self) -> None:
        # codebash / codepy 都以 code 开头，必须优先匹配更长的
        match = snippets.match_trigger("codebash", "markdown")
        self.assertEqual(match.trigger, "codebash")

    def test_all_templates_render(self) -> None:
        for lang, table in snippets.TRIGGERS.items():
            self.assertTrue(table, lang)
            for trigger, template in table.items():
                rendered = snippets.render(template)
                self.assertTrue(rendered.text.strip(), f"{lang}/{trigger} 渲染为空")

    def test_trigger_rows_sorted(self) -> None:
        rows = snippets.trigger_rows("markdown")
        triggers = [r[0] for r in rows]
        self.assertEqual(triggers, sorted(triggers))
        self.assertTrue(any("codebash" == t for t in triggers))


class StorageTest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        items = [snippets.Snippet("A", "x{{cursor}}", "<Control>1"), snippets.Snippet("B", "y")]
        back = snippets.loads(snippets.dumps(items))
        self.assertEqual([s.name for s in back], ["A", "B"])
        self.assertEqual(back[0].accel, "<Control>1")
        self.assertEqual(back[1].accel, "")

    def test_bad_json(self) -> None:
        for raw in (None, "", "not json", "{}", '[1,2]', '"x"'):
            self.assertEqual(snippets.loads(raw), [], raw)

    def test_duplicate_ids_reassigned(self) -> None:
        raw = '[{"id":"dup","name":"a","template":"x"},{"id":"dup","name":"b","template":"y"}]'
        back = snippets.loads(raw)
        self.assertEqual(len(back), 2)
        self.assertNotEqual(back[0].id, back[1].id)

    def test_missing_fields(self) -> None:
        back = snippets.loads('[{"template":"x"}]')
        self.assertEqual(back[0].name, "未命名")
        self.assertTrue(back[0].id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
