package io.github.gscratchpad.domain

/**
 * 文档切换的纯索引逻辑（T1）：从当前文档在列表中的位置，按步长算出目标下标。
 *
 * 抽离出来是为了让 T1 的三个入口（页内按钮 / 命令面板 / 物理快捷键）共用同一套循环规则，
 * 并可由 JVM 单测锁定边界，不依赖 Activity / Compose。
 */
object DocumentSwitch {

    /**
     * 循环切换目标下标。
     * - 空列表或无当前文档（idx < 0）：next 落到 0，prev 落到末尾（mod 自然处理 -1）；
     * - 单文档：next/prev 都指向自身（调用方据此可短路不切换）。
     */
    fun targetIndex(size: Int, currentIndex: Int, delta: Int): Int {
        if (size <= 0) return -1
        val base = if (currentIndex < 0) {
            if (delta < 0) 0 else -1 // prev 从 0 起退一步 = 末尾；next 从 -1 进一步 = 0
        } else currentIndex
        return (base + delta).mod(size)
    }

    /** 当前不在列表中时，next → 0，prev → 末尾。 */
    fun targetIndexById(ids: List<String>, currentId: String?, delta: Int): Int {
        val idx = ids.indexOf(currentId)
        return targetIndex(ids.size, idx, delta)
    }
}
