package io.github.gscratchpad.platform

/**
 * 文件夹命名与语义策略（T3）。
 *
 * 背景：立项探查发现 Android 名称校验弱于桌面（`trim` + 非空），且导入路径绕过校验；
 * 本对象把校验收敛为纯函数，供 Repository 写入路径与 UI 对话框共用，避免两处口径漂移。
 *
 * 规则：
 *  - trim 后非空；
 *  - 长度 ≤ [MAX_LENGTH]（按 Unicode 字符计，与用户可见字数一致）；
 *  - 不含路径分隔符 `/` 与 `\`（Android 上 `\` 虽非法文件名，但 SQLite 名可存，统一拒绝）；
 *  - 不含控制字符（换行/制表等），避免列表排版被破坏；
 *  - 「未归档」为保留显示名（虚拟组），不能作为实体文件夹名——实体未归档用空串表示。
 *
 * Q6 撞名策略：拒绝并提示（不静默合并）。撞名校验在 Repository 层做（需查库），
 * 本对象只负责纯字符串合法性。
 */
object FolderPolicy {
    const val MAX_LENGTH = 60

    /** 未归档虚拟组的显示名；实体 folder 字段用空串表示。 */
    const val UNFILED = "未归档"

    /**
     * 校验名称，合法返回 trim 后的名字，非法抛 [IllegalArgumentException]（消息可直接 toast）。
     */
    fun clean(name: String): String {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) throw IllegalArgumentException("文件夹名不能为空")
        if (trimmed.length > MAX_LENGTH) {
            throw IllegalArgumentException("文件夹名不能超过 $MAX_LENGTH 个字")
        }
        if (trimmed.contains('/') || trimmed.contains('\\')) {
            throw IllegalArgumentException("文件夹名不能包含斜杠 / 或 \\")
        }
        if (trimmed.any { it.isISOControl() }) {
            throw IllegalArgumentException("文件夹名不能包含换行或控制字符")
        }
        if (trimmed == UNFILED) {
            throw IllegalArgumentException("「$UNFILED」是保留名称")
        }
        return trimmed
    }

    /**
     * UI 用：返回错误提示文本，合法返回 null。与 [clean] 共用同一规则，不重复实现。
     */
    fun validate(name: String): String? = runCatching { clean(name) }.exceptionOrNull()?.message

    /** 干净名（供列表显示）：把空 folder 映射为「未归档」。 */
    fun display(folder: String): String = if (folder.isEmpty()) UNFILED else folder
}
