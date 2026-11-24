package io.github.gscratchpad.data

import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Folder
import io.github.gscratchpad.domain.model.Format

/** 文档表的读写（SQL 与桌面 `store.py` 一致，含排序与筛选口径）。 */
class DocumentDao(private val db: SqlDb) {

    fun openDocuments(): List<Document> =
        db.query("SELECT * FROM documents WHERE state='open' ORDER BY sort_index ASC, updated_at ASC")
            .map(::toDocument)

    fun allDocuments(includeClosed: Boolean = true): List<Document> {
        val sql = if (includeClosed) {
            "SELECT * FROM documents ORDER BY opened_at DESC, updated_at DESC, sort_index ASC"
        } else {
            "SELECT * FROM documents WHERE state='open' ORDER BY opened_at DESC, updated_at DESC, sort_index ASC"
        }
        return db.query(sql).map(::toDocument)
    }

    fun get(id: String): Document? =
        db.queryOne("SELECT * FROM documents WHERE id=?", listOf(id))?.let(::toDocument)

    /** 最近列表（首页用）：排除已被「清除记录」的条目，按最近打开时间倒序。 */
    fun recentDocuments(): List<Document> =
        db.query("SELECT * FROM documents WHERE recent_hidden=0 " +
            "ORDER BY opened_at DESC, updated_at DESC, sort_index ASC").map(::toDocument)

    /** 打开文档时打点：写入打开时间并让该条目重新出现在最近列表（v5）。 */
    fun touchOpened(id: String, at: Double) =
        db.exec(
            "UPDATE documents SET opened_at=?, recent_hidden=0 WHERE id=?",
            listOf(at.toString(), id),
        )

    fun setRecentHidden(id: String, hidden: Boolean) =
        db.exec(
            "UPDATE documents SET recent_hidden=? WHERE id=?",
            listOf(if (hidden) 1 else 0, id),
        )

    fun setAllRecentHidden() = db.exec("UPDATE documents SET recent_hidden=1", emptyList())

    fun recent(limit: Int = 60): List<Document> =
        db.query(
            "SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC LIMIT ?",
            listOf(limit.coerceAtLeast(1).toString()),
        ).map(::toDocument)

    fun openDocumentsByRecent(): List<Document> =
        db.query("SELECT * FROM documents WHERE state='open' ORDER BY updated_at DESC, sort_index ASC")
            .map(::toDocument)

    /** 按格式分组，顺序固定 md → txt → html → 其他，组内按更新时间倒序。 */
    fun documentsGroupedByFormat(): Map<String, List<Document>> {
        val grouped = LinkedHashMap<String, MutableList<Document>>()
        db.query("SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC").forEach { row ->
            grouped.getOrPut(row.str("format")) { mutableListOf() }.add(toDocument(row))
        }
        val order = listOf("md", "txt", "html")
        val result = LinkedHashMap<String, List<Document>>()
        order.forEach { fmt -> grouped[fmt]?.let { result[fmt] = it } }
        grouped.filterKeys { it !in order }.forEach { (fmt, docs) -> result[fmt] = docs }
        return result
    }

    fun folders(): List<String> =
        db.query("SELECT name FROM folders ORDER BY name COLLATE NOCASE").map { it.str("name") }

    /** 带创建时间的文件夹列表（T3：UI 分组需要，旧 folders() 丢弃了 createdAt）。 */
    fun folderRows(): List<Folder> =
        db.query("SELECT name, created_at FROM folders ORDER BY name COLLATE NOCASE")
            .map { Folder(it.str("name"), it.double("created_at")) }

    fun folderCounts(): Map<String, Int> =
        db.query("SELECT folder, COUNT(*) AS n FROM documents WHERE folder <> '' GROUP BY folder")
            .associate { it.str("folder") to it.int("n") }

    /** 文件夹内文档（Q7：includeHidden=false 时排除已清除记录），按更新时间倒序。 */
    fun documentsByFolder(folder: String, includeHidden: Boolean = true): List<Document> {
        val hidden = if (includeHidden) "" else " AND recent_hidden=0"
        return db.query(
            "SELECT * FROM documents WHERE folder=?$hidden ORDER BY updated_at DESC, sort_index ASC",
            listOf(folder),
        ).map(::toDocument)
    }

    fun folderExists(name: String): Boolean =
        db.queryOne("SELECT 1 AS x FROM folders WHERE name=?", listOf(name)) != null

    /** 未归档（folder=''）始终存在，作为空字符串键。 */
    fun documentsByFolder(): Map<String, List<Document>> {
        val grouped = LinkedHashMap<String, MutableList<Document>>()
        db.query("SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC").forEach { row ->
            val doc = toDocument(row)
            grouped.getOrPut(doc.folder) { mutableListOf() }.add(doc)
        }
        grouped.getOrPut("") { mutableListOf() }
        return grouped
    }

    fun docFolderOf(id: String): String =
        db.queryOne("SELECT folder FROM documents WHERE id=?", listOf(id))?.str("folder") ?: ""

    fun closedDocuments(): List<Document> =
        db.query("SELECT * FROM documents WHERE state='closed' ORDER BY updated_at DESC")
            .map(::toDocument)

    fun maxSortIndex(): Int =
        db.queryOne("SELECT MAX(sort_index) AS m FROM documents")?.let {
            if (it.isNull("m")) -1 else it.int("m")
        } ?: -1

    fun revisionOf(id: String): Long? =
        db.queryOne("SELECT revision FROM documents WHERE id=?", listOf(id))?.long("revision")

    fun formatOf(id: String): Format =
        Format.fromId(db.queryOne("SELECT format FROM documents WHERE id=?", listOf(id))?.str("format"))

    /** R39 维护用：全部文档 id，供孤儿扫描判定哪些镜像/资源仍有效。 */
    fun allIds(): Set<String> = db.query("SELECT id FROM documents").map { it.str("id") }.toSet()

    fun exists(id: String): Boolean =
        db.queryOne("SELECT 1 AS x FROM documents WHERE id=?", listOf(id)) != null

    // ------------------------------------------------------------------ 写

    fun insert(doc: Document) {
        db.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf(
                doc.id, doc.title, doc.format.id, doc.content, doc.sortIndex, doc.state.id,
                doc.revision, doc.createdAt, doc.updatedAt, doc.folder,
            ),
        )
    }

    /**
     * 提交快照。`revision <= payload` 才写入：晚到的旧快照被丢弃（不变量 I2）。
     * 返回是否真正写入。
     */
    fun applySnapshot(
        id: String,
        title: String,
        format: Format,
        content: String,
        revision: Long,
        updatedAt: Double,
    ): Boolean {
        val before = revisionOf(id) ?: return false
        if (revision < before) return false
        db.exec(
            "UPDATE documents SET title=?, format=?, content=?, revision=?, updated_at=?" +
                " WHERE id=? AND revision<=?",
            listOf(title, format.id, content, revision, updatedAt, id, revision),
        )
        return true
    }

    /**
     * sync v1：远端文档应用（唯一入口，语义与桌面 `store.apply_sync` 一致）。
     * 本地已存在时 revision 取 max(local, incoming)+1，其余字段以 incoming 为准
     * （含 updated_at，保持对端时序用于后续冲突判定）；folder 登记进 folders 表。
     */
    fun applyRemote(
        id: String,
        title: String,
        format: Format,
        content: String,
        sortIndex: Int,
        state: DocState,
        revision: Long,
        createdAt: Double,
        updatedAt: Double,
        folder: String,
    ) {
        db.transaction {
            val before = revisionOf(id)
            if (before != null) {
                val newRev = maxOf(before, revision) + 1
                db.exec(
                    "UPDATE documents SET title=?, format=?, content=?, sort_index=?, state=?," +
                        " revision=?, created_at=?, updated_at=?, folder=? WHERE id=?",
                    listOf(title, format.id, content, sortIndex, state.id, newRev, createdAt, updatedAt, folder, id),
                )
            } else {
                db.exec(
                    "INSERT INTO documents(id, title, format, content, sort_index, state," +
                        " revision, created_at, updated_at, folder, recent_hidden, opened_at)" +
                        " VALUES(?,?,?,?,?,?,?,?,?,?,0,0)",
                    listOf(id, title, format.id, content, sortIndex, state.id, revision, createdAt, updatedAt, folder),
                )
            }
            if (folder.isNotEmpty()) {
                db.exec(
                    "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                    listOf(folder, createdAt),
                )
            }
        }
    }

    fun updateTitle(id: String, title: String, updatedAt: Double) {
        db.exec("UPDATE documents SET title=?, updated_at=? WHERE id=?", listOf(title, updatedAt, id))
    }

    fun setState(id: String, state: DocState, updatedAt: Double) {
        db.exec("UPDATE documents SET state=?, updated_at=? WHERE id=?", listOf(state.id, updatedAt, id))
    }

    fun reorder(orderedIds: List<String>) {
        db.transaction {
            orderedIds.forEachIndexed { index, id ->
                db.exec("UPDATE documents SET sort_index=? WHERE id=?", listOf(index, id))
            }
        }
    }

    fun setFolder(id: String, folder: String, now: Double) {
        db.transaction {
            db.exec("UPDATE documents SET folder=? WHERE id=?", listOf(folder, id))
            if (folder.isNotEmpty()) {
                db.exec(
                    "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                    listOf(folder, now),
                )
            }
        }
    }

    fun delete(id: String) {
        db.exec("DELETE FROM documents WHERE id=?", listOf(id))
    }

    fun createFolder(name: String, now: Double) {
        db.exec("INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)", listOf(name, now))
    }

    fun renameFolder(old: String, new: String, now: Double) {
        // 自重命名（含仅大小写/空白变化经 policy trim 后相同）必须是 no-op：
        // 否则最后一步 DELETE WHERE name=old 会把同名行删掉（T3 真实缺陷）
        if (old == new) return
        db.transaction {
            db.exec("INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)", listOf(new, now))
            db.exec("UPDATE documents SET folder=? WHERE folder=?", listOf(new, old))
            db.exec("DELETE FROM folders WHERE name=?", listOf(old))
        }
    }

    /** 删除文件夹：其中的笔记回到「未归档」，笔记本身不删。 */
    fun deleteFolder(name: String) {
        db.transaction {
            db.exec("UPDATE documents SET folder='' WHERE folder=?", listOf(name))
            db.exec("DELETE FROM folders WHERE name=?", listOf(name))
        }
    }

    // ------------------------------------------------------------------ meta

    fun getMeta(key: String, default: String? = null): String? =
        db.queryOne("SELECT value FROM meta WHERE key=?", listOf(key))?.str("value") ?: default

    fun setMeta(key: String, value: String) {
        db.exec("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", listOf(key, value))
    }

    fun deleteMeta(key: String) {
        db.exec("DELETE FROM meta WHERE key=?", listOf(key))
    }

    fun deleteMeta(keys: List<String>) {
        db.execMany("DELETE FROM meta WHERE key=?", keys.map { listOf(it) })
    }

    fun allExtKeys(): List<String> =
        db.query("SELECT key FROM meta").map { it.str("key") }.filter { it.startsWith("ext:") }

    fun staleMetaKeys(ids: Set<String>): List<String> =
        db.query("SELECT key, value FROM meta").mapNotNull { row ->
            val key = row.str("key")
            val value = row.str("value")
            when {
                key.startsWith("ext:") && value !in ids -> key
                key.startsWith("source_path:") && key.substringAfter(':') !in ids -> key
                key.startsWith("cursor:") && key.substringAfter(':') !in ids -> key
                else -> null
            }
        }

    private fun toDocument(row: Row): Document = Document(
        id = row.str("id"),
        title = row.str("title"),
        format = Format.fromId(row.str("format")),
        content = row.str("content"),
        sortIndex = row.int("sort_index"),
        state = DocState.fromId(row.str("state")),
        revision = row.long("revision"),
        createdAt = row.double("created_at"),
        updatedAt = row.double("updated_at"),
        folder = row.str("folder"),
        recentHidden = row.int("recent_hidden") != 0,
        openedAt = row.double("opened_at"),
    )
}
