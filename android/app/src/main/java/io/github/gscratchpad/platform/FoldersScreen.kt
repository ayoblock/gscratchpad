package io.github.gscratchpad.platform

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.ExperimentalFoundationApi
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Folder

/**
 * T3 文件夹视图（My folders）：按文件夹分组展示文档，含「未归档」虚拟组。
 *
 * 纯展示 Composable：folder 写入操作（新建/重命名/删除/移动）经回调上抛给
 * MainActivity 执行（repository 写入 + reload 刷新 + toast），本文件不访问 repository。
 *
 * Q7：过滤 recentHidden 文档，与「最近」口径一致。
 * Q8：文档长按或点 ⋯ 触发移动菜单（菜单在 MainActivity，因需文件夹全量列表）。
 * T3-R4：独立文件，避免 MainActivity 进一步膨胀。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FoldersScreen(
    folders: List<Folder>,
    docs: List<Document>,
    counts: Map<String, Int>,
    expanded: Set<String>,
    onToggleGroup: (String) -> Unit,
    onOpenDoc: (String) -> Unit,
    onLongClickDoc: (String) -> Unit,
    onMoveDocClick: (String) -> Unit,
    onCreateFolder: () -> Unit,
    onRenameFolder: (String) -> Unit,
    onDeleteFolder: (String) -> Unit,
    isDark: Boolean,
    foreground: Color,
    cardBg: Color,
    muted: Color,
) {
    val background = if (isDark) Color(0xFF1F2328) else Color(0xFFFFFFFF)
    var groupMenu by remember { mutableStateOf<String?>(null) }

    MaterialTheme {
        Surface(Modifier.fillMaxSize(), color = background) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                    .padding(start = 16.dp, end = 16.dp, top = 10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                // 未归档虚拟组（folder=""）—— 无重命名/删除
                val unassigned = docs.filter { it.folder.isEmpty() && !it.recentHidden }
                GroupHeader(
                    label = FolderPolicy.UNFILED,
                    count = unassigned.size,
                    isExpanded = expanded.contains(""),
                    foreground = foreground,
                    cardBg = cardBg,
                    muted = muted,
                    onClick = { onToggleGroup("") },
                    menuFolder = null,
                    onMenuToggle = {},
                    onRename = {},
                    onDelete = {},
                    showActions = false,
                )
                if (expanded.contains("")) {
                    GroupBody(
                        docs = unassigned, cardBg = cardBg, foreground = foreground, muted = muted,
                        onOpenDoc = onOpenDoc, onLongClickDoc = onLongClickDoc, onMoveDocClick = onMoveDocClick,
                    )
                }

                // 实体文件夹组
                folders.forEach { folder ->
                    val inFolder = docs.filter { it.folder == folder.name && !it.recentHidden }
                    GroupHeader(
                        label = folder.name,
                        count = counts[folder.name] ?: inFolder.size,
                        isExpanded = expanded.contains(folder.name),
                        foreground = foreground,
                        cardBg = cardBg,
                        muted = muted,
                        onClick = { onToggleGroup(folder.name) },
                        menuFolder = groupMenu,
                        onMenuToggle = { groupMenu = if (groupMenu == folder.name) null else folder.name },
                        onRename = { onRenameFolder(folder.name) },
                        onDelete = { onDeleteFolder(folder.name) },
                        showActions = true,
                    )
                    if (expanded.contains(folder.name)) {
                        GroupBody(
                            docs = inFolder, cardBg = cardBg, foreground = foreground, muted = muted,
                            onOpenDoc = onOpenDoc, onLongClickDoc = onLongClickDoc, onMoveDocClick = onMoveDocClick,
                        )
                    }
                }

                TextButton(onClick = onCreateFolder, modifier = Modifier.padding(top = 4.dp)) {
                    Text("＋ 新建文件夹", fontSize = 14.sp, color = foreground)
                }
                Spacer(Modifier.height(16.dp))
            }
        }
    }
}

@Composable
private fun GroupHeader(
    label: String,
    count: Int,
    isExpanded: Boolean,
    foreground: Color,
    cardBg: Color,
    muted: Color,
    onClick: () -> Unit,
    menuFolder: String?,
    onMenuToggle: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
    showActions: Boolean,
) {
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(muted.copy(alpha = 0.08f))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (isExpanded) "▾" else "▸", fontSize = 12.sp, color = muted)
        Spacer(Modifier.width(8.dp))
        Text(
            label,
            Modifier.weight(1f),
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            color = foreground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text("$count", fontSize = 12.sp, color = muted)
        if (showActions) {
            Spacer(Modifier.width(6.dp))
            Box {
                Text(
                    "⋯", fontSize = 18.sp, color = muted,
                    modifier = Modifier.size(36.dp).clickable(onClick = onMenuToggle)
                        .padding(top = 2.dp),
                )
                DropdownMenu(
                    expanded = menuFolder == label,
                    onDismissRequest = {},
                    containerColor = cardBg,
                    shape = RoundedCornerShape(12.dp),
                    tonalElevation = 0.dp,
                    shadowElevation = 8.dp,
                ) {
                    DropdownMenuItem(
                        text = { Text("重命名文件夹", fontSize = 15.sp) },
                        leadingIcon = { RenameIcon(foreground) },
                        colors = appMenuColors(foreground, muted),
                        onClick = { onRename() },
                    )
                    DropdownMenuItem(
                        text = { Text("删除文件夹", fontSize = 15.sp) },
                        leadingIcon = { DeleteIcon(foreground) },
                        colors = appMenuColors(foreground, muted),
                        onClick = { onDelete() },
                    )
                }
            }
        }
    }
}

@Composable
private fun GroupBody(
    docs: List<Document>,
    cardBg: Color,
    foreground: Color,
    muted: Color,
    onOpenDoc: (String) -> Unit,
    onLongClickDoc: (String) -> Unit,
    onMoveDocClick: (String) -> Unit,
) {
    if (docs.isEmpty()) {
        Text(
            "（空）长按其他文档可移入本文件夹",
            Modifier.padding(start = 20.dp, top = 2.dp, bottom = 2.dp),
            color = muted,
            fontSize = 12.sp,
        )
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        docs.forEach { doc ->
            Row(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(cardBg)
                    .combinedClickable(
                        onClick = { onOpenDoc(doc.id) },
                        onLongClick = { onLongClickDoc(doc.id) },
                    )
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(
                        doc.title,
                        fontSize = 14.sp,
                        color = foreground,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(doc.format.name.lowercase(), fontSize = 11.sp, color = muted)
                }
                Box(
                    Modifier.size(40.dp).clickable { onMoveDocClick(doc.id) },
                    contentAlignment = Alignment.Center,
                ) { Text("⋯", fontSize = 18.sp, color = muted) }
            }
        }
    }
}
