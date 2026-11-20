package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AllFilesProbeTest {

    @Test
    fun API30_才支持() {
        assertFalse(AllFilesProbe.isSupported(29))
        assertTrue(AllFilesProbe.isSupported(30))
        assertTrue(AllFilesProbe.isSupported(36))
    }

    @Test
    fun 状态文案三态() {
        assertTrue(AllFilesProbe.statusLabel(false, false).contains("不需要"))
        assertTrue(AllFilesProbe.statusLabel(true, false).contains("未授予"))
        assertTrue(AllFilesProbe.statusLabel(true, true).contains("已授予"))
    }

    @Test
    fun 四个缺失项全部出现才判定恢复() {
        val full = listOf(".obsidian", "PDF", "markdor", "RebornMing", "shell", "untitled_2.txt", "web")
        assertTrue(AllFilesProbe.missingEntriesRecovered(full))
    }

    @Test
    fun 缺任一项判定失败且大小写不敏感() {
        assertFalse(AllFilesProbe.missingEntriesRecovered(listOf("markdor", "RebornMing", "shell")))
        assertTrue(
            AllFilesProbe.missingEntriesRecovered(
                listOf("MARKDOR", "rebornming", "SHELL", "UNTITLED_2.TXT"),
            ),
        )
    }

    @Test
    fun 结果文案分四态() {
        assertTrue(AllFilesProbe.resultLabel(false, emptyList()).contains("未运行"))
        assertTrue(AllFilesProbe.resultLabel(true, emptyList()).contains("失败"))
        val full = listOf("markdor", "RebornMing", "shell", "untitled_2.txt")
        assertTrue(AllFilesProbe.resultLabel(true, full).contains("全部可见"))
        assertTrue(AllFilesProbe.resultLabel(true, listOf("PDF")).contains("部分通过"))
        assertEquals(true, AllFilesProbe.missingEntriesRecovered(full))
    }
}
