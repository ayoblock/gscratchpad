package io.github.gscratchpad.platform

/** 文档是否包含公式/图表（决定是否注入 KaTeX/Mermaid，S3 验收项：无图表不加载 Mermaid）。 */
object MarkdownFeatures {
    private val math = Regex("\\$[^\\s$][^$]*\\$|\\$\\$")
    private val mermaid = Regex("(?m)^\\s*(```|~~~)\\s*mermaid\\b")

    fun hasMath(text: String): Boolean = math.containsMatchIn(text)

    fun hasMermaid(text: String): Boolean = mermaid.containsMatchIn(text)
}
