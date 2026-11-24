package io.github.gscratchpad

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpHandler
import com.sun.net.httpserver.HttpServer
import io.github.gscratchpad.data.AppPaths
import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.Schema
import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.platform.DavOps
import io.github.gscratchpad.platform.LocalDocInfo
import io.github.gscratchpad.platform.PeerManifest
import io.github.gscratchpad.platform.SyncDav
import io.github.gscratchpad.platform.SyncDavException
import io.github.gscratchpad.platform.SyncEngine
import io.github.gscratchpad.platform.SyncPlanner
import io.github.gscratchpad.platform.SyncProtocol
import io.github.gscratchpad.platform.SyncState
import io.github.gscratchpad.testing.JdbcSqlDb
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.InetSocketAddress
import java.net.URLDecoder
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

/**
 * sync v1 Android 侧测试（规约 docs/SYNC_PROTOCOL.md）：
 * 1) 纯函数合并规划器 SyncPlanner——SM-01…SM-11 夹具与桌面
 *    `tests/test_sync_merge.py` 逐字段对应，双端判定一致；
 * 2) SyncEngine E2E——内存 DavOps（桌面 JDK 的 HttpURLConnection 拒绝
 *    MKCOL/PROPFIND 自定义方法，无法直连 stub WebDAV；Android 运行时无此限制）+
 *    sqlite-jdbc 真实 DAO，双设备拉推/冲突保全/删除传播/资产同步；
 * 3) SyncDav 传输面——URL 内嵌用户名解析 + Basic 认证（仅 PUT/GET 标准方法）。
 */
class SyncEngineTest {

    @get:Rule
    val tmp = TemporaryFolder()

    // ------------------------------------------------------------ SM 夹具

    private fun entry(id: String, h: String, rev: Long, updatedAt: Double): Map<String, Any?> = mapOf(
        "id" to id,
        "content_hash" to h,
        "revision" to rev,
        "updated_at" to updatedAt,
        "title" to "t",
        "format" to "md",
    )

    private fun peer(
        id: String,
        docs: Map<String, Map<String, Any?>> = emptyMap(),
        deleted: Map<String, Double> = emptyMap(),
    ) = PeerManifest(deviceId = id, deviceName = id, docs = docs, deleted = deleted, folders = emptyList(), exportedAt = 0.0)

    // SM-01 对端新文档 → 应用
    @Test
    fun sm01_new_doc_from_peer() {
        val plan = SyncPlanner.planSync(
            local = emptyMap(),
            ownPushed = emptyMap(),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "H", 1, 100.0)))),
            peerStates = emptyMap(),
            now = 0.0,
        )
        assertEquals(1, plan.applies.size)
        assertEquals("H", plan.newPeers["p"]!!["d1"])
    }

    // SM-02 内容一致 → 仅刷新基线
    @Test
    fun sm02_unchanged_refresh_baseline_only() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("H", 2, 100.0)),
            ownPushed = mapOf("d1" to "H"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "H", 1, 100.0)))),
            peerStates = mapOf("p" to mapOf("d1" to "H")),
            now = 0.0,
        )
        assertTrue(plan.applies.isEmpty())
        assertEquals("H", plan.newPeers["p"]!!["d1"])
    }

    // SM-03 仅对端变（本地干净）→ 应用
    @Test
    fun sm03_remote_changed_local_clean() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("H1", 2, 100.0)),
            ownPushed = mapOf("d1" to "H1"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "H2", 3, 200.0)))),
            peerStates = mapOf("p" to mapOf("d1" to "H1")),
            now = 0.0,
        )
        assertEquals(1, plan.applies.size)
        assertEquals(0, plan.conflicts)
    }

    // SM-04 双变冲突，对端新 → 对端胜（应用 + 本地保全）
    @Test
    fun sm04_conflict_peer_newer_wins() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("Hlocal", 2, 100.0)),
            ownPushed = mapOf("d1" to "H0"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "Hpeer", 3, 200.0)))),
            peerStates = mapOf("p" to mapOf("d1" to "H0")),
            now = 0.0,
        )
        assertEquals(1, plan.conflicts)
        assertEquals(1, plan.applies.size)
        assertTrue(plan.preserveLocalBeforeApply.contains("d1"))
    }

    // SM-05 双变冲突，本地新 → 本地胜（对端保全）
    @Test
    fun sm05_conflict_local_newer_wins() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("Hlocal", 2, 300.0)),
            ownPushed = mapOf("d1" to "H0"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "Hpeer", 3, 200.0)))),
            peerStates = mapOf("p" to mapOf("d1" to "H0")),
            now = 0.0,
        )
        assertEquals(1, plan.conflicts)
        assertTrue(plan.applies.isEmpty())
        assertEquals(listOf("p" to "d1"), plan.preservePeer)
    }

    // SM-06 双变平局 → 本地胜
    @Test
    fun sm06_conflict_tie_local_wins() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("Hlocal", 2, 200.0)),
            ownPushed = mapOf("d1" to "H0"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "Hpeer", 3, 200.0)))),
            peerStates = mapOf("p" to mapOf("d1" to "H0")),
            now = 0.0,
        )
        assertTrue(plan.applies.isEmpty())
        assertEquals(listOf("p" to "d1"), plan.preservePeer)
    }

    // SM-07 墓碑删除本地文档
    @Test
    fun sm07_tombstone_deletes_local() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("H1", 2, 100.0)),
            ownPushed = mapOf("d1" to "H1"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", deleted = mapOf("d1" to 200.0))),
            peerStates = mapOf("p" to mapOf("d1" to "H1")),
            now = 0.0,
        )
        assertEquals(listOf("d1"), plan.deletes)
        assertEquals(mapOf("d1" to 200.0), plan.tombstonesLearned)
        assertTrue(plan.newPeers["p"]!!.isEmpty())
    }

    // SM-08 本地编辑新于墓碑 → 文档胜
    @Test
    fun sm08_local_edit_beats_tombstone() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("Hedit", 5, 300.0)),
            ownPushed = mapOf("d1" to "H0"),
            ownDeleted = emptyMap(),
            peers = listOf(peer("p", deleted = mapOf("d1" to 200.0))),
            peerStates = mapOf("p" to mapOf("d1" to "H0")),
            now = 0.0,
        )
        assertTrue(plan.deletes.isEmpty())
        assertTrue(plan.tombstonesLearned.isEmpty())
        assertEquals(1, plan.deleteVsEdit)
    }

    // SM-09 本地墓碑 + 对端重建 → 恢复
    @Test
    fun sm09_restore_deleted_doc_from_peer() {
        val plan = SyncPlanner.planSync(
            local = emptyMap(),
            ownPushed = emptyMap(),
            ownDeleted = mapOf("d1" to 100.0),
            peers = listOf(peer("p", mapOf("d1" to entry("d1", "H", 9, 400.0)))),
            peerStates = emptyMap(),
            now = 0.0,
        )
        assertEquals(listOf("d1"), plan.undelete)
        assertEquals(1, plan.applies.size)
    }

    // SM-10 墓碑压过对端陈旧条目（150 < 墓碑 200），不得复活
    @Test
    fun sm10_tombstone_suppresses_stale_peer_entry() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("H1", 2, 100.0)),
            ownPushed = mapOf("d1" to "H1"),
            ownDeleted = emptyMap(),
            peers = listOf(
                peer("p1", deleted = mapOf("d1" to 200.0)),
                peer("p2", mapOf("d1" to entry("d1", "H2", 9, 150.0))),
            ),
            peerStates = mapOf("p1" to mapOf("d1" to "H1"), "p2" to mapOf("d1" to "H1")),
            now = 0.0,
        )
        assertEquals(listOf("d1"), plan.deletes)
        assertTrue("p2 的陈旧条目（150 < 墓碑 200）不得复活 d1", plan.applies.isEmpty())
    }

    // SM-11 对端文档（500）新于墓碑（200）→ 恢复
    @Test
    fun sm11_peer_doc_newer_than_tombstone_restores() {
        val plan = SyncPlanner.planSync(
            local = mapOf("d1" to LocalDocInfo("H1", 2, 100.0)),
            ownPushed = mapOf("d1" to "H1"),
            ownDeleted = emptyMap(),
            peers = listOf(
                peer("p1", deleted = mapOf("d1" to 200.0)),
                peer("p2", mapOf("d1" to entry("d1", "H2", 9, 500.0))),
            ),
            peerStates = mapOf("p1" to mapOf("d1" to "H1"), "p2" to mapOf("d1" to "H1")),
            now = 0.0,
        )
        assertEquals(listOf("d1"), plan.undelete)
        assertEquals(1, plan.applies.size)
    }

    // ------------------------------------------------------------ 引擎 E2E

    private class Device(root: File) {
        val paths: AppPaths = AppPaths(root).ensureDirs()
        private val db = JdbcSqlDb.open(paths.dbFile.absolutePath).also {
            Schema.statements(Schema.DDL).forEach { sql -> it.exec(sql) }
        }
        val dao = DocumentDao(db)
        val stateFile = File(paths.root, "sync-state.json")

        fun putDoc(id: String, content: String, updatedAt: Double) {
            dao.insert(
                Document(
                    id = id, title = id, format = Format.MD, content = content,
                    revision = 1L, createdAt = updatedAt, updatedAt = updatedAt,
                )
            )
        }

        fun applyRemote(id: String, content: String, updatedAt: Double) {
            val old = dao.get(id)
            dao.applyRemote(
                id = id, title = old?.title ?: id, format = Format.MD, content = content,
                sortIndex = old?.sortIndex ?: 0, state = DocState.OPEN,
                revision = old?.revision ?: 0, createdAt = old?.createdAt ?: updatedAt,
                updatedAt = updatedAt, folder = old?.folder ?: "",
            )
        }

        fun close() = db.close()
    }

    /** 内存 WebDAV（[DavOps] 全量语义：PUT 覆盖、GET 404、MKCOL 建目录、PROPFIND 列直系子项）。 */
    private class MemoryDav : DavOps {
        val files = ConcurrentHashMap<String, ByteArray>()
        val dirs: MutableSet<String> = ConcurrentHashMap.newKeySet()

        override fun put(path: String, data: ByteArray, contentType: String) {
            files[path] = data
        }

        override fun getOptional(path: String): ByteArray? = files[path]

        override fun get(path: String): ByteArray =
            files[path] ?: throw SyncDavException("远端不存在：$path", 404)

        override fun mkcolDeep(path: String) {
            var current = ""
            path.trim('/').split('/').filter { it.isNotEmpty() }.forEach { seg ->
                current = if (current.isEmpty()) seg else "$current/$seg"
                dirs.add(current)
            }
        }

        override fun propfindChildren(path: String): List<String> {
            val p = path.trim('/')
            return (dirs + files.keys)
                .filter { it.startsWith("$p/") && it.substringAfter("$p/").indexOf('/') < 0 }
                .map { it.substringAfterLast('/') }
                .distinct()
                .sorted()
        }
    }

    private val devices = mutableListOf<Device>()
    private var server: HttpServer? = null

    private fun newDevice(name: String): Device {
        val d = Device(tmp.newFolder(name))
        devices.add(d)
        return d
    }

    private fun engine(d: Device, dav: DavOps) = SyncEngine(d.dao, d.paths, dav)

    @After
    fun tearDown() {
        devices.forEach { it.close() }
        server?.stop(0)
    }

    private fun preservedFiles(d: Device): List<Pair<String, String>> {
        val rec = d.paths.recovery
        if (!rec.isDirectory) return emptyList()
        return rec.walkTopDown().filter { it.isFile }
            .map { it.name to it.readText() }.toList()
    }

    @Test
    fun `two_device_sync_flow_push_pull_update_back`() {
        val dav = MemoryDav()
        val a = newDevice("devA")
        val b = newDevice("devB")
        val ea = engine(a, dav)
        val eb = engine(b, dav)

        a.putDoc("d1", "v1", 100.0)
        val r1 = ea.run()
        assertTrue("msg=${r1.message}", r1.ok)
        assertEquals(1, r1.pushedDocs)

        val r2 = eb.run()
        assertTrue("msg=${r2.message}", r2.ok)
        assertEquals(1, r2.applied)
        assertEquals("v1", b.dao.get("d1")?.content)

        b.applyRemote("d1", "v2", 200.0)
        val r3 = eb.run()
        assertTrue("msg=${r3.message}", r3.ok)

        val r4 = ea.run()
        assertTrue("msg=${r4.message}", r4.ok)
        assertEquals(1, r4.applied)
        assertEquals("v2", a.dao.get("d1")?.content)
    }

    @Test
    fun `conflict_loser_preserved_in_recovery`() {
        val dav = MemoryDav()
        val a = newDevice("devA")
        val b = newDevice("devB")

        // 双方都基于 H0 推送过，之后各自分叉编辑
        val h0 = SyncProtocol.contentHash("base")
        for ((d, own) in listOf(a to "A-edit", b to "B-edit")) {
            val st = SyncState().apply {
                deviceId = if (d === a) "devA" else "devB"
                deviceName = deviceId
                ownPushed["d1"] = h0
            }
            SyncState.save(d.stateFile, st)
            d.putDoc("d1", own, if (d === a) 100.0 else 200.0)
        }

        // B 先推（分叉编辑入云端），A 再拉：对端 B（200）比本地 A（100）新 → B 胜，A 侧应用 + 保全
        val rb = engine(b, dav).run()
        val r = engine(a, dav).run()
        assertTrue("msg=${r.message}", r.ok)
        assertEquals(1, r.conflicts)
        assertEquals("B-edit", a.dao.get("d1")?.content)
        val kept = preservedFiles(a).firstOrNull { it.second == "A-edit" }
        assertNotNull("败者本地正文应保全到 recovery/", kept)

        // B 再跑：对端 A manifest 已是 B 的内容（基线刷新），无冲突
        val r2 = engine(b, dav).run()
        assertTrue("msg=${r2.message}", r2.ok)
        assertEquals("B-edit", b.dao.get("d1")?.content)
    }

    @Test
    fun `delete_propagation_with_preservation`() {
        val dav = MemoryDav()
        val a = newDevice("devA")
        val b = newDevice("devB")
        val ea = engine(a, dav)
        val eb = engine(b, dav)

        a.putDoc("d1", "v1", 100.0)
        val r0 = ea.run()
        assertTrue("msg=${r0.message}", r0.ok)
        val r1 = eb.run()
        assertTrue("msg=${r1.message}", r1.ok)
        assertEquals("v1", b.dao.get("d1")?.content)

        // B 删除（repo 路径同款：墓碑 + 删行）
        val st = SyncState.load(b.stateFile)
        st.addDeleted("d1", 200.0)
        SyncState.save(b.stateFile, st)
        b.dao.delete("d1")
        val r2 = eb.run()
        assertTrue("msg=${r2.message}", r2.ok)

        // A 拉到墓碑 → 本地删除 + 正文保全
        val r = ea.run()
        assertTrue("msg=${r.message}", r.ok)
        assertEquals(1, r.deleted)
        assertNull(a.dao.get("d1"))
        val kept = preservedFiles(a).firstOrNull { it.first == "d1-deleted.md" && it.second == "v1" }
        assertNotNull("被删文档正文应保全到 recovery/", kept)

        // A 推送墓碑后，B 无本地文档也不复活
        val r3 = eb.run()
        assertTrue("msg=${r3.message}", r3.ok)
        assertNull(b.dao.get("d1"))
    }

    @Test
    fun `assets_sync_between_devices`() {
        val dav = MemoryDav()
        val a = newDevice("devA")
        val b = newDevice("devB")

        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x01, 0x02, 0x03)
        a.putDoc("d1", "v1", 100.0)
        File(a.paths.assetDir("d1").apply { mkdirs() }, "img.png").writeBytes(png)

        val r1 = engine(a, dav).run()
        assertTrue("msg=${r1.message}", r1.ok)

        val r2 = engine(b, dav).run()
        assertTrue("msg=${r2.message}", r2.ok)
        assertEquals(1, r2.applied)
        val got = File(b.paths.assetDir("d1"), "img.png")
        assertTrue("资产应同步到对端", got.isFile)
        assertArrayEquals(png, got.readBytes())
    }

    @Test
    fun `state_file_roundtrip`() {
        val dir = tmp.newFolder("state")
        val f = File(dir, "sync-state.json")
        val st = SyncState().apply {
            deviceId = "devX"
            deviceName = "X"
            deleted["d1"] = 200.0
            ownPushed["d1"] = "H1"
            ownFoldersHash = "FH"
            ownPushedDeleted["d1"] = 200.0
            ownAssetsPushed.add("d1/img.png")
            peers["devY"] = mutableMapOf("d1" to "H1")
        }
        SyncState.save(f, st)
        val loaded = SyncState.load(f)
        assertEquals("devX", loaded.deviceId)
        assertEquals("X", loaded.deviceName)
        assertEquals(200.0, loaded.deleted["d1"]!!, 1e-9)
        assertEquals("H1", loaded.ownPushed["d1"])
        assertEquals("FH", loaded.ownFoldersHash)
        assertEquals(200.0, loaded.ownPushedDeleted["d1"]!!, 1e-9)
        assertEquals(setOf("d1/img.png"), loaded.ownAssetsPushed)
        assertEquals("H1", loaded.peers["devY"]!!["d1"])
    }

    @Test
    fun `quiet_success_second_run_zero_ops`() {
        val dav = MemoryDav()
        val a = newDevice("devA")
        a.putDoc("d1", "v1", 100.0)
        val e = engine(a, dav)
        val r1 = e.run()
        assertTrue("msg=${r1.message}", r1.ok)
        val r2 = e.run()
        assertTrue("msg=${r2.message}", r2.ok)
        assertEquals(0, r2.applied)
        assertEquals(0, r2.deleted)
        assertEquals(0, r2.conflicts)
    }

    // ------------------------------------------------------------ 传输面

    @Test
    fun `auth_401_and_embedded_user_parsing`() {
        val handler = object : HttpHandler {
            override fun handle(exchange: HttpExchange) {
                try {
                    val expect = "Basic " + Base64.getEncoder().encodeToString("admin:123456".toByteArray())
                    if (exchange.requestHeaders.getFirst("Authorization") != expect) {
                        exchange.sendResponseHeaders(401, -1)
                        return
                    }
                    when (exchange.requestMethod.uppercase()) {
                        "PUT" -> {
                            exchange.requestBody.readBytes()
                            exchange.sendResponseHeaders(201, -1)
                        }
                        "GET" -> {
                            val body = "hello".toByteArray()
                            exchange.sendResponseHeaders(200, body.size.toLong())
                            exchange.responseBody.use { it.write(body) }
                        }
                        else -> exchange.sendResponseHeaders(405, -1)
                    }
                } finally {
                    exchange.close()
                }
            }
        }
        val s = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server = s
        s.createContext("/", handler)
        s.executor = null
        s.start()
        val base = "http://127.0.0.1:${s.address.port}"

        // 内嵌用户名解析：http://admin@host → user=admin
        val dav = SyncDav("http://admin@${base.removePrefix("http://")}", "", "123456")
        assertEquals("admin", dav.user)
        dav.put("sync/probe.txt", "hello".toByteArray())
        assertEquals("hello", String(dav.get("sync/probe.txt")!!))

        val bad = SyncDav(base, "admin", "wrong")
        try {
            bad.put("sync/probe2.txt", "x".toByteArray())
            fail("错误密码应被拒绝（401）")
        } catch (e: SyncDavException) {
            assertTrue(e.message!!.contains("401"))
        }
    }
}
