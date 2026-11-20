package io.github.gscratchpad.platform

/**
 * 所有文件访问（MANAGE_EXTERNAL_STORAGE）的纯逻辑。
 *
 * R37 曾是"验证探针"：其中 [missingEntriesRecovered]/[resultLabel] 用于真机确认 ColorOS
 * 是否放行、File 直读能否看到 SAF 缺失项——该验证已完成并从设置页移除（R40）。
 * 现仅 [isSupported] 仍被使用：判断系统是否支持该权限（API 30+）；其余函数保留仅供
 * 历史单测，不再进入 UI。实际能力判断在 MainActivity.allFilesAccessGranted()。
 */
object AllFilesProbe {

    /** 需 API 30+ 才有 MANAGE_EXTERNAL_STORAGE；低版本直接视为不可用，回退 SAF。 */
    fun isSupported(apiLevel: Int): Boolean = apiLevel >= 30

    /** 权限状态在设置页展示的文案。 */
    fun statusLabel(supported: Boolean, granted: Boolean): String = when {
        !supported -> "所有文件访问：本系统版本不需要（< Android 11）"
        granted -> "所有文件访问：已授予（File 直读可用）"
        else -> "所有文件访问：未授予（当前走 SAF）"
    }

    /**
     * 判定 File 直读结果是否覆盖了 SAF 选择器里缺失的四个条目。
     * [names] 为 File.list() 返回的文件名集合（可含任意大小写）。
     */
    fun missingEntriesRecovered(names: List<String>): Boolean {
        val expected = listOf("markdor", "RebornMing", "shell", "untitled_2.txt")
        return expected.all { target -> names.any { it.equals(target, ignoreCase = true) } }
    }

    /** 探针结果摘要文案，供设置页展示。 */
    fun resultLabel(granted: Boolean, names: List<String>): String = when {
        !granted -> "探针未运行：尚未获得所有文件访问权"
        names.isEmpty() -> "探针失败：目录不可读或不存在"
        missingEntriesRecovered(names) ->
            "探针通过：File 直读到 ${names.size} 项，SAF 缺失的 4 项全部可见"
        else ->
            "探针部分通过：File 直读到 ${names.size} 项，但 SAF 缺失项未全部出现（${names.sorted().joinToString(", ")}）"
    }
}
