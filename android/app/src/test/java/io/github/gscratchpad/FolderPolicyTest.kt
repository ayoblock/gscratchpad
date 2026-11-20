package io.github.gscratchpad

import io.github.gscratchpad.platform.FolderPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** T3 文件夹命名策略纯单测。 */
class FolderPolicyTest {

    @Test
    fun `合法名返回 trim 结果`() {
        assertEquals("工作", FolderPolicy.clean("  工作  "))
        assertEquals("Project-2026", FolderPolicy.clean("Project-2026"))
        assertEquals("读书笔记 01", FolderPolicy.clean("读书笔记 01"))
    }

    @Test
    fun `空名与纯空白被拒绝`() {
        assertTrue(runCatching { FolderPolicy.clean("") }.exceptionOrNull() is IllegalArgumentException)
        assertTrue(runCatching { FolderPolicy.clean("   ") }.exceptionOrNull() is IllegalArgumentException)
    }

    @Test
    fun `超长名被拒绝`() {
        val tooLong = "字".repeat(FolderPolicy.MAX_LENGTH + 1)
        val ex = runCatching { FolderPolicy.clean(tooLong) }.exceptionOrNull()
        assertTrue(ex is IllegalArgumentException)
        assertTrue(ex!!.message!!.contains(FolderPolicy.MAX_LENGTH.toString()))
        assertEquals(FolderPolicy.MAX_LENGTH, FolderPolicy.clean("字".repeat(FolderPolicy.MAX_LENGTH)).length)
    }

    @Test
    fun `路径分隔符被拒绝`() {
        assertTrue(runCatching { FolderPolicy.clean("a/b") }.exceptionOrNull() is IllegalArgumentException)
        assertTrue(runCatching { FolderPolicy.clean("a\\b") }.exceptionOrNull() is IllegalArgumentException)
    }

    @Test
    fun `控制字符被拒绝`() {
        assertTrue(runCatching { FolderPolicy.clean("a\nb") }.exceptionOrNull() is IllegalArgumentException)
        assertTrue(runCatching { FolderPolicy.clean("a\tb") }.exceptionOrNull() is IllegalArgumentException)
    }

    @Test
    fun `未归档为保留名`() {
        assertTrue(runCatching { FolderPolicy.clean("未归档") }.exceptionOrNull() is IllegalArgumentException)
        assertEquals("未归档 1", FolderPolicy.clean("未归档 1"))
    }

    @Test
    fun `validate 与 clean 同规则`() {
        assertNull(FolderPolicy.validate("  合法  "))
        assertEquals("文件夹名不能为空", FolderPolicy.validate("  "))
        assertTrue(FolderPolicy.validate("a/b")!!.contains("斜杠"))
    }

    @Test
    fun `display 映射空 folder`() {
        assertEquals("未归档", FolderPolicy.display(""))
        assertEquals("工作", FolderPolicy.display("工作"))
    }
}
