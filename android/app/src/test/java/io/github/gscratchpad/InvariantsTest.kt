package io.github.gscratchpad

import io.github.gscratchpad.capture.CaptureRequest
import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.data.SaveQueue
import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.testing.TestHarness
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * 方案 §5.8 语义不变量回归（I1–I7）。
 *
 * 这些用例直接复用生产对象图，仅替换 SQL 驱动；每条不变量对应桌面版的一个契约，
 * 后续 M1/M2 改动必须在同一组用例上回归。
 */
class InvariantsTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var harness: TestHarness

    @Before
    fun setUp() {
        harness = TestHarness(tmp.newFolder("data"), StandardTestDispatcher())
    }

    @After
    fun tearDown() {
        harness.close()
    }

    /** I1：落盘内容恒为全文，折叠不改内容。 */
    @Test
    fun `I1 stored content is the full text`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.MD, "全文")
        val full = buildString {
            repeat(50) { append("第 $it 行：内容\n") }
        }
        val ticket = harness.repo.saveNow(doc.id, full, doc.revision + 1)
        assertTrue(ticket.accepted)

        val stored = harness.repo.get(doc.id)!!
        assertEquals(full, stored.content)
        val mirror = File(harness.paths.notes, "${doc.id}.md").readText()
        assertEquals(full, mirror)
    }

    /** I2：revision 单调递增，晚到的旧快照被丢弃。 */
    @Test
    fun `I2 stale revisions are dropped`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.TXT, "顺序")
        var maxRevision = doc.revision

        // 正常递增 1..100
        for (rev in 1..100) {
            harness.dao.applySnapshot(doc.id, doc.title, doc.format, "content-$rev", rev.toLong(), 0.0)
            legend(doc.id, maxRevision, rev.toLong())
            maxRevision = maxOf(maxRevision, harness.dao.revisionOf(doc.id)!!)
        }
        assertEquals(100L, harness.dao.revisionOf(doc.id))

        // 乱序回放旧的 1..99，库内 revision 与内容都不得回退
        for (rev in 1..99) {
            harness.dao.applySnapshot(doc.id, doc.title, doc.format, "old-$rev", rev.toLong(), 0.0)
            assertEquals(100L, harness.dao.revisionOf(doc.id))
        }
        assertEquals("content-100", harness.dao.get(doc.id)!!.content)
    }

    /** I3：先写 journal 再提交，崩溃后启动回填。 */
    @Test
    fun `I3 recovery journal restores newer content`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.MD, "恢复")
        harness.repo.saveNow(doc.id, "已提交内容", 2)

        // 模拟：journal 已写、数据库提交前进程被杀
        harness.recovery.writeJournal(doc.id, 3, "崩溃前最新内容", 1.0)

        val notes = harness.recovery.recover(harness.db, harness.dao, harness.mirror)
        assertEquals(1, notes.size)
        assertEquals("崩溃前最新内容", harness.repo.get(doc.id)!!.content)
        assertEquals(3L, harness.dao.revisionOf(doc.id))
        assertFalse("journal 回填后应删除", harness.paths.journalFile(doc.id).exists())
        assertEquals(
            "崩溃前最新内容",
            File(harness.paths.notes, "${doc.id}.md").readText(),
        )
    }

    /** I3 补充：journal 的 revision 不比库内新时不覆盖。 */
    @Test
    fun `I3 stale journal does not overwrite`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.TXT, "恢复")
        harness.repo.saveNow(doc.id, "较新内容", 5)
        harness.recovery.writeJournal(doc.id, 4, "较旧内容", 1.0)
        harness.recovery.recover(harness.db, harness.dao, harness.mirror)
        assertEquals("较新内容", harness.repo.get(doc.id)!!.content)
    }

    /** I4：notes 镜像原子替换，写入后不存在半截文件或残留 tmp。 */
    @Test
    fun `I4 mirror atomic replace leaves no temp`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.MD, "镜像")
        harness.repo.saveNow(doc.id, "A".repeat(10_000), 2)
        val mirror = File(harness.paths.notes, "${doc.id}.md")
        assertEquals(10_000, mirror.readText().length)

        harness.repo.saveNow(doc.id, "B".repeat(20_000), 3)
        assertEquals(20_000, mirror.readText().length)
        assertFalse(File(harness.paths.notes, "${doc.id}.md.tmp").exists())
    }

    /** I5：单写线程串行，8 路并发提交无锁错误。 */
    @Test
    fun `I5 concurrent saves are serialized`() = runTest(harness.dispatcher) {
        val docs = (1..8).map { harness.repo.create(Format.TXT, "并发 $it") }
        val jobs = docs.map { doc ->
            async {
                val ticket = harness.repo.saveNow(doc.id, "内容-${doc.title}", doc.revision + 1)
                assertTrue(ticket.accepted)
            }
        }
        jobs.awaitAll()
        docs.forEach { doc ->
            assertEquals("内容-${doc.title}", harness.repo.get(doc.id)!!.content)
        }
    }

    /** I6：关闭标签不删除文档。 */
    @Test
    fun `I6 closing a tab keeps the document`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.MD, "关闭")
        harness.repo.setState(doc.id, open = false)
        assertEquals(DocState.CLOSED, harness.repo.get(doc.id)!!.state)
        assertTrue(harness.dao.allDocuments().any { it.id == doc.id })
        assertEquals(0, harness.dao.openDocuments().size)
    }

    /** I7：capture 同 key 幂等，append 永不覆盖。 */
    @Test
    fun `I7 capture is idempotent and append never overwrites`() = runTest(harness.dispatcher) {
        val now = 1_700_000_000.0
        val request = CaptureRequest(
            text = "第一段",
            title = "读书",
            book = "书",
            page = "1/2 页",
            key = "lectula:book-1",
            mode = "create",
        )
        val first = harness.capture.capture(request, now)
        assertTrue(first.created)

        val second = harness.capture.capture(request, now + 60)
        assertFalse(second.created)
        assertEquals(first.docId, second.docId)
        val doc = harness.repo.get(first.docId)!!
        assertEquals(1, Regex("第一段").findAll(doc.content).count())

        val appended = harness.capture.capture(
            request.copy(text = "第二段", mode = "append"),
            now + 120,
        )
        val after = harness.repo.get(appended.docId)!!
        assertTrue(after.content.contains("第一段"))
        assertTrue(after.content.contains("第二段"))
        assertTrue(after.content.contains("\n---\n"))
        assertTrue(after.content.indexOf("第一段") < after.content.indexOf("第二段"))

        val keyDoc = harness.repo.getMeta(MetaKeys.ext("lectula:book-1"))
        assertEquals(first.docId, keyDoc)
    }

    /** 保存 ticket 对旧 revision 不生效（repository 层校验）。 */
    @Test
    fun `stale save ticket is rejected`() = runTest(harness.dispatcher) {
        val doc = harness.repo.create(Format.TXT, "ticket")
        harness.repo.saveNow(doc.id, "new", 10)
        val ticket: SaveQueue.SaveTicket = harness.repo.saveNow(doc.id, "old", 9)
        assertFalse(ticket.accepted)
        assertEquals("new", harness.repo.get(doc.id)!!.content)
        assertNotNull(harness.dao.revisionOf(doc.id))
    }

    private var lastRevision: Long = 0

    private fun legend(id: String, previous: Long, rev: Long) {
        val current = harness.dao.revisionOf(id)!!
        assertTrue("revision 不得回退：$previous -> $current", current >= previous)
        assertTrue("写入后的 revision 不得小于提交值", current >= rev)
        lastRevision = current
    }
}

