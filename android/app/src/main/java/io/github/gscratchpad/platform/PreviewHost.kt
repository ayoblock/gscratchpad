package io.github.gscratchpad.platform

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader

object PreviewHtml {
    const val BASE_URL = "https://appassets.androidplatform.net/"

    /**
     * 预览外壳（方案 §5.4）：Markdown 在 WebView 内由 markdown-it 渲染，
     * KaTeX/Mermaid 按需注入；资源全部经 AssetLoader 从本地读取。
     */
    fun buildShell(
        dark: Boolean,
        needsMath: Boolean,
        needsMermaid: Boolean,
        fontSize: Int = 16,
        amoled: Boolean = false,
    ): String {
        val background = if (dark) (if (amoled) "#000000" else "#1f2328") else "#ffffff"
        val foreground = if (dark) "#e6edf3" else "#1f2328"
        val border = if (dark) "#30363d" else "#d0d7de"
        val accent = if (dark) "#58a6ff" else "#0969da"
        val sheetBg = if (dark) "#262b31" else "#ffffff"
        val math = if (needsMath) {
            """<link rel="stylesheet" href="/static/vendor/js/katex/katex.min.css">
               <script src="/static/vendor/js/katex/katex.min.js"></script>"""
        } else ""
        val mermaid = if (needsMermaid) {
            """<script src="/static/vendor/js/mermaid.min.js"></script>"""
        } else ""

        return """
<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html,body { margin:0; padding:12px 16px; background:$background; color:$foreground;
    font: ${fontSize}px/1.65 -apple-system, "Noto Sans CJK SC", "Source Han Sans", sans-serif;
    word-wrap: break-word; }
  img { max-width:100%; }
  /* R39：Copy 按钮锚定在不滚动的 wrapper 上；pre 自己 overflow:auto 横向滚动时按钮不跟随。
     旧实现把 absolute 按钮放进 pre（滚动容器），按钮处在滚动坐标系内，横滚时跑到代码行中间。 */
  .gs-codewrap { position:relative; margin:1em 0; }
  pre { position:static; margin:0; background:${if (dark) (if (amoled) "#0a0a0a" else "#161b22") else "#f6f8fa"}; padding:12px; overflow:auto; border-radius:6px; }
  code { font-family: ui-monospace, "JetBrains Mono", monospace; font-size: 0.92em; }
  /* T2 代码块 Copy 按钮：右上角、小号、跟随主题，不遮挡首行代码（pre 右侧留白） */
  .gs-copy { position:absolute; top:6px; right:6px; z-index:2;
    font: 11px/1 -apple-system, sans-serif; padding:4px 8px; border-radius:5px; cursor:pointer;
    border:1px solid $border; color:$foreground; background:${if (dark) "#262b31" else "#eef1f4"};
    opacity:0.75; }
  .gs-copy:active { opacity:1; }
  pre { padding-right:64px; }
  table { border-collapse: collapse; }
  th, td { border:1px solid $border; padding:6px 10px; }
  h1,h2,h3,h4,h5,h6 { line-height:1.25; margin:1.2em 0 0.6em; }
  a { color:$accent; }
  .mermaid { text-align:center; }
  blockquote { margin:0; padding-left:12px; border-left:3px solid $border; color:${if (dark) "#9da7b3" else "#57606a"}; }

  /* 大纲 / 切换文档浮层（R24 / R33）：全屏遮罩 + 卡片，点遮罩空白即关闭 */
  #gs-outline, #gs-docs { position:fixed; top:0; left:0; right:0; bottom:0; z-index:30;
    display:flex; align-items:flex-start; justify-content:center;
    background: rgba(0,0,0,0.45); }
  #gs-outline[hidden], #gs-docs[hidden] { display:none; }
  .gs-sheet { margin-top:8vh; width:min(92vw,560px); max-height:74vh; display:flex; flex-direction:column;
    gap:8px; padding:12px; border-radius:14px; background:$sheetBg; color:$foreground;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
  .gs-head { display:flex; align-items:baseline; gap:8px; font-size:15px; font-weight:600; }
  .gs-count { font-size:12px; font-weight:400; opacity:0.6; margin-left:auto; }
  .gs-outline-list { overflow-y:auto; flex:1 1 auto; -webkit-overflow-scrolling:touch; }
  .gs-outline-item { display:block; width:100%; text-align:left; padding:10px 8px; border:0;
    border-bottom:1px solid $border; background:transparent; color:inherit; font-size:14px; }
  .gs-outline-item:active { background: rgba(128,128,128,0.18); }
  .gs-empty { padding:14px 8px; font-size:13px; opacity:0.6; }
  .gs-close { align-self:flex-end; font-size:14px; padding:8px 16px; border-radius:8px;
    border:1px solid $border; background:rgba(128,128,128,0.12); color:inherit; }
</style>
$math
$mermaid
</head>
<body>
<div id="content"></div>
<div id="gs-outline" hidden>
  <div class="gs-sheet">
    <div class="gs-head"><span>文档大纲</span><span id="gs-outline-count" class="gs-count"></span></div>
    <div id="gs-outline-list" class="gs-outline-list"></div>
    <button id="gs-outline-close" class="gs-close">关闭</button>
  </div>
</div>
<div id="gs-docs" hidden>
  <div class="gs-sheet">
    <div class="gs-head"><span>切换文档</span><span id="gs-docs-count" class="gs-count"></span></div>
    <div id="gs-docs-list" class="gs-outline-list"></div>
    <button id="gs-docs-close" class="gs-close">关闭</button>
  </div>
</div>
<script src="/static/vendor/js/markdown-it.min.js"></script>
<script>
(function(){
  var md = window.markdownit ? window.markdownit({html:false, linkify:true, breaks:false}) : null;

  function postReady(){
    try { document.getElementById('content').setAttribute('data-ready','1'); } catch(e){}
    try { window.gscratchpad && window.gscratchpad.postMessage('ready'); } catch(e){}
  }

  function renderMath(){
    if (!window.katex) return;
    var walker = document.createTreeWalker(document.getElementById('content'), NodeFilter.SHOW_TEXT, {
      acceptNode: function(n){
        var p = n.parentNode;
        while (p) {
          if (p.nodeName === 'CODE' || p.nodeName === 'PRE') return NodeFilter.FILTER_REJECT;
          p = p.parentNode;
        }
        return n.nodeValue.indexOf('$') >= 0 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function(n){
      var s = n.nodeValue;
      var frag = document.createDocumentFragment();
      var re = /\$\$([^$]+)\$\$|\$([^$\n]+)\$|\$/g;
      var last = 0, m;
      while ((m = re.exec(s)) !== null) {
        if (m[0] === '$') continue;
        frag.appendChild(document.createTextNode(s.slice(last, m.index)));
        var span = document.createElement('span');
        try {
          span.innerHTML = katex.renderToString(m[1] || m[2], {throwOnError:false, displayMode: !!m[1]});
        } catch(e) { span.textContent = m[0]; }
        frag.appendChild(span);
        last = m.index + m[0].length;
      }
      if (last === 0) return;
      frag.appendChild(document.createTextNode(s.slice(last)));
      n.parentNode.replaceChild(frag, n);
    });
  }

  function renderMermaid(){
    if (!window.mermaid) return;
    mermaid.initialize({startOnLoad:false, theme:'${if (dark) "dark" else "default"}', securityLevel:'strict'});
    document.querySelectorAll('code.language-mermaid').forEach(function(code){
      var pre = code.closest('pre');
      var box = document.createElement('div');
      box.className = 'mermaid';
      box.textContent = code.textContent;
      if (pre) pre.replaceWith(box);
    });
    mermaid.run().catch(function(){});
  }

  /** T2：给围栏代码块加 Copy 按钮。mermaid 已被 renderMermaid 换成 div，此处仅命中真实 pre>code。
   *  幂等：content.innerHTML 每次全量重建，旧按钮随之销毁，不会叠加。 */
  function addCopyButtons(){
    var pres = document.querySelectorAll('#content pre');
    for (var i=0;i<pres.length;i++){
      var pre = pres[i];
      var code = pre.querySelector('code');
      if (!code) continue;
      var btn = document.createElement('button');
      btn.className = 'gs-copy';
      btn.type = 'button';
      btn.textContent = '复制';
      btn.setAttribute('aria-label','复制代码');
      btn.addEventListener('click', function(ev){
        ev.preventDefault();
        try {
          window.gscratchpad && window.gscratchpad.copyText(code.textContent || '');
          var b = ev.currentTarget;
          b.textContent = '已复制';
          setTimeout(function(){ b.textContent = '复制'; }, 1200);
        } catch(e){}
      });
      // R39：pre 是 overflow:auto 滚动容器，按钮若挂在 pre 内会随代码横滚跑进正文。
      // 用不滚动的 wrapper 包住 pre，按钮挂 wrapper 上 → 永远固定在代码框右上角。
      var wrap = document.createElement('div');
      wrap.className = 'gs-codewrap';
      if (pre.parentNode) pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      wrap.appendChild(btn);
    }
  }

  window.gsRender = function(source){
    var content = document.getElementById('content');
    // 重渲染（主题切换 / 正文刷新）保留阅读位置：无条件回顶是 R20 报的「预览总被刷到顶部」
    var keep = window.scrollY || 0;
    content.innerHTML = md ? md.render(source) : '';
    // 本地图片：正文写相对 `assets/<docId>/<file>`，页内统一改成绝对 /assets/...（映射到 files/assets）
    var imgs = content.querySelectorAll('img');
    for (var i=0;i<imgs.length;i++){
      var s = imgs[i].getAttribute('src') || '';
      if (/^assets\//.test(s)) imgs[i].setAttribute('src', '/' + s);
      // 净化：拒绝任何非 http(s)/相对/数据的图片协议（防 javascript:/file: 注入）
      var finalSrc = imgs[i].getAttribute('src') || '';
      if (finalSrc && !/^(https?:|\/|data:image\/|assets\/)/i.test(finalSrc)) imgs[i].removeAttribute('src');
    }
    var hs = content.querySelectorAll('h1,h2,h3,h4,h5,h6');
    hs.forEach(function(h, i){ h.id = 'h' + i; });
    renderMath();
    renderMermaid();
    addCopyButtons();
    window.scrollTo(0, keep);
    postReady();
  };

  window.gsScrollToHeading = function(i){
    var h = document.getElementById('h' + i);
    if (h) h.scrollIntoView({block:'start'});
  };

  /** 视口顶端命中的标题下标（最后一个 top<=8px 的标题）；无标题返回 -1。 */
  window.gsTopHeadingIndex = function(){
    var hs = document.querySelectorAll('#content h1,#content h2,#content h3,#content h4,#content h5,#content h6');
    var best = -1;
    for (var i=0;i<hs.length;i++){
      if (hs[i].getBoundingClientRect().top <= 8) best = i; else break;
    }
    return best;
  };

  window.gsScrollY = function(){ return window.scrollY; };
  window.gsScrollTo = function(y){ window.scrollTo(0, y); };

  /** 大纲：扫渲染结果里的标题（id 由 gsRender 统一赋为 h+i），点击跳转到对应标题。 */
  function gsOutlineItems(){
    var hs = document.querySelectorAll('#content h1,#content h2,#content h3,#content h4,#content h5,#content h6');
    var items = [];
    for (var i = 0; i < hs.length; i++) {
      items.push({ i: i, level: Number(hs[i].tagName.slice(1)), text: (hs[i].textContent || '').trim().slice(0, 80) });
    }
    return items;
  }

  window.gsOpenOutline = function(){
    var el = document.getElementById('gs-outline');
    var list = document.getElementById('gs-outline-list');
    var count = document.getElementById('gs-outline-count');
    var items = gsOutlineItems();
    list.innerHTML = '';
    count.textContent = items.length ? items.length + ' 个标题' : '';
    if (!items.length) {
      var empty = document.createElement('div');
      empty.className = 'gs-empty';
      empty.textContent = '本文档没有标题';
      list.appendChild(empty);
    }
    items.forEach(function(it){
      var btn = document.createElement('button');
      btn.className = 'gs-outline-item';
      btn.style.paddingLeft = (12 + (it.level - 1) * 12) + 'px';
      btn.textContent = it.text || '(空标题)';
      btn.addEventListener('click', function(){
        window.gsCloseOutline();
        window.gsScrollToHeading(it.i);
      });
      list.appendChild(btn);
    });
    el.hidden = false;
  };

  window.gsCloseOutline = function(){
    var el = document.getElementById('gs-outline');
    if (el) el.hidden = true;
  };

  /* R33：切换文档浮层。列表由 Kotlin 通过 window.gsSetDocs(json) 注入。 */
  var gsDocsCache = [];
  window.gsSetDocs = function(json){
    try { gsDocsCache = JSON.parse(json || '[]'); } catch (e) { gsDocsCache = []; }
  };
  window.gsOpenDocs = function(){
    if (window.gsCloseOutline) window.gsCloseOutline();
    var el = document.getElementById('gs-docs');
    var list = document.getElementById('gs-docs-list');
    var count = document.getElementById('gs-docs-count');
    list.innerHTML = '';
    count.textContent = gsDocsCache.length ? gsDocsCache.length + ' 个文档' : '';
    if (!gsDocsCache.length) {
      var empty = document.createElement('div');
      empty.className = 'gs-empty';
      empty.textContent = '当前没有打开的文档';
      list.appendChild(empty);
    }
    gsDocsCache.forEach(function(d){
      var btn = document.createElement('button');
      btn.className = 'gs-outline-item';
      btn.textContent = d.title || '(未命名)';
      if (d.active) { btn.style.fontWeight = '600'; btn.setAttribute('aria-current','true'); }
      btn.addEventListener('click', function(){
        window.gsCloseDocs();
        if (window.gscratchpad && window.gscratchpad.switchDoc) window.gscratchpad.switchDoc(d.id);
      });
      list.appendChild(btn);
    });
    el.hidden = false;
  };
  window.gsCloseDocs = function(){
    var el = document.getElementById('gs-docs');
    if (el) el.hidden = true;
  };
  document.getElementById('gs-docs-close').addEventListener('click', function(){ window.gsCloseDocs(); });

  document.getElementById('gs-outline-close').addEventListener('click', function(){ window.gsCloseOutline(); });

  // 点遮罩空白关闭：白名单用 .gs-sheet（卡片本体），不能用 #gs-outline（全屏遮罩本身），
  // 否则点空白会被判成「点在面板内」而永不关闭（与编辑器 R24 同一根因）。
  document.addEventListener('click', function(ev){
    var t = ev.target;
    if (!t || typeof t.closest !== 'function') return;
    if (t.closest('.gs-sheet')) return;
    var ol = document.getElementById('gs-outline');
    if (ol && !ol.hidden) { window.gsCloseOutline(); return; }
    var dl = document.getElementById('gs-docs');
    if (dl && !dl.hidden) { window.gsCloseDocs(); return; }
  });

  /**
   * P2-7 金标准语料指纹：正文纯文本（空白折叠）+ 语义标签计数。
   * 与 scripts/golden_fingerprint.py 的 fingerprint() 规则逐字对应：
   * 只统计语义标签，刻意排除 span/div/br 这类引擎实现差异。
   */
  window.gsFingerprint = function(){
    var content = document.getElementById('content');
    var txt = (content.textContent || '').replace(/\s+/g, ' ').trim();
    var canon = ['h1','h2','h3','h4','h5','h6','p','li','ul','ol','pre','blockquote',
                 'table','tr','th','td','strong','em','code','a','img','hr'];
    var counts = {};
    for (var i=0;i<canon.length;i++){
      var n = content.querySelectorAll(canon[i]).length;
      if (n) counts[canon[i]] = n;
    }
    return JSON.stringify({text: txt, counts: counts});
  };

  // 空壳就绪：即便没有正文也通知一次，便于原生判定加载完成
  if (document.readyState === 'complete') postReady();
  else window.addEventListener('load', postReady);
})();
</script>
</body></html>
""".trimIndent()
    }
}

/**
 * WebView 预览宿主（方案 §5.4）。
 *
 * - 资源经 [WebViewAssetLoader] 映射到 `https://appassets.androidplatform.net/`；
 * - 正文由在页面内运行的 markdown-it 渲染，公式/图表按需加载；
 * - 单活跃预览：切走标签即 [release]，释放渲染进程；
 * - 外链走系统浏览器。
 */
class PreviewHost(
    private val context: Context,
    private val webView: WebView,
    private val assetsDir: java.io.File,
) {
    private val assetLoader: WebViewAssetLoader = WebViewAssetLoader.Builder()
        // assets/ 根：URL /static/vendor/js/... → assets/vendor/js/...
        .addPathHandler("/static/", WebViewAssetLoader.AssetsPathHandler(context))
        .addPathHandler("/assets/", WebViewAssetLoader.InternalStoragePathHandler(context, assetsDir))
        .build()

    var onReady: () -> Unit = {}

    /** R33：预览页「切换文档」浮层点选某文档后回传其 id。 */
    var onSwitchDocById: (String) -> Unit = {}

    /** 滚动回调（供 P2-2 双向同步；由调用方轮询 [currentScrollY] 后触发）。 */
    var scrollListener: ((Float) -> Unit)? = null

    private var shellKey: String? = null
    private var pending: String? = null
    private var pendingDocs: String? = null
    private var pageReady = false

    @SuppressLint("SetJavaScriptEnabled")
    fun attach() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            loadWithOverviewMode = true
            useWideViewPort = true
        }
        webView.setBackgroundColor(Color.WHITE)
        webView.addJavascriptInterface(object {
            @JavascriptInterface
            fun postMessage(message: String) {
                if (message == "ready") {
                    pageReady = true
                    pending?.let { apply(it) }
                    pendingDocs?.let { setDocs(it) }
                    webView.post { onReady() }
                }
            }

            /** T2：代码块 Copy 按钮写入系统剪贴板；反馈由 JS 端就地改按钮文字，不依赖 Toast。 */
            @JavascriptInterface
            fun copyText(text: String) {
                val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
                cm.setPrimaryClip(ClipData.newPlainText("gscratchpad-code", text))
            }

            /** R33：预览「切换文档」浮层点选文档 id，投递到 UI 线程。 */
            @JavascriptInterface
            fun switchDoc(id: String) {
                webView.post { onSwitchDocById(id) }
            }
        }, "gscratchpad")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest,
            ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)

            override fun onPageFinished(view: WebView, url: String?) {
                pageReady = true
                pending?.let { apply(it) }
                pendingDocs?.let { setDocs(it) }
            }

            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                val url = request.url
                if (url.host == "appassets.androidplatform.net") return false
                runCatching {
                    context.startActivity(
                        Intent(Intent.ACTION_VIEW, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                }
                return true
            }
        }
    }

    private var lastMarkdown: String? = null

    fun renderMarkdown(markdown: String, dark: Boolean = false, fontSize: Int = 16, amoled: Boolean = false) {
        // 预览不显示 frontmatter 与 HTML 注释；清洗只作用于渲染副本，编辑器原文与
        // ScrollSync 的标题行号映射仍用原文（标题行号必须对应编辑器里的真实位置）。
        val renderSource = MarkdownSanitizer.clean(markdown)
        val needsMath = MarkdownFeatures.hasMath(renderSource)
        val needsMermaid = MarkdownFeatures.hasMermaid(renderSource)
        val key = "$dark|$amoled|$needsMath|$needsMermaid|$fontSize"
        // 幂等：内容与外壳都没变时不重复渲染（避免高频调用把预览当渲染队列刷）
        if (renderSource == lastMarkdown && key == shellKey) return
        lastMarkdown = renderSource
        android.util.Log.d("Gscratchpad", "preview load math=$needsMath mermaid=$needsMermaid chars=${renderSource.length}")
        if (key != shellKey) {
            shellKey = key
            pageReady = false
            pending = renderSource
            webView.loadDataWithBaseURL(
                PreviewHtml.BASE_URL,
                PreviewHtml.buildShell(dark, needsMath, needsMermaid, fontSize, amoled),
                "text/html",
                "utf-8",
                null,
            )
        } else {
            apply(renderSource)
        }
    }

    private fun apply(markdown: String) {
        if (!pageReady) return
        pending = null
        val quoted = org.json.JSONObject.quote(markdown)
        // JavaBridge 线程不能直接调 WebView 方法，统一投递到 UI 线程
        webView.post { runCatching { webView.evaluateJavascript("window.gsRender($quoted)", null) } }
    }

    fun scrollToHeading(index: Int) {
        webView.evaluateJavascript("window.gsScrollToHeading && window.gsScrollToHeading($index)", null)
    }

    /** 打开预览页内大纲浮层（R24）：标题来自渲染结果，点条目跳转 + 点遮罩空白关闭。 */
    fun openOutline() {
        webView.post {
            runCatching { webView.evaluateJavascript("window.gsOpenOutline && window.gsOpenOutline()", null) }
        }
    }

    /** R33：下发文档列表到预览页「切换文档」浮层。json 为 [{id,title,active}]。 */
    fun setDocs(json: String) {
        pendingDocs = json
        if (!pageReady) return
        webView.post {
            runCatching {
                webView.evaluateJavascript("window.gsSetDocs && window.gsSetDocs(${org.json.JSONObject.quote(json)})", null)
            }
        }
    }

    /** R33：打开预览页「切换文档」浮层。 */
    fun openDocs() {
        webView.post {
            runCatching { webView.evaluateJavascript("window.gsOpenDocs && window.gsOpenDocs()", null) }
        }
    }

    fun scrollTo(y: Float) {
        webView.evaluateJavascript("window.gsScrollTo && window.gsScrollTo($y)", null)
    }

    fun currentScrollY(onResult: (Float) -> Unit) {
        webView.evaluateJavascript("window.gsScrollY ? window.gsScrollY() : 0") { value ->
            onResult(value.toFloatOrNull() ?: 0f)
        }
    }

    /** 视口顶端命中的标题下标（P2-2 反方向：预览滚动 → 编辑器跳行）。 */    fun topHeadingIndex(onResult: (Int) -> Unit) {
        webView.evaluateJavascript("window.gsTopHeadingIndex ? window.gsTopHeadingIndex() : -1") { value ->
            onResult(value?.toIntOrNull() ?: -1)
        }
    }

    /** 通用 JS 取值（金标准语料自检用；回调在 UI 线程）。 */
    fun evaluate(script: String, onResult: (String?) -> Unit) {
        webView.post { runCatching { webView.evaluateJavascript(script, onResult) } }
    }

    /** 释放渲染进程（方案 §5.4：单活跃预览）。 */
    fun release() {
        runCatching {
            webView.loadUrl("about:blank")
            webView.removeAllViews()
            webView.destroy()
        }
    }
}

/** 供外部打开 URI 时的 MIME 过滤。 */
object MimeFilters {
    val TEXT = arrayOf("text/plain", "text/markdown")

    fun mimeFor(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "md", "markdown" -> "text/markdown"
        "html", "htm" -> "text/html"
        else -> "text/plain"
    }

    fun isTextUri(uri: Uri): Boolean = true
}
