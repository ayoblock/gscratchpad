package io.github.gscratchpad.platform

/**
 * R38：File 直读通道的纯策略（可 JVM 单测，不依赖 Android）。
 *
 * 背景：SAF 把文件系统抽象成能力不定的 provider 接口。OPPO/ColorOS 等 provider 的
 * `deleteDocument` 常被拒，导致 [SafFileGateway] 的「临时文件 + 换名」写回留下 `.old`
 * 冗余备份，且重名/覆写行为受 provider 干预。获得 `MANAGE_EXTERNAL_STORAGE` 后，
 * 若能把 SAF documentId 映射成真实磁盘路径，即可用 [java.io.File] 原子写回，回到 POSIX 语义：
 * 同目录临时文件写满 + fsync + `Files.move(REPLACE_EXISTING, ATOMIC_MOVE)` 直接覆盖原名，
 * 全程不产生 `.old`，也不受 provider 的命名/删除能力限制。
 *
 * 设计原则：**安全回退**。映射不出真实路径的 documentId（云盘、其它 provider、非共享存储）
 * 返回 null，调用方保持原 SAF 逻辑，行为与未授权时完全一致。
 *
 * 已实测的两类 documentId：
 *  - externalstorage provider：`primary:Download/Obsidian/x.md` 或 `raw:/storage/emulated/0/...`；
 *  - Termux DocumentsProvider：documentId 本身就是绝对路径 `getDocIdForFile = file.getAbsolutePath()`，
 *    本场景下为 `/storage/emulated/0/Download/Obsidian/x.md`（截图面包屑 Termux > sdcard > Download > Obsidian）。
 */
object FileDirectPolicy {

    /** 规范化的共享存储根前缀。所有映射结果必须落在其下，否则视为不可映射。 */
    const val SHARED_PRIMARY = "/storage/emulated/0"
    val SHARED_PREFIXES = listOf("/storage/emulated/0", "/sdcard", "/storage/")

    /**
     * 把 SAF documentId 解析为真实磁盘绝对路径；不可解析（云盘/未知 provider）返回 null。
     *
     * 规则：
     *  1. `raw:<abs>` → 取 `<abs>`（externalstorage 的 raw 形式）；
     *  2. `primary:<rel>` → `$SHARED_PRIMARY/<rel>`；
     *  3. `<volume>:<rel>`（SD 卡，如 `1234-5678:DCIM/x`）→ `/storage/<volume>/<rel>`；
     *     仅当 volume 形如卷标（含 `-` 或纯大写字母数字）才认，避免误伤普通文件名里的冒号；
     *  4. 以 `共享存储前缀` 开头的绝对路径（Termux 等）→ 原样返回。
     *
     * 所有路径统一去掉重复斜杠，并拒绝含 `..` 的路径穿越。
     */
    fun resolvePath(documentId: String?): String? {
        if (documentId.isNullOrBlank()) return null
        val raw = documentId.trim()
        val path = when {
            raw.startsWith("raw:", ignoreCase = true) -> raw.substring(4)
            raw.startsWith("primary:", ignoreCase = true) -> "$SHARED_PRIMARY/${raw.substring(8).trimStart('/')}"
            volumePrefixed(raw) != null -> {
                val (volume, rel) = volumePrefixed(raw)!!
                "/storage/$volume/${rel.trimStart('/')}"
            }
            SHARED_PREFIXES.any { raw.startsWith(it, ignoreCase = true) } -> raw
            else -> return null
        }
        return normalizeAndValidate(path)
    }

    /** 是否是可 File 直读的共享存储路径（用于二次校验，避免越界写入 app 私有/系统目录）。 */
    fun isSharedStoragePath(path: String?): Boolean {
        if (path.isNullOrBlank()) return false
        if (path.contains("..")) return false
        return SHARED_PREFIXES.any { path.startsWith(it, ignoreCase = true) }
    }

    /**
     * 写回时是否采用 File 原子替换（而非 SAF rename 舞蹈）。
     * 仅当「已授予权限 && API 支持 && 映射出合法共享存储路径」三者同时成立才为 true。
     */
    fun shouldUseFileDirect(supported: Boolean, granted: Boolean, resolvedPath: String?): Boolean =
        supported && granted && isSharedStoragePath(resolvedPath)

    /** 某文件名是否为写回遗留的 `.old` 冗余备份（供清理判定）。 */
    fun isOldBackup(name: String, targetName: String): Boolean =
        name == "$targetName.old" || name == targetName.replace(Regex("(\\.[^.]+)$"), ".old$1")

    private fun volumePrefixed(raw: String): Pair<String, String>? {
        val colon = raw.indexOf(':')
        if (colon <= 0) return null
        val volume = raw.substring(0, colon)
        val rel = raw.substring(colon + 1)
        // 卷标形如 1234-5678 / ABCD-1234 / 纯大写字母数字；且 remainder 非空。
        val looksVolume = volume.matches(Regex("[A-Za-z0-9]{4}-[A-Za-z0-9]{4}")) ||
            volume.matches(Regex("[A-Z0-9]{3,}"))
        return if (looksVolume && rel.isNotBlank()) volume to rel else null
    }

    private fun normalizeAndValidate(path: String): String? {
        if (path.contains("..")) return null
        val normalized = path.replace(Regex("/+"), "/")
        return normalized.takeIf { isSharedStoragePath(it) }
    }
}
