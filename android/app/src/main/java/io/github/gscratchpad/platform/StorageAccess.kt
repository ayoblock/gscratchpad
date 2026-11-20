package io.github.gscratchpad.platform

/**
 * R42：共享存储访问能力的统一判定（纯函数，JVM 可单测）。
 *
 * 背景：File 直读工作目录 / 本地文件打开需要"能列真实共享存储目录"的系统能力：
 *  - API 30+（Android 11+）：`MANAGE_EXTERNAL_STORAGE`（所有文件访问）；
 *  - API 29-（含华为 YAL-AL10 的 Android 10）：该权限不存在，必须走传统
 *    `READ_EXTERNAL_STORAGE`（Manifest 声明 + 运行时申请）。
 * 旧逻辑把所有版本都绑死在 MANAGE_EXTERNAL_STORAGE 上，导致低版本机 `granted` 恒 false、
 * 授权入口也守卫返回——目录永远列不出（用户实测的死结）。本对象把"该走哪条路"抽成纯判定，
 * 系统 API 调用（isExternalStorageManager / checkSelfPermission）留在 MainActivity。
 */
object StorageAccess {

    /** 该 API 级别是否支持"所有文件访问"（MANAGE_EXTERNAL_STORAGE，API 30+）。 */
    fun supportsManageAll(api: Int): Boolean = api >= 30

    /**
     * 给定 API 级别与两种权限的实际授予状态，判断"能否列真实共享存储目录"。
     * [manageAll] 仅 API 30+ 有意义；[legacyRead] 仅 API 29- 有意义。
     */
    fun canBrowse(api: Int, manageAll: Boolean, legacyRead: Boolean): Boolean =
        if (supportsManageAll(api)) manageAll else legacyRead

    /** 该 API 级别是否需要在运行时弹传统 READ_EXTERNAL_STORAGE 授权。 */
    fun needsRuntimeRead(api: Int): Boolean = !supportsManageAll(api)

    /** 权限未授予时给用户的说明（区分两条路径）。 */
    fun hint(api: Int): String = if (supportsManageAll(api)) {
        "需授予「所有文件访问」权限才能浏览真实目录（Android 11+）。授权后返回本页再点一次。"
    } else {
        "需授予「存储权限」才能浏览真实目录（Android 10 及以下）。授权后返回本页再点一次。"
    }

    /** 授权按钮文案。 */
    fun actionLabel(api: Int): String =
        if (supportsManageAll(api)) "授予所有文件访问" else "授予存储权限"
}
