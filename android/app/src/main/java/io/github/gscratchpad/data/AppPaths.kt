package io.github.gscratchpad.data

import java.io.File

/**
 * 应用私有数据布局（方案附录 A）。
 *
 * 等价桌面的 `~/.local/share/gscratchpad`：
 * ```
 * files/
 * ├── gscratchpad.db
 * ├── notes/            每篇文档的全文镜像
 * ├── assets/<docId>/   图片资源（SHA-256 去重）
 * ├── recovery/         写前日志
 * ├── backups/          批量替换与导入前备份
 * └── conflicts/        导入冲突副本
 * ```
 */
class AppPaths(filesDir: File) {
    val root: File = filesDir
    val notes = File(root, "notes")
    val assets = File(root, "assets")
    val recovery = File(root, "recovery")
    val backups = File(root, "backups")
    val conflicts = File(root, "conflicts")
    val dbFile = File(root, "gscratchpad.db")
    val cacheDir = File(root, "tmp")

    fun ensureDirs(): AppPaths {
        listOf(root, notes, assets, recovery, backups, conflicts, cacheDir).forEach { it.mkdirs() }
        return this
    }

    fun noteFile(docId: String, format: io.github.gscratchpad.domain.model.Format) =
        File(notes, "$docId.${format.ext}")

    fun assetDir(docId: String) = File(assets, docId)

    fun journalFile(docId: String) = File(recovery, "$docId.json")
}
