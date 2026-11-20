package io.github.gscratchpad.data

import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * 编辑热日志（P2-5 余项的根因修法）。
 *
 * 缺口：编辑器路径的 journal 由 [SaveQueue] 在 300 ms 防抖后才写，
 * 因此「最后一次输入 → 可恢复」的窗口等于 300 ms + 一次写盘；
 * 在防抖窗内 `am force-stop` 时最后一批字符没有任何落盘痕迹，重开即丢。
 *
 * 修法：输入即刻把「当前全文 + 递增 revision」投递到本类的单线程合并队列，
 * 由独立守护线程原子写 `recovery/<docId>.json`（不含数据库提交）。
 * 于是最坏窗口只剩一次文件写（毫秒级），启动时由 [RecoveryManager.recover]
 * 按 `journal.revision > db.revision` 判定回填 —— 与桌面 `_do_save_with` 的顺序语义一致：
 * 库已提交则 journal 被丢弃，库未提交则 journal 胜出。
 *
 * 合并策略：多笔输入只保留最新快照，写入线程永远写「队列里最新的那一份」，
 * 因此 1 MB 文档连续输入不会产生写盘堆积。
 */
class DraftJournal(private val recovery: RecoveryManager) {

    private data class Entry(val docId: String, val revision: Long, val content: String, val ts: Double)

    private val latest = AtomicReference<Entry?>(null)
    private val scheduled = AtomicBoolean(false)

    private val executor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "gs-draft-journal").apply { isDaemon = true }
    }

    /** 最近一次热日志写盘耗时（毫秒），供真机排障与文档引用。 */
    @Volatile
    var lastWriteMs: Long = -1L
        private set

    /** 最近一次写盘失败原因（空串表示无失败）。 */
    @Volatile
    var lastError: String = ""
        private set

    /**
     * 投递最新快照。非阻塞；同一快照重复投递会被合并。
     * [revision] 必须与随后 `saveNow` 提交的 revision 一致，恢复判定才成立。
     */
    fun offer(docId: String, revision: Long, content: String, ts: Double = System.currentTimeMillis() / 1000.0) {
        if (docId.isEmpty() || revision <= 0L) return
        val cur = latest.get()
        if (cur != null && cur.docId == docId && cur.revision == revision && cur.content === content) return
        latest.set(Entry(docId, revision, content, ts))
        schedule()
    }

    /** 文档关闭 / 保存完成时丢弃尚未写出的快照（已写出的 journal 由 SaveQueue 负责删除）。 */
    fun drop(docId: String) {
        while (true) {
            val cur = latest.get() ?: return
            if (cur.docId != docId) return
            if (latest.compareAndSet(cur, null)) return
        }
    }

    private fun schedule() {
        if (scheduled.compareAndSet(false, true)) {
            runCatching { executor.execute(::drain) }
        }
    }

    private fun drain() {
        while (true) {
            val e = latest.getAndSet(null) ?: break
            val t0 = System.nanoTime()
            try {
                recovery.writeJournal(e.docId, e.revision, e.content, e.ts)
                lastError = ""
            } catch (t: Throwable) {
                lastError = t.message ?: t.toString()
                android.util.Log.d("Gscratchpad", "draft journal failed: $lastError")
            }
            lastWriteMs = (System.nanoTime() - t0) / 1_000_000
        }
        scheduled.set(false)
        // 收尾竞争：写完后若又有新快照进来，补一次调度
        if (latest.get() != null) schedule()
    }
}
