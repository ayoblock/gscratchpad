package io.github.gscratchpad.platform

/**
 * 标题索引：把 Markdown 的 ATX 标题（`#{1,6} `）解析为（行号、层级、文本）。
 *
 * 与编辑器页内 `outline()` 使用同一规则（跳过围栏代码块内的 `#`），
 * 预览侧据此把「编辑器顶端行」映射为「第 n 个标题」，反之亦然（P2-2 双向同步）。
 */
object HeadingIndex {

    data class H(val line: Int, val level: Int, val text: String)

    private val heading = Regex("^(#{1,6})\\s+(.*)$")
    private val fence = Regex("^\\s*(```|~~~)")

    fun parse(markdown: String, limit: Int = 500): List<H> {
        val out = ArrayList<H>()
        var inFence = false
        var fenceMark = ""
        markdown.lineSequence().forEachIndexed { idx, raw ->
            val line = raw.trimEnd()
            val f = fence.find(line)
            if (f != null) {
                if (!inFence) {
                    inFence = true
                    fenceMark = f.groupValues[1]
                } else if (line.trimStart().startsWith(fenceMark)) {
                    inFence = false
                }
                return@forEachIndexed
            }
            if (inFence) return@forEachIndexed
            val m = heading.find(line)
            if (m != null && out.size < limit) {
                out.add(H(idx + 1, m.groupValues[1].length, m.groupValues[2].trim()))
            }
        }
        return out
    }

    /** 顶端行 → 命中的标题下标（最后一个 startLine ≤ line 的标题）；无命中返回 -1。 */
    fun indexForLine(headings: List<H>, line: Int): Int {
        var idx = -1
        for (i in headings.indices) {
            if (headings[i].line <= line) idx = i else break
        }
        return idx
    }
}
