package io.github.gscratchpad.platform

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.MenuItemColors
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

/**
 * 弹出层统一视觉（R35）：长按菜单项配色 + 线条图标。
 *
 * App 主体使用自定义 foreground/cardBg/muted 配色，未走 MaterialTheme.colorScheme，
 * 因此 Material3 默认的浅色系统菜单在深色/AMOLED 主题下格外突兀。本文件把菜单项
 * 颜色与图标集中一处，MainActivity 与 FoldersScreen 共用，避免两处样式漂移。
 */

/** 菜单项配色：正文前景色、图标前景色、禁用态弱化色，与卡片文字一致。 */
@Composable
fun appMenuColors(foreground: Color, muted: Color): MenuItemColors =
    MenuDefaults.itemColors(
        textColor = foreground,
        leadingIconColor = foreground,
        trailingIconColor = muted,
        disabledTextColor = muted.copy(alpha = 0.5f),
        disabledLeadingIconColor = muted.copy(alpha = 0.5f),
        disabledTrailingIconColor = muted.copy(alpha = 0.5f),
    )

/** 重命名（铅笔）。 */
@Composable
fun RenameIcon(tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.size(20.dp)) {
        val sw = 1.6.dp.toPx()
        val w = size.width
        val h = size.height
        drawLine(tint, Offset(w * 0.30f, h * 0.70f), Offset(w * 0.72f, h * 0.28f), sw)
        drawLine(tint, Offset(w * 0.72f, h * 0.28f), Offset(w * 0.84f, h * 0.40f), sw)
        drawLine(tint, Offset(w * 0.30f, h * 0.70f), Offset(w * 0.22f, h * 0.80f), sw)
        drawLine(tint, Offset(w * 0.18f, h * 0.86f), Offset(w * 0.86f, h * 0.86f), sw)
    }
}

/** 删除（垃圾桶）。 */
@Composable
fun DeleteIcon(tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.size(20.dp)) {
        val sw = 1.6.dp.toPx()
        val w = size.width
        val h = size.height
        drawLine(tint, Offset(w * 0.40f, h * 0.22f), Offset(w * 0.60f, h * 0.22f), sw)
        drawLine(tint, Offset(w * 0.22f, h * 0.30f), Offset(w * 0.78f, h * 0.30f), sw)
        drawRect(tint, Offset(w * 0.30f, h * 0.30f), Size(w * 0.40f, h * 0.55f), style = Stroke(sw))
        drawLine(tint, Offset(w * 0.43f, h * 0.42f), Offset(w * 0.43f, h * 0.72f), sw)
        drawLine(tint, Offset(w * 0.57f, h * 0.42f), Offset(w * 0.57f, h * 0.72f), sw)
    }
}

/** 移动（右箭头）。 */
@Composable
fun MoveIcon(tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.size(20.dp)) {
        val sw = 1.6.dp.toPx()
        val w = size.width
        val h = size.height
        drawLine(tint, Offset(w * 0.20f, h * 0.50f), Offset(w * 0.78f, h * 0.50f), sw)
        drawLine(tint, Offset(w * 0.58f, h * 0.30f), Offset(w * 0.80f, h * 0.50f), sw)
        drawLine(tint, Offset(w * 0.80f, h * 0.50f), Offset(w * 0.58f, h * 0.70f), sw)
    }
}

/** 文件夹轮廓（文件夹菜单）。 */
@Composable
fun FolderOutlineIcon(tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.size(20.dp)) {
        val sw = 1.6.dp.toPx()
        val w = size.width
        val h = size.height
        drawLine(tint, Offset(w * 0.15f, h * 0.34f), Offset(w * 0.42f, h * 0.34f), sw)
        drawLine(tint, Offset(w * 0.15f, h * 0.34f), Offset(w * 0.15f, h * 0.78f), sw)
        drawLine(tint, Offset(w * 0.15f, h * 0.78f), Offset(w * 0.85f, h * 0.78f), sw)
        drawLine(tint, Offset(w * 0.85f, h * 0.78f), Offset(w * 0.85f, h * 0.44f), sw)
        drawLine(tint, Offset(w * 0.42f, h * 0.34f), Offset(w * 0.50f, h * 0.44f), sw)
        drawLine(tint, Offset(w * 0.50f, h * 0.44f), Offset(w * 0.85f, h * 0.44f), sw)
    }
}
