package io.github.gscratchpad.platform

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File

/**
 * R40：目录浏览器对话框。用 [File] 逐级列举共享存储真实目录，绕开 SAF「下载」视图过滤。
 *
 * 主题色由调用方传入（与设置页/维护确认框一致），不自行取 MaterialTheme，保证深色/AMOLED 一致。
 * 目录列举走 [FileDirPolicy.listSubdirs]（只读第一级子目录、过滤隐藏项），进入子目录时即时刷新。
 * 受 MANAGE_EXTERNAL_STORAGE 约束：无权限时根目录下 listFiles 返回空，调用方在打开前先申请权限。
 */
@Composable
fun FileDirPicker(
    startPath: String,
    granted: Boolean,
    foreground: Color,
    muted: Color,
    background: Color,
    cardBg: Color,
    onPick: (String) -> Unit,
    onRequestPermission: () -> Unit,
    onDismiss: () -> Unit,
    permissionHint: String = "需授予存储权限才能浏览真实目录。授权后返回本页再点一次。",
    permissionAction: String = "授予存储权限",
) {
    var current by remember { mutableStateOf(FileDirPolicy.normalize(startPath)) }
    val dirs = remember(current) { FileDirPolicy.listSubdirs(File(current)) }
    val atRoot = FileDirPolicy.parentOf(current) == null

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = background,
        title = {
            Column {
                Text("选择工作目录", color = foreground, fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    FileDirPolicy.displayPath(current),
                    color = muted,
                    fontSize = 12.sp,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        },
        text = {
            Column {
                if (!granted) {
                    Text(
                        permissionHint,
                        color = muted,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 8.dp),
                    )
                    TextButton(onClick = onRequestPermission) {
                        Text(permissionAction, color = foreground, fontSize = 13.sp)
                    }
                }
                if (dirs.isEmpty()) {
                    Text(
                        if (granted) "此目录无可选子目录" else "未授权时无法列出目录",
                        color = muted,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                } else {
                    LazyColumn(
                        Modifier
                            .fillMaxWidth()
                            .height(280.dp)
                            .background(cardBg, RoundedCornerShape(10.dp)),
                    ) {
                        items(dirs, key = { it.absolutePath }) { dir ->
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clickable { current = dir.absolutePath }
                                    .padding(horizontal = 14.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(Modifier.weight(1f)) {
                                    Text("▸ ${dir.name}", color = foreground, fontSize = 14.sp)
                                }
                                Text("进入", color = muted, fontSize = 11.sp)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onPick(current) }, enabled = granted) {
                Text("选择此目录", color = if (granted) foreground else muted, fontSize = 13.sp)
            }
        },
        dismissButton = {
            Row {
                TextButton(onClick = { FileDirPolicy.parentOf(current)?.let { current = it } }, enabled = !atRoot) {
                    Text("上级", color = if (!atRoot) foreground else muted, fontSize = 13.sp)
                }
                TextButton(onClick = onDismiss) {
                    Text("取消", color = muted, fontSize = 13.sp)
                }
            }
        },
    )
}
