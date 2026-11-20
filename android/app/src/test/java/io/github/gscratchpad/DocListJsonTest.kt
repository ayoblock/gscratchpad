package io.github.gscratchpad

import io.github.gscratchpad.domain.DocListJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONArray

/** R33：文档切换浮层的列表序列化（纯逻辑）。 */
class DocListJsonTest {

    private fun parse(json: String): List<DocListJson.Item> {
        val arr = JSONArray(json)
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            DocListJson.Item(o.getString("id"), o.getString("title"), o.getBoolean("active"))
        }
    }

    @Test
    fun `空列表序列化为空数组`() {
        assertEquals("[]", DocListJson.serialize(emptyList(), emptyList(), "x"))
    }

    @Test
    fun `按顺序序列化并标记激活项`() {
        val json = DocListJson.serialize(
            listOf("a", "b", "c"),
            listOf("甲", "乙", "丙"),
            "b",
        )
        val items = parse(json)
        assertEquals(3, items.size)
        assertEquals("a", items[0].id)
        assertEquals("甲", items[0].title)
        assertFalse(items[0].active)
        assertTrue(items[1].active)
        assertFalse(items[2].active)
    }

    @Test
    fun `标题为空时回落未命名`() {
        val items = parse(DocListJson.serialize(listOf("x"), listOf("   "), "x"))
        assertEquals("未命名", items[0].title)
    }

    @Test
    fun `标题数少于id数时安全回落`() {
        val items = parse(DocListJson.serialize(listOf("a", "b"), listOf("甲"), null))
        assertEquals("甲", items[0].title)
        assertEquals("未命名", items[1].title)
        assertFalse(items.any { it.active })
    }

    @Test
    fun `激活id不存在时无活跃项`() {
        val items = parse(DocListJson.serialize(listOf("a"), listOf("甲"), "不存在"))
        assertFalse(items[0].active)
    }
}
