package io.github.gscratchpad.data

import java.io.File
import java.security.MessageDigest

/**
 * 图片资源：内容按 SHA-256 前 12 位去重（与 `assets.import_image` 一致）。
 * 原始图片被移动或删除后，文档引用仍然有效。
 */
class AssetStore(private val appPaths: AppPaths) {

    companion object {
        val SUPPORTED_EXT = setOf(
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif",
        )

        fun digest(bytes: ByteArray): String {
            val md = MessageDigest.getInstance("SHA-256")
            return md.digest(bytes).joinToString("") { "%02x".format(it) }.take(12)
        }

        /** Markdown 链接转义：只处理会破坏链接的字符（与 `assets._md_url` 一致）。 */
        fun mdUrl(rel: String): String = rel
            .replace("%", "%25")
            .replace(" ", "%20")
            .replace("(", "%28")
            .replace(")", "%29")
            .replace("<", "%3C")
            .replace(">", "%3E")
            .replace("\n", "")
    }

    /** 保存图片字节，返回可直接写进正文的相对引用 `assets/<docId>/<sha>.<ext>`。 */
    fun importBytes(docId: String, bytes: ByteArray, suffix: String): String {
        val ext = suffix.lowercase()
        require(ext in SUPPORTED_EXT) { "不支持的图片格式：$suffix" }
        val name = "${digest(bytes)}$ext"
        val dir = appPaths.assetDir(docId).apply { mkdirs() }
        val target = File(dir, name)
        if (!target.exists()) AtomicFiles.write(target, bytes)
        return "assets/$docId/$name"
    }

    fun copyFile(docId: String, source: File): String =
        importBytes(docId, source.readBytes(), "." + source.extension.lowercase())

    fun assetsOf(docId: String): List<File> =
        appPaths.assetDir(docId).listFiles { f -> f.isFile && !f.name.startsWith(".") }
            ?.sortedBy { it.name } ?: emptyList()

    fun delete(docId: String) {
        appPaths.assetDir(docId).deleteRecursively()
    }
}
