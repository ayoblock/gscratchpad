package io.github.gscratchpad.platform

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.util.AttributeSet
import android.view.ActionMode
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject

/**
 * 保留 WebView 原生长按选词与拖手柄，只隐藏系统 ActionMode 菜单（复制/全选等），
 * 动作统一由页内选区浮栏承载，避免「系统菜单 + 浮栏」双弹。
 *
 * 关键：不能 menu.clear()——WebView 发现菜单为空会立即 finish ActionMode 并清空 DOM 选区，
 * 导致浮栏永远来不及显示（R53 实测根因）。保留条目、仅设不可见即可。
 */
private class SelectionMenuCallback(private val delegate: ActionMode.Callback) : ActionMode.Callback {
    private fun hideItems(menu: Menu) {
        for (i in 0 until menu.size()) menu.getItem(i).isVisible = false
    }

    override fun onCreateActionMode(mode: ActionMode, menu: Menu): Boolean {
        if (!delegate.onCreateActionMode(mode, menu)) return false
        hideItems(menu)
        return true
    }

    override fun onPrepareActionMode(mode: ActionMode, menu: Menu): Boolean {
        delegate.onPrepareActionMode(mode, menu)
        hideItems(menu)
        return true
    }

    override fun onActionItemClicked(mode: ActionMode, item: MenuItem): Boolean =
        delegate.onActionItemClicked(mode, item)

    override fun onDestroyActionMode(mode: ActionMode) {
        delegate.onDestroyActionMode(mode)
    }
}

/** R53：编辑器专用 WebView，接管 ActionMode 回调以隐藏系统菜单但保留原生手柄。 */
class EditorWebView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : WebView(context, attrs) {
    override fun startActionMode(callback: ActionMode.Callback?): ActionMode? {
        return super.startActionMode(callback?.let(::SelectionMenuCallback))
    }

    override fun startActionMode(callback: ActionMode.Callback?, type: Int): ActionMode? {
        return super.startActionMode(callback?.let(::SelectionMenuCallback), type)
    }

    override fun startActionModeForChild(
        originalView: View?, callback: ActionMode.Callback?,
    ): ActionMode? {
        return super.startActionModeForChild(originalView, callback?.let(::SelectionMenuCallback))
    }

    override fun startActionModeForChild(
        originalView: View?, callback: ActionMode.Callback?, type: Int,
    ): ActionMode? {
        return super.startActionModeForChild(originalView, callback?.let(::SelectionMenuCallback), type)
    }
}

/**
 * 编辑器宿主（路线 D）：WebView 内跑 CodeMirror 6，Kotlin 侧只做文档装载与事件编排。
 *
 * 正文由 CodeMirror 的 rope 维护，1 MB 文档不做整段 Compose 布局；折叠、查找、撤销在 JS 侧完成，
 * Kotlin 接收防抖后的全文回调用于既有 SaveQueue 落盘。
 */
class EditorHost(private val webView: WebView) {

    class Metrics(val openMs: Long?, val foldMs: Long?)

    var onReady: () -> Unit = {}
    var onDocChanged: (String) -> Unit = {}
    var onMetrics: (Metrics) -> Unit = {}
    var onJsShortcut: (String) -> Unit = {}
    var onAction: (String) -> Unit = {}
    /** 「切换文档」浮层点选某文档后回传其 id（R33）。 */
    var onSwitchDocById: (String) -> Unit = {}
    /** 页内设置面板改动后回传（JSON：fontSize / lineHeight / wrap），宿主负责持久化。 */
    var onPrefsChanged: (String) -> Unit = {}
    /** R52：选区变化回传（JSON：from/to/empty/text/line/column）。 */
    var onSelectionChanged: (String) -> Unit = {}

    private val assetLoader: WebViewAssetLoader = WebViewAssetLoader.Builder()
        .addPathHandler("/static/", WebViewAssetLoader.AssetsPathHandler(webView.context))
        .build()

    private var pageReady = false
    private var pendingDoc: String? = null
    private var pendingTheme: Boolean? = null
    private var pendingTitle: String? = null
    private var pendingDocs: String? = null
    private var pendingRead = false
    private var suppressChanges = false
    private var lastOpenMs: Long? = null
    private var attachedAt: Long = 0

    @SuppressLint("SetJavaScriptEnabled")
    fun attach() {
        attachedAt = android.os.SystemClock.elapsedRealtime()
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            loadWithOverviewMode = true
            useWideViewPort = true
            textZoom = 100
        }
        webView.setBackgroundColor(Color.WHITE)
        webView.isVerticalScrollBarEnabled = true
        // panel 窗口有自己的焦点，Activity.onBackPressed 收不到返回键，这里转发给业务层
        webView.setOnKeyListener { _, keyCode, event ->
            if (keyCode == android.view.KeyEvent.KEYCODE_BACK &&
                event.action == android.view.KeyEvent.ACTION_UP
            ) {
                webView.post { this@EditorHost.onAction("back") }
                true
            } else {
                false
            }
        }
        webView.addJavascriptInterface(
            object {
                @JavascriptInterface
                fun onReady() {
                    val elapsed = android.os.SystemClock.elapsedRealtime() - attachedAt
                    android.util.Log.d("Gscratchpad", "editor page ready in ${elapsed}ms")
                    webView.post {
                        pageReady = true
                        pendingTheme?.let { setTheme(it) }
                        pendingTitle?.let { setTitle(it) }
                        pendingDocs?.let { setDocs(it) }
                        pendingDoc?.let { setDocument(it) }
                        this@EditorHost.onReady()
                    }
                }

                @JavascriptInterface
                fun onChange(text: String) {
                    if (suppressChanges) return
                    webView.post { onDocChanged(text) }
                }

                @JavascriptInterface
                fun onMetric(kind: String, value: String) {
                    webView.post {
                        when (kind) {
                            "open" -> {
                                lastOpenMs = value.toLongOrNull()
                                android.util.Log.d("Gscratchpad", "editor ready in ${lastOpenMs}ms")
                                onMetrics(Metrics(lastOpenMs, null))
                            }
                            "fold" -> {
                                android.util.Log.d("Gscratchpad", "editor fold ${value}ms")
                                onMetrics(Metrics(lastOpenMs, value.toLongOrNull()))
                            }
                            else -> android.util.Log.d("Gscratchpad", "editor metric $kind=$value")
                        }
                    }
                }

                @JavascriptInterface
                fun onShortcut(name: String) {
                    webView.post { onJsShortcut(name) }
                }

                @JavascriptInterface
                fun onAction(action: String) {
                    android.util.Log.d("Gscratchpad", "editor action $action")
                    webView.post { this@EditorHost.onAction(action) }
                }

                @JavascriptInterface
                fun switchDoc(id: String) {
                    webView.post { this@EditorHost.onSwitchDocById(id) }
                }

                @JavascriptInterface
                fun onPrefsChanged(json: String) {
                    // 必须显式限定外部类：匿名对象内同名调用会解析成自调用（递归 post）
                    webView.post { this@EditorHost.onPrefsChanged(json) }
                }

                @JavascriptInterface
                fun onSelection(json: String) {
                    webView.post { this@EditorHost.onSelectionChanged(json) }
                }

                @JavascriptInterface
                fun copy(text: String) {
                    webView.post {
                        val cm = webView.context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                        cm?.setPrimaryClip(ClipData.newPlainText("gscratchpad", text))
                    }
                }
            },
            "AndroidEditor",
        )
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest,
            ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)

            override fun onPageFinished(view: WebView, url: String?) {
                if (!pageReady) android.util.Log.d("Gscratchpad", "editor page finished ${url.orEmpty()}")
            }
        }
        webView.webChromeClient = object : android.webkit.WebChromeClient() {
            override fun onConsoleMessage(m: android.webkit.ConsoleMessage): Boolean {
                android.util.Log.d("Gscratchpad", "editor console: ${m.message()}")
                return true
            }
        }
        // 加时间戳绕过 WebView 资产缓存：每次进程都取最新 index.html（否则旧 bundle 会静默命中）
        webView.loadUrl("https://appassets.androidplatform.net/static/editor/index.html?t=$attachedAt")
    }

    fun setDocument(text: String) {
        if (!pageReady) {
            pendingDoc = text
            return
        }
        pendingDoc = null
        suppressChanges = true
        val quoted = JSONObject.quote(text)
        webView.evaluateJavascript("window.NativeEditor.setDoc($quoted)") { _ ->
            webView.postDelayed({ suppressChanges = false }, 400)
        }
    }

    /** 面包屑标题：页内 `#doc-title` 显示当前文档名。 */
    fun setTitle(title: String) {
        pendingTitle = title
        if (!pageReady) return
        pendingTitle = null
        webView.evaluateJavascript("window.NativeEditor.setDocTitle(${JSONObject.quote(title)})", null)
    }

    fun setTheme(dark: Boolean) {
        if (!pageReady) {
            pendingTheme = dark
            return
        }
        pendingTheme = null
        webView.setBackgroundColor(if (dark) 0xFF1F2328.toInt() else Color.WHITE)
        webView.evaluateJavascript("window.NativeEditor.setTheme($dark)", null)
    }

    fun insert(text: String) {
        webView.evaluateJavascript("window.NativeEditor.insert(${JSONObject.quote(text)})", null)
    }

    /** R52：从系统剪贴板读文本，再复用 CM 当前选区插入（粘贴链路不依赖 JS 权限）。 */
    fun paste() {
        val cm = webView.context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
        val clip = cm.primaryClip ?: return
        if (clip.itemCount == 0) return
        val item = clip.getItemAt(0)
        val text = item.text?.toString() ?: item.coerceToText(webView.context).toString()
        if (text.isNotEmpty()) insert(text)
    }

    fun copySelection() {
        webView.evaluateJavascript("window.NativeEditor.copySelection()", null)
    }

    fun cutSelection() {
        webView.evaluateJavascript("window.NativeEditor.cutSelection()", null)
    }

    fun selectAll() {
        webView.evaluateJavascript("window.NativeEditor.selectAll()", null)
    }

    fun undo() {
        webView.evaluateJavascript("window.NativeEditor.undo()", null)
    }

    fun redo() {
        webView.evaluateJavascript("window.NativeEditor.redo()", null)
    }

    fun selfCheckEdit() {
        webView.evaluateJavascript("window.NativeEditor.selfCheckEdit()", null)
    }

    /** 诊断钩子：持续注入中文，验证中文渲染/防抖/落盘链路（替代无法自动化的 IME 组合态）。 */
    fun soakChinese(seconds: Int) {
        webView.evaluateJavascript("window.NativeEditor.soakChinese($seconds)", null)
    }

    fun foldAtCursor() {
        webView.evaluateJavascript("window.NativeEditor.foldAtCursor()", null)
    }

    fun focus() {
        webView.evaluateJavascript("window.NativeEditor.focus()", null)
    }

    fun scrollToLine(line: Int) {
        webView.evaluateJavascript("window.NativeEditor.scrollToLine($line)", null)
    }

    /** 大纲：读全文标题行（JSON 数组），回调在 UI 线程。 */
    fun outline(onResult: (String) -> Unit) {
        webView.evaluateJavascript("window.NativeEditor.outline()") { value ->
            webView.post { onResult(value) }
        }
    }

    /** 视口顶端所在行（预览滚动对齐）。 */
    fun topLine(onResult: (Int) -> Unit) {
        webView.evaluateJavascript("window.NativeEditor.topLine()") { value ->
            webView.post { onResult(value?.toIntOrNull() ?: 1) }
        }
    }

    /** 阅读偏好（字号/行高/折行）热替换。 */
    fun setPrefs(fontSize: Int, lineHeight: Float, wrap: Boolean, fontFamily: String = "sans") {
        val json = "{\"fontSize\":$fontSize,\"lineHeight\":$lineHeight,\"wrap\":$wrap," +
            "\"fontFamily\":\"$fontFamily\"}"
        webView.evaluateJavascript("window.NativeEditor.setPrefsFromHost(${JSONObject.quote(json)})", null)
    }

    /** 把动作表下发到页内命令面板（Kotlin 侧 [EditorActions] 是唯一真源）。 */
    fun pushActions() {
        val arr = org.json.JSONArray()
        EditorActions.all.forEach { action ->
            arr.put(
                JSONObject()
                    .put("id", action.id)
                    .put("label", action.label)
                    .put("keywords", action.keywords)
                    .put("category", action.category),
            )
        }
        webView.evaluateJavascript("window.NativeEditor.setActions(${JSONObject.quote(arr.toString())})", null)
    }

    fun openPalette() {
        webView.evaluateJavascript("window.NativeEditor.openPalette()", null)
    }

    fun openOutline() {
        webView.evaluateJavascript("window.NativeEditor.openOutline()", null)
    }

    /** 下发文档列表到页内「切换文档」浮层。json 为 [{id,title,active}]。 */
    fun setDocs(json: String) {
        pendingDocs = json
        if (!pageReady) return
        webView.evaluateJavascript("window.NativeEditor.setDocs(${JSONObject.quote(json)})", null)
    }

    fun openDocs() {
        webView.evaluateJavascript("window.NativeEditor.openDocs()", null)
    }

    fun openSettings() {
        webView.evaluateJavascript("window.NativeEditor.openSettings()", null)
    }

    /** Q2：页内快捷键面板（物理键盘一等交互的可见入口）。 */
    fun openHelp() {
        webView.evaluateJavascript("window.NativeEditor.openHelp()", null)
    }

    /** 打开页内查找条（路线 C 的 Compose 查找栏已删，Ctrl/Cmd+F 走这里）。 */
    fun openFind() {
        webView.evaluateJavascript("window.NativeEditor.openFind()", null)
    }

    fun closeOverlays() {
        webView.evaluateJavascript("window.NativeEditor.closeOverlays()", null)
    }

    // ------------------------------------------------------------------ 折叠与动作

    fun foldAll() {
        webView.evaluateJavascript("window.NativeEditor.foldAll()", null)
    }

    fun unfoldAll() {
        webView.evaluateJavascript("window.NativeEditor.unfoldAll()", null)
    }

    /** 宿主退出时释放 WebView：面板窗口已摘掉，这里只销毁渲染资源。 */
    fun release() {
        webView.stopLoading()
        webView.loadUrl("about:blank")
        webView.destroy()
    }
}

