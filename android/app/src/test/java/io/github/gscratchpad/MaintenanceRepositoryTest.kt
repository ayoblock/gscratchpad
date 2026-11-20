package io.github.gscratchpad

import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.testing.TestHarness
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** R39：孤儿扫描/清理与清除已关闭笔记的仓库级回归（真实 sqlite + 临时文件树）。 */
class MaintenanceRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var h: TestHarness

    @Before
    fun setUp() {
        h = TestHarness(tmp.newFolder("data"), StandardTestDispatcher())
    }

    @After
    fun tearDown() = h.close()

    private fun orphanFixtures() {
        File(h.paths.notes, "deadbeefdeadbeef.md").writeText("孤儿", Charsets.UTF_8)
        File(h.paths.assets, "deadbeefdeadbeef").mkdirs()
        File(h.paths.assets, "deadbeefdeadbeef/p.png").writeBytes(ByteArray(2048))
        File(h.paths.recovery, "deadbeefdeadbeef.json").writeText("{}", Charsets.UTF_8)
    }

    @Test
    fun `scan只统计不删除且区分孤儿类型`() = runTest(h.dispatcher) {
        val live = h.repo.create(Format.MD, "在用")
        orphanFixtures()
        val scan = h.repo.scanOrphans()
        assertEquals(1, scan.orphanNotes)
        assertEquals(1, scan.orphanAssets)
        assertEquals(1, scan.orphanJournals)
        assertTrue(scan.orphanAssetsBytes >= 2048)
        // 只统计：孤儿文件仍在
        assertTrue(File(h.paths.notes, "deadbeefdeadbeef.md").exists())
        // 在用文档的镜像不应被当作孤儿（create 已落镜像）
        assertFalse("在用文档不应计入孤儿", h.dao.allIds().isEmpty())
        assertTrue(live.id in h.dao.allIds())
    }

    @Test
    fun `maintain删除孤儿保留在用文档并在事务后清理失效映射`() = runTest(h.dispatcher) {
        val live = h.repo.create(Format.MD, "在用")
        orphanFixtures()
        h.dao.setMeta("source_path:deadbeefdeadbeef", "/sdcard/gone.md")
        val report = h.repo.maintain(vacuum = true)
        assertEquals(1, report.orphanNotes)
        assertEquals(1, report.orphanAssets)
        assertEquals(1, report.orphanJournals)
        assertEquals(1, report.staleMeta)
        assertTrue("VACUUM 应在 sqlite-jdbc 上成功", report.vacuumed)
        assertTrue(report.errors.isEmpty())
        assertFalse(File(h.paths.notes, "deadbeefdeadbeef.md").exists())
        assertFalse(File(h.paths.assets, "deadbeefdeadbeef").exists())
        assertFalse(File(h.paths.recovery, "deadbeefdeadbeef.json").exists())
        assertTrue("失效映射已删除", h.dao.staleMetaKeys(setOf(live.id)).isEmpty())
        assertTrue("在用文档不受影响", h.dao.exists(live.id))
    }

    @Test
    fun `新鲜tmp不清理`() = runTest(h.dispatcher) {
        val fresh = File(h.paths.notes, "fresh.tmp")
        fresh.writeText("原子写进行中", Charsets.UTF_8)
        h.repo.maintain(vacuum = false)
        assertTrue("刚写入的 .tmp 不应被当作残留", fresh.exists())
    }

    @Test
    fun `purgeClosed删除已关闭文档及镜像但保留在用文档`() = runTest(h.dispatcher) {
        val open = h.repo.create(Format.MD, "开着")
        val closed = h.repo.create(Format.MD, "已关")
        h.repo.setState(closed.id, false)
        val report = h.repo.purgeClosed(keepIds = setOf(open.id))
        assertEquals(1, report.purgedDocs)
        // 新建文档正文为空，purgedBytes 合法为 0；这里只断言统计字段存在且非负
        assertTrue(report.purgedBytes >= 0)
        assertTrue(h.dao.exists(open.id))
        assertFalse(h.dao.exists(closed.id))
    }
}
