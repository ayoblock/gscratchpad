package io.github.gscratchpad

import io.github.gscratchpad.domain.search.SearchOptions
import io.github.gscratchpad.domain.search.TextSearch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** §9.2 查找替换：字面/大小写/正则/分组/计数。 */
class TextSearchTest {

    @Test
    fun `literal find is case insensitive by default`() {
        val text = "Alpha beta ALPHA"
        val hits = TextSearch.findAll(text, "alpha")
        assertEquals(2, hits.size)
        assertEquals(0, hits[0].first)
        assertEquals(11, hits[1].first)
    }

    @Test
    fun `case sensitive option`() {
        val hits = TextSearch.findAll("Alpha alpha", "Alpha", SearchOptions(caseSensitive = true))
        assertEquals(1, hits.size)
        assertEquals(0, hits[0].first)
    }

    @Test
    fun `regex with group replacement`() {
        val text = "第1章 第22章 第333章"
        val out = TextSearch.replaceAll(text, "第(\\d+)章", "Chapter $1", SearchOptions(regex = true))
        assertEquals(3, out.count)
        assertEquals("Chapter 1 Chapter 22 Chapter 333", out.text)
    }

    @Test
    fun `literal replace all counts occurrences`() {
        val out = TextSearch.replaceAll("a-b-a-b", "a", "x")
        assertEquals(2, out.count)
        assertEquals("x-b-x-b", out.text)
    }

    @Test
    fun `zero width regex does not hang`() {
        val hits = TextSearch.findAll("abc", "x*", SearchOptions(regex = true))
        assertTrue(hits.isEmpty())
    }

    @Test
    fun `regex replacement escapes dollar literal`() {
        val out = TextSearch.replaceAll("价格 10", "10", "\\\$20", SearchOptions(regex = true))
        assertEquals("价格 \$20", out.text)
    }
}
