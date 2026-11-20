package io.github.gscratchpad

import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.testing.TestHarness
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * T3 文件夹仓库测试（T3-R5）：用真实 sqlite 验证五方法事务语义。
 * 覆盖：创建/重命名（带文档迁移）/删除（回未归档不删正文）/移动/撞名拒绝/命名校验/
 * 分组与计数/recentHidden 过滤。
 */
class FoldersRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var h: TestHarness

    @Before
    fun setUp() {
        h = TestHarness(tmp.newFolder("data"), StandardTestDispatcher())
    }

    @After
    fun tearDown() = h.close()

    private suspend fun seedDoc(title: String, folder: String = "", hidden: Boolean = false): String {
        val d = h.repo.create(Format.MD, title)
        if (folder.isNotEmpty()) h.repo.moveToFolder(d.id, folder)
        if (hidden) h.repo.clearRecent(d.id)
        return d.id
    }

    @Test
    fun `folders 初始为空且 createdAt 保留`() = runTest(h.dispatcher) {
        assertTrue(h.repo.folders().isEmpty())
        h.repo.createFolder("工作")
        val folders = h.repo.folders()
        assertEquals(1, folders.size)
        assertEquals("工作", folders[0].name)
        assertTrue("createdAt 应保留真实时间", folders[0].createdAt > 0.0)
    }

    @Test
    fun `createFolder trim 后创建且拒绝空名与保留名`() = runTest(h.dispatcher) {
        h.repo.createFolder("  项目A  ")
        assertEquals("项目A", h.repo.folders().single().name)
        for (bad in listOf("", "   ", "未归档", "a/b")) {
            try {
                h.repo.createFolder(bad)
                fail("应拒绝非法名: [$bad]")
            } catch (e: IllegalArgumentException) {
                // expected
            }
        }
        assertEquals(1, h.repo.folders().size)
    }

    @Test
    fun `撞名拒绝不静默合并 Q6`() = runTest(h.dispatcher) {
        h.repo.createFolder("同名")
        try {
            h.repo.createFolder("同名")
            fail("同名创建应被拒绝")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("已存在"))
        }
        // 库里仍只有一个
        assertEquals(1, h.repo.folders().size)
    }

    @Test
    fun `renameFolder 撞名拒绝`() = runTest(h.dispatcher) {
        h.repo.createFolder("甲")
        h.repo.createFolder("乙")
        try {
            h.repo.renameFolder("甲", "乙")
            fail("重命名到已存在名应被拒绝")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("已存在"))
        }
        assertEquals(setOf("甲", "乙"), h.repo.folders().map { it.name }.toSet())
    }

    @Test
    fun `renameFolder 带文档迁移且正文不变`() = runTest(h.dispatcher) {
        h.repo.createFolder("旧名")
        val id = seedDoc("迁移文档", "旧名")
        val before = h.repo.get(id)!!.content
        h.repo.renameFolder("旧名", "新名")
        val after = h.repo.get(id)!!
        assertEquals("新名", after.folder)
        assertEquals(before, after.content)
        assertEquals(setOf("新名"), h.repo.folders().map { it.name }.toSet())
    }

    @Test
    fun `renameFolder 到自身不冲突`() = runTest(h.dispatcher) {
        h.repo.createFolder("自身")
        h.repo.renameFolder("自身", "自身")
        assertEquals("自身", h.repo.folders().single().name)
    }

    @Test
    fun `deleteFolder 文档回未归档且正文不删`() = runTest(h.dispatcher) {
        h.repo.createFolder("待删")
        val d = h.repo.create(Format.MD, "保留正文")
        h.repo.saveNow(d.id, "# 不能丢的内容", 2)
        h.repo.moveToFolder(d.id, "待删")
        h.repo.deleteFolder("待删")
        val after = h.repo.get(d.id)!!
        assertEquals("", after.folder)
        assertTrue(after.content.contains("不能丢的内容"))
        assertTrue(h.repo.folders().isEmpty())
    }

    @Test
    fun `moveToFolder 到未归档用空串且自动建目录行`() = runTest(h.dispatcher) {
        val d = h.repo.create(Format.MD, "移动我")
        h.repo.moveToFolder(d.id, "新目录") // setFolder 应自动 INSERT 目录行
        assertEquals("新目录", h.repo.folders().single().name)
        h.repo.moveToFolder(d.id, "")
        assertEquals("", h.repo.get(d.id)!!.folder)
        // 目录行仍在（move 不删目录）
        assertEquals("新目录", h.repo.folders().single().name)
    }

    @Test
    fun `folderCounts 与 documentsInFolder 分组正确`() = runTest(h.dispatcher) {
        h.repo.createFolder("A")
        h.repo.createFolder("B")
        seedDoc("a1", "A")
        seedDoc("a2", "A")
        seedDoc("b1", "B")
        val counts = h.repo.folderCounts()
        assertEquals(2, counts["A"])
        assertEquals(1, counts["B"])
        assertEquals(2, h.repo.documentsInFolder("A").size)
        assertEquals(1, h.repo.documentsInFolder("B").size)
    }

    @Test
    fun `documentsInFolder 默认排除 recentHidden Q7`() = runTest(h.dispatcher) {
        seedDoc("显示", "A")
        seedDoc("隐藏", "A", hidden = true)
        assertEquals(1, h.repo.documentsInFolder("A").size)
        assertEquals("显示", h.repo.documentsInFolder("A").single().title)
        assertEquals(2, h.repo.documentsInFolder("A", includeHidden = true).size)
    }
}
