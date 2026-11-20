package io.github.gscratchpad.domain

/**
 * R41：编辑器/预览「切换文档」浮层的数据源策略（纯函数，JVM 可单测）。
 *
 * 痛点：切换列表的旧数据源只有数据库里「打开过」的文档，工作目录里没打开过的 .md 不出现。
 * 需求：绑定工作目录后，切换列表要列出该目录下**所有**文档（无论是否打开过）。
 *
 * 合并口径：
 *  1. 未绑定工作目录（dirPath=null）→ 退回原有行为，只列库内文档（兼容）。
 *  2. 已绑定 → 目录内文件优先：
 *     - 文件已在库（sourcePath 精确命中）→ 用其 doc id + 库内标题；
 *     - 文件未入库 → 用 [FILE_PREFIX] + 绝对路径作虚拟 id，标题取文件名，点击时按需导入。
 *     目录之外的库文档继续保留（打开过的其它文档仍可切换），排在同目录文档之后。
 *
 * 纯字符串判断父子目录，不依赖 java.io.File，便于单测。调用方负责用真实 File API 列文件。
 */
object WorkDirSwitchList {
    /** 虚拟 id 前缀：目录里尚未入库的文件。桥接回调据此识别并按需导入。 */
    const val FILE_PREFIX = "file:"

    data class DocEntry(val id: String, val title: String, val sourcePath: String?)
    data class Item(val id: String, val title: String)

    fun isVirtual(id: String): Boolean = id.startsWith(FILE_PREFIX)
    fun pathOf(id: String): String = id.removePrefix(FILE_PREFIX)

    /** 路径的父目录（字符串口径，正斜杠）。无父目录返回空串。 */
    fun parentOf(path: String): String {
        val i = path.lastIndexOf('/')
        return if (i <= 0) "" else path.substring(0, i)
    }

    fun fileName(path: String): String = path.substringAfterLast('/')

    /**
     * 构建切换列表。
     * @param dirPath 绑定的工作目录绝对路径（已规范化）；null 表示未绑定。
     * @param docs 库内文档（含 sourcePath，来自 meta）。
     * @param dirFiles 工作目录内文档文件的绝对路径（调用方用 File API 列出）。
     */
    fun build(dirPath: String?, docs: List<DocEntry>, dirFiles: List<String>): List<Item> {
        if (dirPath.isNullOrBlank()) return docs.map { Item(it.id, it.title) }

        val dir = dirPath.trimEnd('/')
        val docByPath = docs.associateBy { it.sourcePath }
        val items = linkedMapOf<String, Item>() // id 去重，保持插入顺序

        // 1) 目录内文件（调用方已按文件名排序）：已入库用 doc id，未入库用虚拟 id
        dirFiles.forEach { path ->
            val bound = docByPath[path]
            val id = bound?.id ?: (FILE_PREFIX + path)
            val title = bound?.title?.takeIf { it.isNotBlank() } ?: fileName(path)
            items.putIfAbsent(id, Item(id, title))
        }

        // 2) 目录外的库文档（sourcePath 为空或不在本目录），保留切换能力
        docs.forEach { d ->
            val inDir = d.sourcePath != null && parentOf(d.sourcePath!!) == dir
            if (!inDir && d.id !in items) {
                items[d.id] = Item(d.id, d.title)
            }
        }
        return items.values.toList()
    }
}
