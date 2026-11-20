package io.github.gscratchpad.platform

/**
 * 「另存为」（SAF）的纯策略，集中三条易错规则，便于 JVM 单测锁定：
 *  1) MIME 必须是 application/octet-stream——系统仅为 text/plain / text/markdown 等「已知文本类型」
 *     自动补扩展名；text/plain 会把用户文件名改成 .txt（「未命名.md.txt」），text/markdown 会把
 *     用户手输的 .txt 改回 .md。octet-stream 是无扩展名推断的中性类型，后缀完全交给文件名。
 *  2) 另存内容源以编辑器实时正文（editorLatest）为准，Compose 旧通路 text 仅作兜底；
 *  3) 文件名后缀幂等，避免 title 已带 .md 时被拼成 .md.md。
 *
 * 纯 Kotlin object，不依赖 Activity / ContentResolver，可直接单测。
 */
object SaveAsPolicy {
    /** SAF CreateDocument 的 MIME：中性类型，不触发系统按 MIME 改写用户文件名的后缀。 */
    const val MIME = "application/octet-stream"

    /**
     * 另存内容源：编辑器实时正文优先，旧 Compose 通路 text 兜底。
     * 新建文档 → 输入 → 另存时 text 仍是空串，只有 editorLatest 是最新正文。
     */
    fun content(editorLatest: String, textFallback: String): String =
        editorLatest.ifEmpty { textFallback }

    /** 另存文件名：确保恰好一个 .md 后缀（大小写不敏感）。 */
    fun fileName(title: String): String =
        if (title.endsWith(".md", ignoreCase = true)) title else "$title.md"

    /**
     * 另存后文档标题：取文件名的 stem（去最后一个扩展名），对齐桌面版「stem 优先」。
     * 用户手输 foo.txt → "foo"；未命名.md → "未命名"；无扩展名 → 原名。
     * 空 stem（如 ".bashrc"）回退整名，避免出现空白标题。
     */
    fun savedTitle(displayName: String): String {
        val stem = displayName.substringBeforeLast('.', displayName)
        return stem.ifEmpty { displayName }
    }
}
