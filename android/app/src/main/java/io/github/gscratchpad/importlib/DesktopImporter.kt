package io.github.gscratchpad.importlib

import io.github.gscratchpad.data.AppPaths
import io.github.gscratchpad.data.AssetStore
import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.data.SqlDb
import io.github.gscratchpad.domain.model.Format
import org.json.JSONObject
import java.io.File
import java.util.zip.ZipFile

data class ImportReport(
    var docsInSource: Int = 0,
    var docsImported: Int = 0,
    var docsSkipped: Int = 0,
    var conflicts: Int = 0,
    var foldersImported: Int = 0,
    var metaImported: Int = 0,
    var brokenImages: Int = 0,
    var deadPaths: Int = 0,
    var verified: Boolean = false,
    var revisionMismatch: Int = 0,
    val errors: MutableList<String> = mutableListOf(),
)

/**
 * 桌面备份导入（方案 §6）。
 *
 * 备份结构：
 * ```
 * manifest.json   {"schema":3,"app_version":"1.14.3","exported_at":...}
 * gscratchpad.db  只读快照（导出前 checkpoint(TRUNCATE)）
 * notes/          镜像文件（可选）
 * assets/         图片资源（可选）
 * ```
 *
 * 步骤：校验 → 事务导入 documents/folders/meta（跳过窗口几何与 fs_root）
 * → source_path 转 URI → 图片重写为私有 assets → 逐条校验 → 报告。
 */
class DesktopImporter(
    private val targetDb: SqlDb,
    private val dao: DocumentDao,
    private val assets: AssetStore,
    private val paths: AppPaths,
    private val openSourceDb: (File) -> SqlDb,
    private val resolveSourceUri: (String) -> String? = { null },
) {

    companion object {
        const val SUPPORTED_SCHEMA = 3
        val IMAGE_EXT = setOf(".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif")

        /** 解开 zip 到目录，拒绝 zip-slip。 */
        fun extract(zip: File, dest: File) {
            dest.mkdirs()
            ZipFile(zip).use { zf ->
                zf.entries().asSequence().forEach { entry ->
                    val target = File(dest, entry.name)
                    if (!target.canonicalPath.startsWith(dest.canonicalPath + File.separator) &&
                        target.canonicalPath != dest.canonicalPath
                    ) {
                        throw IllegalArgumentException("压缩包包含越界路径：${entry.name}")
                    }
                    if (entry.isDirectory) target.mkdirs() else {
                        target.parentFile?.mkdirs()
                        zf.getInputStream(entry).use { input ->
                            target.outputStream().use { output -> input.copyTo(output) }
                        }
                    }
                }
            }
        }
    }

    fun import(backupDir: File): ImportReport {
        val report = ImportReport()
        val manifestFile = File(backupDir, "manifest.json")
        if (!manifestFile.isFile) {
            report.errors.add("缺少 manifest.json")
            return report
        }
        val manifest = runCatching { JSONObject(manifestFile.readText(Charsets.UTF_8)) }
            .getOrElse {
                report.errors.add("manifest.json 无法解析")
                return report
            }
        if (manifest.optInt("schema", -1) != SUPPORTED_SCHEMA) {
            report.errors.add("schema 版本不匹配：${manifest.optInt("schema", -1)}，需要 $SUPPORTED_SCHEMA")
            return report
        }

        val sourceFile = File(backupDir, "gscratchpad.db")
        if (!sourceFile.isFile) {
            report.errors.add("缺少 gscratchpad.db")
            return report
        }

        val sourceDb = runCatching { openSourceDb(sourceFile) }.getOrElse {
            report.errors.add("源库无法打开：${it.message}")
            return report
        }

        try {
            val integrity = sourceDb.queryOne("PRAGMA integrity_check")
            if (integrity == null || integrity.str("integrity_check") != "ok") {
                report.errors.add("源库完整性检查未通过：${integrity?.str("integrity_check")}")
                return report
            }
            val docs = sourceDb.query("SELECT * FROM documents")
            report.docsInSource = docs.size

            val folderNames = sourceDb.query("SELECT name FROM folders").map { it.str("name") }
            val metaRows = sourceDb.query("SELECT key, value FROM meta")

            // 事务写入，失败整体回滚
            targetDb.transaction {
                folderNames.forEach { name ->
                    targetDb.exec(
                        "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                        listOf(name, 0.0),
                    )
                    report.foldersImported++
                }

                docs.forEach { row ->
                    val doc = SourceDoc.from(row)
                    val existing = dao.get(doc.id)
                    if (existing != null) {
                        // §6.3：同 id 冲突，以 revision 较大者为准；revision 相同看 updated_at。
                        // 落败的一份写入 conflicts/<id>.md，绝不静默丢弃。
                        val keepSource = doc.revision > existing.revision ||
                            (doc.revision == existing.revision && doc.updatedAt >= existing.updatedAt)
                        val loserContent = if (keepSource) existing.content else doc.content
                        writeConflict(doc.id, loserContent, report)
                        if (!keepSource) {
                            report.docsSkipped++
                            return@forEach
                        }
                    }

                    targetDb.exec(
                        "INSERT OR REPLACE INTO documents(id, title, format, content, sort_index," +
                            " state, revision, created_at, updated_at, folder)" +
                            " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        listOf(
                            doc.id, doc.title, doc.format.id, doc.content, doc.sortIndex,
                            doc.state, doc.revision, doc.createdAt, doc.updatedAt, doc.folder,
                        ),
                    )
                    if (doc.folder.isNotEmpty()) {
                        targetDb.exec(
                            "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                            listOf(doc.folder, 0.0),
                        )
                    }
                    report.docsImported++
                }

                metaRows.forEach { row ->
                    val key = row.str("key")
                    if (key in MetaKeys.SKIP_ON_IMPORT || key == MetaKeys.SCHEMA_VERSION) return@forEach
                    if (key.startsWith("window_")) return@forEach
                    if (key.startsWith("source_path:")) return@forEach
                    val value = row.str("value")
                    targetDb.exec(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                        listOf(key, value),
                    )
                    report.metaImported++
                }
            }

            // 路径映射与图片重写（事务外，失败只影响单条并计数）
            docs.forEach { row ->
                val doc = SourceDoc.from(row)
                rewriteImages(backupDir, doc, report)

                val sourcePath = metaRows.firstOrNull { it.str("key") == MetaKeys.sourcePath(doc.id) }
                    ?.str("value").orEmpty()
                if (sourcePath.isNotEmpty()) {
                    val mapped = resolveSourceUri(sourcePath)
                    if (mapped == null) {
                        report.deadPaths++
                        targetDb.exec(
                            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                            listOf(MetaKeys.sourcePath(doc.id), ""),
                        )
                    } else {
                        targetDb.exec(
                            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                            listOf(MetaKeys.sourcePath(doc.id), mapped),
                        )
                    }
                }
            }

            report.verified = verify(sourceDb, report)
        } catch (e: Exception) {
            report.errors.add("导入中断：${e.message}")
            report.verified = false
        } finally {
            runCatching { sourceDb.close() }
        }
        return report
    }

    private fun writeConflict(docId: String, content: String, report: ImportReport) {
        val target = File(paths.conflicts, "$docId.md")
        target.parentFile?.mkdirs()
        target.writeText(content, Charsets.UTF_8)
        report.conflicts++
    }

    /** `![](../x.png)`、`![](assets/x.png)` 统一复制进 `assets/<docId>/` 并按内容去重。 */
    private fun rewriteImages(backupDir: File, doc: SourceDoc, report: ImportReport) {
        val pattern = Regex("!\\[([^]]*)]\\(([^)]+)\\)")
        val current = dao.get(doc.id)?.content ?: return
        var broken = 0
        val rewritten = pattern.replace(current) { match ->
            val alt = match.groupValues[1]
            val raw = match.groupValues[2].substringBefore(' ').trim()
            if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("data:")) {
                return@replace match.value
            }
            val fileName = raw.substringAfterLast('/').substringBefore('?')
            val ext = "." + fileName.substringAfterLast('.', "").lowercase()
            val found = findInBackup(backupDir, fileName)
            if (found == null || ext !in IMAGE_EXT) {
                broken++
                return@replace match.value
            }
            val rel = assets.copyFile(doc.id, found)
            "![$alt]($rel)"
        }
        report.brokenImages += broken
        if (rewritten != current) {
            targetDb.exec(
                "UPDATE documents SET content=? WHERE id=? AND revision=?",
                listOf(rewritten, doc.id, doc.revision),
            )
        }
    }

    private fun findInBackup(backupDir: File, fileName: String): File? =
        backupDir.walkTopDown().firstOrNull { it.isFile && it.name == fileName }

    /** 校验：文档数、revision、正文长度。 */
    private fun verify(sourceDb: SqlDb, report: ImportReport): Boolean {
        val sourceCount = sourceDb.query("SELECT COUNT(*) AS n FROM documents").firstOrNull()?.int("n") ?: 0
        val targetCount = dao.allDocuments().size
        var ok = true
        sourceDb.query("SELECT id, revision, LENGTH(CAST(content AS BLOB)) AS n FROM documents").forEach { row ->
            val id = row.str("id")
            val target = dao.get(id)
            if (target == null) {
                // 被冲突策略跳过的文档允许缺席
                if (report.docsSkipped == 0) ok = false
                return@forEach
            }
            if (target.revision != row.long("revision")) {
                report.revisionMismatch++
                ok = false
            }
            val targetLen = target.content.toByteArray(Charsets.UTF_8).size
            if (targetLen.toLong() != row.long("n")) {
                // 图片重写会改变正文长度，长度校验只对未重写文档生效
                if (!target.content.contains("assets/")) ok = false
            }
        }
        return ok && targetCount >= sourceCount - report.docsSkipped
    }

    private data class SourceDoc(
        val id: String,
        val title: String,
        val format: Format,
        val content: String,
        val sortIndex: Int,
        val state: String,
        val revision: Long,
        val createdAt: Double,
        val updatedAt: Double,
        val folder: String,
    ) {
        companion object {
            fun from(row: io.github.gscratchpad.data.Row) = SourceDoc(
                id = row.str("id"),
                title = row.str("title"),
                format = Format.fromId(row.str("format")),
                content = row.str("content"),
                sortIndex = row.int("sort_index"),
                state = row.str("state"),
                revision = row.long("revision"),
                createdAt = row.double("created_at"),
                updatedAt = row.double("updated_at"),
                folder = row.str("folder"),
            )
        }
    }
}
