package io.github.gscratchpad.platform

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpHandler
import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.net.InetSocketAddress
import java.nio.file.Files

/** R50：每设备独立备份名 + 旧名只读兼容 + PROPFIND 候选解析。 */
class CloudBackupTest {

    private var server: HttpServer? = null
    private val remote = mutableMapOf<String, ByteArray>()

    @After
    fun tearDown() {
        server?.stop(0)
    }

    private fun startServer() {
        val handler = object : HttpHandler {
            override fun handle(exchange: HttpExchange) {
                try {
                    val path = exchange.requestURI.path.trimStart('/')
                    when (exchange.requestMethod.uppercase()) {
                        "PUT" -> {
                            remote[path] = exchange.requestBody.readBytes()
                            exchange.sendResponseHeaders(201, -1)
                        }
                        "GET" -> {
                            val bytes = remote[path]
                            if (bytes == null) {
                                exchange.sendResponseHeaders(404, -1)
                            } else {
                                exchange.sendResponseHeaders(200, bytes.size.toLong())
                                exchange.responseBody.use { it.write(bytes) }
                            }
                        }
                        "PROPFIND" -> {
                            val self = path.trimEnd('/').substringAfterLast('/')
                            val entries = remote.keys.filter { it.startsWith(self) }
                            val xml = buildString {
                                append("<?xml version=\"1.0\"?><D:multistatus xmlns:D=\"DAV:\">")
                                append("<D:response><D:href>/").append(self).append("/</D:href></D:response>")
                                entries.forEach { name ->
                                    append("<D:response><D:href>/").append(name)
                                    append("</D:href><D:propstat><D:prop>")
                                    append("<D:getcontentlength>").append(remote[name]!!.size).append("</D:getcontentlength>")
                                    append("<D:getlastmodified>Tue, 24 Nov 2026 18:00:00 GMT</D:getlastmodified>")
                                    append("</D:prop></D:propstat></D:response>")
                                }
                                append("</D:multistatus>")
                            }.toByteArray(Charsets.UTF_8)
                            exchange.sendResponseHeaders(207, xml.size.toLong())
                            exchange.responseBody.use { it.write(xml) }
                        }
                        else -> exchange.sendResponseHeaders(405, -1)
                    }
                } finally {
                    exchange.close()
                }
            }
        }
        val s = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/", handler)
            executor = null
            start()
        }
        server = s
    }

    @Test
    fun `device names are unique and legacy names stay readable`() {
        val a = CloudBackup.remoteName("devA")
        val b = CloudBackup.remoteName("devB")
        assertEquals("gscratchpad-cloud-devA.zip", a)
        assertTrue(a != b)
        assertTrue(CloudBackup.isBackupZip(a))
        assertTrue(CloudBackup.isBackupZip(CloudBackup.REMOTE_NAME))
        assertTrue(CloudBackup.isBackupZip(CloudBackup.DESKTOP_LEGACY_NAME))
        assertFalse(CloudBackup.isBackupZip("notes.md"))
        assertFalse(CloudBackup.isBackupZip("gscratchpad-cloud-.zip"))
    }

    @Test
    fun `upload writes device name and download reads it back`() {
        startServer()
        val cfg = CloudBackup.Config("http://127.0.0.1:${server!!.address.port}/dav", "", "")
        val name = CloudBackup.remoteName("devA")
        val tmp = Files.createTempFile("gs-upload", ".zip").toFile()
        tmp.writeBytes("zip-bytes".toByteArray())
        val up = CloudBackup.upload(cfg, tmp, name)
        assertTrue("upload=${up.detail}", up.ok)
        assertTrue(remote.containsKey("dav/$name"))

        val target = Files.createTempFile("gs-download", ".zip").toFile()
        val down = CloudBackup.download(cfg, target, name)
        assertTrue("download=${down.detail}", down.ok)
        assertEquals("zip-bytes", target.readText())
        tmp.delete()
        target.delete()
    }

    @Test
    fun `propfind returns size and modified for zip candidates`() {
        startServer()
        val cfg = CloudBackup.Config("http://127.0.0.1:${server!!.address.port}/dav", "", "")
        val name = CloudBackup.remoteName("devB")
        remote["dav/${CloudBackup.REMOTE_NAME}"] = "old".toByteArray()
        remote["dav/$name"] = "12345".toByteArray()
        remote["dav/notes.md"] = "x".toByteArray()

        val dav = SyncDav(cfg.baseUrl, "", "")
        val entries = dav.propfindEntries("dav").filter { CloudBackup.isBackupZip(it.name) }
        assertEquals(2, entries.size)
        val fresh = entries.first { it.name == name }
        assertEquals(5L, fresh.size)
        assertEquals("Tue, 24 Nov 2026 18:00:00 GMT", fresh.modified)
        assertTrue(entries.any { it.name == CloudBackup.REMOTE_NAME })
    }
}
