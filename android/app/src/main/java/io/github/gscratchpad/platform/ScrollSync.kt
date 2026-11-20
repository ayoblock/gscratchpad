package io.github.gscratchpad.platform

/**
 * 编辑器 ↔ 预览 滚动同步（P2-2）。
 *
 * 两侧不在同一 WebView：编辑器的顶端行由 `topLine()` 给出，预览按标题下标滚动。
 * 用标题行号做中间量（[HeadingIndex]），并以「最近一次由谁驱动」的抑制窗口避免互相拉回：
 * - 预览滚动后 900 ms 内不再把编辑器顶端行推给预览；
 * - 编辑器滚动后 900 ms 内不再把预览顶端标题推给编辑器。
 */
object ScrollSync {

    /** 由 MainActivity 在编辑器就绪 / 关闭时设置，避免持有已销毁的 WebView。 */
    @Volatile
    var editor: EditorHost? = null

    @Volatile
    var headings: List<HeadingIndex.H> = emptyList()

    private val lock = Any()
    private var preview: PreviewHost? = null
    private var lastPreviewY = -1f
    private var lastEditorLine = -1
    private var lastPreviewIndex = -1
    private var suppressEditorUntil = 0L
    private var suppressPreviewUntil = 0L

    fun attach(host: PreviewHost, markdown: String) {
        synchronized(lock) {
            // 同一预览宿主重复 attach（翻页/重绘）时保留上次位置，避免跳回顶部
            if (preview !== host) {
                preview = host
                headings = HeadingIndex.parse(markdown)
                lastPreviewY = -1f
                lastEditorLine = -1
                lastPreviewIndex = -1
            } else {
                headings = HeadingIndex.parse(markdown)
            }
        }
        host.scrollListener = { y -> onPreviewScrolled(y) }
    }

    fun detach(host: PreviewHost) {
        synchronized(lock) { if (preview === host) preview = null }
    }

    fun onPreviewScrolled(y: Float) {
        val now = android.os.SystemClock.elapsedRealtime()
        if (now < suppressPreviewUntil) return
        lastPreviewY = y
        suppressPreviewUntil = 0L
        val ed = editor ?: return
        val p = preview ?: return
        p.topHeadingIndex { idx ->
            if (idx < 0) return@topHeadingIndex
            val line = headings.getOrNull(idx)?.line ?: return@topHeadingIndex
            if (line == lastEditorLine) return@topHeadingIndex
            lastEditorLine = line
            lastPreviewIndex = idx
            suppressEditorUntil = android.os.SystemClock.elapsedRealtime() + 900
            ed.scrollToLine(line)
        }
    }

    /** 由预览页的轮询器驱动：把编辑器顶端行推给预览。 */
    fun pullFromEditor() {
        val now = android.os.SystemClock.elapsedRealtime()
        if (now < suppressEditorUntil) return
        val ed = editor ?: return
        val p = preview ?: return
        ed.topLine { line ->
            if (line == lastEditorLine) return@topLine
            lastEditorLine = line
            val idx = HeadingIndex.indexForLine(headings, line)
            if (idx < 0 || idx == lastPreviewIndex) return@topLine
            // 顶端行就在该标题行下方几行内：视为已对齐，避免「顶行↔标题」互相拉扯导致向上漂移
            val headingLine = headings.getOrNull(idx)?.line
            if (headingLine != null && line - headingLine <= 3) {
                lastPreviewIndex = idx
                return@topLine
            }
            lastPreviewIndex = idx
            suppressPreviewUntil = android.os.SystemClock.elapsedRealtime() + 900
            p.scrollToHeading(idx)
        }
    }

    fun currentHeadings(): List<HeadingIndex.H> = synchronized(lock) { headings }
}
