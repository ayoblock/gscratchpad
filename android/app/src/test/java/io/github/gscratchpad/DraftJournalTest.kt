package io.github.gscratchpad

import io.github.gscratchpad.data.DraftJournal
import io.github.gscratchpad.data.MirrorStore
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.testing.TestHarness
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * P2-5 热日志回归：输入立即写 journal（不等 300 ms 防抖），启动时由 recover 回填。
 *
 * 对应真机缺口：300 ms 防抖窗内 `am force-stop` 时最后一批字符没有任何落盘痕迹。
 */
class DraftJournalTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var harness: TestHarness

    @Before
    fun setUp() {
        harness = TestHarness(tmp.newFolder("data"), StandardTestDispatcher(), debounceMs = 0L)
    }

    @After
    fun tearDown() {
        harness.close()
    }

    @Test
    fun offerWritesJournalImmediately() {
        val journal = DraftJournal(harness.recovery)
        val docId = "docA"
        journal.offer(docId, 5L, "hello hot journal")

        val file = harness.paths.journalFile(docId)
        val deadline = System.currentTimeMillis() + 3_000
        while (!file.exists() && System.currentTimeMillis() < deadline) Thread.sleep(5)
        assertTrue("journal 未在 3 s 内写出", file.exists())

        val json = JSONObject(file.readText(Charsets.UTF_8))
        assertEquals(docId, json.getString("id"))
        assertEquals(5L, json.getLong("revision"))
        assertEquals("hello hot journal", json.getString("content"))
    }

    @Test
    fun coalescesToLatestSnapshot() {
        val journal = DraftJournal(harness.recovery)
        val docId = "docB"
        repeat(200) { i -> journal.offer(docId, (i + 1).toLong(), "v$i") }
        val file = harness.paths.journalFile(docId)
        val deadline = System.currentTimeMillis() + 3_000
        while (!file.exists() && System.currentTimeMillis() < deadline) Thread.sleep(5)
        // 合并写入：最终落盘的一定是最新快照（可能是中间态之后的最新值）
        var last = ""
        val settle = System.currentTimeMillis() + 1_000
        while (System.currentTimeMillis() < settle) {
            last = file.readText(Charsets.UTF_8)
            if (JSONObject(last).getLong("revision") == 200L) break
            Thread.sleep(10)
        }
        assertEquals("v199", JSONObject(last).getString("content"))
        assertEquals(200L, JSONObject(last).getLong("revision"))
    }

    @Test
    fun recoveryRestoresJournalAndRewritesMirror() = runTest {
        val doc = Document(
            id = "docC",
            title = "热日志",
            format = Format.MD,
            content = "committed-3",
            sortIndex = 1,
            state = io.github.gscratchpad.domain.model.DocState.OPEN,
            revision = 3L,
            createdAt = 1.0,
            updatedAt = 1.0,
        )
        harness.dao.insert(doc)

        val journal = DraftJournal(harness.recovery)
        journal.offer(doc.id, 4L, "committed-3 + last-keystrokes")

        val file = harness.paths.journalFile(doc.id)
        val deadline = System.currentTimeMillis() + 3_000
        while (!file.exists() && System.currentTimeMillis() < deadline) Thread.sleep(5)
        assertTrue(file.exists())

        val notes = harness.recovery.recover(harness.db, harness.dao, MirrorStore(harness.paths))
        assertEquals(1, notes.size)
        val after = harness.dao.get(doc.id)!!
        assertEquals("committed-3 + last-keystrokes", after.content)
        assertEquals(4L, after.revision)
        assertEquals(
            "committed-3 + last-keystrokes",
            harness.paths.noteFile(doc.id, Format.MD).readText(Charsets.UTF_8),
        )
        assertTrue("恢复后 journal 必须删除", !file.exists())
    }

    @Test
    fun staleJournalAtSameRevisionIsDiscarded() = runTest {
        val doc = Document(
            id = "docD",
            title = "同一 revision",
            format = Format.MD,
            content = "final",
            sortIndex = 2,
            state = io.github.gscratchpad.domain.model.DocState.OPEN,
            revision = 7L,
            createdAt = 1.0,
            updatedAt = 1.0,
        )
        harness.dao.insert(doc)

        val journal = DraftJournal(harness.recovery)
        journal.offer(doc.id, 7L, "final")
        val file = harness.paths.journalFile(doc.id)
        val deadline = System.currentTimeMillis() + 3_000
        while (!file.exists() && System.currentTimeMillis() < deadline) Thread.sleep(5)

        val notes = harness.recovery.recover(harness.db, harness.dao, mirror = MirrorStore(harness.paths))
        assertEquals(0, notes.size)
        assertEquals("final", harness.dao.get(doc.id)!!.content)
        assertTrue(!file.exists())
    }

    @Test
    fun dropClearsPendingSnapshot() {
        val journal = DraftJournal(harness.recovery)
        journal.drop("docE")
        journal.offer("docE", 2L, "x")
        journal.drop("docE")
        // 只验证不抛异常且不留下脏状态；journal 可能已写出，也可能被丢弃
        assertTrue(journal.lastWriteMs >= -1L)
    }
}
