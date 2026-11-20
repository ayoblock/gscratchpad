package io.github.gscratchpad

import android.content.Context
import io.github.gscratchpad.data.AndroidSqlDb
import io.github.gscratchpad.data.AppPaths
import io.github.gscratchpad.data.AssetStore
import io.github.gscratchpad.data.DbHelper
import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.DocumentRepository
import io.github.gscratchpad.data.DocumentRepositoryImpl
import io.github.gscratchpad.data.DraftJournal
import io.github.gscratchpad.data.MirrorStore
import io.github.gscratchpad.data.RecoveryManager
import io.github.gscratchpad.data.SaveQueue
import io.github.gscratchpad.data.SqlDb
import io.github.gscratchpad.capture.CaptureService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 手写 DI 容器（方案 §4.3：应用规模不需要框架）。
 * 启动顺序：打开 DB → 回放 WAL → 扫描 recovery 目录的 json 日志回填 → 写镜像 → 删除日志。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AppContainer(context: Context) {

    val paths: AppPaths = AppPaths(context.filesDir).ensureDirs()

    private val helper = DbHelper(context, paths)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val db: SqlDb by lazy { AndroidSqlDb(helper.writableDatabase) }
    val dao: DocumentDao by lazy { DocumentDao(db) }
    val mirror: MirrorStore by lazy { MirrorStore(paths) }
    val recovery: RecoveryManager by lazy { RecoveryManager(paths) }

    /** 编辑热日志：输入即刻写 journal，把「最后一批输入」的可恢复窗口压到一次写盘。 */
    val draftJournal by lazy { DraftJournal(recovery) }
    val assets: AssetStore by lazy { AssetStore(paths) }

    val saveQueue: SaveQueue by lazy {
        SaveQueue(
            dao = dao,
            mirror = mirror,
            recovery = recovery,
            scope = scope,
            debounceMs = 300L,
            writerDispatcher = Dispatchers.IO.limitedParallelism(1),
        )
    }

    val repository: DocumentRepository by lazy {
        DocumentRepositoryImpl(
            db = db,
            dao = dao,
            mirror = mirror,
            assets = assets,
            paths = paths,
            saveQueue = saveQueue,
            io = Dispatchers.IO,
            scope = scope,
        )
    }

    val captureService: CaptureService by lazy { CaptureService(repository, dao) }

    private val _recoveryNotes = MutableStateFlow<List<String>>(emptyList())
    val recoveryNotes: StateFlow<List<String>> = _recoveryNotes.asStateFlow()

    @Volatile
    var bootstrapped: Boolean = false
        private set

    suspend fun bootstrap(): List<String> = withContext(Dispatchers.IO) {
        if (bootstrapped) return@withContext _recoveryNotes.value
        db.exec("PRAGMA journal_mode=WAL")
        val notes = recovery.recover(db, dao, mirror)
        _recoveryNotes.value = notes
        bootstrapped = true
        notes
    }

    /** 进程级后台保存（`Activity.onStop` 用，不依赖界面生命周期）。 */
    fun saveAndFlush(id: String, content: String, revision: Long) {
        scope.launch {
            repository.saveNow(id, content, revision)
            repository.flush()
        }
    }
}
