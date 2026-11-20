package io.github.gscratchpad

import io.github.gscratchpad.domain.fold.FoldModel
import io.github.gscratchpad.domain.fold.FoldStrategy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** §5.7 折叠区间：markdown 标题 / 围栏、缩进、括号三种策略与 `folding.py` 对齐。 */
class FoldModelTest {

    @Test
    fun `markdown headings fold to next same level`() {
        val text = """
# A
正文 1
## B
正文 2
## C
正文 3
# D
结尾
""".trim()
        val model = FoldModel("markdown")
        assertEquals(FoldStrategy.MARKDOWN, model.strategy)
        val ranges = model.foldableRanges(text)
        // 第 0 行（# A）折叠到第 5 行（## C 的最后一行），第 2 行（## B）折叠到第 3 行
        assertTrue(ranges.any { it.headerLine == 0 && it.endLine == 5 })
        assertTrue(ranges.any { it.headerLine == 2 && it.endLine == 3 })
    }

    @Test
    fun `fenced code block is foldable`() {
        val text = """
说明
```kotlin
val a = 1
val b = 2
```
结尾
""".trim()
        val model = FoldModel("markdown")
        val ranges = model.foldableRanges(text)
        assertTrue(ranges.any { it.headerLine == 1 && it.endLine == 4 })
    }

    @Test
    fun `indent strategy folds nested block`() {
        val text = """
root
  child
    grandchild
  child2
next
""".trim()
        val model = FoldModel("")
        assertEquals(FoldStrategy.INDENT, model.strategy)
        val range = model.rangeAt(text, 0)
        assertNotNull(range)
        assertEquals(0, range!!.headerLine)
        assertEquals(3, range.endLine)
    }

    @Test
    fun `brace strategy folds json object`() {
        val text = """
{
  "a": 1,
  "b": [1, 2]
}
""".trim()
        val model = FoldModel("json")
        assertEquals(FoldStrategy.BRACE, model.strategy)
        val range = model.rangeAt(text, 0)
        assertNotNull(range)
        assertEquals(0, range!!.headerLine)
        assertEquals(3, range.endLine)
    }

    @Test
    fun `single line is not foldable`() {
        val model = FoldModel("markdown")
        org.junit.Assert.assertNull(model.rangeAt("# 只有标题", 0))
    }
}
