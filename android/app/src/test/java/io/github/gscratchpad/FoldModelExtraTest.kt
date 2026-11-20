package io.github.gscratchpad

import io.github.gscratchpad.domain.fold.FoldModel
import io.github.gscratchpad.domain.fold.FoldRange
import io.github.gscratchpad.domain.fold.FoldStrategy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** FoldModel 覆盖补齐：三种策略的区间枚举、单块结束行、行内度量。 */
class FoldModelExtraTest {

    @Test
    fun `strategy selection by language id`() {
        assertEquals(FoldStrategy.MARKDOWN, FoldModel("markdown").strategy)
        listOf(
            "json", "c", "cpp", "go", "rust", "java", "js", "typescript", "css", "sql",
            "kotlin", "kts",
        ).forEach { assertEquals("lang=$it", FoldStrategy.BRACE, FoldModel(it).strategy) }
        assertEquals(FoldStrategy.INDENT, FoldModel("text").strategy)
        assertEquals(FoldStrategy.INDENT, FoldModel().strategy)
    }

    @Test
    fun `hidden line count excludes header`() {
        assertEquals(0, FoldRange(3, 3).hiddenLineCount)
        assertEquals(4, FoldRange(3, 7).hiddenLineCount)
    }

    @Test
    fun `indent ranges fold nested blocks`() {
        val text = """
            root
              child a
              child b
            	sibling
            last
        """.trimIndent()
        val ranges = FoldModel().foldableRanges(text)
        assertTrue("应至少有一条缩进区间", ranges.isNotEmpty())
        assertEquals(0, ranges.first().headerLine)
        // tab 按 4 空格计：sibling 仍在 child 块内
        assertTrue(ranges.first().endLine >= 2)
    }

    @Test
    fun `indent block end stops at equal indent`() {
        val text = "a\n  b\nc"
        val range = FoldModel().rangeAt(text, 0)
        assertEquals(1, range!!.endLine)
        assertNull("末行无可折叠内容", FoldModel().rangeAt(text, 1))
        assertNull("越界行", FoldModel().rangeAt(text, 99))
    }

    @Test
    fun `brace ranges cover nested to matching close`() {
        val code = listOf(
            "fun f() {",
            "    if (x) {",
            "        y()",
            "    }",
            "}",
            "val z = 1",
        ).joinToString("\n")
        val ranges = FoldModel("kotlin").foldableRanges(code)
        assertEquals(2, ranges.size)
        assertEquals(FoldRange(0, 4), ranges[0])
        assertEquals(FoldRange(1, 3), ranges[1])
    }

    @Test
    fun `brace depth ignores quoted braces`() {
        val code = """val s = "{" + "}" """
        val model = FoldModel("json")
        // 引号内括号不计深度 → 单行无折叠区间
        assertTrue(model.foldableRanges(code).isEmpty())
        assertNull(model.rangeAt(code, 0))
    }

    @Test
    fun `markdown ranges fold headings and fences`() {
        val md = """
            # 一
            正文
            ```kotlin
            val a = 1
            ```
            ## 二
            内容
        """.trimIndent()
        val ranges = FoldModel("markdown").foldableRanges(md)
        // 标题区间 + 围栏区间
        assertTrue(ranges.any { it.headerLine == 0 })
        assertTrue(ranges.any { it.headerLine == 2 && it.endLine == 4 })
    }

    @Test
    fun `markdown block end for heading stops at same level`() {
        val md = "# a\nbody\n# b\nbody"
        val r = FoldModel("markdown").rangeAt(md, 0)
        assertEquals(1, r!!.endLine)
        assertNull("标题同级的下一块不算", FoldModel("markdown").rangeAt(md, 2)?.takeIf { it.endLine > 3 })
    }

    @Test
    fun `markdown block end for unclosed fence goes to last line`() {
        val md = "```\ncode\ncode2"
        val r = FoldModel("markdown").rangeAt(md, 0)
        assertEquals(2, r!!.endLine)
    }

    @Test
    fun `markdown heading level guard handles non heading start`() {
        val md = "普通段落\n后续段落"
        // 非标题行按 level=1 处理：块末为最后一条非空行
        val range = FoldModel("markdown").rangeAt(md, 0)
        assertEquals(1, range!!.endLine)
        assertNull("末行无后续内容", FoldModel("markdown").rangeAt(md, 1))
    }
}
