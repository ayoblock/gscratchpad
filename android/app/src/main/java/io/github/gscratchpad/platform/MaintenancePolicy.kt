package io.github.gscratchpad.platform

/**
 * 维护/孤儿清理的纯策略（R39，对齐桌面 store.py `_orphan_paths` / `_stale_temp`）。
 *
 * 只做「名字判定 + 体积文案」，不碰文件 IO——文件枚举与删除留在 Repository，
 * 判定规则在此集中并可在 JVM 上单测（与 FileDirectPolicy 同风格）。
 */
object MaintenancePolicy {
    /** 原子写临时文件超过 10 分钟视为残留（桌面 `_stale_temp` 默认 600 秒）。 */
    const val TMP_STALE_MS = 600_000L

    /** 只处理这三个应用私有目录的第一层，不递归未知目录。 */
    enum class Area { NOTES, ASSETS, RECOVERY }

    /**
     * 某条目是否为孤儿。
     * @param isDir 是否目录（符号链接按文件处理，由调用方传入）
     * @param ageMs 距最后修改的毫秒数，仅 .tmp 需要（新鲜 tmp 不动）
     */
    fun isOrphan(
        area: Area,
        name: String,
        isDir: Boolean,
        ageMs: Long,
        liveIds: Set<String>,
    ): Boolean = when (area) {
        Area.NOTES -> when {
            name.endsWith(".tmp") -> ageMs >= TMP_STALE_MS
            isDir -> true // notes/ 下不该有子目录
            else -> name.substringBeforeLast('.', name) !in liveIds
        }
        Area.ASSETS -> name !in liveIds
        Area.RECOVERY -> name.endsWith(".json") && name.removeSuffix(".json") !in liveIds
    }

    /** 人类可读体积，确认对话框用（对齐桌面 `_human_size` 的量级表达）。 */
    fun humanSize(bytes: Long): String {
        if (bytes < 1024) return "$bytes B"
        val kb = bytes / 1024.0
        if (kb < 1024) return if (kb < 10) "%.1f KB".format(kb) else "${kb.toLong()} KB"
        val mb = kb / 1024.0
        return if (mb < 10) "%.1f MB".format(mb) else "${mb.toLong()} MB"
    }
}
