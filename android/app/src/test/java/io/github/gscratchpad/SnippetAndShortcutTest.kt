package io.github.gscratchpad

import io.github.gscratchpad.domain.keys.KeyAction
import io.github.gscratchpad.domain.keys.Shortcuts
import io.github.gscratchpad.domain.snippet.Snippet
import io.github.gscratchpad.domain.snippet.SnippetLibrary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** §13 降级项：片段插入与物理键盘快捷键映射。 */
class SnippetAndShortcutTest {

    @Test
    fun `snippet append keeps separator rules`() {
        assertEquals("```kotlin\n\n```\n", SnippetLibrary.append("", Snippet.CODE))
        assertEquals("正文\n```kotlin\n\n```\n", SnippetLibrary.append("正文", Snippet.CODE))
        assertEquals("正文\n```kotlin\n\n```\n", SnippetLibrary.append("正文\n", Snippet.CODE))
    }

    @Test
    fun `snippet library exposes stable ids`() {
        assertTrue(Snippet.entries.all { it.id.isNotBlank() && it.label.isNotBlank() && it.body.isNotBlank() })
        assertEquals(Snippet.TABLE, SnippetLibrary.byId("table"))
        assertNull(SnippetLibrary.byId("nope"))
        assertEquals(4, Snippet.entries.size)
    }

    @Test
    fun `ctrl shortcuts resolve to actions`() {
        assertEquals(KeyAction.NEW, Shortcuts.resolve(true, false, "N"))
        assertEquals(KeyAction.CLOSE, Shortcuts.resolve(true, false, "W"))
        assertEquals(KeyAction.FIND, Shortcuts.resolve(true, false, "F"))
        assertEquals(KeyAction.REPLACE, Shortcuts.resolve(true, false, "H"))
        assertEquals(KeyAction.PREVIEW, Shortcuts.resolve(true, true, "P"))
        assertEquals(KeyAction.NEXT_TAB, Shortcuts.resolve(true, false, "TAB"))
    }

    @Test
    fun `tab switches map to next and prev doc`() {
        assertEquals(KeyAction.NEXT_TAB, Shortcuts.resolve(true, false, "TAB"))
        assertEquals(KeyAction.PREV_TAB, Shortcuts.resolve(true, true, "TAB"))
    }

    @Test
    fun `plain keys and unknown combos are not shortcuts`() {
        assertNull(Shortcuts.resolve(false, false, "N"))
        assertNull(Shortcuts.resolve(true, false, "X"))
        assertNull(Shortcuts.resolve(true, true, "F"))
        // 小写键名同样识别
        assertEquals(KeyAction.NEW, Shortcuts.resolve(true, false, "n"))
    }
}
