package io.github.gscratchpad

import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.data.Schema
import io.github.gscratchpad.importlib.DesktopImporter
import io.github.gscratchpad.testing.JdbcSqlDb
import io.github.gscratchpad.testing.TestHarness
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.test.StandardTestDispatcher
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * 契约测试（方案 §11「契约」层）：
 * 固定桌面备份包 → Android 导入 → 断言文档数 / 标题 / 顺序 / 文件夹 / revision / 正文哈希。
 *
 * 备份包按 §6.1 结构现场生成（manifest.json + gscratchpad.db + assets/），
 * 语料固定，任何一端 schema 或导入逻辑变更都会在这里暴露。
 */
class DesktopBackupContractTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var harness: TestHarness

    @Before
    fun setUp() {
        harness = TestHarness(tmp.newFolder("target"), StandardTestDispatcher())
    }

    @After
    fun tearDown() {
        harness.close()
    }

    private data class SourceDoc(
        val id: String,
        val title: String,
        val format: String,
        val content: String,
        val sortIndex: Int,
        val folder: String,
        val revision: Int,
        val updatedAt: Double,
    )

    private val corpus = listOf(
        SourceDoc("d-001", "第一篇", "md", "# 标题\n\n正文 甲乙丙。", 0, "", 3, 1000.0),
        SourceDoc("d-002", "第二篇", "txt", "纯文本 CRLF 行\r\n第二行", 1, "工作", 5, 1001.0),
        SourceDoc("d-003", "带图篇", "md", "段落\n\n![示意图](assets/pic.png)\n\n结尾", 2, "工作", 2, 1002.0),
        SourceDoc("d-004", "已关闭篇", "html", "<p>html 正文</p>", 3, "归档", 1, 1003.0),
        SourceDoc("d-005", "空文档", "md", "", 4, "", 0, 1004.0),
    )

    private fun sha256(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    /** 生成符合 §6.1 的备份 zip。 */
    private fun buildBackup(dir: File): File {
        val root = File(dir, "gscratchpad-backup").apply { mkdirs() }
        File(root, "manifest.json").writeText(
            """{"schema":3,"app_version":"1.14.3","exported_at":1700000000}""",
            Charsets.UTF_8,
        )

        val dbFile = File(root, "gscratchpad.db")
        val src = JdbcSqlDb.open(dbFile.absolutePath)
        Schema.statements(Schema.DDL).forEach { src.exec(it) }
        src.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>(MetaKeys.SCHEMA_VERSION, "3"),
        )
        src.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>(MetaKeys.WINDOW_W, "1280"),
        )
        src.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>(MetaKeys.sourcePath("d-001"), "/home/u/notes/a.md"),
        )
        src.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>("view_mode", "edit"),
        )
        corpus.forEach { d ->
            src.exec(
                "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                    " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
                listOf<Any?>(
                    d.id, d.title, d.format, d.content, d.sortIndex,
                    if (d.title == "已关闭篇") "closed" else "open",
                    d.revision, d.updatedAt, d.updatedAt, d.folder,
                ),
            )
            if (d.folder.isNotEmpty()) {
                src.exec(
                    "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                    listOf<Any?>(d.folder, 0.0),
                )
            }
        }
        src.checkpointTruncate()
        src.close()

        // assets/pic.png：1×1 PNG
        val assetsDir = File(root, "assets").apply { mkdirs() }
        File(assetsDir, "pic.png").writeBytes(PNG_1X1)

        val zip = File(dir, "backup.zip")
        ZipOutputStream(zip.outputStream()).use { out ->
            root.walkTopDown().filter { it.isFile }.forEach { f ->
                val name = f.relativeTo(root).invariantSeparatorsPath
                out.putNextEntry(ZipEntry(name))
                f.inputStream().use { it.copyTo(out) }
                out.closeEntry()
            }
        }
        return zip
    }

    private fun importer() = DesktopImporter(
        targetDb = harness.db,
        dao = harness.dao,
        assets = harness.assets,
        paths = harness.paths,
        openSourceDb = { file -> JdbcSqlDb.open(file.absolutePath) },
        resolveSourceUri = { null },
    )

    @Test
    fun `backup imports with full fidelity`() {
        val zip = buildBackup(tmp.newFolder("backup"))
        val unpacked = tmp.newFolder("unpacked")
        DesktopImporter.extract(zip, unpacked)
        val report = importer().import(unpacked)

        assertEquals(0, report.errors.size)
        assertTrue(report.verified)
        assertEquals(5, report.docsInSource)
        assertEquals(5, report.docsImported)
        assertEquals(0, report.conflicts)
        assertEquals(2, report.foldersImported)

        // 文档数 / 标题 / 顺序 / 文件夹 / revision / 正文哈希
        val rows = harness.dao.allDocuments()
        assertEquals(5, rows.size)
        val byId = rows.associateBy { it.id }
        assertEquals(listOf("d-005", "d-001", "d-004", "d-002", "d-003").sorted(), rows.map { it.id }.sorted())
        corpus.forEach { d ->
            val doc = byId.getValue(d.id)
            assertEquals(d.title, doc.title)
            assertEquals(d.revision.toLong(), doc.revision)
            assertEquals(d.folder, doc.folder)
            if (d.title != "带图篇") {
                assertEquals("content hash ${d.id}", sha256(d.content), sha256(doc.content))
            }
        }

        // 顺序：sort_index 单调
        val ordered = rows.sortedBy { it.sortIndex }.map { it.id }
        assertEquals(listOf("d-001", "d-002", "d-003", "d-004", "d-005"), ordered)

        // 窗口几何与 fs_root 不得导入
        assertEquals(null, harness.dao.getMeta(MetaKeys.WINDOW_W))
        // 普通 meta 保留
        assertEquals("edit", harness.dao.getMeta("view_mode"))
        // source_path 未匹配到已授权树 → 置空并计入 deadPaths
        assertEquals(1, report.deadPaths)
        assertEquals("", harness.dao.getMeta(MetaKeys.sourcePath("d-001")))
    }

    @Test
    fun `images are rewritten into private assets`() {
        val zip = buildBackup(tmp.newFolder("backup"))
        val unpacked = tmp.newFolder("unpacked")
        DesktopImporter.extract(zip, unpacked)
        val report = importer().import(unpacked)

        assertEquals(0, report.brokenImages)
        val doc = harness.dao.get("d-003")!!
        assertTrue("正文应改写为私有 assets 引用", doc.content.contains("assets/d-003/"))
        assertFalse(doc.content.contains("](assets/pic.png)"))
        val files = harness.assets.assetsOf("d-003")
        assertEquals(1, files.size)
        assertTrue(files[0].name.endsWith(".png"))
        // 引用路径必须指向实际文件
        val rel = Regex("!\\[[^]]*]\\((assets/[^)]+)\\)").find(doc.content)!!.groupValues[1]
        val onDisk = File(harness.paths.assets, rel.removePrefix("assets/").replaceFirst("d-003/", "d-003/"))
        assertTrue("引用应可解析：$rel", File(harness.paths.root, "assets/d-003/${onDisk.name}").isFile)
    }

    @Test
    fun `conflicting revision keeps newer and preserves loser`() {
        val existingId = "d-001"
        harness.db.exec(
            "INSERT OR REPLACE INTO documents(id, title, format, content, sort_index, state," +
                " revision, created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf<Any?>(existingId, "第一篇", "md", "旧内容", 0, "open", 9, 999.0, 999.0, ""),
        )

        val zip = buildBackup(tmp.newFolder("backup"))
        val unpacked = tmp.newFolder("unpacked")
        DesktopImporter.extract(zip, unpacked)
        val report = importer().import(unpacked)

        // 源 revision 3 < 目标 revision 9 → 保留目标，输家落 conflict 副本
        assertEquals(1, report.conflicts)
        val kept = harness.dao.get(existingId)!!
        assertEquals(9L, kept.revision)
        assertEquals("旧内容", kept.content)
        val conflict = File(harness.paths.conflicts, "$existingId.md")
        assertTrue(conflict.isFile)
        assertEquals(corpus[0].content, conflict.readText(Charsets.UTF_8))
    }

    @Test
    fun `zip slip is rejected`() {
        val dir = tmp.newFolder("evil")
        val zip = File(dir, "evil.zip")
        ZipOutputStream(zip.outputStream()).use { out ->
            out.putNextEntry(ZipEntry("../../escape.txt"))
            out.write("x".toByteArray())
            out.closeEntry()
        }
        val dest = tmp.newFolder("evil-dest")
        val error = runCatching { DesktopImporter.extract(zip, dest) }.exceptionOrNull()
        assertNotNull("越界路径必须拒绝", error)
        assertTrue(error is IllegalArgumentException)
    }

    @Test
    fun `schema mismatch aborts without touching target`() {
        val dir = tmp.newFolder("bad")
        val root = File(dir, "pkg").apply { mkdirs() }
        File(root, "manifest.json").writeText("""{"schema":2}""", Charsets.UTF_8)
        val dbFile = File(root, "gscratchpad.db")
        JdbcSqlDb.open(dbFile.absolutePath).also { db -> Schema.statements(Schema.DDL).forEach { db.exec(it) }; db.close() }

        val before = harness.dao.openDocuments().size
        val report = importer().import(root)
        assertFalse(report.verified)
        assertTrue(report.errors.isNotEmpty())
        assertEquals(before, harness.dao.openDocuments().size)
    }

    companion object {
        val PNG_1X1: ByteArray = byteArrayOf(
            0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15.toByte(), 0xC4.toByte(), 0x89.toByte(),
            0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54,
            0x78, 0x9C.toByte(), 0x63, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01,
            0x0D, 0x0A, 0x2D, 0xB4.toByte(),
            0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE.toByte(), 0x42, 0x60, 0x82.toByte(),
        )
    }
}
