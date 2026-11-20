package io.github.gscratchpad

import io.github.gscratchpad.platform.WorkDirPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** R33：工作目录绑定的纯逻辑（不依赖 Android 环境）。 */
class WorkDirPolicyTest {

    @Test
    fun `显示名规范化_空白回落默认`() {
        assertEquals(WorkDirPolicy.DEFAULT_NAME, WorkDirPolicy.normalizeName(null))
        assertEquals(WorkDirPolicy.DEFAULT_NAME, WorkDirPolicy.normalizeName(""))
        assertEquals(WorkDirPolicy.DEFAULT_NAME, WorkDirPolicy.normalizeName("   "))
    }

    @Test
    fun `显示名规范化_去首尾空白`() {
        assertEquals("笔记", WorkDirPolicy.normalizeName("  笔记  "))
    }

    @Test
    fun `按钮文案含显示名_SAF绑定`() {
        assertEquals(
            "工作目录：笔记",
            WorkDirPolicy.label(WorkDirPolicy.Binding("content://x/tree/1", "笔记")),
        )
    }

    @Test
    fun `按钮文案_路径绑定取末级目录名`() {
        assertEquals(
            "工作目录：Obsidian",
            WorkDirPolicy.label(WorkDirPolicy.Binding("", "忽略", "/storage/emulated/0/Download/Obsidian")),
        )
        assertEquals(
            "工作目录：内部存储",
            WorkDirPolicy.label(WorkDirPolicy.Binding("", "忽略", "/storage/emulated/0")),
        )
    }

    @Test
    fun `校验SAF tree URI`() {
        assertTrue(WorkDirPolicy.isValidUri("content://com.android.externalstorage.documents/tree/primary%3ANotes"))
        assertTrue(WorkDirPolicy.isValidUri("content://x/tree/y"))
    }

    @Test
    fun `拒绝非法URI`() {
        assertFalse(WorkDirPolicy.isValidUri(null))
        assertFalse(WorkDirPolicy.isValidUri(""))
        assertFalse(WorkDirPolicy.isValidUri("file:///sdcard/notes"))
        assertFalse(WorkDirPolicy.isValidUri("content://x/document/y"))
        assertFalse(WorkDirPolicy.isValidUri("https://example.com/tree/a"))
    }

    @Test
    fun `校验File直读路径`() {
        assertTrue(WorkDirPolicy.isValidPath("/storage/emulated/0"))
        assertTrue(WorkDirPolicy.isValidPath("/storage/emulated/0/Download/Obsidian"))
    }

    @Test
    fun `拒绝越界路径`() {
        assertFalse(WorkDirPolicy.isValidPath(null))
        assertFalse(WorkDirPolicy.isValidPath(""))
        assertFalse(WorkDirPolicy.isValidPath("/data/data/io.github.gscratchpad"))
        assertFalse(WorkDirPolicy.isValidPath("/storage/emulated/0/../private"))
    }
}
