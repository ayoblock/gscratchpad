"""escapecodec.decode 单元测试（不依赖 GTK）。"""

from __future__ import annotations

import unittest

from scratchpad import escapecodec as ec


class TestSimpleEscapes(unittest.TestCase):
    def test_newline(self):
        self.assertEqual(ec.decode("a\\nb"), "a\nb")

    def test_crlf_sequence(self):
        self.assertEqual(ec.decode("\\r\\n"), "\r\n")

    def test_tab(self):
        self.assertEqual(ec.decode("\\t"), "\t")

    def test_plain_passthrough(self):
        self.assertEqual(ec.decode("no escapes"), "no escapes")

    def test_empty(self):
        self.assertEqual(ec.decode(""), "")


class TestBackslashRule(unittest.TestCase):
    def test_double_backslash_is_literal(self):
        # `\\` → 一个反斜杠
        self.assertEqual(ec.decode("a\\\\b"), "a\\b")

    def test_double_backslash_then_n_stays_literal(self):
        # `\\n` 必须是「反斜杠 + n」两个字符，绝不能变成换行（单遍扫描的意义）
        self.assertEqual(ec.decode("\\\\n"), "\\n")

    def test_trailing_backslash(self):
        self.assertEqual(ec.decode("abc\\"), "abc\\")

    def test_unknown_letter_kept(self):
        self.assertEqual(ec.decode("\\q"), "\\q")

    def test_path_with_tab_letter_is_decoded(self):
        # 已知副作用：`C:\temp` 里的 `\t` 会被解码为制表符。这正是「转义」开关
        # 默认关闭的原因——本应用常用来贴路径与日志。此处把行为钉死，防止误改。
        self.assertEqual(ec.decode("C:\\temp"), "C:" + "\t" + "emp")
        self.assertEqual(ec.decode("\\new"), "\n" + "ew")


class TestHexEscapes(unittest.TestCase):
    def test_hex_two_digits(self):
        self.assertEqual(ec.decode("\\x41"), "A")

    def test_hex_utf8_byte_value(self):
        # \xHH 按码点解释（不是按字节再拼 UTF-8）
        self.assertEqual(ec.decode("\\xe4"), "ä")

    def test_hex_too_short(self):
        self.assertEqual(ec.decode("\\x4"), "\\x4")

    def test_hex_non_hex_digits(self):
        self.assertEqual(ec.decode("\\xZZ"), "\\xZZ")

    def test_hex_nul_rejected(self):
        # NUL 无法进入 GtkTextBuffer，按字面保留
        self.assertEqual(ec.decode("\\x00"), "\\x00")

    def test_unicode_four_digits(self):
        self.assertEqual(ec.decode("\\u4e2d"), "中")

    def test_unicode_surrogate_rejected(self):
        self.assertEqual(ec.decode("\\ud800"), "\\ud800")

    def test_unicode_too_short(self):
        self.assertEqual(ec.decode("\\u4e2"), "\\u4e2")

    def test_no_uppercase_u8_support(self):
        # \U0001F600 不在支持列表内 → 原样（文档明确只支持 \uHHHH）
        self.assertEqual(ec.decode("\\U0001F600"), "\\U0001F600")


class TestBackrefsPassthrough(unittest.TestCase):
    def test_digit_refs_untouched(self):
        for s in ("\\1", "\\0", "\\9", "\\12"):
            self.assertEqual(ec.decode(s), s)

    def test_escaped_backref_becomes_literal(self):
        # `\\1` → 字面 `\1`，不再被当成反向引用
        self.assertEqual(ec.decode("\\\\1"), "\\1")

    def test_mixed_refs_and_escapes(self):
        self.assertEqual(ec.decode("\\2\\n\\1"), "\\2\n\\1")


class TestMixed(unittest.TestCase):
    def test_blank_line_collapse_operand(self):
        # 用户场景的操作数：\n\n → \n
        self.assertEqual(ec.decode("\\n\\n"), "\n\n")
        self.assertEqual(ec.decode("\\n"), "\n")

    def test_multiple_in_one_string(self):
        self.assertEqual(ec.decode("a\\tb\\nc\\\\d"), "a\tb\nc\\d")


if __name__ == "__main__":
    unittest.main()
