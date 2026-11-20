package io.github.gscratchpad.platform

import android.content.Context
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.WebView

/**
 * PDF 导出（方案 §5.5）。
 *
 * 采用 `WebView.createPrintDocumentAdapter` + `PrintManager.print`：由平台打印框架
 * 完成 A4 分页与矢量输出，可直接“另存为 PDF”，也可送系统打印服务。
 * 真分页与文字可选中由平台承担，替代桌面 WeasyPrint。
 */
class PdfExporter(
    private val context: Context,
    private val webView: WebView,
    private val title: String = "Gscratchpad",
) {

    fun print() {
        val adapter = webView.createPrintDocumentAdapter(title)
        val attributes = PrintAttributes.Builder()
            .setMediaSize(PrintAttributes.MediaSize.ISO_A4)
            .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
            .build()
        val manager = context.getSystemService(Context.PRINT_SERVICE) as PrintManager
        manager.print(title, adapter, attributes)
    }

    companion object {
        /** 打印版外壳：浅色主题、A4 内容宽度，代码块与表格避免跨页拆断。 */
        fun printCss(contentWidthPx: Int = 672): String = """
            @page { size: A4; margin: 12mm; }
            body { background:#fff; color:#000; width:${contentWidthPx}px; }
            pre, table, .mermaid { break-inside: avoid; page-break-inside: avoid; }
            h1, h2, h3 { break-after: avoid; page-break-after: avoid; }
        """.trimIndent()
    }
}
