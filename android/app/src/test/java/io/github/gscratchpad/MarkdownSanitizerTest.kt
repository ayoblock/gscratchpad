package io.github.gscratchpad

import io.github.gscratchpad.platform.MarkdownSanitizer
import org.junit.Assert.assertEquals
import org.junit.Test

/** 预览清洗器：frontmatter 与 HTML 注释在预览中不可见，但正文原样保留。 */
class MarkdownSanitizerTest {

    @Test
    fun stripsFrontmatterWithDelimiters() {
        val src = "---\ntitle: 测试\ntags: [a, b]\n---\n# 正文\n内容"
        assertEquals("# 正文\n内容", MarkdownSanitizer.clean(src))
    }

    @Test
    fun stripsFrontmatterWithDotTerminatorAndBom() {
        val src = "\uFEFF---\nlayout: post\n...\n# H"
        assertEquals("# H", MarkdownSanitizer.clean(src))
    }

    @Test
    fun keepsHorizontalRuleInBody() {
        // 首行是标题而非 --- ，正文中的 --- 是水平线，不能当 frontmatter 删
        val src = "# H\n段落\n\n---\n\n下一段"
        assertEquals(src, MarkdownSanitizer.clean(src))
    }

    @Test
    fun keepsUnclosedLeadingDashes() {
        // 只有开始符、无结束符：可能是水平线，不改动
        val src = "---\n没有闭合"
        assertEquals(src, MarkdownSanitizer.clean(src))
    }

    @Test
    fun stripsInlineAndEmptyHtmlComments() {
        val src = "甲<!-- 批注 -->乙<!---->丙"
        assertEquals("甲乙丙", MarkdownSanitizer.clean(src))
    }

    @Test
    fun stripsMultilineCommentKeepingNewlines() {
        val src = "A<!-- 跨\n行\n注释 -->B\nC"
        // 注释内部两个换行保留，行结构不塌陷
        assertEquals("A\n\nB\nC", MarkdownSanitizer.clean(src))
    }

    @Test
    fun keepsCommentsInsideFencedCode() {
        val src = "```html\n<!-- 这是代码 -->\n```\n正文<!-- 隐藏 -->"
        assertEquals("```html\n<!-- 这是代码 -->\n```\n正文", MarkdownSanitizer.clean(src))
    }

    @Test
    fun keepsTildeFenceComments() {
        val src = "~~~\n<!-- code -->\n~~~\nX"
        assertEquals("~~~\n<!-- code -->\n~~~\nX", MarkdownSanitizer.clean(src))
    }

    @Test
    fun stripsFrontmatterThenComments() {
        val src = "---\ntitle: x <!-- 批注 -->\n---\n# H <!-- 隐藏 -->"
        assertEquals("# H ", MarkdownSanitizer.clean(src))
    }
}
