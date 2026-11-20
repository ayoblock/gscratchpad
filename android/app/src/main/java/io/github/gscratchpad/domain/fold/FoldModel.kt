package io.github.gscratchpad.domain.fold

/**
 * 折叠模型（`folding.py` 策略选择与区间计算 1:1 转写）。
 *
 * 与桌面「物理移除 + 影子恢复」不同，Android 端只计算不可见区间，由界面层用
 * `VisualTransformation` 隐藏，正文始终是全文（方案 ADR-05）：
 * 落盘内容恒为全文，折叠不改内容（不变量 I1）。
 */
enum class FoldStrategy { MARKDOWN, BRACE, INDENT }

/** headerLine 保留可见，headerLine+1..endLine 隐藏（闭区间）。 */
data class FoldRange(val headerLine: Int, val endLine: Int) {
    val hiddenLineCount: Int get() = endLine - headerLine
}

class FoldModel(private val langId: String = "") {

    private val headingRegex = Regex("^(#{1,6})\\s")
    private val fenceRegex = Regex("^\\s*(```|~~~)")

    val strategy: FoldStrategy
        get() = when {
            langId == "markdown" -> FoldStrategy.MARKDOWN
            langId in setOf(
                "json", "c", "cpp", "go", "rust", "java", "js", "typescript", "css", "sql",
                "kotlin", "kts",
            ) -> FoldStrategy.BRACE
            else -> FoldStrategy.INDENT
        }

    fun foldableRanges(text: String): List<FoldRange> {
        val lines = text.split("\n")
        return when (strategy) {
            FoldStrategy.MARKDOWN -> markdownRanges(lines)
            FoldStrategy.BRACE -> braceRanges(lines)
            FoldStrategy.INDENT -> indentRanges(lines)
        }
    }

    /** 某行可折叠的区间（用于点击折叠手柄）；不可折叠返回 null。 */
    fun rangeAt(text: String, headerLine: Int): FoldRange? {
        val lines = text.split("\n")
        if (headerLine !in lines.indices) return null
        val end = blockEnd(lines, headerLine) ?: return null
        return if (end > headerLine) FoldRange(headerLine, end) else null
    }

    // ------------------------------------------------------------------ 区间枚举

    private fun indentRanges(lines: List<String>): List<FoldRange> {
        val result = mutableListOf<FoldRange>()
        for ((i, line) in lines.withIndex()) {
            if (line.isBlank()) continue
            val ind = indentOf(line)
            var last = -1
            var j = i + 1
            while (j < lines.size) {
                val l2 = lines[j]
                if (l2.isNotBlank()) {
                    if (indentOf(l2) <= ind) break
                    last = j
                }
                j++
            }
            if (last > i) result.add(FoldRange(i, last))
        }
        return result
    }

    private fun braceRanges(lines: List<String>): List<FoldRange> {
        val result = mutableListOf<FoldRange>()
        var depth = 0
        for ((i, line) in lines.withIndex()) {
            val before = depth
            depth += lineDepthDelta(line)
            if (depth > before) {
                var d = depth
                var last: Int? = null
                for (j in i + 1 until lines.size) {
                    d += lineDepthDelta(lines[j])
                    if (d <= before) {
                        last = j
                        break
                    }
                }
                if (last != null && last > i) result.add(FoldRange(i, last))
            }
        }
        return result
    }

    private fun markdownRanges(lines: List<String>): List<FoldRange> {
        val result = mutableListOf<FoldRange>()
        val headings = mutableListOf<Pair<Int, Int>>()
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            if (fenceRegex.containsMatchIn(line)) {
                var j = i + 1
                while (j < lines.size && !fenceRegex.containsMatchIn(lines[j])) j++
                if (j < lines.size && j > i + 1) result.add(FoldRange(i, j))
                i = j + 1
                continue
            }
            headingRegex.find(line)?.let { m -> headings.add(i to m.groupValues[1].length) }
            i++
        }
        for ((idx, pair) in headings.withIndex()) {
            val (start, level) = pair
            var end = lines.size
            for ((s2, lv) in headings.drop(idx + 1)) {
                if (lv <= level) {
                    end = s2
                    break
                }
            }
            var last = -1
            for (j in start + 1 until minOf(end, lines.size)) {
                if (lines[j].isNotBlank()) last = j
            }
            if (last > start) result.add(FoldRange(start, last))
        }
        return result
    }

    // ------------------------------------------------------------------ 单块结束行

    private fun blockEnd(lines: List<String>, start: Int): Int? = when (strategy) {
        FoldStrategy.MARKDOWN -> markdownBlockEnd(lines, start)
        FoldStrategy.BRACE -> braceBlockEnd(lines, start)
        FoldStrategy.INDENT -> indentBlockEnd(lines, start)
    }

    private fun indentBlockEnd(lines: List<String>, start: Int): Int? {
        val ind = indentOf(lines[start])
        var last: Int? = null
        for (j in start + 1 until lines.size) {
            val line = lines[j]
            if (line.isNotBlank()) {
                if (indentOf(line) <= ind) break
                last = j
            }
        }
        return last
    }

    private fun braceBlockEnd(lines: List<String>, start: Int): Int? {
        var depth = lines.take(start).sumOf { lineDepthDelta(it) }
        for (j in start until lines.size) {
            depth += lineDepthDelta(lines[j])
            if (depth <= 0 && j > start) return j
        }
        return if (lines.size - 1 > start) lines.size - 1 else null
    }

    private fun markdownBlockEnd(lines: List<String>, start: Int): Int? {
        val n = lines.size
        if (fenceRegex.containsMatchIn(lines[start])) {
            for (j in start + 1 until n) {
                if (fenceRegex.containsMatchIn(lines[j])) return j
            }
            return if (n - 1 > start) n - 1 else null
        }
        val level = headingRegex.find(lines[start])?.groupValues?.get(1)?.length ?: 1
        var last: Int? = null
        var j = start + 1
        while (j < n) {
            val l2 = lines[j]
            if (l2.isNotBlank()) {
                val m2 = headingRegex.find(l2)
                if (m2 != null && m2.groupValues[1].length <= level) break
            }
            if (fenceRegex.containsMatchIn(l2)) {
                var k = j + 1
                while (k < n && !fenceRegex.containsMatchIn(lines[k])) k++
                last = minOf(k, n - 1)
                j = k + 1
                continue
            }
            if (l2.isNotBlank()) last = j
            j++
        }
        return last
    }

    // ------------------------------------------------------------------ 行内度量

    private fun indentOf(line: String): Int {
        var n = 0
        for (ch in line) {
            when (ch) {
                ' ' -> n += 1
                '\t' -> n += 4
                else -> return n
            }
        }
        return n
    }

    /** 一行内括号深度增量（粗略跳过引号内容，与 `_line_depth_delta` 一致）。 */
    private fun lineDepthDelta(line: String, opens: String = "([{", closes: String = ")]}"): Int {
        var depth = 0
        var quote = ' '
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            if (quote != ' ') {
                if (ch == '\\') {
                    i += 2
                    continue
                }
                if (ch == quote) quote = ' '
            } else if (ch == '"' || ch == '\'') {
                quote = ch
            } else if (ch in opens) {
                depth += 1
            } else if (ch in closes) {
                depth -= 1
            }
            i++
        }
        return depth
    }
}
