package io.github.gscratchpad.testing

import io.github.gscratchpad.data.AppPaths
import io.github.gscratchpad.data.AssetStore
import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.DocumentRepository
import io.github.gscratchpad.data.DocumentRepositoryImpl
import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.data.MirrorStore
import io.github.gscratchpad.data.RecoveryManager
import io.github.gscratchpad.data.SaveQueue
import io.github.gscratchpad.data.Schema
import io.github.gscratchpad.data.SqlDb
import io.github.gscratchpad.capture.CaptureService
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestDispatcher
import java.io.File

/**
 * 测试装配：与生产 [io.github.gscratchpad.AppContainer] 相同的对象图，
 * 仅把 Android 驱动换成 sqlite-jdbc。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TestHarness(
    val root: File,
    val dispatcher: TestDispatcher,
    debounceMs: Long = 0L,
) {
    val paths: AppPaths = AppPaths(root).ensureDirs()
    val db: SqlDb = JdbcSqlDb.open(paths.dbFile.absolutePath).also {
        Schema.statements(Schema.DDL).forEach { sql -> it.exec(sql) }
        it.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>(MetaKeys.SCHEMA_VERSION, Schema.VERSION.toString()),
        )
    }
    val dao = DocumentDao(db)
    val mirror = MirrorStore(paths)
    val recovery = RecoveryManager(paths)
    val assets = AssetStore(paths)
    val scope = CoroutineScope(dispatcher)
    val queue: SaveQueue = SaveQueue(
        dao = dao,
        mirror = mirror,
        recovery = recovery,
        scope = scope,
        debounceMs = debounceMs,
        writerDispatcher = dispatcher as CoroutineDispatcher,
    )
    val repo: DocumentRepository = DocumentRepositoryImpl(
        db = db,
        dao = dao,
        mirror = mirror,
        assets = assets,
        paths = paths,
        saveQueue = queue,
        io = dispatcher as CoroutineDispatcher,
        scope = scope,
    )
    val capture = CaptureService(repo, dao)

    fun close() {
        runCatching { db.close() }
    }
}
