package io.github.gscratchpad.capture

import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.DocumentRepository
import io.github.gscratchpad.domain.model.Format

data class CaptureResult(val docId: String, val title: String, val created: Boolean)

/**
 * capture 落库（`capture.capture_document` 的 1:1 转写）。
 *
 * - 同 key 的 create 幂等返回既有文档，不写内容；
 * - 同 key 的 append 在文末追加（行首 `---` 分隔），永不覆盖；
 * - 无 key 锚点时建新文档，首块不带 `---`；
 * - 不建界面、不切标签、不弹通知。
 */
class CaptureService(
    private val repository: DocumentRepository,
    private val dao: DocumentDao,
) {

    suspend fun capture(request: CaptureRequest, now: Double = System.currentTimeMillis() / 1000.0): CaptureResult {
        CaptureValidator.validate(request)
        val title = request.title.trim().take(CaptureContract.TITLE_MAX)
        val book = request.book.trim()
        val page = request.page.trim()
        val key = request.key.trim()
        val stamp = CaptureValidator.timestamp(now)

        var doc = key.takeIf { it.isNotEmpty() }
            ?.let { k -> dao.getMeta(CaptureContract.extKey(k)) }
            ?.let { id -> repository.get(id) }

        if (doc != null && request.mode == CaptureContract.MODE_CREATE) {
            return CaptureResult(doc.id, doc.title, false)
        }

        val created: Boolean
        val body: String
        if (doc == null) {
            created = true
            val fallbackTitle = when {
                title.isNotEmpty() -> title
                book.isNotEmpty() -> "《$book》笔记"
                else -> "速记 ${stamp.substring(5)}"
            }
            doc = repository.create(Format.MD, fallbackTitle)
            body = CaptureValidator.block(book, page, stamp, request.text)
        } else {
            created = false
            var head = doc.content
            if (head.isNotEmpty() && !head.endsWith("\n")) head += "\n"
            body = head + "\n---\n" + CaptureValidator.block(book, page, stamp, request.text)
        }

        val newRevision = doc.revision + 1
        val ticket = repository.saveNow(doc.id, body, newRevision)
        val after = repository.get(doc.id)
        if (after == null || after.revision < newRevision || !ticket.accepted) {
            throw CaptureException(
                CaptureContract.EXIT_STORE,
                "落盘失败：revision 未推进（可能被并发保存合并）",
            )
        }
        if (key.isNotEmpty()) repository.setMeta(CaptureContract.extKey(key), doc.id)
        return CaptureResult(doc.id, after.title, created)
    }
}
