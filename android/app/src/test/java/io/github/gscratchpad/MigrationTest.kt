package io.github.gscratchpad

import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.data.Schema
import io.github.gscratchpad.importlib.DesktopImporter
import io.github.gscratchpad.testing.JdbcSqlDb
import io.github.gscratchpad.testing.TestHarness
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Before
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** §6 桌面备份导入：结构校验、冲突策略、图片重写、meta 过滤与报告。 */
class MigrationTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var harness: TestHarness

    @Before
    fun setUp() {
        harness = TestHarness(tmp.newFolder("target"), StandardTestDispatcher())
    }

    @After
    fun tearDown() {
        if (::harness.isInitialized) harness.close()
    }

    private fun buildBackup(dir: File): File {
        dir.mkdirs()
        val dbFile = File(dir, "gscratchpad.db")
        val source = JdbcSqlDb.open(dbFile.absolutePath)
        Schema.statements(Schema.DDL).forEach { source.exec(it) }
        source.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf(
                "doc-a", "读书笔记", "md",
                "段落\n\n![封面](../photo.png)\n", 0, "open", 7L, 1.0, 100.0, "项目",
            ),
        )
        source.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf("doc-b", "旧版本", "txt", "旧内容", 1, "closed", 2L, 1.0, 50.0, ""),
        )
        source.exec("INSERT INTO folders(name, created_at) VALUES(?,?)", listOf("项目", 0.0))
        source.exec("INSERT INTO meta(key, value) VALUES(?,?)", listOf(MetaKeys.ACTIVE_DOC, "doc-a"))
        source.exec("INSERT INTO meta(key, value) VALUES(?,?)", listOf(MetaKeys.VIEW_MODE, "split"))
        source.exec("INSERT INTO meta(key, value) VALUES(?,?)", listOf(MetaKeys.WINDOW_W, "1280"))
        source.exec("INSERT INTO meta(key, value) VALUES(?,?)", listOf(MetaKeys.FS_ROOT, "/home/u"))
        source.exec(
            "INSERT INTO meta(key, value) VALUES(?,?)",
            listOf(MetaKeys.sourcePath("doc-a"), "D:/notes/a.md"),
        )
        source.exec("PRAGMA wal_checkpoint(TRUNCATE)")
        source.close()

        File(dir, "manifest.json").writeText(
            """{"schema":3,"app_version":"1.14.3","exported_at":1700000000}""",
        )
        val images = File(dir, "assets").apply { mkdirs() }
        File(images, "photo.png").writeBytes(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x01, 0x02))
        return dir
    }

    @Test
    fun `imports documents, skips window geometry, rewrites images`() = runTest(harness.dispatcher) {
        harness.dao.setMeta("unrelated", "keep")

        val backup = buildBackup(tmp.newFolder("backup"))
        val importer = DesktopImporter(
            targetDb = harness.db,
            dao = harness.dao,
            assets = harness.assets,
            paths = harness.paths,
            openSourceDb = { JdbcSqlDb.open(it.absolutePath) },
            resolveSourceUri = { null },
        )
        val report = importer.import(backup)

        assertTrue(report.errors.toString(), report.errors.isEmpty())
        assertEquals(2, report.docsInSource)
        assertEquals(2, report.docsImported)
        assertEquals("项目", harness.dao.get("doc-a")!!.folder)
        assertNotNull(harness.dao.get("doc-b"))
        assertEquals(7L, harness.dao.revisionOf("doc-a"))

        val content = harness.dao.get("doc-a")!!.content
        assertTrue("图片应重写为私有 assets 引用：$content", content.contains("assets/doc-a/"))
        assertFalse(content.contains("../photo.png"))
        val assetDir = File(harness.paths.assets, "doc-a")
        assertEquals(1, assetDir.listFiles()!!.size)

        // meta：view_mode 导入，window_w / fs_root / source_path 过滤
        assertEquals("split", harness.dao.getMeta(MetaKeys.VIEW_MODE))
        assertEquals(null, harness.dao.getMeta(MetaKeys.WINDOW_W))
        assertEquals(null, harness.dao.getMeta(MetaKeys.FS_ROOT))
        assertEquals(1, report.deadPaths)
        assertEquals("", harness.dao.getMeta(MetaKeys.sourcePath("doc-a")))

        assertTrue(report.verified)
    }

    @Test
    fun `rejects wrong schema version`() = runTest(harness.dispatcher) {
        val backup = tmp.newFolder("backup")
        File(backup, "manifest.json").writeText("""{"schema":2}""")
        val importer = DesktopImporter(
            harness.db, harness.dao, harness.assets, harness.paths,
            openSourceDb = { JdbcSqlDb.open(it.absolutePath) },
        )
        val report = importer.import(backup)
        assertFalse(report.errors.isEmpty())
        assertEquals(0, report.docsImported)
        assertFalse(report.verified)
    }

    @Test
    fun `conflict keeps newer revision and writes loser copy`() = runTest(harness.dispatcher) {
        val keep = harness.repo.create(io.github.gscratchpad.domain.model.Format.MD, "本地新")
        harness.repo.saveNow(keep.id, "本地较新内容", 3)

        val backup = buildBackup(tmp.newFolder("backup"))
        // 把源库 doc-a 指向同一 id，源 revision=1 < 本地 3
        val source = JdbcSqlDb.open(File(backup, "gscratchpad.db").absolutePath)
        source.exec("UPDATE documents SET revision=1, content='源旧内容' WHERE id='doc-a'")
        source.close()

        val importer = DesktopImporter(
            harness.db, harness.dao, harness.assets, harness.paths,
            openSourceDb = { JdbcSqlDb.open(it.absolutePath) },
        )
        // 制造同 id 冲突：把本地文档 id 改成 doc-a
        harness.db.exec("DELETE FROM documents WHERE id=?", listOf(keep.id))
        harness.db.exec(
            "INSERT INTO documents(id, title, format, content, revision, updated_at)" +
                " VALUES('doc-a','本地新','md','本地较新内容',3,200.0)",
        )

        val report = importer.import(backup)
        assertEquals(3L, harness.dao.revisionOf("doc-a"))
        assertEquals("本地较新内容", harness.dao.get("doc-a")!!.content)
        assertTrue(report.conflicts >= 1)
        assertTrue(File(harness.paths.conflicts, "doc-a.md").readText().contains("源旧内容"))
    }
}

