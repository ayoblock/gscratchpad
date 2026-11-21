package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * R42：分版本存储访问判定（重建于 R45——原文件误放于 gscatchpad/ 目录且未入库，
 * R45 文档清洗时随目录删除，按同一覆盖口径重写）。
 */
class StorageAccessTest {

    @Test
    fun `API30以上才支持所有文件访问`() {
        assertFalse(StorageAccess.supportsManageAll(29))
        assertTrue(StorageAccess.supportsManageAll(30))
        assertTrue(StorageAccess.supportsManageAll(36))
    }

    @Test
    fun `canBrowse按API分流到对应权限`() {
        // Android 10 及以下只认传统 READ
        assertTrue(StorageAccess.canBrowse(29, manageAll = false, legacyRead = true))
        assertFalse(StorageAccess.canBrowse(29, manageAll = true, legacyRead = false))
        // Android 11+ 只认 MANAGE_EXTERNAL_STORAGE
        assertTrue(StorageAccess.canBrowse(34, manageAll = true, legacyRead = false))
        assertFalse(StorageAccess.canBrowse(34, manageAll = false, legacyRead = true))
    }

    @Test
    fun `API29以下需要运行时申请READ`() {
        assertTrue(StorageAccess.needsRuntimeRead(23))
        assertTrue(StorageAccess.needsRuntimeRead(29))
        assertFalse(StorageAccess.needsRuntimeRead(30))
    }

    @Test
    fun `hint按版本区分说明文案`() {
        assertTrue(StorageAccess.hint(36).contains("所有文件访问"))
        assertTrue(StorageAccess.hint(29).contains("存储权限"))
        assertFalse(StorageAccess.hint(29).contains("Android 11+"))
    }

    @Test
    fun `actionLabel按版本区分按钮文案`() {
        assertEquals("授予所有文件访问", StorageAccess.actionLabel(34))
        assertEquals("授予存储权限", StorageAccess.actionLabel(29))
    }

    @Test
    fun `华为Android10死结场景_补权限后可浏览`() {
        // R42 实证场景：YAL-AL10(API 29) 上 MANAGE 不存在，granted 恒 false 导致目录永远列不出。
        // 修复后：API 29 + 传统 READ 授予 → canBrowse 必须为 true。
        assertFalse(StorageAccess.supportsManageAll(29))
        assertTrue(StorageAccess.canBrowse(29, manageAll = false, legacyRead = true))
    }
}
