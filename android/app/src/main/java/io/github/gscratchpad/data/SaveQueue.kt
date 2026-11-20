package io.github.gscratchpad.data

import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.domain.model.SaveState
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * 自动保存队列（方案 §5.2 状态机）。
 *
 * Idle → Debouncing(300ms) → Queued → Writing → Saved/Failed。
 * 同一文档的多次提交合并为最后一次；单写线程串行（不变量 I5）；
 * revision 单调（I2）；journal 先写后提交（I3）；镜像原子替换（I4）。
 */
class SaveQueue(
    private val dao: DocumentDao,
    private val mirror: MirrorStore,
    private val recovery: RecoveryManager,
    private val scope: CoroutineScope,
    private val debounceMs: Long = 300L,
    private val writerDispatcher: CoroutineDispatcher,
    private val maxRetries: Int = 3,
) {
    data class Payload(
        val id: String,
        val title: String,
        val format: Format,
        val content: String,
        val revision: Long,
        val updatedAt: Double,
    )

    data class SaveTicket(val docId: String, val revision: Long, val accepted: Boolean)

    private val pending = MutableStateFlow<Map<String, Payload>>(emptyMap())
    private val debounceJobs = HashMap<String, Job>()
    private val jobsLock = Mutex()
    private val writerMutex = Mutex()

    private val _states = MutableSharedFlow<SaveState>(extraBufferCapacity = 128)
    val states = _states.asSharedFlow()

    @Volatile
    var lastError: String = ""
        private set

    /** 非阻塞提交：立即进入 Debouncing，300 ms 后落盘；期间新快照覆盖旧快照。 */
    fun submit(payload: Payload) {
        pending.update { it + (payload.id to payload) }
        emit(SaveState(payload.id, SaveState.Status.SAVING, "", now()))
        scope.launch {
            jobsLock.withLock {
                debounceJobs.remove(payload.id)?.cancel()
                debounceJobs[payload.id] = scope.launch {
                    if (debounceMs > 0) delay(debounceMs)
                    writePending(payload.id)
                }
            }
        }
    }

    /** 阻塞式提交（capture、关闭标签时用）：跳过防抖立即写。 */
    suspend fun submitNow(payload: Payload): SaveTicket {
        pending.update { it + (payload.id to payload) }
        emit(SaveState(payload.id, SaveState.Status.SAVING, "", now()))
        jobsLock.withLock { debounceJobs.remove(payload.id)?.cancel() }
        val ok = writePending(payload.id)
        return SaveTicket(payload.id, payload.revision, ok)
    }

    /** 等待队列清空（`Activity.onStop`、退出前调用）。 */
    suspend fun flush(timeoutMs: Long = 10_000): Boolean {
        val done = withTimeoutOrNull(timeoutMs) {
            jobsLock.withLock {
                debounceJobs.values.forEach { it.cancel() }
                debounceJobs.clear()
            }
            val ids = pending.value.keys.toList()
            for (id in ids) writePending(id)
            true
        }
        return done == true
    }

    private suspend fun writePending(id: String): Boolean {
        val payload = pending.value[id] ?: return true
        return writerMutex.withLock {
            withContext(writerDispatcher) {
                pending.update { it - id }
                doSave(payload)
            }
        }
    }

    private suspend fun doSave(payload: Payload): Boolean {
        var attempt = 0
        while (true) {
            try {
                // 1. 先写 journal（写失败不阻断提交，但把问题暴露给 UI）
                try {
                    recovery.writeJournal(payload.id, payload.revision, payload.content, payload.updatedAt)
                } catch (e: Exception) {
                    lastError = e.message ?: e.toString()
                    emit(
                        SaveState(
                            payload.id, SaveState.Status.ERROR,
                            "恢复日志写入失败：${e.message}", now(),
                        ),
                    )
                }

                // 2. 提交（revision 保护由 DAO 的 WHERE revision<=? 承担）
                val applied = dao.applySnapshot(
                    payload.id, payload.title, payload.format,
                    payload.content, payload.revision, payload.updatedAt,
                )

                // 3. 提交成功才删 journal
                recovery.deleteJournal(payload.id)

                if (!applied) {
                    // 晚到的旧快照：库内已有更新版本，丢弃本次内容（不变量 I2）
                    emit(
                        SaveState(
                            payload.id, SaveState.Status.SAVED,
                            "旧快照已丢弃（库内 revision 更新）", payload.updatedAt,
                        ),
                    )
                    return false
                }

                // 4. 镜像原子替换
                return try {
                    mirror.write(payload.id, payload.content, payload.format)
                    emit(SaveState(payload.id, SaveState.Status.SAVED, "", payload.updatedAt))
                    true
                } catch (e: Exception) {
                    emit(
                        SaveState(
                            payload.id, SaveState.Status.ERROR,
                            "内容已入库，镜像文件写入失败：${e.message}", now(),
                        ),
                    )
                    true
                }
            } catch (e: Exception) {
                attempt++
                lastError = e.message ?: e.toString()
                if (attempt > maxRetries) {
                    emit(
                        SaveState(
                            payload.id, SaveState.Status.ERROR,
                            "保存失败：${e.message}", now(),
                        ),
                    )
                    return false
                }
                delay(100L * (1L shl (attempt - 1)))
            }
        }
    }

    private fun emit(state: SaveState) {
        _states.tryEmit(state)
    }

    private fun now(): Double = System.currentTimeMillis() / 1000.0
}
