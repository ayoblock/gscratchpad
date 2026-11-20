package io.github.gscratchpad.platform

import android.content.SharedPreferences

/**
 * 工作目录（R33）：一个通过 SAF `ACTION_OPEN_DOCUMENT_TREE` 绑定的本地文件夹。
 *
 * 语义：绑定后，「另存」的选择器初始定位到该目录、「新建文档」在该目录建同名文件，
 * 已绑定外存的文档在 flush 时同步写回。与 v0.7.22 的应用内「虚拟文件夹」相互独立、可共存。
 *
 * 仅保存 URI 字符串 + 显示名到 SharedPreferences；URI 的持久读权限由
 * `SafFileGateway.takePersistablePermission` 单独持有（系统 PersistedUriPermission）。
 * [normalizeName]/[label]/[isValidUri] 为纯函数，可 JVM 单测；读写方法需 Android 环境。
 */
object WorkDirPolicy {
    const val PREF_URI = "workDirUri"
    const val PREF_NAME = "workDirName"
    const val DEFAULT_NAME = "本地文件夹"

    data class Binding(val uri: String, val name: String)

    /** 显示名规范化：空白回落默认名。 */
    fun normalizeName(name: String?): String =
        name?.takeIf { it.isNotBlank() }?.trim() ?: DEFAULT_NAME

    /** 主页按钮文案。 */
    fun label(binding: Binding): String = "工作目录：${normalizeName(binding.name)}"

    /** SAF tree URI 形如 content://.../tree/...，至少要是非空 content:// 且含 tree 段。 */
    fun isValidUri(uri: String?): Boolean {
        if (uri.isNullOrBlank()) return false
        return uri.startsWith("content://") && uri.contains("/tree/")
    }

    fun save(prefs: SharedPreferences, uri: String, name: String) {
        prefs.edit()
            .putString(PREF_URI, uri)
            .putString(PREF_NAME, normalizeName(name))
            .apply()
    }

    fun clear(prefs: SharedPreferences) {
        prefs.edit().remove(PREF_URI).remove(PREF_NAME).apply()
    }

    fun read(prefs: SharedPreferences): Binding? {
        val uri = prefs.getString(PREF_URI, null)
        if (!isValidUri(uri)) return null
        return Binding(uri!!, normalizeName(prefs.getString(PREF_NAME, null)))
    }
}
