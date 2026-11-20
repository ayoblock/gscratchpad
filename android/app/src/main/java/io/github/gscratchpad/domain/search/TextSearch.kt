package io.github.gscratchpad.domain.search

data class SearchOptions(
    val regex: Boolean = false,
    val caseSensitive: Boolean = false,
)

data class ReplaceOutcome(
    val text: String,
    val count: Int,
)

/**
 * 文本查找与替换（方案 §9.2「查找替换」的纯逻辑部分）。
 *
 * - 普通模式按字面匹配，正则模式走 [Regex]，替换串支持 `$1` 分组引用；
 * - 命中区间为半开区间 `[start, end)`；
 * - 空匹配被跳过，避免零宽正则造成死循环。
 */
object TextSearch {

    fun findAll(text: String, query: String, options: SearchOptions = SearchOptions()): List<IntRange> {
        if (query.isEmpty()) return emptyList()
        val regex = compile(query, options) ?: return literalFindAll(text, query, options.caseSensitive)
        val out = ArrayList<IntRange>()
        var index = 0
        while (index <= text.length) {
            val m = regex.find(text, index) ?: break
            if (m.value.isEmpty()) {
                index = m.range.last + 2
                continue
            }
            out.add(m.range.first until m.range.last + 1)
            index = m.range.last + 1
        }
        return out
    }

    fun replaceAll(
        text: String,
        query: String,
        replacement: String,
        options: SearchOptions = SearchOptions(),
    ): ReplaceOutcome {
        if (query.isEmpty()) return ReplaceOutcome(text, 0)
        val regex = compile(query, options)
        if (regex != null) {
            var count = 0
            val result = regex.replace(text) { m ->
                count += 1
                m.expandReplacement(replacement)
            }
            return ReplaceOutcome(result, count)
        }
        val ranges = literalFindAll(text, query, options.caseSensitive)
        if (ranges.isEmpty()) return ReplaceOutcome(text, 0)
        val sb = StringBuilder(text.length)
        var last = 0
        for (r in ranges) {
            sb.append(text, last, r.first).append(replacement)
            last = r.last + 1
        }
        sb.append(text, last, text.length)
        return ReplaceOutcome(sb.toString(), ranges.size)
    }

    private fun compile(query: String, options: SearchOptions): Regex? {
        if (!options.regex) return null
        return runCatching { Regex(query) }.getOrNull()
    }

    private fun literalFindAll(text: String, query: String, caseSensitive: Boolean): List<IntRange> {
        val haystack = if (caseSensitive) text else text.lowercase()
        val needle = if (caseSensitive) query else query.lowercase()
        val out = ArrayList<IntRange>()
        var index = haystack.indexOf(needle)
        while (index >= 0) {
            out.add(index until index + needle.length)
            index = haystack.indexOf(needle, index + needle.length)
        }
        return out
    }

    private fun MatchResult.expandReplacement(replacement: String): String {
        val sb = StringBuilder()
        var i = 0
        while (i < replacement.length) {
            val ch = replacement[i]
            if (ch == '\\' && i + 1 < replacement.length && replacement[i + 1] == '$') {
                sb.append('$')
                i += 2
                continue
            }
            if (ch == '$' && i + 1 < replacement.length && replacement[i + 1].isDigit()) {
                val n = replacement[i + 1] - '0'
                sb.append(groupValues.getOrNull(n).orEmpty())
                i += 2
                continue
            }
            sb.append(ch)
            i += 1
        }
        return sb.toString()
    }
}
