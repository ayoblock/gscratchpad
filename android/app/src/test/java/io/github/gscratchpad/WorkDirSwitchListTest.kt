package io.github.gscratchpad

import io.github.gscratchpad.domain.WorkDirSwitchList
import io.github.gscratchpad.domain.WorkDirSwitchList.DocEntry
import io.github.gscratchpad.domain.WorkDirSwitchList.Item
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkDirSwitchListTest {
    private val dir = "/storage/emulated/0/Documents/notes"

    @Test
    fun `未绑定目录退回库内文档`() {
        val docs = listOf(DocEntry("id1", "甲", null), DocEntry("id2", "乙", "$dir/a.md"))
        assertEquals(
            listOf(Item("id1", "甲"), Item("id2", "乙")),
            WorkDirSwitchList.build(null, docs, listOf("$dir/a.md")),
        )
    }

    @Test
    fun `目录内已入库文件用doc id和库内标题`() {
        val docs = listOf(DocEntry("d1", "我的笔记", "$dir/a.md"))
        val result = WorkDirSwitchList.build(dir, docs, listOf("$dir/a.md"))
        assertEquals(listOf(Item("d1", "我的笔记")), result)
    }

    @Test
    fun `目录内未入库文件用虚拟id和文件名`() {
        val result = WorkDirSwitchList.build(dir, emptyList(), listOf("$dir/b.md"))
        assertEquals(listOf(Item("file:$dir/b.md", "b.md")), result)
    }

    @Test
    fun `目录文件全部列出无论是否入库`() {
        val docs = listOf(DocEntry("d1", "甲", "$dir/a.md"))
        val files = listOf("$dir/a.md", "$dir/b.md", "$dir/c.txt")
        val result = WorkDirSwitchList.build(dir, docs, files)
        assertEquals(
            listOf(
                Item("d1", "甲"),
                Item("file:$dir/b.md", "b.md"),
                Item("file:$dir/c.txt", "c.txt"),
            ),
            result,
        )
    }

    @Test
    fun `目录外库文档保留并排在同目录之后`() {
        val docs = listOf(
            DocEntry("d1", "甲", "$dir/a.md"),
            DocEntry("d2", "别处", "/storage/emulated/0/other/x.md"),
            DocEntry("d3", "无源", null),
        )
        val result = WorkDirSwitchList.build(dir, docs, listOf("$dir/a.md", "$dir/b.md"))
        assertEquals(
            listOf(
                Item("d1", "甲"),
                Item("file:$dir/b.md", "b.md"),
                Item("d2", "别处"),
                Item("d3", "无源"),
            ),
            result,
        )
    }

    @Test
    fun `虚拟id识别与取路径`() {
        assertTrue(WorkDirSwitchList.isVirtual("file:$dir/a.md"))
        assertFalse(WorkDirSwitchList.isVirtual("d1"))
        assertEquals("$dir/a.md", WorkDirSwitchList.pathOf("file:$dir/a.md"))
    }

    @Test
    fun `父目录与文件名`() {
        assertEquals(dir, WorkDirSwitchList.parentOf("$dir/a.md"))
        assertEquals("", WorkDirSwitchList.parentOf("a.md"))
        assertEquals("a.md", WorkDirSwitchList.fileName("$dir/a.md"))
    }

    @Test
    fun `尾斜杠目录规范化后仍能匹配`() {
        val docs = listOf(DocEntry("d1", "甲", "$dir/a.md"))
        val result = WorkDirSwitchList.build("$dir/", docs, listOf("$dir/a.md"))
        assertEquals(listOf(Item("d1", "甲")), result)
    }

    // ---- R45：切换列表列目录口径（当前文档同目录优先，绑定工作目录回退） ----

    @Test
    fun `当前文档有共享存储路径时用其父目录_无视绑定`() {
        val active = "/storage/emulated/0/Download/Obsidian/a.md"
        // 即使绑定了别的目录，也以当前文档同目录为准
        assertEquals("/storage/emulated/0/Download/Obsidian", WorkDirSwitchList.dirForList(active, dir))
    }

    @Test
    fun `当前文档无有效路径时回退绑定目录`() {
        assertEquals(dir, WorkDirSwitchList.dirForList(null, dir))
        // content://（旧 SAF 打开）不是 File 路径 → 回退
        assertEquals(dir, WorkDirSwitchList.dirForList("content://x/y/tree/a", dir))
        // 共享存储之外的绝对路径（私有目录）不认 → 回退
        assertEquals(dir, WorkDirSwitchList.dirForList("/data/data/x/a.md", dir))
    }

    @Test
    fun `都没有时返回null_列表只列库内文档`() {
        assertNull(WorkDirSwitchList.dirForList(null, null))
        assertNull(WorkDirSwitchList.dirForList(null, ""))
        // 绑定路径为空串也视为未绑定
        assertNull(WorkDirSwitchList.dirForList("content://x", ""))
        // 路径穿越不认
        assertNull(WorkDirSwitchList.dirForList("/storage/emulated/0/../evil/a.md", null))
    }
}
