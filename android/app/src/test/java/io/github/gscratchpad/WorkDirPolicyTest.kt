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
    fun `按钮文案含显示名`() {
        assertEquals(
            "工作目录：笔记",
            WorkDirPolicy.label(WorkDirPolicy.Binding("content://x/tree/1", "笔记")),
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
}
