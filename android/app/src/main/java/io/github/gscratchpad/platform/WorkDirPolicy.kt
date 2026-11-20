package io.github.gscratchpad.platform

import android.content.SharedPreferences

/**
 * 工作目录（R33 引入，R40 支持 File 直读绑定）：绑定的本地文件夹。
 *
 * 语义：绑定后，「另存」的选择器初始定位到该目录、「新建文档」在该目录建同名文件，
 * 已绑定外存的文档在 flush 时同步写回。与 v0.7.22 的应用内「虚拟文件夹」相互独立、可共存。
 *
 * R40 绑定方式二选一：File 直读真实路径（[PREF_PATH]，绕开 SAF 视图过滤，需
 * MANAGE_EXTERNAL_STORAGE）/ 旧 SAF tree 授权（[PREF_URI]，向后兼容）。显示名存 SharedPreferences。
 * [normalizeName]/[label]/[isValidUri]/[isValidPath] 为纯函数，可 JVM 单测；读写方法需 Android 环境。
 */
object WorkDirPolicy {
    const val PREF_URI = "workDirUri"
    const val PREF_PATH = "workDirPath"
    const val PREF_NAME = "workDirName"
    const val DEFAULT_NAME = "本地文件夹"

    /**
     * [uri] 为 SAF tree 授权（content://…/tree/…），[path] 为 MANAGE_EXTERNAL_STORAGE
     * 下的真实磁盘路径（/storage/emulated/0/…）。二者互斥：
     * - R40 起 File 直读绑定走 [path]，绕开 SAF「下载」视图过滤（Android 14 目录不全）；
     * - 旧版本已保存的 [uri] 绑定继续可用，行为不变（向后兼容）。
     */
    data class Binding(val uri: String, val name: String, val path: String? = null)

    /** 显示名规范化：空白回落默认名。 */
    fun normalizeName(name: String?): String =
        name?.takeIf { it.isNotBlank() }?.trim() ?: DEFAULT_NAME

    /** SAF tree URI 形如 content://.../tree/...，至少要是非空 content:// 且含 tree 段。 */
    fun isValidUri(uri: String?): Boolean {
        if (uri.isNullOrBlank()) return false
        return uri.startsWith("content://") && uri.contains("/tree/")
    }

    /** File 直读路径必须是共享存储根下的真实路径。 */
    fun isValidPath(path: String?): Boolean =
        !path.isNullOrBlank() && FileDirPolicy.isUnderRoot(path)

    /** 主页按钮文案：path 绑定取路径末级名，uri 绑定取 SAF 显示名。 */
    fun label(binding: Binding): String = "工作目录：${normalizeName(
        if (binding.path != null) FileDirPolicy.label(binding.path) else binding.name,
    )}"

    /** 旧 SAF 绑定写入（保留兼容）。 */
    fun save(prefs: SharedPreferences, uri: String, name: String) {
        prefs.edit()
            .putString(PREF_URI, uri)
            .putString(PREF_PATH, null)
            .putString(PREF_NAME, normalizeName(name))
            .apply()
    }

    /** R40 File 直读绑定写入：清掉旧 SAF URI，二者互斥。 */
    fun savePath(prefs: SharedPreferences, path: String) {
        prefs.edit()
            .putString(PREF_URI, null)
            .putString(PREF_PATH, path)
            .putString(PREF_NAME, normalizeName(FileDirPolicy.label(path)))
            .apply()
    }

    fun clear(prefs: SharedPreferences) {
        prefs.edit().remove(PREF_URI).remove(PREF_PATH).remove(PREF_NAME).apply()
    }

    /** 优先读 File 直读路径；无有效 path 时回落旧 SAF URI。 */
    fun read(prefs: SharedPreferences): Binding? {
        val path = prefs.getString(PREF_PATH, null)
        if (isValidPath(path)) return Binding("", normalizeName(prefs.getString(PREF_NAME, null)), path!!)
        val uri = prefs.getString(PREF_URI, null)
        if (!isValidUri(uri)) return null
        return Binding(uri!!, normalizeName(prefs.getString(PREF_NAME, null)))
    }
}
