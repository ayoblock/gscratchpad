package io.github.gscratchpad.domain.snippet

/**
 * 片段库（方案 §13「Tab 触发词展开」的触屏降级）。
 *
 * 桌面用 `Tab` 展开 `snippet` 触发词；软键盘没有 Tab 键，Android 端改为工具栏「片段」按钮
 * 选择模板后插入到正文末尾。触发词与模板内容与桌面 `snippets` 保持一致的最小集合。
 */
enum class Snippet(val id: String, val label: String, val body: String) {
    CODE(
        "code",
        "代码块",
        "```kotlin\n\n```\n",
    ),
    TABLE(
        "table",
        "表格",
        "| 列 1 | 列 2 |\n|---|---|\n|  |  |\n",
    ),
    TODOS(
        "todo",
        "清单",
        "- [ ] \n- [ ] \n",
    ),
    QUOTE(
        "quote",
        "引用",
        "> \n",
    ),
}

object SnippetLibrary {

    /** 追加到正文末尾：保证与前文之间有一个换行，不吞掉已有尾随换行。 */
    fun append(text: String, snippet: Snippet): String = when {
        text.isEmpty() -> snippet.body
        text.endsWith("\n") -> text + snippet.body
        else -> text + "\n" + snippet.body
    }

    fun byId(id: String): Snippet? = Snippet.entries.firstOrNull { it.id == id }
}
