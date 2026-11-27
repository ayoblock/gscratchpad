package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EditorActionsTest {

    @Test
    fun 空查询返回全部动作且保持声明顺序() {
        val result = EditorActions.search("")
        assertEquals(EditorActions.all.size, result.size)
        assertEquals("new", result.first().id)
    }

    @Test
    fun 中文标签可检索() {
        assertEquals(listOf("outline"), EditorActions.search("大纲").map { it.id })
    }

    @Test
    fun 英文别名可检索() {
        assertTrue(EditorActions.search("save").map { it.id }.contains("saveAs"))
    }

    @Test
    fun 检索大小写不敏感() {
        assertEquals(EditorActions.search("OUTLINE").map { it.id }, EditorActions.search("outline").map { it.id })
    }

    @Test
    fun 多词为与关系() {
        val ids = EditorActions.search("视图 大纲").map { it.id }
        assertEquals(listOf("outline"), ids)
    }

    @Test
    fun 无命中返回空() {
        assertTrue(EditorActions.search("zzz").isEmpty())
    }

    @Test
    fun 每个动作id唯一() {
        assertEquals(EditorActions.all.size, EditorActions.all.map { it.id }.toSet().size)
    }

    @Test
    fun find按id取用() {
        assertEquals("预览", EditorActions.find("preview")?.label)
        assertNull(EditorActions.find("missing"))
    }

    @Test
    fun R54撤销重做不进命令面板() {
        val ids = EditorActions.all.map { it.id }
        assertTrue("undo 不应出现在命令面板（编辑栏承载）", !ids.contains("undo"))
        assertTrue("redo 不应出现在命令面板（编辑栏承载）", !ids.contains("redo"))
        listOf("copy", "cut", "paste", "selectAll").forEach {
            assertTrue("缺少动作 $it", ids.contains(it))
        }
    }
}
