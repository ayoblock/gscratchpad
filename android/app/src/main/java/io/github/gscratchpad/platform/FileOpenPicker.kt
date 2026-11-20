package io.github.gscratchpad.platform

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
 * R42：本地文件打开浏览器。用 [File] 逐级列举共享存储真实目录 + 文档文件，
 * 绕开 SAF 文档选择器在「下载」等入口的 provider 视图过滤（Android 14 真机实测缺目录的根治）。
 *
 * - 子目录：点「进入」逐级下钻；「上级」回退（R43：以 [startPath] 为根不越出起点——
 *   绑定工作目录后打开文件直接落在工作目录，设置工作目录才有意义）；
 * - 文档文件（后缀白名单见 [FileDirPolicy.isDocFileName]）：点击回调 [onPickFile] 打开；
 * - 权限未授予时给出说明与授权入口（API 30+ 所有文件访问 / API 29- 传统存储权限）。
 *
 * 主题色由调用方传入，与设置页/目录浏览器一致。
 */
@Composable
fun FileOpenPicker(
    startPath: String,
    granted: Boolean,
    foreground: Color,
    muted: Color,
    background: Color,
    cardBg: Color,
    onPickFile: (String) -> Unit,
    onRequestPermission: () -> Unit,
    onDismiss: () -> Unit,
    permissionHint: String,
    permissionAction: String,
) {
    var current by remember { mutableStateOf(FileDirPolicy.normalize(startPath)) }
    val dir = remember(current) { File(current) }
    val dirs = remember(current) { FileDirPolicy.listSubdirs(dir) }
    val files = remember(current) { FileDirPolicy.listDocFiles(dir) }
    // R43：以 startPath（绑定的工作目录或共享存储根）为根，「上级」不越出起点。
    val atRoot = FileDirPolicy.parentWithin(current, startPath) == null

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = background,
        title = {
            Column {
                Text("打开本地文件", color = foreground, fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
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
                if (dirs.isEmpty() && files.isEmpty()) {
                    Text(
                        if (granted) "此目录无子目录或文档文件" else "未授权时无法列出目录",
                        color = muted,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                } else {
                    LazyColumn(
                        Modifier
                            .fillMaxWidth()
                            .height(300.dp)
                            .background(cardBg, RoundedCornerShape(10.dp)),
                    ) {
                        items(dirs, key = { "d:" + it.absolutePath }) { d ->
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clickable(enabled = granted) { current = d.absolutePath }
                                    .padding(horizontal = 14.dp, vertical = 11.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(Modifier.weight(1f)) {
                                    Text("▸ ${d.name}", color = foreground, fontSize = 14.sp)
                                }
                                Text("进入", color = muted, fontSize = 11.sp)
                            }
                        }
                        items(files, key = { "f:" + it.absolutePath }) { f ->
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clickable(enabled = granted) { onPickFile(f.absolutePath) }
                                    .padding(horizontal = 14.dp, vertical = 11.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(Modifier.weight(1f)) {
                                    Text("▤ ${f.name}", color = foreground, fontSize = 14.sp)
                                }
                                Text("打开", color = muted, fontSize = 11.sp)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("关闭", color = muted, fontSize = 13.sp)
            }
        },
        dismissButton = {
            TextButton(
                onClick = { FileDirPolicy.parentWithin(current, startPath)?.let { current = it } },
                enabled = !atRoot,
            ) {
                Text("上级", color = if (!atRoot) foreground else muted, fontSize = 13.sp)
            }
        },
    )
}
