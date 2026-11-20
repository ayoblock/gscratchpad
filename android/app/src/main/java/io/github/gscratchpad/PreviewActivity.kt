package io.github.gscratchpad

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import androidx.core.graphics.toColorInt
import androidx.lifecycle.lifecycleScope
import io.github.gscratchpad.platform.PreviewScreen
import kotlinx.coroutines.launch

/**
 * 全屏预览（方案 §5.4：「单活跃预览」）的独立 Activity 宿主。
 *
 * 编辑器内的预览已改为同页切换（见 MainActivity 的 enterPreview），本类保留用于
 * 「从外部以 ACTION_VIEW 直接打开预览」等需要独立任务栈的入口，以及兼容既有 intent。
 * 顶栏、渲染、滚动同步统一在 [PreviewScreen]，与编辑器页风格一致。
 */
class PreviewActivity : androidx.activity.ComponentActivity() {

    private val container: AppContainer by lazy { (application as GscratchpadApp).container }
    private var screen: PreviewScreen? = null
    private var dark = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dark = intent.getBooleanExtra(EXTRA_DARK, false)
        val docId = intent.getStringExtra(EXTRA_DOC_ID)
        if (docId == null) {
            finish()
            return
        }
        screen = PreviewScreen(this, container.paths.assets, onClose = { finish() }, onToggleTheme = { toggleTheme() })
            .also { setContentView(it) }
        applySystemBars(dark)
        lifecycleScope.launch {
            container.bootstrap()
            val doc = container.repository.get(docId)
            screen?.show(doc?.content ?: "", intent.getStringExtra(EXTRA_TITLE).orEmpty(), dark)
        }
    }

    private fun toggleTheme() {
        dark = !dark
        applySystemBars(dark)
        screen?.setDark(dark)
    }

    /** 预览页主题切换时同步系统栏（夜间模式延展到通知栏，R20）。 */
    private fun applySystemBars(isDark: Boolean) {
        val bars = androidx.core.view.WindowCompat.getInsetsController(window, window.decorView)
        bars.isAppearanceLightStatusBars = !isDark
        bars.isAppearanceLightNavigationBars = !isDark
        @Suppress("DEPRECATION")
        window.statusBarColor = if (isDark) BG_DARK.toColorInt() else Color.WHITE
        @Suppress("DEPRECATION")
        window.navigationBarColor = if (isDark) BG_DARK.toColorInt() else Color.WHITE
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            window.isNavigationBarContrastEnforced = false
        }
    }

    override fun onDestroy() {
        screen?.release()
        screen = null
        super.onDestroy()
    }

    companion object {
        const val EXTRA_DOC_ID = "doc_id"
        const val EXTRA_TITLE = "title"
        const val EXTRA_DARK = "dark"

        private const val BG_DARK = "#1f2328"

        fun intent(context: Context, docId: String, title: String, dark: Boolean): Intent =
            Intent(context, PreviewActivity::class.java)
                .putExtra(EXTRA_DOC_ID, docId)
                .putExtra(EXTRA_TITLE, title)
                .putExtra(EXTRA_DARK, dark)
    }
}
