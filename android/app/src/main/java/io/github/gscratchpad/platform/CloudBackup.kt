package io.github.gscratchpad.platform

import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64

/**
 * 云备份（Q5）：两条通道，均为「用户自带目的地」，应用自身不引入账号体系。
 *
 * 1. **WebDAV**：`PUT/GET/HEAD` 一个 zip。地址填到目录级，例如
 *    `https://dav.example.com/remote.php/dav/files/alice/`，文件名固定 [_REMOTE_NAME]。
 * 2. **云盘目录（SAF）**：用户在系统文件选择器里选一个由云盘 DocumentsProvider 提供的目录，
 *    由 `MainActivity` 用 `DocumentsContract` 写入/读取同一个 zip。
 *
 * 两条通道复用同一份导出包（[io.github.gscratchpad.importlib.BackupExporter]），
 * 因此云备份与「导出备份 / 导入备份」的格式完全一致。
 */
object CloudBackup {

    const val REMOTE_NAME = "gscratchpad-cloud.zip"

    data class Config(val baseUrl: String, val user: String, val password: String) {
        val remoteUrl: String
            get() {
                val base = baseUrl.trim().trimEnd('/')
                return "$base/$REMOTE_NAME"
            }

        val usable: Boolean get() = baseUrl.startsWith("http")
    }

    class Result2(val ok: Boolean, val detail: String)

    private fun authHeader(cfg: Config): String? {
        if (cfg.user.isEmpty()) return null
        val token = Base64.getEncoder().encodeToString("${cfg.user}:${cfg.password}".toByteArray())
        return "Basic $token"
    }

    /** 上传：成功返回 `200/201/204` 之一。 */
    fun upload(cfg: Config, file: File): Result2 {
        if (!cfg.usable) return Result2(false, "地址需以 http(s) 开头")
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(cfg.remoteUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "PUT"
                doOutput = true
                connectTimeout = 12_000
                readTimeout = 30_000
                setRequestProperty("Content-Type", "application/zip")
                authHeader(cfg)?.let { setRequestProperty("Authorization", it) }
            }
            conn.outputStream.use { it.write(file.readBytes()) }
            val code = conn.responseCode
            Result2(code in 200..299, "HTTP $code ${conn.responseMessage}")
        } catch (e: IOException) {
            Result2(false, "上传失败：${e.message}")
        } finally {
            conn?.disconnect()
        }
    }

    /** 远端文件大小（HEAD）；未实现 HEAD 的服务器回退为 -1。 */
    fun remoteSize(cfg: Config): Long {
        if (!cfg.usable) return -1
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(cfg.remoteUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "HEAD"
                connectTimeout = 8_000
                readTimeout = 12_000
                authHeader(cfg)?.let { setRequestProperty("Authorization", it) }
            }
            if (conn.responseCode in 200..299) conn.getHeaderField("Content-Length")?.toLongOrNull() ?: -1 else -1
        } catch (e: IOException) {
            -1
        } finally {
            conn?.disconnect()
        }
    }

    /** 下载到 [target]，返回结果与字节数。 */
    fun download(cfg: Config, target: File): Result2 {
        if (!cfg.usable) return Result2(false, "地址需以 http(s) 开头")
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(cfg.remoteUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 12_000
                readTimeout = 30_000
                authHeader(cfg)?.let { setRequestProperty("Authorization", it) }
            }
            val code = conn.responseCode
            if (code !in 200..299) return Result2(false, "HTTP $code ${conn.responseMessage}")
            target.parentFile?.mkdirs()
            val bytes = conn.inputStream.use { it.readBytes() }
            if (bytes.isEmpty()) return Result2(false, "远端文件为空")
            target.writeBytes(bytes)
            Result2(true, "${bytes.size} B")
        } catch (e: IOException) {
            Result2(false, "下载失败：${e.message}")
        } finally {
            conn?.disconnect()
        }
    }
}
