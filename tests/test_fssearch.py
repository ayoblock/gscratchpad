"""fssearch 单元测试：编码 / 换行 / BOM / 递归 / 正则 / 备份 / 并发校验。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scratchpad import fssearch  # noqa: E402


class FsSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    # ---------------------------------------------------------------- helpers

    def write(self, rel: str, text: str, encoding: str = "utf-8", bom: bool = False) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode(encoding)
        if bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)
        return path

    # ------------------------------------------------------------------ 搜索

    def test_search_basic_groups_by_file(self) -> None:
        self.write("a.md", "第一行\n关键词在这里\n")
        self.write("sub/b.md", "关键词 1\n关键词 2\n")
        self.write("c.md", "无关内容\n")
        out = fssearch.search(self.root, "关键词")
        self.assertEqual(out.matched_files, 2)
        self.assertEqual(out.total_hits, 3)
        self.assertEqual(out.scanned, 3)
        rels = sorted(f.rel for f in out.files)
        self.assertEqual(rels, ["a.md", os.path.join("sub", "b.md")])
        hit = out.files[0].hits[0]
        self.assertEqual(hit.line_no, 2)
        self.assertEqual(hit.column, 0)

    def test_search_non_recursive(self) -> None:
        self.write("a.md", "命中\n")
        self.write("deep/b.md", "命中\n")
        out = fssearch.search(self.root, "命中", recursive=False)
        self.assertEqual([f.rel for f in out.files], ["a.md"])

    def test_search_case_sensitivity(self) -> None:
        self.write("a.md", "Hello World\n")
        self.assertEqual(fssearch.search(self.root, "hello").total_hits, 1)
        self.assertEqual(
            fssearch.search(self.root, "hello", case_sensitive=True).total_hits, 0
        )

    def test_search_regex(self) -> None:
        self.write("a.md", "v1.2.3\nv10.0.1\n")
        out = fssearch.search(self.root, r"v\d+\.\d+\.\d+", regex=True)
        self.assertEqual(out.total_hits, 2)

    def test_search_skips_binary_and_hidden(self) -> None:
        (self.root / "bin.md").write_bytes(b"\x00\x01\x02\xff\xfe")
        self.write(".hidden/x.md", "命中\n")
        self.write("node_modules/y.md", "命中\n")
        out = fssearch.search(self.root, "命中")
        self.assertEqual(out.total_hits, 0)
        self.assertGreaterEqual(out.skipped, 1)

    def test_empty_pattern_returns_empty(self) -> None:
        self.write("a.md", "abc\n")
        self.assertEqual(fssearch.search(self.root, "").total_hits, 0)

    def test_truncation_flag(self) -> None:
        self.write("a.md", "\n".join(["命中"] * 20))
        out = fssearch.search(self.root, "命中", max_hits=5)
        self.assertTrue(out.truncated)
        self.assertEqual(out.total_hits, 5)

    # ------------------------------------------------------------ 转义与跨行

    def test_unescape_known_sequences(self) -> None:
        self.assertEqual(fssearch.unescape(r"a\nb"), "a\nb")
        self.assertEqual(fssearch.unescape(r"a\tb"), "a\tb")
        self.assertEqual(fssearch.unescape(r"a\rb"), "a\rb")
        self.assertEqual(fssearch.unescape(r"a\\b"), "a\\b")

    def test_unescape_keeps_unknown_and_trailing(self) -> None:
        self.assertEqual(fssearch.unescape(r"\q"), r"\q")
        # 路径里的反斜杠必须写成 \\，否则 \t 会被解释成制表符（与 C 字符串一致）
        self.assertEqual(fssearch.unescape("C:\\\\temp"), "C:\\temp")
        self.assertEqual(fssearch.unescape("结尾\\"), "结尾\\")
        self.assertEqual(fssearch.unescape("无转义"), "无转义")
        # \\n = 反斜杠 + n（不构成换行）
        self.assertEqual(fssearch.unescape(r"\\n"), "\\n")

    def test_search_multiline_pattern_hits_cross_line(self) -> None:
        self.write("a.md", "第一行\n第二行\n第三行\n")
        out = fssearch.search(self.root, fssearch.unescape(r"第一行\n第二行"))
        self.assertEqual(out.total_hits, 1)
        hit = out.files[0].hits[0]
        self.assertEqual(hit.line_no, 1)
        self.assertEqual(hit.column, 0)
        self.assertIn("⏎", hit.excerpt)
        self.assertTrue(hit.excerpt.startswith("第一行"))

    def test_search_multiline_line_number_of_later_match(self) -> None:
        self.write("a.md", "head\n\n尾1\n尾2\n")
        out = fssearch.search(self.root, fssearch.unescape(r"尾1\n尾2"))
        self.assertEqual(out.total_hits, 1)
        self.assertEqual(out.files[0].hits[0].line_no, 3)
        self.assertEqual(out.files[0].hits[0].column, 0)

    def test_search_column_after_crlf(self) -> None:
        self.write("crlf.md", "ab\r\ncd\r\n")
        hit = fssearch.search(self.root, "cd").files[0].hits[0]
        self.assertEqual((hit.line_no, hit.column), (2, 0))
        self.assertEqual(hit.line_text, "cd")

    def test_replace_inserts_newline(self) -> None:
        path = self.write("a.md", "标题 内容\n")
        plan = fssearch.plan_replace(
            self.root, "标题", fssearch.unescape(r"标题\n\n")
        )
        self.assertEqual(plan.total_replacements, 1)
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(path.read_text(encoding="utf-8"), "标题\n\n 内容\n")

    def test_replace_multiline_pattern(self) -> None:
        path = self.write("a.md", "a\nb\nc\n")
        plan = fssearch.plan_replace(
            self.root, fssearch.unescape(r"a\nb"), "ab"
        )
        self.assertEqual(plan.total_replacements, 1)
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(path.read_text(encoding="utf-8"), "ab\nc\n")

    # ------------------------------------------------------------------ 替换

    def test_plan_replace_counts_without_writing(self) -> None:
        path = self.write("a.md", "foo foo bar\nfoo\n")
        plan = fssearch.plan_replace(self.root, "foo", "baz")
        self.assertEqual(plan.total_replacements, 3)
        self.assertEqual(plan.changed_files[0].rel, "a.md")
        self.assertEqual(path.read_text(encoding="utf-8"), "foo foo bar\nfoo\n")

    def test_apply_replace_writes_and_backs_up(self) -> None:
        path = self.write("a.md", "foo foo\n")
        plan = fssearch.plan_replace(self.root, "foo", "baz")
        backup = fssearch.make_backup_dir(self.root / "_bak", "2026-11-05_120000")
        result = fssearch.apply_plan(plan, backup)
        self.assertEqual(result.replacements, 2)
        self.assertEqual(path.read_text(encoding="utf-8"), "baz baz\n")
        self.assertEqual((backup / "a.md").read_text(encoding="utf-8"), "foo foo\n")
        self.assertEqual(result.errors, [])

    def test_apply_respects_selected_files(self) -> None:
        a = self.write("a.md", "foo\n")
        b = self.write("b.md", "foo\n")
        plan = fssearch.plan_replace(self.root, "foo", "bar")
        backup = fssearch.make_backup_dir(self.root / "_bak", "t")
        result = fssearch.apply_plan(plan, backup, only=[b])
        self.assertEqual(result.changed, [b])
        self.assertEqual(a.read_text(encoding="utf-8"), "foo\n")
        self.assertEqual(b.read_text(encoding="utf-8"), "bar\n")

    def test_case_sensitive_by_default(self) -> None:
        path = self.write("a.md", "Hello hello\n")
        plan = fssearch.plan_replace(self.root, "hello", "hi")
        self.assertEqual(plan.total_replacements, 1)
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(path.read_text(encoding="utf-8"), "Hello hi\n")

    def test_case_insensitive_replace(self) -> None:
        self.write("a.md", "Hello hello\n")
        plan = fssearch.plan_replace(self.root, "hello", "hi", case_sensitive=False)
        self.assertEqual(plan.total_replacements, 2)

    def test_regex_replace_with_backreference(self) -> None:
        path = self.write("a.md", "v1.2.3 与 v10.20.30\n")
        plan = fssearch.plan_replace(
            self.root, r"v(\d+)\.(\d+)\.(\d+)", r"V\1-\2-\3", regex=True
        )
        self.assertEqual(plan.total_replacements, 2)
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(path.read_text(encoding="utf-8"), "V1-2-3 与 V10-20-30\n")

    # -------------------------------------------------------- 编码与换行的保真

    def test_gbk_file_keeps_encoding(self) -> None:
        path = self.write("gbk.md", "中文关键词 内容\n", encoding="gb18030")
        plan = fssearch.plan_replace(self.root, "关键词", "关键字")
        self.assertEqual(plan.files[0].encoding, "gb18030")
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        raw = path.read_bytes()
        self.assertEqual(raw.decode("gb18030"), "中文关键字 内容\n")
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")

    def test_bom_preserved(self) -> None:
        path = self.write("bom.md", "abc def\n", bom=True)
        plan = fssearch.plan_replace(self.root, "def", "ghi")
        self.assertTrue(plan.files[0].bom)
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(path.read_bytes()[3:].decode("utf-8"), "abc ghi\n")

    def test_crlf_preserved(self) -> None:
        path = self.write("crlf.md", "line1\r\nline2 foo\r\n")
        plan = fssearch.plan_replace(self.root, "foo", "bar")
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        data = path.read_bytes()
        self.assertIn(b"\r\n", data)
        self.assertNotIn(b"\n\n", data.replace(b"\r\n", b""))
        self.assertEqual(data.decode("utf-8"), "line1\r\nline2 bar\r\n")

    def test_concurrent_modification_skipped(self) -> None:
        path = self.write("a.md", "foo\n")
        plan = fssearch.plan_replace(self.root, "foo", "bar")
        path.write_text("foo changed externally\n", encoding="utf-8")
        result = fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(result.changed, [])
        self.assertTrue(any("已被修改" in e for e in result.errors))
        self.assertEqual(path.read_text(encoding="utf-8"), "foo changed externally\n")

    def test_unwritable_backup_skips_file(self) -> None:
        path = self.write("a.md", "foo\n")
        plan = fssearch.plan_replace(self.root, "foo", "bar")
        blocker = self.root / "blocked"
        blocker.write_text("我是文件，不是目录", encoding="utf-8")
        result = fssearch.apply_plan(plan, blocker)
        self.assertEqual(result.changed, [])
        self.assertTrue(result.errors)
        self.assertEqual(path.read_text(encoding="utf-8"), "foo\n")

    def test_permissions_preserved(self) -> None:
        path = self.write("a.md", "foo\n")
        os.chmod(path, 0o640)
        plan = fssearch.plan_replace(self.root, "foo", "bar")
        fssearch.apply_plan(plan, fssearch.make_backup_dir(self.root / "_bak", "t"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main(verbosity=2)
