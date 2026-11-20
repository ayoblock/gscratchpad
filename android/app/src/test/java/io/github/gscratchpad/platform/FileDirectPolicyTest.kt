package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FileDirectPolicyTest {

    // ---- resolvePath: externalstorage provider ----

    @Test
    fun primary_前缀映射到共享存储根() {
        assertEquals(
            "/storage/emulated/0/Download/Obsidian/x.md",
            FileDirectPolicy.resolvePath("primary:Download/Obsidian/x.md"),
        )
    }

    @Test
    fun primary_带前导斜杠也不重复() {
        assertEquals(
            "/storage/emulated/0/Download/a.md",
            FileDirectPolicy.resolvePath("primary:/Download/a.md"),
        )
    }

    @Test
    fun raw_前缀直接取绝对路径() {
        assertEquals(
            "/storage/emulated/0/Download/a.md",
            FileDirectPolicy.resolvePath("raw:/storage/emulated/0/Download/a.md"),
        )
    }

    @Test
    fun SD卡卷标映射() {
        assertEquals(
            "/storage/1234-5678/DCIM/a.jpg",
            FileDirectPolicy.resolvePath("1234-5678:DCIM/a.jpg"),
        )
    }

    // ---- resolvePath: Termux provider（documentId 本身是绝对路径）----

    @Test
    fun Termux_绝对路径原样返回() {
        assertEquals(
            "/storage/emulated/0/Download/Obsidian/untitled_2.txt",
            FileDirectPolicy.resolvePath("/storage/emulated/0/Download/Obsidian/untitled_2.txt"),
        )
    }

    @Test
    fun sdcard_别名路径原样返回() {
        assertEquals("/sdcard/Download/a.md", FileDirectPolicy.resolvePath("/sdcard/Download/a.md"))
    }

    // ---- 安全回退：不可映射返回 null ----

    @Test
    fun 空或未知前缀返回null() {
        assertNull(FileDirectPolicy.resolvePath(null))
        assertNull(FileDirectPolicy.resolvePath(""))
        assertNull(FileDirectPolicy.resolvePath("   "))
        // 云盘 provider 的 documentId 通常是 ID 串而非路径
        assertNull(FileDirectPolicy.resolvePath("sandbox:/mnt/data/abc"))
        assertNull(FileDirectPolicy.resolvePath("some-opaque-id-12345"))
    }

    @Test
    fun 路径穿越被拒绝() {
        assertNull(FileDirectPolicy.resolvePath("primary:Download/../../data/data/x"))
        assertNull(FileDirectPolicy.resolvePath("raw:/storage/emulated/0/../../etc/passwd"))
        assertNull(FileDirectPolicy.resolvePath("/storage/emulated/0/../secret"))
    }

    @Test
    fun 非共享存储绝对路径被拒绝() {
        assertNull(FileDirectPolicy.resolvePath("/data/data/com.termux/files/home/x"))
        assertNull(FileDirectPolicy.resolvePath("/system/etc/hosts"))
    }

    @Test
    fun 普通文件名里的冒号不误判为卷标() {
        // "note:2026.md" 的 "note" 不像卷标，应返回 null 而非映射成 /storage/note/...
        assertNull(FileDirectPolicy.resolvePath("note:2026.md"))
    }

    @Test
    fun 重复斜杠被规范化() {
        assertEquals(
            "/storage/emulated/0/Download/a.md",
            FileDirectPolicy.resolvePath("primary:Download//a.md"),
        )
    }

    // ---- shouldUseFileDirect ----

    @Test
    fun 三条件全满足才走File直读() {
        val path = "/storage/emulated/0/Download/a.md"
        assertTrue(FileDirectPolicy.shouldUseFileDirect(true, true, path))
        assertFalse(FileDirectPolicy.shouldUseFileDirect(false, true, path)) // API 不支持
        assertFalse(FileDirectPolicy.shouldUseFileDirect(true, false, path)) // 未授权
        assertFalse(FileDirectPolicy.shouldUseFileDirect(true, true, null)) // 路径不可映射
        assertFalse(FileDirectPolicy.shouldUseFileDirect(true, true, "/data/data/x")) // 越界路径
    }

    // ---- isSharedStoragePath ----

    @Test
    fun 共享存储路径判定() {
        assertTrue(FileDirectPolicy.isSharedStoragePath("/storage/emulated/0/Download/a.md"))
        assertTrue(FileDirectPolicy.isSharedStoragePath("/sdcard/Download/a.md"))
        assertTrue(FileDirectPolicy.isSharedStoragePath("/storage/1234-5678/x"))
        assertFalse(FileDirectPolicy.isSharedStoragePath("/data/data/x"))
        assertFalse(FileDirectPolicy.isSharedStoragePath("/storage/emulated/0/../x"))
        assertFalse(FileDirectPolicy.isSharedStoragePath(null))
        assertFalse(FileDirectPolicy.isSharedStoragePath(""))
    }

    // ---- isOldBackup ----

    @Test
    fun old备份文件判定() {
        assertTrue(FileDirectPolicy.isOldBackup("a.md.old", "a.md"))
        assertTrue(FileDirectPolicy.isOldBackup("a.old.md", "a.md"))
        assertFalse(FileDirectPolicy.isOldBackup("a.md", "a.md"))
        assertFalse(FileDirectPolicy.isOldBackup("b.md.old", "a.md"))
    }
}
