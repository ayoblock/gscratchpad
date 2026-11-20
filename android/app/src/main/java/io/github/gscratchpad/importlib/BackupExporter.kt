package io.github.gscratchpad.importlib

import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class ExportReport(
    var notes: Int = 0,
    var assets: Int = 0,
    var dbBytes: Long = 0L,
    var bytes: Long = 0L,
    val errors: MutableList<String> = mutableListOf(),
)

/**
 * 桌面备份导出（方案 §6.1 / §13「备份到私有目录」）。
 *
 * 输出结构与 [DesktopImporter] 读取的结构逐字段一致，导出包可直接被桌面版与 Android 版导入：
 * ```
 * manifest.json   {"schema":3,"app_version":"0.5.1","exported_at":...}
 * gscratchpad.db  WAL checkpoint(TRUNCATE) 后的快照
 * notes/          镜像文件
 * assets/         图片资源（按 docId 分目录）
 * ```
 *
 * `snapshotDb` 由调用方提供：先 `checkpointTruncate()`，再把库文件复制到目标路径。
 * 导出器自身不打开数据库，JVM 单测与设备运行可共用同一段代码。
 */
object BackupExporter {

    const val SCHEMA = 3

    fun export(
        target: File,
        appVersion: String,
        exportedAt: Double,
        snapshotDb: (File) -> Unit,
        notesDir: File?,
        assetsDir: File?,
    ): ExportReport {
        val report = ExportReport()
        target.parentFile?.mkdirs()
        val tmpDb = File(target.parentFile ?: File("."), ".export-${System.nanoTime()}.db")
        try {
            snapshotDb(tmpDb)
            if (!tmpDb.isFile) {
                report.errors.add("数据库快照未生成")
                return report
            }
            report.dbBytes = tmpDb.length()
            ZipOutputStream(BufferedOutputStream(target.outputStream())).use { zip ->
                val manifest = JSONObject()
                    .put("schema", SCHEMA)
                    .put("app_version", appVersion)
                    .put("exported_at", exportedAt)
                zip.putNextEntry(ZipEntry("manifest.json"))
                zip.write(manifest.toString().toByteArray(Charsets.UTF_8))
                zip.closeEntry()

                addFile(zip, "gscratchpad.db", tmpDb)

                notesDir?.let { dir ->
                    dir.walkTopDown().filter { it.isFile }.forEach { file ->
                        if (addFile(zip, "notes/${file.relativeTo(dir).invariantSeparatorsPath}", file)) {
                            report.notes += 1
                        }
                    }
                }
                assetsDir?.let { dir ->
                    dir.walkTopDown().filter { it.isFile }.forEach { file ->
                        if (addFile(zip, "assets/${file.relativeTo(dir).invariantSeparatorsPath}", file)) {
                            report.assets += 1
                        }
                    }
                }
            }
            report.bytes = target.length()
        } catch (e: Exception) {
            report.errors.add("导出失败：${e.message}")
        } finally {
            tmpDb.delete()
        }
        return report
    }

    private fun addFile(zip: ZipOutputStream, entryName: String, file: File): Boolean {
        if (!file.isFile) return false
        zip.putNextEntry(ZipEntry(entryName))
        file.inputStream().use { it.copyTo(zip) }
        zip.closeEntry()
        return true
    }
}

