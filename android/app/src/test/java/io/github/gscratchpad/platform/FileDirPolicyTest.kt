package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** R40：File 直读工作目录选择器的纯策略单测（路径规则 + 目录过滤，不依赖 Android）。 */
class FileDirPolicyTest {

    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun `规范化_空与尾斜杠回落根`() {
        assertEquals(FileDirPolicy.ROOT, FileDirPolicy.normalize(null))
        assertEquals(FileDirPolicy.ROOT, FileDirPolicy.normalize(""))
        assertEquals(FileDirPolicy.ROOT, FileDirPolicy.normalize("/"))
        assertEquals(FileDirPolicy.ROOT, FileDirPolicy.normalize("  "))
    }

    @Test
    fun `规范化_去尾斜杠`() {
        assertEquals(
            "/storage/emulated/0/Download",
            FileDirPolicy.normalize("/storage/emulated/0/Download///"),
        )
    }

    @Test
    fun `上级目录_根无上级_子目录回根`() {
        assertNull(FileDirPolicy.parentOf(FileDirPolicy.ROOT))
        assertEquals(FileDirPolicy.ROOT, FileDirPolicy.parentOf("/storage/emulated/0/Download"))
        assertEquals(
            "/storage/emulated/0/Download",
            FileDirPolicy.parentOf("/storage/emulated/0/Download/Obsidian"),
        )
    }

    @Test
    fun `越界判定_根与子目录在内_外部拒绝`() {
        assertTrue(FileDirPolicy.isUnderRoot(FileDirPolicy.ROOT))
        assertTrue(FileDirPolicy.isUnderRoot("/storage/emulated/0/Download"))
        assertFalse(FileDirPolicy.isUnderRoot("/data/data/x"))
        assertFalse(FileDirPolicy.isUnderRoot("/storage/emulated/0/../evil"))
    }

    @Test
    fun `限界上级_已在起点为空_子目录回起点_可越级回退`() {
        val root = "/storage/emulated/0/Notes"
        // R43：已在 root（含尾斜杠变体）→ null，UI 禁用「上级」
        assertNull(FileDirPolicy.parentWithin(root, root))
        assertNull(FileDirPolicy.parentWithin("$root/", root))
        // root 的孙目录 → 逐级回退、不停在半路
        assertEquals("$root/2026", FileDirPolicy.parentWithin("$root/2026/11", root))
        assertEquals(root, FileDirPolicy.parentWithin("$root/sub", root))
        // root 之下的更深处逐级回退不停在半路
        assertEquals(
            "/storage/emulated/0/Notes/2026",
            FileDirPolicy.parentWithin("/storage/emulated/0/Notes/2026/11", "/storage/emulated/0"),
        )
        // 起点 normalize（去尾斜杠）一致即可比较
        assertNull(FileDirPolicy.parentWithin("/storage/emulated/0/Notes", "/storage/emulated/0/Notes/"))
    }

    @Test
    fun `显示名与面包屑`() {
        assertEquals("内部存储", FileDirPolicy.label(FileDirPolicy.ROOT))
        assertEquals("Obsidian", FileDirPolicy.label("/storage/emulated/0/Download/Obsidian"))
        assertEquals("内部存储", FileDirPolicy.displayPath(FileDirPolicy.ROOT))
        assertEquals("/Download/Obsidian", FileDirPolicy.displayPath("/storage/emulated/0/Download/Obsidian"))
    }

    @Test
    fun `目录可选性_过滤隐藏与空白`() {
        assertTrue(FileDirPolicy.isSelectableDir("Download"))
        assertTrue(FileDirPolicy.isSelectableDir(" Obsidian "))
        assertFalse(FileDirPolicy.isSelectableDir(".git"))
        assertFalse(FileDirPolicy.isSelectableDir(""))
        assertFalse(FileDirPolicy.isSelectableDir("   "))
    }

    @Test
    fun `列举子目录_排序_排除文件与隐藏目录`() {
        val root = tmp.root
        listOf("zeta", "Alpha", "mid").forEach { tmp.newFolder(it) }
        tmp.newFolder(".hidden")
        tmp.newFile("note.md")
        val names = FileDirPolicy.listSubdirs(root).map { it.name }
        assertEquals(listOf("Alpha", "mid", "zeta"), names)
    }

    @Test
    fun `列举子目录_空目录返回空`() {
        assertTrue(FileDirPolicy.listSubdirs(tmp.root).isEmpty())
        assertTrue(FileDirPolicy.listSubdirs(File(tmp.root, "不存在的目录")).isEmpty())
    }

    @Test
    fun `文档文件判定_白名单后缀_拒绝隐藏与二进制`() {
        assertTrue(FileDirPolicy.isDocFileName("note.md"))
        assertTrue(FileDirPolicy.isDocFileName("README.MD"))
        assertTrue(FileDirPolicy.isDocFileName("a.txt"))
        assertTrue(FileDirPolicy.isDocFileName("page.html"))
        assertFalse(FileDirPolicy.isDocFileName(".hidden.md"))
        assertFalse(FileDirPolicy.isDocFileName("pic.png"))
        assertFalse(FileDirPolicy.isDocFileName("app.apk"))
        assertFalse(FileDirPolicy.isDocFileName("noext"))
    }

    @Test
    fun `列举文档文件_排序_排除子目录与非文档`() {
        val root = tmp.root
        listOf("zeta.md", "Alpha.txt", "mid.markdown").forEach { tmp.newFile(it) }
        tmp.newFile("image.png")
        tmp.newFile(".hidden.md")
        tmp.newFolder("sub.md")
        val names = FileDirPolicy.listDocFiles(root).map { it.name }
        assertEquals(listOf("Alpha.txt", "mid.markdown", "zeta.md"), names)
    }
}
