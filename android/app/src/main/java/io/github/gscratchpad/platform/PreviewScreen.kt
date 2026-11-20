package io.github.gscratchpad.platform

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * 预览页原生视图：顶栏 + WebView + 滚动同步。
 *
 * 供两种宿主复用：
 * - [io.github.gscratchpad.PreviewActivity]：独立全屏 Activity（外部 intent 入口）；
 * - MainActivity：同页切换（关闭编辑器 WebView、显示本视图，无 Activity 跳转）。
 *
 * 顶栏与编辑器 #bar 对齐：56 dp 高、1 px 分隔线、44 dp 触摸区图标（见 [PanelIconView]）。
 * 滚动同步沿用「预览滚动 → 编辑器跳行」单向：同页切换时编辑器 WebView 虽仍在窗口内但不可见，
 * 轮询它的 topLine 只会拿到旧值并把预览拽回顶部（R20 缺陷根因），故不在此做 editor→preview 推送。
 */
class PreviewScreen(
    context: Context,
    assetsDir: File,
    private val onClose: () -> Unit,
    private val onToggleTheme: (Boolean) -> Unit,
    /** R33：预览页内「切换文档」按钮回调；null 表示宿主不支持（外部入口）。 */
    private val onOpenDocs: (() -> Unit)? = null,
    /** R33：预览浮层点选某文档后回传其 id。 */
    private val onSelectDoc: ((String) -> Unit)? = null,
) : LinearLayout(context) {

    private val webView = WebView(context)
    private val host = PreviewHost(context, webView, assetsDir)
    private var bar: LinearLayout? = null
    private var titleView: TextView? = null
    private var dark = false
    private var amoled = false
    private var fontSize = 16
    private var fullScreenReading = false
    private var pdfDark = false
    private var content = ""
    private var title = ""
    private var lastScrollY = -1f

    private val handler = Handler(Looper.getMainLooper())
    private val syncTick = object : Runnable {
        override fun run() {
            host.currentScrollY { y ->
                if (lastScrollY >= 0f && abs(y - lastScrollY) > 6f) {
                    ScrollSync.onPreviewScrolled(y)
                }
                lastScrollY = y
            }
            handler.postDelayed(this, SYNC_INTERVAL_MS)
        }
    }

    init {
        val prefs = context.getSharedPreferences("editor-prefs", Context.MODE_PRIVATE)
        amoled = prefs.getBoolean("amoled", false)
        fontSize = prefs.getInt("readingSize", 16)
        fullScreenReading = prefs.getBoolean("fullRead", false)
        pdfDark = prefs.getBoolean("pdfDark", false)

        orientation = VERTICAL
        ViewCompat.setOnApplyWindowInsetsListener(this) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }

        val barHeight = if (fullScreenReading) 0 else dp(56)
        LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(6), 0, dp(4), 0)
            bar = this
        }.also { addView(it, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, barHeight)) }

        // 与编辑器 #bar border-bottom 1px rgba(128,128,128,0.22) 对齐
        addView(
            View(context).apply { setBackgroundColor(0x38808080.toInt()) },
            LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, if (fullScreenReading) 0 else dp(1)),
        )

        addView(webView, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        host.attach()
        host.onReady = { ScrollSync.pullFromEditor() }
        host.onSwitchDocById = { id -> onSelectDoc?.invoke(id) }
    }

    /** R33：下发文档列表到预览页「切换文档」浮层。 */
    fun setDocs(json: String) = host.setDocs(json)

    /** R33：打开预览页「切换文档」浮层（宿主在打开前应先 [setDocs] 刷新数据）。 */
    fun openDocs() = host.openDocs()

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).roundToInt()

    /** 加载文档并启动同步。content 取编辑器实时正文，保留未落盘的编辑。 */
    fun show(content: String, docTitle: String, isDark: Boolean) {
        this.content = content
        this.title = docTitle
        this.dark = isDark
        // T1：切换文档后清零旧位置，避免 syncTick 拿上一篇的 lastScrollY 误判滚动、
        // 也避免 gsRender 的 keep=window.scrollY 把新文档滚到旧位置（R20 同类缺陷）。
        lastScrollY = -1f
        ScrollSync.detach(host)
        host.scrollTo(0f)
        paintBar()
        paintBackground()
        ScrollSync.attach(host, content)
        host.renderMarkdown(content, dark, fontSize, amoled)
        resumeSync()
    }

    /** 退出预览但保留 WebView 时暂停轮询，避免隐藏状态下空转。 */
    fun pauseSync() {
        handler.removeCallbacks(syncTick)
        ScrollSync.detach(host)
    }

    fun resumeSync() {
        handler.removeCallbacks(syncTick)
        handler.postDelayed(syncTick, SYNC_INTERVAL_MS)
    }

    /** 宿主主题切换后调用：重绘顶栏与背景并重渲染正文。 */
    fun setDark(isDark: Boolean) {
        if (isDark == dark) return
        dark = isDark
        paintBar()
        paintBackground()
        host.renderMarkdown(content, dark, fontSize, amoled)
    }

    private fun paintBackground() {
        setBackgroundColor(
            when {
                dark && amoled -> Color.BLACK
                dark -> 0xFF1F2328.toInt()
                else -> Color.WHITE
            },
        )
    }

    private fun icon(kind: PanelIconView.Kind, onClick: () -> Unit): PanelIconView =
        PanelIconView(context, kind).apply {
            setOnClickListener { onClick() }
            layoutParams = LayoutParams(dp(44), dp(44)).apply { marginStart = dp(2) }
        }

    private fun paintBar() {
        val b = bar ?: return
        val fg = if (dark) 0xFFE6EDF3.toInt() else 0xFF1F2328.toInt()
        b.removeAllViews()

        b.addView(icon(PanelIconView.Kind.BACK) { onClose() }.also { it.tint = fg })

        // R33：预览页内「切换文档」弹出列表。宿主未传回调（外部 PreviewActivity 入口）时不显示。
        if (onOpenDocs != null) {
            b.addView(icon(PanelIconView.Kind.DOCS) { onOpenDocs() }.also { it.tint = fg })
        }

        titleView = TextView(context).apply {
            text = this@PreviewScreen.title.ifBlank { "预览" }
            setTextColor(fg)
            textSize = 15f
            typeface = Typeface.DEFAULT_BOLD
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), 0, dp(6), 0)
        }
        b.addView(titleView, LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))

        b.addView(icon(PanelIconView.Kind.OUTLINE) { host.openOutline() }.also { it.tint = fg })
        b.addView(icon(PanelIconView.Kind.THEME) { onToggleTheme(dark) }.also { it.tint = fg })
        b.addView(icon(PanelIconView.Kind.PDF) {
            val printNow = { PdfExporter(context, webView, title).print() }
            if (pdfDark == dark) {
                printNow()
            } else {
                host.renderMarkdown(content, pdfDark, fontSize, amoled && pdfDark)
                handler.postDelayed({
                    printNow()
                    host.renderMarkdown(content, dark, fontSize, amoled)
                }, 1200)
            }
        }.also { it.tint = fg })
        b.addView(icon(PanelIconView.Kind.CLOSE) { onClose() }.also { it.tint = fg })
    }

    /** 释放渲染进程与同步轮询；宿主销毁或退出预览时调用。 */
    fun release() {
        handler.removeCallbacks(syncTick)
        ScrollSync.detach(host)
        host.release()
    }

    companion object {
        private const val SYNC_INTERVAL_MS = 600L
    }
}
