package io.github.gscratchpad.platform

/**
 * 预览专用的 Markdown 清洗（桌面版 frontmatter / HTML 注释不在预览中显示）。
 *
 * - frontmatter：仅当文档**首行**为 `---`（允许 UTF-8 BOM 与行尾空格），且后续存在独立的
 *   结束行 `---` 或 `...` 时，才视为 YAML frontmatter 并连同结束行一起移除。
 *   正文中作为水平线的 `---` 不会被误删（因为不在首行）。
 * - HTML 注释：`<!-- ... -->`，含空注释 `<!---->` 与跨行注释；围栏代码块内的注释按字面保留
 *   （那是代码内容，不是需要隐藏的批注）。移除注释时保留其中的换行，避免行号结构塌陷。
 *
 * 输出仅用于渲染；编辑器原文不变，故保存/导出仍保留 frontmatter 与注释。
 */
object MarkdownSanitizer {

    /** 一次完成两项清洗；顺序无关，先去 frontmatter 再去注释。 */
    fun clean(markdown: String): String = stripHtmlComments(stripFrontmatter(markdown))

    /** 移除文档开头的 YAML frontmatter；无合法 frontmatter 时原样返回。 */
    fun stripFrontmatter(text: String): String {
        val bom = if (text.startsWith('\uFEFF')) 1 else 0
        val firstNl = text.indexOf('\n', bom)
        if (firstNl < 0) return text
        val first = text.substring(bom, firstNl).trim().trimEnd('\r')
        if (first != "---") return text

        val body = text.substring(firstNl + 1)
        var pos = 0
        while (true) {
            val nl = body.indexOf('\n', pos)
            val raw = if (nl < 0) body.substring(pos) else body.substring(pos, nl)
            val line = raw.trim().trimEnd('\r')
            if (line == "---" || line == "...") {
                return if (nl < 0) "" else body.substring(nl + 1)
            }
            if (nl < 0) break
            pos = nl + 1
        }
        // 未闭合：首行 `---` 可能只是水平线，不改动
        return text
    }

    /** 移除围栏代码块之外的 HTML 注释，保留注释占据的换行以维持行结构。 */
    fun stripHtmlComments(text: String): String {
        val out = StringBuilder(text.length)
        var inFence = false
        var fenceChar = ' '
        var fenceLen = 0
        var i = 0
        var atLineStart = true

        while (i < text.length) {
            if (atLineStart) {
                val fence = fenceMarkerAt(text, i)
                if (fence != null) {
                    if (!inFence) {
                        inFence = true
                        fenceChar = fence.first
                        fenceLen = fence.second
                    } else if (fence.first == fenceChar && fence.second >= fenceLen) {
                        inFence = false
                    }
                }
            }
            if (inFence) {
                out.append(text[i])
                atLineStart = text[i] == '\n'
                i++
                continue
            }
            if (startsWithComment(text, i)) {
                val end = text.indexOf("-->", i + 4)
                if (end >= 0) {
                    for (p in i until end + 3) if (text[p] == '\n') out.append('\n')
                    atLineStart = text[end + 2] == '\n'
                    i = end + 3
                    continue
                }
            }
            out.append(text[i])
            atLineStart = text[i] == '\n'
            i++
        }
        return out.toString()
    }

    private fun startsWithComment(s: String, i: Int): Boolean =
        i + 3 < s.length && s[i] == '<' && s[i + 1] == '!' && s[i + 2] == '-' && s[i + 3] == '-'

    /** 行首（允许最多 3 个空格）的 ``` 或 ~~~ 围栏，返回 (字符, 长度)。 */
    private fun fenceMarkerAt(s: String, start: Int): Pair<Char, Int>? {
        var i = start
        var spaces = 0
        while (i < s.length && s[i] == ' ' && spaces < 4) { i++; spaces++ }
        if (i >= s.length || (s[i] != '`' && s[i] != '~')) return null
        val ch = s[i]
        var j = i
        while (j < s.length && s[j] == ch) j++
        val len = j - i
        return if (len >= 3) ch to len else null
    }
}
