package io.github.gscratchpad.capture

/** capture v1 契约常量（方案 §5.6，与桌面 `capture.py` 逐条一致）。 */
object CaptureContract {
    const val ACTION = "io.github.gscratchpad.CAPTURE"

    const val EXTRA_TEXT = "text"
    const val EXTRA_TITLE = "title"
    const val EXTRA_BOOK = "book"
    const val EXTRA_PAGE = "page"
    const val EXTRA_KEY = "key"
    const val EXTRA_MODE = "mode"
    const val EXTRA_REASON = "reason"

    const val MODE_CREATE = "create"
    const val MODE_APPEND = "append"

    const val MAX_TEXT_BYTES = 1024 * 1024
    const val KEY_MAX = 256
    const val TITLE_MAX = 200

    /** 返回码：校验失败用 RESULT_FIRST_USER，写入失败用 RESULT_FIRST_USER + 1。 */
    const val RESULT_INVALID = android.app.Activity.RESULT_FIRST_USER
    const val RESULT_STORE = android.app.Activity.RESULT_FIRST_USER + 1

    /** CLI 退出码同源（供桌面脚本对照）。 */
    const val EXIT_OK = 0
    const val EXIT_ARGS = 1
    const val EXIT_INVALID = 3
    const val EXIT_STORE = 4

    fun extKey(key: String) = "ext:$key"
}
