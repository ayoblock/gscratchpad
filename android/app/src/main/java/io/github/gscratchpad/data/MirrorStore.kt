package io.github.gscratchpad.data

import java.io.File
import java.io.FileOutputStream

/** 原子写入：写临时文件 → fsync → rename。目录 fsync 在 Android 上不可用，语义由 rename 提供。 */
object AtomicFiles {
    fun write(target: File, bytes: ByteArray) {
        target.parentFile?.mkdirs()
        val tmp = File(target.parentFile, target.name + ".tmp")
        FileOutputStream(tmp).use { out ->
            out.write(bytes)
            out.flush()
            out.fd.sync()
        }
        if (!tmp.renameTo(target)) {
            // rename 失败（跨卷或目标被占用）：退化为覆盖写，仍保证内容完整
            FileOutputStream(target).use { out ->
                out.write(bytes)
                out.flush()
                out.fd.sync()
            }
            tmp.delete()
        }
    }
}

/** `notes/<docId>.<ext>` 全文镜像，原子替换；不参与恢复决策（恢复只看 journal）。 */
class MirrorStore(private val appPaths: AppPaths) {

    fun write(docId: String, content: String, format: io.github.gscratchpad.domain.model.Format) {
        AtomicFiles.write(appPaths.noteFile(docId, format), content.toByteArray(Charsets.UTF_8))
        val other = appPaths.noteFile(
            docId,
            if (format == io.github.gscratchpad.domain.model.Format.TXT) {
                io.github.gscratchpad.domain.model.Format.MD
            } else {
                io.github.gscratchpad.domain.model.Format.TXT
            },
        )
        if (other.exists()) other.delete()
    }

    fun delete(docId: String) {
        appPaths.notes.listFiles { f -> f.name.startsWith("$docId.") }?.forEach { it.delete() }
    }
}
