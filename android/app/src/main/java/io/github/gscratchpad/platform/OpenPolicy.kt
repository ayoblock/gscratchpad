package io.github.gscratchpad.platform

/**
 * 「打开文件」（SAF OpenDocument）的纯策略，与 [SaveAsPolicy] 成对，集中两条易错规则：
 *
 *  1) MIME 过滤器必须是全类型通配符（见 [MIME_TYPES]）：部分国产 ROM（已实测华为 EMUI）会把以
 *     application/octet-stream 另存的 .md 文件登记成「BIN 档案」。若打开过滤器仍是
 *     text/plain / text/markdown，这类文件在选择器里被按 MIME 过滤掉，表现为「灰掉、无法选中」——
 *     文件本身没坏。
 *  2) 由于过滤器放开到全类型，必须在回调里按扩展名白名单兜底：本应用处理纯文本 / 标记 / 源码 / 配置类
 *     文档（见 [ALLOWED]），白名单之外的文件即便被选中也拒绝读入，避免图片/压缩包/二进制被当成正文
 *     灌进编辑器。真实二进制还有 SafFileGateway 的 NUL 检测二道把关。
 *
 * 纯 Kotlin object，不依赖 Activity / ContentResolver，可直接 JVM 单测。
 */
object OpenPolicy {
    /** OpenDocument 的 MIME 数组：中性通配符，避免 ROM 按 MIME 隐藏 octet-stream 另存的文档。 */
    val MIME_TYPES: Array<String> = arrayOf("*/*")

    /**
     * 允许打开的扩展名（小写）：文档 / 标记、脚本 / 源码、配置 / 数据三类纯文本后缀。
     * 不含任何二进制后缀（zip/jpg/png/mp4/apk/bin/so/…），那些由白名单拒绝 + gateway NUL 检测双重拦截。
     */
    private val ALLOWED = setOf(
        // 文档 / 标记 / 文本
        "txt", "text", "md", "markdown", "html", "htm", "xhtml", "rst", "org", "tex",
        "csv", "tsv", "log", "diff", "patch",
        // 脚本 / 源码
        "sh", "bash", "zsh", "fish", "py", "pyw", "rb", "pl", "pm", "lua",
        "js", "jsx", "ts", "tsx", "php", "go", "rs", "java", "kt", "kts",
        "c", "h", "cpp", "hpp", "cc", "cs", "swift", "scala", "sql", "r",
        "css", "scss", "less", "vue", "svelte",
        // 配置 / 数据
        "json", "xml", "yaml", "yml", "toml", "ini", "cfg", "conf", "config",
        "properties", "env", "gradle", "gitignore", "gitattributes", "dockerfile", "dockerignore",
        "makefile", "mk", "cmake", "bat", "cmd", "ps1",
    )

    /** 从显示名取扩展名（最后一个点之后，大小写不敏感）。无点返回空串。 */
    fun extensionOf(displayName: String): String =
        displayName.substringAfterLast('.', "").lowercase()

    /**
     * 显示名是否命中白名单。除扩展名外也匹配整个小写名——
     * Makefile / Dockerfile / .gitignore 这类「无扩展名或点文件」的语义后缀即全名本身。
     */
    fun isSupported(displayName: String): Boolean {
        val lower = displayName.lowercase()
        return extensionOf(displayName) in ALLOWED || lower in ALLOWED
    }

    /** 支持的文本大类数（供单测锁定白名单非空且成规模）。 */
    fun supportedCount(): Int = ALLOWED.size

    /** 拒绝提示：给代表后缀，不穷举（白名单较宽，穷举会淹没提示条）。 */
    const val REJECT_MESSAGE = "不支持的文件类型，仅可打开文本 / 源码 / 配置类文档（.md .txt .html .sh .py .conf 等）"
}
