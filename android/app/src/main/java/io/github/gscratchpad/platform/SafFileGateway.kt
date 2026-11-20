package io.github.gscratchpad.platform

import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.FileNotFoundException

data class OpenedFile(
    val uri: Uri,
    val displayName: String,
    val text: String,
    val style: TextStyle,
)

data class TreeEntry(
    val uri: Uri,
    val name: String,
    val isDirectory: Boolean,
    val size: Long,
    val lastModified: Long,
    val mime: String?,
)

enum class WriteMode { ATOMIC_RENAME, IN_PLACE, FILE_DIRECT }

/**
 * R38：File 直读写回能力（双轨）。由 MainActivity 注入，仅在「已授权所有文件访问」时返回 true。
 * 单独抽成接口便于 JVM 单测时注入假实现，不依赖 Android 环境。
 */
fun interface FileDirectWriter {
    /** 尝试用 File 原子写回；把 documentId 映射成真实路径后调用。成功返回 true。 */
    suspend fun trySave(documentId: String?, text: String, style: TextStyle): Boolean
}

/**
 * SAF 文件网关（方案 §5.3）。
 *
 * 规则：
 * 1. 读入识别 UTF-8 / GB18030，保留 BOM 与换行风格，写回原样还原；
 * 2. 写回优先「临时文件 + 重命名」，provider 不支持时退化为原文件 truncate + fsync；
 * 3. 二进制（含 NUL）直接拒绝；
 * 4. 目录遍历在 IO 线程，单目录超过 400 项截断。
 */
class SafFileGateway(
    private val context: Context,
    private val fileDirectWriter: FileDirectWriter? = null,
) {

    private val resolver: ContentResolver get() = context.contentResolver

    suspend fun open(uri: Uri): OpenedFile = withContext(Dispatchers.IO) {
        val name = displayName(uri)
        val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
            ?: throw FileNotFoundException("无法读取：$uri")
        if (TextCodec.looksBinary(bytes)) {
            throw IllegalArgumentException("二进制文件，拒绝打开：$name")
        }
        val decoded = TextCodec.decode(bytes)
        OpenedFile(uri, name, decoded.text, decoded.style)
    }

    /** 写回。返回实际采用的写入模式，供迁移报告与日志。 */
    suspend fun save(uri: Uri, text: String, style: TextStyle): WriteMode =
        withContext(Dispatchers.IO) {
            // R38 双轨：已授权且 documentId 可映射为真实路径时，优先走 File 原子写回——
            // 不产生 .old、不受 provider 重名/删除能力限制。失败或不可用则原样回退 SAF，
            // 保证「File 通道失败 = 退回原行为」，不会比未授权时更糟。
            if (fileDirectWriter != null) {
                val documentId = runCatching { DocumentsContract.getDocumentId(uri) }.getOrNull()
                val resolved = FileDirectPolicy.resolvePath(documentId)
                if (FileDirectPolicy.shouldUseFileDirect(true, true, resolved)) {
                    val ok = runCatching { fileDirectWriter.trySave(documentId, text, style) }
                        .getOrDefault(false)
                    if (ok) return@withContext WriteMode.FILE_DIRECT
                    android.util.Log.d("SafGW", "file-direct failed, fallback SAF: $documentId -> $resolved")
                }
            }
            val bytes = TextCodec.encode(text, style)
            // 优先尝试同目录临时文件 + 校验 + 替换；失败则原文件覆盖写。
            val renamed = runCatching { writeWithRename(uri, bytes) }.getOrDefault(false)
            if (renamed) WriteMode.ATOMIC_RENAME else {
                writeInPlace(uri, bytes)
                WriteMode.IN_PLACE
            }
        }

    suspend fun createInTree(treeUri: Uri, name: String, mime: String): Uri =
        withContext(Dispatchers.IO) {
            val tree = DocumentFile.fromTreeUri(context, treeUri)
                ?: throw IllegalArgumentException("目录不可用：$treeUri")
            val created = tree.createFile(mime, name)
                ?: throw IllegalStateException("无法创建文件：$name")
            created.uri
        }

    fun takePersistablePermission(uri: Uri) {
        val takeFlags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        runCatching { resolver.takePersistableUriPermission(uri, takeFlags) }
    }

    /** 递归枚举目录树，单目录超过 [maxPerDirectory] 项时截断（与桌面一致）。 */
    suspend fun listTree(treeUri: Uri, maxPerDirectory: Int = 400): List<TreeEntry> =
        withContext(Dispatchers.IO) {
            val root = DocumentFile.fromTreeUri(context, treeUri) ?: return@withContext emptyList()
            val out = ArrayList<TreeEntry>()
            val queue = ArrayDeque<DocumentFile>()
            queue.add(root)
            while (queue.isNotEmpty()) {
                val dir = queue.removeFirst()
                val children = dir.listFiles().take(maxPerDirectory)
                for (child in children) {
                    out.add(
                        TreeEntry(
                            uri = child.uri,
                            name = child.name ?: "",
                            isDirectory = child.isDirectory,
                            size = child.length(),
                            lastModified = child.lastModified(),
                            mime = child.type,
                        ),
                    )
                    if (child.isDirectory) queue.add(child)
                }
            }
            out
        }

    /** 仅返回 tree 型持久授权；单文件（OpenDocument）授权的 URI 无 tree 段，
     *  传入 DocumentFile.fromTreeUri 会抛 IllegalArgumentException，必须过滤掉。 */
    fun documentTreeRoots(): List<Uri> =
        resolver.persistedUriPermissions
            .filter { it.isReadPermission && it.uri.pathSegments?.firstOrNull() == "tree" }
            .map { it.uri }

    fun displayName(uri: Uri): String =
        runCatching { DocumentFile.fromSingleUri(context, uri)?.name }.getOrNull()
            ?: uri.lastPathSegment
            ?: "未命名"

    // ------------------------------------------------------------------ 写入实现

    private fun writeWithRename(uri: Uri, bytes: ByteArray): Boolean {
        val documentId = runCatching { DocumentsContract.getDocumentId(uri) }.getOrNull()
            ?: run { android.util.Log.d("SafGW", "rename-skip: getDocumentId failed"); return false }
        if ('/' !in documentId) { android.util.Log.d("SafGW", "rename-skip: no slash in $documentId"); return false }
        val parentId = documentId.substringBeforeLast('/')
        val parent = DocumentsContract.buildDocumentUriUsingTree(uri, parentId)
        val name = displayName(uri)
        val base = name.substringBeforeLast('.')
        val ext = if ('.' in name) "." + name.substringAfterLast('.') else ""
        // externalstorage provider 会拒绝「扩展名与 MIME 不一致」的 createDocument（Failed to create unique file），
        // 临时文件用 octet-stream + 稳妥后缀命名，避免整条原子链路静默失效。
        val tempUri = runCatching {
            DocumentsContract.createDocument(resolver, parent, "application/octet-stream", "$base.tmp$ext")
        }.getOrElse {
            android.util.Log.d("SafGW", "rename-skip: createDocument failed: ${it.message}")
            return false
        } ?: run { android.util.Log.d("SafGW", "rename-skip: createDocument null"); return false }

        return try {
            resolver.openOutputStream(tempUri, "wt")?.use { out ->
                out.write(bytes)
                out.flush()
                (out as? java.io.FileOutputStream)?.fd?.sync()
            } ?: run { android.util.Log.d("SafGW", "rename-skip: tmp openOutputStream null"); return false }
            // 保留原文件：先确认临时文件可读回，再换名
            val readBack = resolver.openInputStream(tempUri)?.use { it.readBytes() }
            if (readBack == null || !readBack.contentEquals(bytes)) {
                android.util.Log.d("SafGW", "rename-skip: tmp readback mismatch (${readBack?.size} vs ${bytes.size})")
                resolver.delete(tempUri, null, null)
                return false
            }
            // 原子换名：旧文件改名 .old → 临时文件改名回原名 → 删 .old（尽力而为）。
            // 任意时刻断电，目标名下都是完整旧版或完整新版；.old 清理失败只产生冗余备份，不影响原子性。
            val oldUri = runCatching {
                DocumentsContract.renameDocument(resolver, uri, "$base.old$ext")
            }.getOrElse {
                android.util.Log.d("SafGW", "rename-skip: rename original failed: ${it.message}")
                return false
            } ?: run { android.util.Log.d("SafGW", "rename-skip: rename original null"); return false }
            runCatching {
                DocumentsContract.renameDocument(resolver, tempUri, name)
            }.getOrElse {
                android.util.Log.d("SafGW", "rename-fallback: rename tmp failed: ${it.message}")
                runCatching { DocumentsContract.renameDocument(resolver, oldUri, name) }
                runCatching { resolver.delete(tempUri, null, null) }
                return false
            } ?: run {
                android.util.Log.d("SafGW", "rename-fallback: rename tmp null")
                runCatching { DocumentsContract.renameDocument(resolver, oldUri, name) }
                runCatching { resolver.delete(tempUri, null, null) }
                return false
            }
            val delOld = runCatching { resolver.delete(oldUri, null, null) > 0 }.getOrDefault(false)
            android.util.Log.d("SafGW", if (delOld) "rename-ok: $name" else "rename-ok: $name (old 清理被 provider 拒绝)")
            true
        } catch (e: Exception) {
            android.util.Log.d("SafGW", "rename-fail: ${e.message}")
            runCatching { resolver.delete(tempUri, null, null) }
            false
        }
    }

    private fun writeInPlace(uri: Uri, bytes: ByteArray) {
        resolver.openOutputStream(uri, "wt")?.use { out ->
            out.write(bytes)
            out.flush()
            (out as? java.io.FileOutputStream)?.fd?.sync()
        } ?: throw FileNotFoundException("无法写入：$uri")
    }
}
