package io.github.gscratchpad

import io.github.gscratchpad.platform.OpenPolicy
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「打开文件」回归锁定：
 *  - BIN 档案缺陷：MIME 过滤器必须放开到全类型通配符，否则华为把 octet-stream 另存的 .md
 *    登记为 BIN 后，text/plain 过滤器会在选择器里把它过滤掉，用户无法选中；
 *  - 放宽过滤器后必须有扩展名白名单兜底，二进制/压缩包不得进入编辑器；
 *  - 白名单覆盖文档 / 脚本 / 源码 / 配置四类纯文本（R31 用户拍板放宽）。
 */
class OpenPolicyTest {
    @Test
    fun `打开过滤器必须放开到通配类型`() {
        assertArrayEquals(arrayOf("*/*"), OpenPolicy.MIME_TYPES)
    }

    @Test
    fun `文档类后缀命中白名单 大小写不敏感`() {
        listOf("笔记.md", "README.MD", "doc.markdown", "doc.MarkDown", "page.html",
            "page.htm", "note.txt", "NOTE.TXT", "readme.rst", "table.csv")
            .forEach { assertTrue(it, OpenPolicy.isSupported(it)) }
    }

    @Test
    fun `脚本与源码类后缀命中白名单`() {
        listOf("run.sh", "BUILD.BASH", "init.py", "main.PY", "a.js", "a.ts", "Main.kt",
            "Main.java", "x.go", "x.rs", "style.css", "q.sql", "Makefile", "Dockerfile")
            .forEach { assertTrue(it, OpenPolicy.isSupported(it)) }
    }

    @Test
    fun `配置与数据类后缀命中白名单`() {
        listOf("app.conf", "app.ini", "settings.yaml", "data.json", "cfg.xml", "Cargo.toml",
            ".gitignore", ".env", "build.gradle", ".dockerignore")
            .forEach { assertTrue(it, OpenPolicy.isSupported(it)) }
    }

    @Test
    fun `二进制与压缩包后缀被拒绝`() {
        listOf("archive.zip", "photo.jpg", "movie.mp4", "font.ttf", "app.apk", "data.bin",
            "lib.so", "paper.pdf", "song.mp3", "image.png")
            .forEach { assertFalse(it, OpenPolicy.isSupported(it)) }
    }

    @Test
    fun `无扩展名与空名被拒绝`() {
        assertFalse(OpenPolicy.isSupported("README"))
        assertFalse(OpenPolicy.isSupported(""))
    }

    @Test
    fun `扩展名取最后一个点之后`() {
        assertEquals("md", OpenPolicy.extensionOf("a.b.c.MD"))
        assertEquals("", OpenPolicy.extensionOf("noext"))
    }

    @Test
    fun `白名单成规模且拒绝提示给出代表后缀`() {
        assertTrue(OpenPolicy.supportedCount() >= 50)
        val msg = OpenPolicy.REJECT_MESSAGE
        listOf(".md", ".txt", ".html", ".sh", ".py", ".conf").forEach { assertTrue(msg.contains(it)) }
    }
}
