package io.github.gscratchpad.platform

/**
 * 命令面板的动作表（方案 §9.2「多标签 + 会话恢复 + 命令面板」）。
 *
 * 这里只描述动作元数据与检索规则，执行由界面层按 [EditorAction.id] 分发，
 * 因此可以被纯 JVM 单测覆盖，不依赖 Android 运行时。
 */
data class EditorAction(
    val id: String,
    val label: String,
    /** 同义词与英文别名，供检索命中（空格分隔）。 */
    val keywords: String,
    val category: String,
)

object EditorActions {

    val all: List<EditorAction> = listOf(
        EditorAction("new", "新建文档", "new create 新建", "文件"),
        EditorAction("openFile", "打开本地文件", "open saf 打开 导入文件", "文件"),
        EditorAction("save", "立即保存", "save flush 保存", "文件"),
        EditorAction("saveAs", "另存为", "saveas export 另存 导出", "文件"),
        EditorAction("share", "分享当前文档", "share send 分享 发送", "文件"),
        EditorAction("close", "关闭当前文档", "close 关闭", "文件"),
        EditorAction("docs", "切换文档（弹出列表）", "docs switch 切换文档 文档列表 上一篇 下一篇", "文件"),
        EditorAction("find", "查找", "find search 查找 搜索", "编辑"),
        EditorAction("replace", "替换", "replace 替换", "编辑"),
        EditorAction("snippets", "插入片段", "snippet template 片段 模板", "编辑"),
        EditorAction("fold", "折叠/展开光标所在块", "fold 折叠 展开", "视图"),
        EditorAction("foldAll", "全部折叠", "foldall 折叠全部", "视图"),
        EditorAction("unfoldAll", "全部展开", "unfold 展开全部", "视图"),
        EditorAction("outline", "文档大纲", "outline toc 大纲 目录", "视图"),
        EditorAction("preview", "预览", "preview 预览", "视图"),
        EditorAction("theme", "切换日间/夜间", "theme dark 主题 夜间 日间", "视图"),
        EditorAction("settings", "设置（字号/行高/折行）", "settings prefs 设置 偏好 字号", "视图"),
        EditorAction("split", "分屏预览", "split dual 分屏 双栏 并排", "视图"),
        EditorAction("image", "插入图片", "image picture 图片 插图", "编辑"),
        EditorAction("help", "快捷键帮助", "help keys 快捷键 帮助", "帮助"),
        EditorAction("cloudBackup", "云备份", "cloud backup webdav 云 备份", "文件"),
    )

    private val byId: Map<String, EditorAction> = all.associateBy { it.id }

    fun find(id: String): EditorAction? = byId[id]

    /**
     * 检索：query 按空格分词，所有词都要命中（label 或 keywords 或 category，大小写不敏感）；
     * 空串返回全部，顺序保持声明顺序（即常用动作在前）。
     */
    fun search(query: String): List<EditorAction> {
        val tokens = query.trim().lowercase().split(' ').filter { it.isNotEmpty() }
        if (tokens.isEmpty()) return all
        return all.filter { action ->
            val haystack = "${action.label} ${action.keywords} ${action.category}".lowercase()
            tokens.all { haystack.contains(it) }
        }
    }
}
