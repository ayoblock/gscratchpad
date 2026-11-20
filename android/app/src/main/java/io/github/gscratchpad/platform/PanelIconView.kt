package io.github.gscratchpad.platform

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View

/**
 * 预览栏图标按钮（R24 重绘）：Canvas 自绘，按 24 单位网格等比缩放，圆头描边。
 *
 * 与编辑器页内 icons 保持同一视觉语言（24 网格 / 1.7 单位线宽 / 圆角端点）：
 * 返回 / 大纲 / 主题 / 导出 PDF / 关闭。
 * 对比 R18 版本：路径按网格对齐、月牙用双圆弧求交、PDF 加折角、按压有圆角底色反馈。
 */
class PanelIconView(context: Context, private val kind: Kind) : View(context) {

    enum class Kind { BACK, THEME, PDF, CLOSE, OUTLINE, DOCS }

    var tint: Int = Color.BLACK
        set(value) {
            field = value
            invalidate()
        }

    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val pressPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }

    /** 24 单位网格 → 像素的换算系数与原点。 */
    private var unit = 1f
    private var ox = 0f
    private var oy = 0f

    init {
        isClickable = true
        isFocusable = true
        contentDescription = when (kind) {
            Kind.BACK -> "返回"
            Kind.OUTLINE -> "文档大纲"
            Kind.THEME -> "切换日间/夜间"
            Kind.PDF -> "导出 PDF"
            Kind.CLOSE -> "关闭预览"
            Kind.DOCS -> "切换文档"
        }
    }

    private fun gx(x: Float) = ox + x * unit

    private fun gy(y: Float) = oy + y * unit

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        // 与编辑器顶栏 SVG 图标同规格：44 dp 触摸区里放 22 dp 视觉图标（视觉/触摸 = 0.5），
        // 24 单位网格按 0.5 缩放；线宽 1.6 网格单位（= 编辑器 svg stroke-width）。
        unit = minOf(w, h) / 24f * 0.5f
        ox = (w - 24f * unit) / 2f
        oy = (h - 24f * unit) / 2f

        stroke.strokeWidth = 1.6f * unit
        stroke.color = tint
        fill.color = tint

        if (isPressed) {
            // 按压反馈铺满整个 44 dp 触摸区、12 dp 圆角，与编辑器 #bar .ico:active 一致
            pressPaint.color = tint
            pressPaint.alpha = 38
            val r = 12f * resources.displayMetrics.density
            canvas.drawRoundRect(0f, 0f, w, h, r, r, pressPaint)
        }

        when (kind) {
            Kind.BACK -> drawBack(canvas)
            Kind.OUTLINE -> drawOutline(canvas)
            Kind.THEME -> drawCrescent(canvas)
            Kind.PDF -> drawDocument(canvas)
            Kind.CLOSE -> drawClose(canvas)
            Kind.DOCS -> drawDocs(canvas)
        }
    }

    /** 切换文档：三行「圆点 + 文本线」+ 底部虚线，与编辑器 #bar 的 docs 图标同构。 */
    private fun drawDocs(canvas: Canvas) {
        for (y in floatArrayOf(5.5f, 10.5f, 15.5f)) {
            canvas.drawLine(gx(9f), gy(y), gx(20f), gy(y), stroke)
            canvas.drawCircle(gx(5.5f), gy(y), 0.9f * unit, fill)
        }
        // 底部虚线表示「还有更多文档」
        val dash = android.graphics.DashPathEffect(floatArrayOf(2f * unit, 2f * unit), 0f)
        val dashPaint = Paint(stroke).apply { pathEffect = dash }
        canvas.drawLine(gx(5.5f), gy(20f), gx(20f), gy(20f), dashPaint)
    }

    private fun drawBack(canvas: Canvas) {
        val p = Path().apply {
            moveTo(gx(19.2f), gy(12f))
            lineTo(gx(5.2f), gy(12f))
            moveTo(gx(10.8f), gy(6.2f))
            lineTo(gx(5.2f), gy(12f))
            lineTo(gx(10.8f), gy(17.8f))
        }
        canvas.drawPath(p, stroke)
    }

    /** 大纲：三行「圆点 + 文本线」，与编辑器工具栏的大纲图标同构。 */
    private fun drawOutline(canvas: Canvas) {
        val rows = floatArrayOf(6.4f, 12f, 17.6f)
        for (y in rows) {
            canvas.drawCircle(gx(5.2f), gy(y), 1.15f * unit, fill)
            canvas.drawLine(gx(9.0f), gy(y), gx(19.4f), gy(y), stroke)
        }
    }

    /**
     * 主题：月牙。外圆 O=(11.6,12) 与内圆 I=(15.4,11.2) 同半径 6.6 求交，
     * 两交点 (12.20,5.43)/(14.80,17.77) 之间先走外圆左侧长弧，再走内圆左侧短弧回到起点。
     */
    private fun drawCrescent(canvas: Canvas) {
        val r = 6.6f * unit
        val outer = RectF(gx(11.6f) - r, gy(12.0f) - r, gx(11.6f) + r, gy(12.0f) + r)
        val inner = RectF(gx(15.4f) - r, gy(11.2f) - r, gx(15.4f) + r, gy(11.2f) + r)
        val p = Path().apply {
            arcTo(outer, -84.8f, -275.9f, true)
            arcTo(inner, 95.2f, 145.8f, false)
            close()
        }
        canvas.drawPath(p, stroke)
        // 一颗小星：让「夜间」语义在小尺寸下也能读出来
        canvas.drawCircle(gx(19.6f), gy(5.2f), 0.95f * unit, fill)
    }

    /** PDF：折角文档 + 两行正文线（折角让「导出文档」在 40 dp 下不被误读成普通矩形）。 */
    private fun drawDocument(canvas: Canvas) {
        val page = Path().apply {
            moveTo(gx(5.6f), gy(3.2f))
            lineTo(gx(14.4f), gy(3.2f))
            lineTo(gx(18.6f), gy(7.4f))
            lineTo(gx(18.6f), gy(20.8f))
            lineTo(gx(5.6f), gy(20.8f))
            close()
        }
        canvas.drawPath(page, stroke)
        val fold = Path().apply {
            moveTo(gx(14.4f), gy(3.2f))
            lineTo(gx(14.4f), gy(7.4f))
            lineTo(gx(18.6f), gy(7.4f))
        }
        canvas.drawPath(fold, stroke)
        canvas.drawLine(gx(8.6f), gy(12.6f), gx(15.6f), gy(12.6f), stroke)
        canvas.drawLine(gx(8.6f), gy(16.2f), gx(13.2f), gy(16.2f), stroke)
    }

    private fun drawClose(canvas: Canvas) {
        val p = Path().apply {
            moveTo(gx(6.6f), gy(6.6f))
            lineTo(gx(17.4f), gy(17.4f))
            moveTo(gx(17.4f), gy(6.6f))
            lineTo(gx(6.6f), gy(17.4f))
        }
        canvas.drawPath(p, stroke)
    }
}
