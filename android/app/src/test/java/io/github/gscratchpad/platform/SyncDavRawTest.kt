package io.github.gscratchpad.platform

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpHandler
import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetSocketAddress
import java.util.Base64
import java.util.Collections

/**
 * 覆盖 Android 上 HttpURLConnection 不支持的 MKCOL/PROPFIND 原生 socket 路径。
 * 桌面 JDK 的 HttpURLConnection 同样拒绝这两个方法，因此本测试是该路径唯一的
 * JVM 回归保障；真实 WebDAV 服务端联调仍需真机。
 */
class SyncDavRawTest {

    private var server: HttpServer? = null
    private val seen = Collections.synchronizedList(mutableListOf<Pair<String, String>>())
    private val depths = Collections.synchronizedList(mutableListOf<String>())
    private val expectedAuth = "Basic " + Base64.getEncoder().encodeToString("admin:123456".toByteArray())

    @After
    fun tearDown() {
        server?.stop(0)
    }

    @Test
    fun `mkcol_and_propfind_use_raw_socket_with_auth_and_chunked_multistatus`() {
        val handler = object : HttpHandler {
            override fun handle(exchange: HttpExchange) {
                try {
                    seen.add(exchange.requestMethod.uppercase() to exchange.requestURI.path)
                    depths.add(exchange.requestHeaders.getFirst("Depth") ?: "")
                    if (exchange.requestHeaders.getFirst("Authorization") != expectedAuth) {
                        exchange.sendResponseHeaders(401, -1)
                        return
                    }
                    when (exchange.requestMethod.uppercase()) {
                        "MKCOL" -> exchange.sendResponseHeaders(201, -1)
                        "PROPFIND" -> {
                            val xml = """
                                <?xml version="1.0" encoding="utf-8"?>
                                <D:multistatus xmlns:D="DAV:">
                                  <D:response><D:href>/dav/sync/</D:href></D:response>
                                  <D:response><D:href>/dav/sync/devA/</D:href></D:response>
                                  <D:response><D:href>/dav/sync/devB/</D:href></D:response>
                                </D:multistatus>
                            """.trimIndent()
                            exchange.responseHeaders.set("Content-Type", "application/xml; charset=utf-8")
                            exchange.sendResponseHeaders(207, 0) // chunked，顺带验证分块解码
                            exchange.responseBody.use { it.write(xml.toByteArray(Charsets.UTF_8)) }
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
        val base = "http://127.0.0.1:${s.address.port}"

        // 内嵌用户名必须被拆出并用于 Basic Auth；两个非标准方法都必须真正到达服务端
        val dav = SyncDav("http://admin@${base.removePrefix("http://")}/dav", "", "123456")
        dav.mkcolDeep("sync/devA")
        val children = dav.propfindChildren("sync")

        assertEquals(listOf("devA", "devB"), children.sorted())
        assertTrue("MKCOL /dav/sync 未到达服务端：seen=$seen", seen.contains("MKCOL" to "/dav/sync"))
        assertTrue("MKCOL /dav/sync/devA 未到达服务端：seen=$seen", seen.contains("MKCOL" to "/dav/sync/devA"))
        assertTrue("PROPFIND 未到达服务端：seen=$seen", seen.contains("PROPFIND" to "/dav/sync/"))
        assertEquals("PROPFIND 必须带 Depth:1", "1", depths.firstOrNull { it == "1" })
    }

    @Test
    fun `wrong_auth_on_mkcol_is_reported`() {
        val handler = object : HttpHandler {
            override fun handle(exchange: HttpExchange) {
                try {
                    exchange.sendResponseHeaders(401, -1)
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
        val dav = SyncDav("http://127.0.0.1:${s.address.port}", "admin", "wrong")
        val err = try {
            dav.mkcolDeep("sync")
            null
        } catch (e: SyncDavException) {
            e
        }
        assertTrue("401 必须报创建目录被拒，实际=$err", err?.message?.contains("401") == true)
    }
}
