package io.github.gscratchpad.platform

import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import java.net.URL
import java.util.Base64
import javax.net.ssl.SNIHostName
import javax.net.ssl.SSLParameters
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * WebDAV 通用客户端（sync v1，语义规约 docs/SYNC_PROTOCOL.md §8）。
 *
 * 与 [CloudBackup] 的固定文件传输互补：这里提供 put/get/headSize/mkcolDeep/
 * propfindChildren 通用方法，供 SyncEngine 按设备目录读写 manifest/docs.zip/
 * assets。PUT/GET/HEAD 走 HttpURLConnection；MKCOL/PROPFIND 因 Android
 * 的方法白名单改走原生 socket（见 [rawRequest]），无新增依赖；超时与重试对齐 R35。
 *
 * 地址允许内嵌用户名 `http://user@host/path`（与桌面版一致），解析后拆为
 * 独立 user 字段；密码单独传入。
 */
class SyncDav(baseUrl: String, user: String, password: String) : DavOps {

    val base: String
    val user: String

    init {
        val parsed = parseBaseUrl(baseUrl)
        base = parsed.base
        this.user = user.ifEmpty { parsed.user }
    }

    private val token: String? = run {
        if (this.user.isEmpty() && password.isEmpty()) null
        else Base64.getEncoder().encodeToString("${this.user}:$password".toByteArray())
    }

    data class Parsed(val base: String, val user: String)

    companion object {
        /** 拆分内嵌用户名：`http://admin@host:port/path` → (http://host:port/path, admin)。 */
        fun parseBaseUrl(url: String): Parsed {
            val trimmed = url.trim().trimEnd('/')
            require(trimmed.startsWith("http")) { "地址需以 http(s):// 开头" }
            val schemeEnd = trimmed.indexOf("://") + 3
            val slash = trimmed.indexOf('/', schemeEnd)
            val authority = if (slash < 0) trimmed.substring(schemeEnd) else trimmed.substring(schemeEnd, slash)
            val path = if (slash < 0) "" else trimmed.substring(slash)
            val at = authority.lastIndexOf('@')
            return if (at >= 0) {
                Parsed(trimmed.substring(0, schemeEnd) + authority.substring(at + 1) + path, authority.substring(0, at))
            } else {
                Parsed(trimmed.substring(0, schemeEnd) + authority + path, "")
            }
        }

        /** 拼接路径片段（各片段做 URL 编码，`/` 保留为分隔符）。 */
        fun joinUrl(base: String, vararg parts: String): String {
            var path = base.trimEnd('/')
            for (part in parts) {
                val segment = part.trim('/')
                path += "/" + java.net.URLEncoder.encode(segment, "UTF-8")
                    .replace("%2F", "/").replace("+", "%20")
            }
            return path
        }
    }

    data class DavResult(val ok: Boolean, val status: Int, val detail: String)

    private fun connect(method: String, url: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 12_000
            readTimeout = 30_000
            token?.let { setRequestProperty("Authorization", "Basic $it") }
        }

    /**
     * MKCOL/PROPFIND 不在 Android HttpURLConnection 允许的方法集合内
     * （真机报 "expected one of [options,get,head,post,put,delete,trace,patch] but was mkcol"），
     * 因此这两个方法改走原生 socket；其余标准方法仍用 HttpURLConnection。
     */
    private fun request(method: String, url: String, body: ByteArray?, contentType: String?): Pair<Int, ByteArray> =
        try {
            if (method == "MKCOL" || method == "PROPFIND") {
                rawRequest(method, url, body, contentType)
            } else {
                httpRequest(method, url, body, contentType)
            }
        } catch (e: SyncDavException) {
            throw e
        } catch (e: IOException) {
            throw SyncDavException("网络错误：${e.message}", 0)
        }

    private fun httpRequest(method: String, url: String, body: ByteArray?, contentType: String?): Pair<Int, ByteArray> {
        var conn: HttpURLConnection? = null
        return try {
            conn = connect(method, url)
            if (contentType != null) conn.setRequestProperty("Content-Type", contentType)
            if (body != null) {
                conn.doOutput = true
                conn.setFixedLengthStreamingMode(body.size)
                conn.outputStream.use { it.write(body) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..399) conn.inputStream else conn.errorStream
            val data = stream?.use { it.readBytes() } ?: ByteArray(0)
            code to data
        } finally {
            conn?.disconnect()
        }
    }

    /** 用裸 socket 发送一个 HTTP/1.1 请求并读回状态码与响应体。 */
    private fun rawRequest(method: String, url: String, body: ByteArray?, contentType: String?): Pair<Int, ByteArray> {
        val uri = URI(url)
        val host = uri.host ?: throw IOException("WebDAV 地址缺少主机名：$url")
        val secure = uri.scheme == "https"
        val port = if (uri.port >= 0) uri.port else if (secure) 443 else 80
        val target = (uri.rawPath?.takeIf { it.isNotEmpty() } ?: "/") +
            (uri.rawQuery?.let { "?$it" } ?: "")
        val payload = body ?: ByteArray(0)
        val authority = if (port == 80 || port == 443) host else "$host:$port"

        val head = StringBuilder().apply {
            append(method).append(' ').append(target).append(" HTTP/1.1\r\n")
            append("Host: ").append(authority).append("\r\n")
            token?.let { append("Authorization: Basic ").append(it).append("\r\n") }
            if (contentType != null) append("Content-Type: ").append(contentType).append("\r\n")
            if (method == "PROPFIND") append("Depth: 1\r\n")
            append("Content-Length: ").append(payload.size).append("\r\n")
            append("Connection: close\r\n\r\n")
        }.toString().toByteArray(Charsets.ISO_8859_1)

        val socket: Socket = if (secure) sslSocket(host, port) else Socket()
        return try {
            if (!secure) socket.connect(InetSocketAddress(host, port), 12_000)
            socket.soTimeout = 30_000
            val out = socket.getOutputStream()
            out.write(head)
            if (payload.isNotEmpty()) out.write(payload)
            out.flush()

            val input = BufferedInputStream(socket.getInputStream())
            var code: Int
            var headers: Map<String, String>
            while (true) {
                val status = readAsciiLine(input) ?: throw IOException("WebDAV 响应为空")
                code = Regex("HTTP/\\d(?:\\.\\d)?\\s+(\\d{3})").find(status)
                    ?.groupValues?.get(1)?.toIntOrNull()
                    ?: throw IOException("WebDAV 响应格式异常：$status")
                headers = readHeaders(input)
                if (code != 100) break // 100 Continue 后还有正式响应
            }
            code to readBody(input, code, headers)
        } finally {
            socket.close()
        }
    }

    private fun sslSocket(host: String, port: Int): SSLSocket {
        val socket = SSLSocketFactory.getDefault().createSocket() as SSLSocket
        socket.connect(InetSocketAddress(host, port), 12_000)
        val params = SSLParameters().apply {
            endpointIdentificationAlgorithm = "HTTPS"
            // IP 字面量不能作为 SNI 主机名
            if (!Regex("^\\d+(\\.\\d+){3}$").matches(host) && !host.contains(':')) {
                try { serverNames = listOf(SNIHostName(host)) } catch (_: IllegalArgumentException) { }
            }
        }
        socket.sslParameters = params
        socket.startHandshake()
        return socket
    }

    private fun readAsciiLine(input: InputStream): String? {
        val buf = ByteArrayOutputStream()
        while (true) {
            when (val b = input.read()) {
                -1 -> return if (buf.size() == 0) null else buf.toString("ISO-8859-1")
                '\r'.code -> {
                    if (input.read() != '\n'.code) throw IOException("WebDAV 响应行缺少 LF")
                    return buf.toString("ISO-8859-1")
                }
                else -> buf.write(b)
            }
        }
    }

    private fun readHeaders(input: InputStream): Map<String, String> {
        val map = mutableMapOf<String, String>()
        while (true) {
            val line = readAsciiLine(input) ?: throw IOException("WebDAV 响应头提前结束")
            if (line.isEmpty()) return map
            val i = line.indexOf(':')
            if (i > 0) map[line.substring(0, i).trim().lowercase()] = line.substring(i + 1).trim()
        }
    }

    private fun readBody(input: InputStream, code: Int, headers: Map<String, String>): ByteArray {
        if (headers["transfer-encoding"]?.lowercase()?.contains("chunked") == true) return readChunked(input)
        val length = headers["content-length"]?.toLongOrNull()
        if (length != null) return readExactly(input, length.toInt())
        if (code in 100..199 || code == 204 || code == 304) return ByteArray(0)
        return input.readBytes()
    }

    private fun readChunked(input: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        while (true) {
            val line = readAsciiLine(input) ?: throw IOException("chunked 响应提前结束")
            val size = line.substringBefore(';').trim().toIntOrNull(16)
                ?: throw IOException("chunked 长度非法：$line")
            if (size == 0) {
                while (true) {
                    val trailer = readAsciiLine(input) ?: break
                    if (trailer.isEmpty()) break
                }
                break
            }
            out.write(readExactly(input, size))
            readAsciiLine(input) // chunk 末尾 CRLF
        }
        return out.toByteArray()
    }

    private fun readExactly(input: InputStream, size: Int): ByteArray {
        val buf = ByteArray(size)
        var off = 0
        while (off < size) {
            val n = input.read(buf, off, size - off)
            if (n < 0) throw IOException("WebDAV 响应体提前结束")
            off += n
        }
        return buf
    }

    private fun requestRetry(method: String, url: String, body: ByteArray? = null, contentType: String? = null): Pair<Int, ByteArray> {
        return try {
            request(method, url, body, contentType)
        } catch (e: SyncDavException) {
            Thread.sleep(500)
            request(method, url, body, contentType)
        }
    }

    /** 上传；2xx 成功。 */
    override fun put(path: String, data: ByteArray, contentType: String) {
        val (code, _) = requestRetry("PUT", joinUrl(base, path), data, contentType)
        if (code !in 200..299) throw SyncDavException("上传失败 HTTP $code", code)
    }

    /** 下载；404 返回 null，其余非 2xx 抛异常。 */
    override fun getOptional(path: String): ByteArray? {
        val (code, body) = requestRetry("GET", joinUrl(base, path))
        if (code == 404) return null
        if (code !in 200..299) throw SyncDavException("下载失败 HTTP $code", code)
        return body
    }

    override fun get(path: String): ByteArray {
        return getOptional(path) ?: throw SyncDavException("远端不存在：$path", 404)
    }

    /** 远端大小；404 返回 -1；不支持 HEAD 的服务器降级为 GET。 */
    fun headSize(path: String): Long {
        var conn: HttpURLConnection? = null
        return try {
            conn = connect("HEAD", joinUrl(base, path))
            var code = conn.responseCode
            if (code == 405 || code == 501) {
                conn.disconnect()
                conn = connect("GET", joinUrl(base, path))
                conn.setRequestProperty("Range", "bytes=0-0")
                code = conn.responseCode
            }
            if (code !in 200..299) -1
            else conn.getHeaderField("Content-Length")?.toLongOrNull() ?: -1
        } catch (e: IOException) {
            -1
        } finally {
            conn?.disconnect()
        }
    }

    /** 逐级创建目录；405（已存在）视为成功。 */
    override fun mkcolDeep(path: String) {
        val segments = path.trim('/').split('/').filter { it.isNotEmpty() }
        var current = ""
        for (seg in segments) {
            current = "$current/$seg"
            val (code, _) = requestRetry("MKCOL", joinUrl(base, current))
            if (code in intArrayOf(401, 403)) {
                throw SyncDavException("创建目录被拒 HTTP $code", code)
            }
        }
    }

    /** Depth:1 枚举子项名（URL 解码后，排除自身）。404 返回空列表。 */
    override fun propfindChildren(path: String): List<String> {
        val body = """
            <?xml version="1.0" encoding="utf-8"?>
            <D:propfind xmlns:D="DAV:"><D:prop><D:resourcetype/></D:prop></D:propfind>
        """.trimIndent().toByteArray()
        val url = joinUrl(base, path) + "/"
        val (code, data) = requestRetry("PROPFIND", url, body, "application/xml")
        if (code == 404) return emptyList()
        if (code !in 200..299 && code != 207) {
            throw SyncDavException("列目录失败 HTTP $code", code)
        }
        return parsePropfindNames(String(data, Charsets.UTF_8), path.trim('/').substringAfterLast('/'))
    }
}

class SyncDavException(message: String, val status: Int = 0) : IOException(message)

/** multistatus → 子项名列表（命名空间无关，正则提取 href）。 */
internal fun parsePropfindNames(xmlText: String, selfName: String): List<String> {
    val names = mutableListOf<String>()
    val regex = Regex("<(?:[A-Za-z0-9]+:)?href>(.*?)</(?:[A-Za-z0-9]+:)?href>")
    for (match in regex.findAll(xmlText)) {
        val href = java.net.URLDecoder.decode(match.groupValues[1].trim(), "UTF-8")
        val name = href.trimEnd('/').substringAfterLast('/')
        if (name.isNotEmpty() && name != selfName) names.add(name)
    }
    return names
}
