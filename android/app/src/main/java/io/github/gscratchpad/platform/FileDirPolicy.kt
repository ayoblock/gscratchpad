package io.github.gscratchpad.platform

import java.io.File

/**
 * R40：工作目录 File 直读选择器的纯策略（JVM 可单测）。
 *
 * 背景：SAF `ACTION_OPEN_DOCUMENT_TREE` 在 ColorOS 等 ROM 上按 MIME / provider 视图过滤，
 * 从「下载」进入时目录不全（R37 探针已证明 File API 能看到全量）。获得
 * MANAGE_EXTERNAL_STORAGE 后改用 [java.io.File] 逐级列举共享存储真实目录，绕开 SAF 视图过滤。
 *
 * 本对象只放路径规则与目录过滤；实际 `listFiles()` 依赖文件系统，但 [listSubdirs]
 * 接收 [File] 参数，JVM 单测可用临时目录树覆盖。
 */
object FileDirPolicy {
    /** 主共享存储根（多数真机与模拟器一致）。运行时可用 Environment 取值覆盖。 */
    const val ROOT = "/storage/emulated/0"

    /** 规范化路径：去首尾空白与尾部斜杠，空回退根。不做大小写改写。 */
    fun normalize(path: String?): String {
        if (path.isNullOrBlank()) return ROOT
        val trimmed = path.trim().trimEnd('/')
        return if (trimmed.isEmpty() || trimmed == "/") ROOT else trimmed
    }

    /** 上级目录；已在根则返回 null（UI 禁用「上级」按钮）。 */
    fun parentOf(path: String): String? {
        val p = normalize(path)
        if (p == ROOT) return null
        val idx = p.lastIndexOf('/')
        return if (idx <= 0) ROOT else p.substring(0, idx)
    }

    /**
     * R43：以 [root] 为界的上级目录——path 已在 root（含等于 root）则返回 null，
     * UI 用它禁用「上级」，使文件浏览器以工作目录为根、不越出起点。
     */
    fun parentWithin(path: String, root: String): String? {
        val r = normalize(root)
        val p = normalize(path)
        if (p == r) return null
        return parentOf(p)
    }

    /** 路径是否在共享存储根下（防越界到 app 私有 / 系统目录，拒绝 `..` 穿越）。 */
    fun isUnderRoot(path: String): Boolean {
        if (path.contains("..")) return false
        val p = normalize(path)
        return p == ROOT || p.startsWith("$ROOT/")
    }

    /** 目录显示名：根显示「内部存储」，否则取最后一级。 */
    fun label(path: String): String {
        val p = normalize(path)
        return if (p == ROOT) "内部存储" else p.substringAfterLast('/')
    }

    /** 相对根的面包屑文案。 */
    fun displayPath(path: String): String {
        val p = normalize(path)
        return when {
            p == ROOT -> "内部存储"
            p.startsWith("$ROOT/") -> p.removePrefix(ROOT)
            else -> p
        }
    }

    /** 目录项是否可选：非空且非隐藏（. 开头）。 */
    fun isSelectableDir(name: String): Boolean =
        name.isNotBlank() && !name.startsWith(".")

    /** 列出当前目录下可选子目录，按名称（忽略大小写）排序。JVM 单测可传临时目录。 */
    fun listSubdirs(dir: File): List<File> =
        dir.listFiles { f -> f.isDirectory && f.canRead() && isSelectableDir(f.name) }
            ?.sortedBy { it.name.lowercase() }
            ?: emptyList()

    /**
     * 文档文件后缀白名单（R41 切换列表用）：只列可当正文打开的纯文本类文件，
     * 与 [OpenPolicy] 的文档类子集对齐。刻意比 OpePolicy 全集窄——切换列表只关心笔记文档，
     * 不把源码/配置类也塞进去。JVM 单测可直接断言。
     */
    private val DOC_EXT = setOf("md", "markdown", "txt", "text", "html", "htm", "xhtml", "org", "rst")

    /** 文件名是否是切换列表该列的文档文件（非隐藏、后缀在白名单）。 */
    fun isDocFileName(name: String): Boolean {
        if (name.isBlank() || name.startsWith(".")) return false
        val ext = name.substringAfterLast('.', "").lowercase()
        return ext in DOC_EXT
    }

    /** 列出目录下文档文件，按文件名（忽略大小写）排序。JVM 单测可传临时目录。 */
    fun listDocFiles(dir: File): List<File> =
        dir.listFiles { f -> f.isFile && f.canRead() && isDocFileName(f.name) }
            ?.sortedBy { it.name.lowercase() }
            ?: emptyList()
}
