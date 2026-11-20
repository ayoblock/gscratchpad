package io.github.gscratchpad

import io.github.gscratchpad.domain.DocumentSwitch
import org.junit.Assert.assertEquals
import org.junit.Test

/** T1 文档切换索引逻辑单测：三入口共用的循环规则。 */
class DocumentSwitchTest {

    @Test
    fun `空列表返回负一`() {
        assertEquals(-1, DocumentSwitch.targetIndex(0, 0, 1))
        assertEquals(-1, DocumentSwitch.targetIndex(0, -1, -1))
    }

    @Test
    fun `多文档 next 循环到开头`() {
        assertEquals(1, DocumentSwitch.targetIndex(5, 0, 1))
        assertEquals(2, DocumentSwitch.targetIndex(5, 1, 1))
        assertEquals(0, DocumentSwitch.targetIndex(5, 4, 1))
    }

    @Test
    fun `多文档 prev 循环到末尾`() {
        assertEquals(3, DocumentSwitch.targetIndex(5, 4, -1))
        assertEquals(4, DocumentSwitch.targetIndex(5, 0, -1))
    }

    @Test
    fun `单文档 next 与 prev 都指向自身`() {
        assertEquals(0, DocumentSwitch.targetIndex(1, 0, 1))
        assertEquals(0, DocumentSwitch.targetIndex(1, 0, -1))
    }

    @Test
    fun `当前不在列表时 next 到首个 prev 到末尾`() {
        val ids = listOf("a", "b", "c")
        assertEquals(0, DocumentSwitch.targetIndexById(ids, "missing", 1))
        assertEquals(2, DocumentSwitch.targetIndexById(ids, "missing", -1))
        assertEquals(2, DocumentSwitch.targetIndexById(ids, "b", 1))
    }
}
