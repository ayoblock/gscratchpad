package io.github.gscratchpad.platform

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileNotFoundException
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * R38：基于 [java.io.File] 的直读网关（MANAGE_EXTERNAL_STORAGE 授权后启用）。
 *
 * 与 [SafFileGateway] 平行存在、双轨增量：仅在获得所有文件访问权、且 SAF documentId
 * 能被 [FileDirectPolicy] 映射成真实路径时，替换「写回」这一条最易出问题的链路。
 * 其它能力（打开/列目录/创建）仍走 SAF，故不破坏既有行为。
 *
 * 写回核心：同目录临时文件写满 + fsync + 读回校验 + `Files.move(REPLACE_EXISTING, ATOMIC_MOVE)`。
 * 相较 SAF rename 舞蹈的三个根治点：
 *  1. 不产生 `.old`：直接 REPLACE_EXISTING 覆盖原名，无「旧文件改名 .old」中间态；
 *  2. 不受 provider 重名干预：文件名由我们指定，系统不会拼 `.md.txt` 或改写后缀；
 *  3. 不依赖 deleteDocument：删除/覆盖是文件系统级操作，无 provider 能力探测问题。
 * 任意时刻断电，目标名下都是完整旧版或完整新版；ATOMIC_MOVE 失败时回退普通 REPLACE_EXISTING。
 */
class FileGateway {

    /**
     * 原子写回。返回 true 表示成功；调用方（SafFileGateway.save）据此决定是否跳过 SAF 写回。
     * 失败不抛异常——由调用方回退 SAF，保证「File 通道失败 = 退回原行为」，不会更糟。
     */
    suspend fun saveAtomic(path: String, text: String, style: TextStyle): Boolean =
        saveAtomicDetailed(path, text, style) == null

    /**
     * R45：带失败原因的原子写回。返回 null 表示成功；非 null 为具体失败环节描述，
     * 供调用方提示与日志定位——「路径不可写」可能是五个环节中任意一个，不能再一律笼统上报。
     */
    suspend fun saveAtomicDetailed(path: String, text: String, style: TextStyle): String? =
        withContext(Dispatchers.IO) {
            val target = File(path)
            if (!FileDirectPolicy.isSharedStoragePath(target.absolutePath)) {
                return@withContext "路径不在共享存储内：${target.absolutePath}"
            }
            val bytes = TextCodec.encode(text, style)
            val parent = target.parentFile
                ?: return@withContext "无父目录：${target.absolutePath}"
            if (!parent.exists() && !parent.mkdirs()) {
                return@withContext "父目录不存在且无法创建：${parent.absolutePath}"
            }

            val tmp = File(parent, ".${target.name}.gs-${System.nanoTime()}.tmp")
            try {
                try {
                    tmp.outputStream().use { out ->
                        out.write(bytes)
                        out.flush()
                        runCatching { out.fd.sync() }
                    }
                } catch (e: Exception) {
                    return@withContext "临时文件写入失败：${e.message}"
                }
                // 读回校验：确认临时文件完整后再替换，避免半截写覆盖原文件。
                val readBack = runCatching { tmp.readBytes() }.getOrNull()
                if (readBack == null || !readBack.contentEquals(bytes)) {
                    return@withContext "读回校验失败（写入不完整）"
                }

                val moved = runCatching {
                    Files.move(
                        tmp.toPath(),
                        target.toPath(),
                        StandardCopyOption.REPLACE_EXISTING,
                        StandardCopyOption.ATOMIC_MOVE,
                    )
                }.isSuccess || runCatching {
                    Files.move(tmp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
                }.isSuccess
                if (!moved) return@withContext "原子替换失败（rename 被拒绝）：${target.name}"
                android.util.Log.d("FileGateway", "atomic-save ok: ${target.name} bytes=${bytes.size}")
                null
            } catch (e: Exception) {
                android.util.Log.d("FileGateway", "atomic-save failed: ${e.message}")
                "写回异常：${e.message}"
            } finally {
                if (tmp.exists()) runCatching { tmp.delete() }
            }
        }

    /**
     * R40：在目录（File 直读工作目录）下创建一个空文档文件，返回其绝对路径。
     * 仅共享存储路径、文件名必须是纯文件名（拒绝分隔符/..）。失败返回 null，由调用方回退本地文档。
     */
    fun createEmptyFile(dirPath: String, fileName: String): String? {
        if (!FileDirectPolicy.isSharedStoragePath(dirPath)) return null
        if (fileName.isBlank() || fileName.contains('/') || fileName.contains("..")) return null
        val dir = File(dirPath)
        if (!dir.isDirectory && !dir.mkdirs()) return null
        val target = File(dir, fileName)
        return runCatching {
            if (target.exists()) target.absolutePath
            else if (target.createNewFile()) target.absolutePath else null
        }.getOrNull()
    }

    /** 删除一个真实路径下的文件；仅共享存储路径、返回是否删除成功。 */
    suspend fun delete(path: String): Boolean = withContext(Dispatchers.IO) {
        if (!FileDirectPolicy.isSharedStoragePath(path)) return@withContext false
        runCatching {
            val f = File(path)
            !f.exists() || f.delete()
        }.getOrDefault(false)
    }

    /**
     * R41：列出工作目录下的文档文件绝对路径（按文件名排序），供「切换文档」浮层展示。
     * 仅共享存储路径；目录不可读时返回空列表（调用方回退到库内文档列表）。
     */
    fun listDocFiles(dirPath: String): List<String> {
        if (!FileDirectPolicy.isSharedStoragePath(dirPath)) return emptyList()
        val dir = File(dirPath)
        if (!dir.isDirectory) return emptyList()
        return FileDirPolicy.listDocFiles(dir).map { it.absolutePath }
    }

    /**
     * R41：读取工作目录文档文件的正文（TextCodec 自动识别编码、二进制拒绝）。
     * 仅共享存储路径；读取/解码失败返回 null，调用方据此提示并跳过导入。
     */
    suspend fun readDocText(path: String): String? = withContext(Dispatchers.IO) {
        if (!FileDirectPolicy.isSharedStoragePath(path)) return@withContext null
        runCatching {
            val bytes = File(path).readBytes()
            if (TextCodec.looksBinary(bytes)) return@withContext null
            TextCodec.decode(bytes).text
        }.getOrNull()
    }
}
