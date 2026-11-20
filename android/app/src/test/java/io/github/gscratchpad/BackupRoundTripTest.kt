package io.github.gscratchpad

import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.importlib.BackupExporter
import io.github.gscratchpad.importlib.DesktopImporter
import io.github.gscratchpad.testing.JdbcSqlDb
import io.github.gscratchpad.testing.TestHarness
import java.io.File
import java.util.zip.ZipFile
import kotlinx.coroutines.test.StandardTestDispatcher
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * 导出/导入往返（方案 §6.1 / §13）：Android 导出包必须能被 Android 导入器原样读回。
 * 语料固定：3 篇文档（open/closed、带图）、1 个文件夹、notes 镜像、assets 资源。
 */
class BackupRoundTripTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var source: TestHarness

    @Before
    fun setUp() {
        source = TestHarness(tmp.newFolder("source"), StandardTestDispatcher())
    }

    @After
    fun tearDown() {
        source.close()
    }

    private val png1x1 = byteArrayOf(
        0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08,
        0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4.toByte(), 0x89.toByte(),
    )

    private fun seedSource() {
        val db = source.db
        db.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf<Any?>(
                "e-001", "导出甲", "md", "# 甲\n\n正文", 0, "open", 4,
                2000.0, 2000.0, "",
            ),
        )
        db.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf<Any?>(
                "e-002", "导出乙", "txt", "纯文本", 1, "closed", 2,
                2001.0, 2001.0, "工作",
            ),
        )
        db.exec(
            "INSERT INTO documents(id, title, format, content, sort_index, state, revision," +
                " created_at, updated_at, folder) VALUES(?,?,?,?,?,?,?,?,?,?)",
            listOf<Any?>(
                "e-003", "导出丙", "md", "![图](assets/pic.png)", 2, "open", 1,
                2002.0, 2002.0, "工作",
            ),
        )
        db.exec(
            "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
            listOf<Any?>("工作", 2000.0),
        )
        db.exec(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
            listOf<Any?>(MetaKeys.SCHEMA_VERSION, "3"),
        )

        File(source.paths.notes, "e-001.md").writeText("# 甲\n\n正文", Charsets.UTF_8)
        File(source.paths.notes, "e-002.txt").writeText("纯文本", Charsets.UTF_8)
        val assetDir = source.paths.assetDir("e-003").apply { mkdirs() }
        File(assetDir, "pic.png").writeBytes(png1x1)
    }

    private fun export(dir: File): Pair<File, File> {
        seedSource()
        val out = File(dir, "export.zip")
        val report = BackupExporter.export(
            target = out,
            appVersion = TestHarness::class.java.simpleName,
            exportedAt = 1700000000.0,
            snapshotDb = { file ->
                source.db.checkpointTruncate()
                source.paths.dbFile.copyTo(file, overwrite = true)
            },
            notesDir = source.paths.notes,
            assetsDir = source.paths.assets,
        )
        assertEquals(0, report.errors.size)
        return out to dir
    }

    @Test
    fun `export produces schema compatible manifest and members`() {
        val dir = tmp.newFolder("export")
        val (zip, _) = export(dir)
        ZipFile(zip).use { zf ->
            val names = zf.entries().asSequence().map { it.name }.toList()
            assertTrue("manifest.json 必须在根", "manifest.json" in names)
            assertTrue("gscratchpad.db 必须在根", "gscratchpad.db" in names)
            assertTrue("镜像必须进 notes/", names.any { it.startsWith("notes/") })
            assertTrue("资源必须进 assets/", names.any { it.startsWith("assets/") })

            val manifest = zf.getInputStream(zf.getEntry("manifest.json")).use { input ->
                JSONObject(input.readBytes().toString(Charsets.UTF_8))
            }
            assertEquals(3, manifest.getInt("schema"))
            assertEquals(1700000000.0, manifest.getDouble("exported_at"), 0.001)
            assertTrue(manifest.getString("app_version").isNotEmpty())
        }
    }

    @Test
    fun `export then import preserves documents folders and revisions`() {
        val dir = tmp.newFolder("roundtrip")
        val (zip, _) = export(dir)

        val target = TestHarness(tmp.newFolder("target"), StandardTestDispatcher())
        try {
            val unpacked = tmp.newFolder("unpacked")
            DesktopImporter.extract(zip, unpacked)
            val report = DesktopImporter(
                targetDb = target.db,
                dao = target.dao,
                assets = target.assets,
                paths = target.paths,
                openSourceDb = { file -> JdbcSqlDb.open(file.absolutePath) },
                resolveSourceUri = { null },
            ).import(unpacked)

            assertEquals(0, report.errors.size)
            assertTrue(report.verified)
            assertEquals(3, report.docsImported)
            assertEquals(1, report.foldersImported)
            assertEquals(0, report.conflicts)

            val docs = target.dao.allDocuments().associateBy { it.id }
            assertEquals(setOf("e-001", "e-002", "e-003"), docs.keys)
            assertEquals("导出甲", docs.getValue("e-001").title)
            assertEquals(4L, docs.getValue("e-001").revision)
            assertEquals("工作", docs.getValue("e-002").folder)
            assertEquals("导出丙", docs.getValue("e-003").title)
            // 图片引用被重写为私有 assets 路径
            assertTrue(docs.getValue("e-003").content.contains("assets/"))
        } finally {
            target.close()
        }
    }
}
