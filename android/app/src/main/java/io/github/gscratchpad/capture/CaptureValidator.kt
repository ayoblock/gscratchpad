package io.github.gscratchpad.capture

import io.github.gscratchpad.capture.CaptureContract.MODE_APPEND
import io.github.gscratchpad.capture.CaptureContract.MODE_CREATE

class CaptureException(val code: Int, message: String) : Exception(message)

data class CaptureRequest(
    val text: String,
    val title: String = "",
    val book: String = "",
    val page: String = "",
    val key: String = "",
    val mode: String = MODE_APPEND,
)

/** 校验规则 1:1 转写（`capture.validate`）：参数错误 1，内容问题 3。 */
object CaptureValidator {

    fun validate(request: CaptureRequest) {
        val text = request.text
        if (request.mode != MODE_CREATE && request.mode != MODE_APPEND) {
            throw CaptureException(
                CaptureContract.EXIT_ARGS,
                "mode 必须是 create/append，收到 ${request.mode}",
            )
        }
        if ('\u0000' in text) throw CaptureException(CaptureContract.EXIT_INVALID, "正文包含 NUL 字符")
        if (text.isBlank()) throw CaptureException(CaptureContract.EXIT_INVALID, "正文为空")
        if (text.toByteArray(Charsets.UTF_8).size > CaptureContract.MAX_TEXT_BYTES) {
            throw CaptureException(CaptureContract.EXIT_INVALID, "正文超过 1MB 上限")
        }
        val key = request.key
        if (key.length > CaptureContract.KEY_MAX) {
            throw CaptureException(
                CaptureContract.EXIT_INVALID,
                "key 超过 ${CaptureContract.KEY_MAX} 字符",
            )
        }
        if (key.any { it.isWhitespace() }) {
            throw CaptureException(CaptureContract.EXIT_INVALID, "key 不得包含空白字符")
        }
        if (request.title.trim().length > CaptureContract.TITLE_MAX) {
            throw CaptureException(
                CaptureContract.EXIT_INVALID,
                "title 超过 ${CaptureContract.TITLE_MAX} 字符",
            )
        }
    }

    /**
     * 追加块：行首独立 `---` 分隔，引用行只由非空字段组成（永久约定）。
     * 首个块没有 `---`。
     */
    fun block(book: String, page: String, stamp: String, text: String): String {
        val parts = mutableListOf<String>()
        if (book.isNotEmpty()) parts.add("《$book》")
        if (page.isNotEmpty()) parts.add(page)
        parts.add(stamp)
        val body = text.trimEnd('\n')
        return "> " + parts.joinToString(" · ") + "\n\n" + body + "\n"
    }

    /** `2026-11-19 15:30` 形式的时间戳（与 `time.strftime("%Y-%m-%d %H:%M")` 一致）。 */
    fun timestamp(epochSeconds: Double): String {
        val fmt = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.US)
        return fmt.format(java.util.Date((epochSeconds * 1000).toLong()))
    }
}
