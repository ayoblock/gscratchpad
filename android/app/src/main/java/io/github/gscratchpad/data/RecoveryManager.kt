package io.github.gscratchpad.data

import io.github.gscratchpad.domain.model.Format
import org.json.JSONObject
import java.io.File

/**
 * 写前日志与启动回填（不变量 I3）。
 *
 * 顺序与桌面 `_do_save_with` / `_recover` 一致：
 * 写 journal → 提交数据库 → 删 journal → 写镜像。
 * 崩溃发生在「journal 已写、提交未完成」之间时，启动以 journal 回填。
 */
class RecoveryManager(private val appPaths: AppPaths) {

    fun writeJournal(docId: String, revision: Long, content: String, ts: Double) {
        val json = JSONObject()
            .put("id", docId)
            .put("revision", revision)
            .put("content", content)
            .put("ts", ts)
            .toString()
        AtomicFiles.write(appPaths.journalFile(docId), json.toByteArray(Charsets.UTF_8))
    }

    fun deleteJournal(docId: String) {
        appPaths.journalFile(docId).delete()
    }

    /**
     * 扫描 recovery 目录下的 json 日志：revision 大于库内记录则以日志回填并重写镜像。
     * 返回恢复说明列表（供 UI 提示）。
     */
    fun recover(db: SqlDb, dao: DocumentDao, mirror: MirrorStore): List<String> {
        val notes = mutableListOf<String>()
        val journals = appPaths.recovery.listFiles { f -> f.isFile && f.name.endsWith(".json") }
            ?.sortedBy { it.name } ?: emptyList()
        for (journal in journals) {
            val data = try {
                JSONObject(journal.readText(Charsets.UTF_8))
            } catch (_: Exception) {
                journal.delete()
                continue
            }
            val docId = data.optString("id")
            val revision = data.optLong("revision", -1L)
            if (docId.isEmpty() || revision < 0) {
                journal.delete()
                continue
            }
            val content = data.optString("content")
            val dbRevision = dao.revisionOf(docId)
            if (dbRevision == null) {
                journal.delete()
                continue
            }
            if (revision > dbRevision) {
                val now = System.currentTimeMillis() / 1000.0
                db.exec(
                    "UPDATE documents SET content=?, revision=?, updated_at=? WHERE id=?",
                    listOf(content, revision, now, docId),
                )
                mirror.write(docId, content, dao.formatOf(docId))
                notes.add("已从恢复日志还原文档 $docId（revision $revision）")
                android.util.Log.d(
                    "Gscratchpad",
                    "recover restored doc=${docId.take(8)} journalRev=$revision dbRev=$dbRevision chars=${content.length}",
                )
            } else {
                android.util.Log.d(
                    "Gscratchpad",
                    "recover discards doc=${docId.take(8)} journalRev=$revision dbRev=$dbRevision",
                )
            }
            journal.delete()
        }
        return notes
    }
}
