package io.github.gscratchpad.data

import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Folder
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.domain.model.MaintenanceReport
import io.github.gscratchpad.domain.model.PurgeReport
import io.github.gscratchpad.platform.FolderPolicy
import io.github.gscratchpad.platform.MaintenancePolicy
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.nio.file.FileVisitResult
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.SimpleFileVisitor
import java.nio.file.attribute.BasicFileAttributes
import java.util.UUID

/** 文档仓库接口（方案 §5.2）。 */
interface DocumentRepository {
    fun observeOpen(): Flow<List<Document>>
    fun observeAll(): Flow<List<Document>>
    suspend fun get(id: String): Document?
    suspend fun create(format: Format = Format.TXT, title: String? = null): Document
    suspend fun rename(id: String, title: String)
    suspend fun setState(id: String, open: Boolean)

    /** 清除一条最近记录（文档与正文保留，仅从最近列表隐藏）。 */
    suspend fun clearRecent(id: String)

    /** 一键清除全部最近记录（不删除任何文档）。 */
    suspend fun clearAllRecent()

    /** 把被清除的文档重新放回最近列表。 */
    suspend fun restoreRecent(id: String)

    /** 打开文档打点：写最近打开时间，并让该条目重新出现在最近列表（v5）。 */
    suspend fun touchOpened(id: String)
    suspend fun reorder(orderedIds: List<String>, activeId: String)
    suspend fun delete(id: String)
    suspend fun purgeClosed(keepIds: Set<String> = emptySet()): PurgeReport

    /** R39：只统计不删除——应用私有 notes/ assets/ recovery/ 内无对应文档的孤儿与失效映射。 */
    suspend fun scanOrphans(): MaintenanceReport

    /** R39：清理孤儿文件 + 失效映射，可选 VACUUM 回收空闲页。不触碰关联的本机原文件。 */
    suspend fun maintain(vacuum: Boolean = true): MaintenanceReport
    suspend fun submitSave(id: String, content: String, revision: Long): SaveQueue.SaveTicket

    /** 编辑路径：300 ms 防抖提交，立即返回（不阻塞输入）。 */
    fun submitDebounced(id: String, content: String, revision: Long)
    suspend fun saveNow(id: String, content: String, revision: Long): SaveQueue.SaveTicket
    suspend fun flush(timeoutMs: Long = 10_000): Boolean
    suspend fun getMeta(key: String, default: String? = null): String?
    suspend fun setMeta(key: String, value: String)

    suspend fun folders(): List<Folder>
    suspend fun folderCounts(): Map<String, Int>
    suspend fun documentsInFolder(folder: String, includeHidden: Boolean = false): List<Document>
    suspend fun createFolder(name: String)
    suspend fun renameFolder(old: String, new: String)
    suspend fun deleteFolder(name: String)
    suspend fun moveToFolder(id: String, folder: String)
}

class DocumentRepositoryImpl(
    private val db: SqlDb,
    private val dao: DocumentDao,
    private val mirror: MirrorStore,
    private val assets: AssetStore,
    private val paths: AppPaths,
    private val saveQueue: SaveQueue,
    private val io: CoroutineDispatcher,
    private val scope: CoroutineScope,
) : DocumentRepository {

    private val tick = MutableStateFlow(0L)

    private fun bump() = tick.update { it + 1 }

    override fun observeOpen(): Flow<List<Document>> =
        tick.map { dao.openDocuments() }.distinctUntilChanged().flowOn(io)

    override fun observeAll(): Flow<List<Document>> =
        tick.map { dao.allDocuments(includeClosed = true) }.distinctUntilChanged().flowOn(io)

    override suspend fun get(id: String): Document? = withContext(io) { dao.get(id) }

    override suspend fun create(format: Format, title: String?): Document = withContext(io) {
        val id = UUID.randomUUID().toString().replace("-", "")
        val now = now()
        val doc = Document(
            id = id,
            title = title ?: "未命名",
            format = format,
            content = "",
            sortIndex = dao.maxSortIndex() + 1,
            state = DocState.OPEN,
            revision = 1L,
            createdAt = now,
            updatedAt = now,
        )
        dao.insert(doc)
        mirror.write(doc.id, doc.content, doc.format)
        bump()
        doc
    }

    override suspend fun rename(id: String, title: String) = withContext(io) {
        dao.updateTitle(id, title, now())
        bump()
    }

    override suspend fun setState(id: String, open: Boolean) = withContext(io) {
        dao.setState(id, if (open) DocState.OPEN else DocState.CLOSED, now())
        bump()
    }

    override suspend fun clearRecent(id: String) = withContext(io) {
        dao.setRecentHidden(id, true)
        bump()
    }

    override suspend fun clearAllRecent() = withContext(io) {
        dao.setAllRecentHidden()
        bump()
    }

    override suspend fun restoreRecent(id: String) = withContext(io) {
        dao.setRecentHidden(id, false)
        bump()
    }

    override suspend fun touchOpened(id: String) = withContext(io) {
        dao.touchOpened(id, now())
        bump()
    }

    override suspend fun reorder(orderedIds: List<String>, activeId: String) = withContext(io) {
        dao.reorder(orderedIds)
        dao.setMeta(MetaKeys.ACTIVE_DOC, activeId)
        bump()
    }

    override suspend fun delete(id: String) = withContext(io) {
        dao.delete(id)
        mirror.delete(id)
        assets.delete(id)
        // 清掉指向该文档的 meta 指针
        val stale = mutableListOf<String>()
        dao.getMeta(MetaKeys.ACTIVE_DOC)?.let { if (it == id) stale.add(MetaKeys.ACTIVE_DOC) }
        stale.add(MetaKeys.cursor(id))
        stale.add(MetaKeys.sourcePath(id))
        dao.allExtKeys().filter { dao.getMeta(it) == id }.forEach { stale.add(it) }
        dao.deleteMeta(stale)
        bump()
    }

    override suspend fun purgeClosed(keepIds: Set<String>): PurgeReport = withContext(io) {
        val report = PurgeReport()
        val closed = dao.closedDocuments().filter { it.id !in keepIds }
        if (closed.isEmpty()) return@withContext report
        val ids = closed.map { it.id }.toSet()
        report.purgedDocs = closed.size
        report.purgedBytes = closed.sumOf { it.content.toByteArray(Charsets.UTF_8).size.toLong() }
        db.transaction {
            closed.forEach { dao.delete(it.id) }
            dao.deleteMeta(dao.staleMetaKeys(ids))
        }
        closed.forEach { doc ->
            try {
                mirror.delete(doc.id)
                assets.delete(doc.id)
            } catch (e: Exception) {
                report.errors.add("${doc.id}: ${e.message}")
            }
        }
        bump()
        report
    }

    // ------------------------------------------------------------------ R39 维护

    override suspend fun scanOrphans(): MaintenanceReport = withContext(io) {
        val report = MaintenanceReport()
        val ids = dao.allIds()
        report.dbBytesBefore = dbFootprint()
        report.dbBytesAfter = report.dbBytesBefore
        runCatching {
            val pageSize = db.queryOne("PRAGMA page_size")?.long("page_size") ?: 0L
            val freePages = db.queryOne("PRAGMA freelist_count")?.long("freelist_count") ?: 0L
            report.dbFreeBytes = pageSize * freePages
        }
        collectOrphans(ids, report, remove = false)
        report.staleMeta = dao.staleMetaKeys(ids).size
        report
    }

    override suspend fun maintain(vacuum: Boolean): MaintenanceReport = withContext(io) {
        val report = MaintenanceReport()
        val ids = dao.allIds()
        report.dbBytesBefore = dbFootprint()
        collectOrphans(ids, report, remove = true)
        val stale = dao.staleMetaKeys(ids)
        if (stale.isNotEmpty()) dao.deleteMeta(stale)
        report.staleMeta = stale.size
        if (vacuum) {
            runCatching {
                db.vacuum()
                db.checkpointTruncate()
            }.onSuccess { report.vacuumed = true }
                .onFailure { report.errors.add("数据库压缩未完成：${it.message}") }
        }
        report.dbBytesAfter = dbFootprint()
        report
    }

    /** 数据库实际占用 = 主库 + WAL（只看主库会把压缩前后量反，桌面同款口径）。 */
    private fun dbFootprint(): Long =
        paths.dbFile.length() + File(paths.dbFile.path + "-wal").length()

    /** 枚举应用私有 notes/ assets/ recovery/ 第一层；符号链接按文件处理、绝不跟随。 */
    private fun collectOrphans(ids: Set<String>, report: MaintenanceReport, remove: Boolean) {
        val now = System.currentTimeMillis()
        fun consider(file: File, area: MaintenancePolicy.Area, isDir: Boolean, bytes: Long) {
            val ageMs = if (file.name.endsWith(".tmp")) now - file.lastModified() else 0L
            if (!MaintenancePolicy.isOrphan(area, file.name, isDir, ageMs, ids)) return
            when (area) {
                MaintenancePolicy.Area.NOTES -> if (isDir) {
                    report.orphanAssets += 1
                    report.orphanAssetsBytes += bytes
                } else {
                    report.orphanNotes += 1
                    report.orphanNotesBytes += bytes
                }
                MaintenancePolicy.Area.ASSETS -> {
                    report.orphanAssets += 1
                    report.orphanAssetsBytes += bytes
                }
                MaintenancePolicy.Area.RECOVERY -> report.orphanJournals += 1
            }
            if (remove) {
                runCatching { removePath(file) }
                    .onFailure { report.errors.add("${file.name}: ${it.message}") }
            }
        }
        paths.notes.listFiles()?.forEach { f ->
            val dir = f.isDirectory && !Files.isSymbolicLink(f.toPath())
            consider(f, MaintenancePolicy.Area.NOTES, dir, if (dir) treeSize(f) else f.length())
        }
        paths.assets.listFiles()?.forEach { f ->
            val dir = f.isDirectory && !Files.isSymbolicLink(f.toPath())
            consider(f, MaintenancePolicy.Area.ASSETS, dir, if (dir) treeSize(f) else f.length())
        }
        paths.recovery.listFiles()?.forEach { f ->
            if (f.name.endsWith(".json")) consider(f, MaintenancePolicy.Area.RECOVERY, false, 0L)
        }
    }

    private fun treeSize(file: File): Long =
        if (!file.isDirectory) file.length()
        else file.walkTopDown()
            .filter { !Files.isSymbolicLink(it.toPath()) }
            .sumOf { if (it.isDirectory) 0L else it.length() }

    /** 目录递归删除但不跟随符号链接（链接本身按文件删）。 */
    private fun removePath(file: File) {
        val path = file.toPath()
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS) && !Files.isSymbolicLink(path)) return
        if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            Files.walkFileTree(path, object : SimpleFileVisitor<Path>() {
                override fun visitFile(p: Path, attrs: BasicFileAttributes): FileVisitResult {
                    Files.deleteIfExists(p)
                    return FileVisitResult.CONTINUE
                }
                override fun postVisitDirectory(p: Path, exc: IOException?): FileVisitResult {
                    Files.deleteIfExists(p)
                    return FileVisitResult.CONTINUE
                }
            })
        } else {
            Files.deleteIfExists(path)
        }
    }

    override suspend fun submitSave(id: String, content: String, revision: Long): SaveQueue.SaveTicket {
        val doc = withContext(io) { dao.get(id) } ?: return SaveQueue.SaveTicket(id, revision, false)
        val ticket = saveQueue.submitNow(
            SaveQueue.Payload(doc.id, doc.title, doc.format, content, revision, now()),
        )
        bump()
        return ticket
    }

    /** 防抖提交（编辑路径）：立即返回，300 ms 后落盘。 */
    override fun submitDebounced(id: String, content: String, revision: Long) {
        scope.launch {
            val doc = withContext(io) { dao.get(id) } ?: return@launch
            saveQueue.submit(
                SaveQueue.Payload(doc.id, doc.title, doc.format, content, revision, now()),
            )
            bump()
        }
    }

    override suspend fun saveNow(id: String, content: String, revision: Long): SaveQueue.SaveTicket =
        submitSave(id, content, revision)

    override suspend fun flush(timeoutMs: Long): Boolean = saveQueue.flush(timeoutMs)

    override suspend fun getMeta(key: String, default: String?): String? =
        withContext(io) { dao.getMeta(key, default) }

    override suspend fun setMeta(key: String, value: String) = withContext(io) {
        dao.setMeta(key, value)
        bump()
    }

    override suspend fun folders(): List<Folder> = withContext(io) { dao.folderRows() }

    override suspend fun folderCounts(): Map<String, Int> = withContext(io) { dao.folderCounts() }

    override suspend fun documentsInFolder(folder: String, includeHidden: Boolean): List<Document> =
        withContext(io) { dao.documentsByFolder(folder, includeHidden) }

    override suspend fun createFolder(name: String) = withContext(io) {
        val trimmed = FolderPolicy.clean(name)
        // Q6：撞名拒绝（不静默合并），与桌面版语义对齐
        require(!dao.folderExists(trimmed)) { "文件夹「$trimmed」已存在" }
        dao.createFolder(trimmed, now())
        bump()
    }

    override suspend fun renameFolder(old: String, new: String) = withContext(io) {
        val trimmed = FolderPolicy.clean(new)
        if (trimmed != old) {
            // Q6：撞名拒绝；重命名到自身（仅大小写/空白变化之外）不视为冲突
            require(!dao.folderExists(trimmed)) { "文件夹「$trimmed」已存在" }
        }
        dao.renameFolder(old, trimmed, now())
        bump()
    }

    override suspend fun deleteFolder(name: String) = withContext(io) {
        dao.deleteFolder(name)
        bump()
    }

    override suspend fun moveToFolder(id: String, folder: String) = withContext(io) {
        dao.setFolder(id, folder, now())
        bump()
    }

    private fun now(): Double = System.currentTimeMillis() / 1000.0
}
