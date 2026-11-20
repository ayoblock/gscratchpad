package io.github.gscratchpad.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** R39：孤儿判定与体积文案（对齐桌面 store.py 的 _orphan_paths/_stale_temp）。 */
class MaintenancePolicyTest {

    private val live = setOf("aaa", "bbb")

    // ---- notes/ ----

    @Test
    fun notes_有对应文档的镜像不是孤儿() {
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, "aaa.md", false, 0L, live))
    }

    @Test
    fun notes_无对应文档的镜像是孤儿() {
        assertTrue(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, "deadbeef.md", false, 0L, live))
    }

    @Test
    fun notes_无扩展名按整名比对() {
        assertTrue(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, "deadbeef", false, 0L, live))
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, "aaa", false, 0L, live))
    }

    @Test
    fun notes_子目录一律视为垃圾() {
        assertTrue(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, "aaa", true, 0L, live))
    }

    @Test
    fun notes_新鲜tmp不动_过期tmp才清() {
        val tmp = "write.tmp"
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.NOTES, tmp, false, 0L, live))
        assertFalse(
            MaintenancePolicy.isOrphan(
                MaintenancePolicy.Area.NOTES, tmp, false,
                MaintenancePolicy.TMP_STALE_MS - 1, live,
            ),
        )
        assertTrue(
            MaintenancePolicy.isOrphan(
                MaintenancePolicy.Area.NOTES, tmp, false,
                MaintenancePolicy.TMP_STALE_MS, live,
            ),
        )
    }

    // ---- assets/ ----

    @Test
    fun assets_按docId目录名判定() {
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.ASSETS, "aaa", true, 0L, live))
        assertTrue(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.ASSETS, "deadbeef", true, 0L, live))
    }

    // ---- recovery/ ----

    @Test
    fun recovery_只认json且按stem比对() {
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.RECOVERY, "aaa.json", false, 0L, live))
        assertTrue(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.RECOVERY, "deadbeef.json", false, 0L, live))
        assertFalse(MaintenancePolicy.isOrphan(MaintenancePolicy.Area.RECOVERY, "deadbeef.txt", false, 0L, live))
    }

    // ---- humanSize ----

    @Test
    fun humanSize_按量级输出() {
        assertEquals("512 B", MaintenancePolicy.humanSize(512))
        assertEquals("1.5 KB", MaintenancePolicy.humanSize(1536))
        assertEquals("12 KB", MaintenancePolicy.humanSize(12 * 1024))
        assertEquals("2.0 MB", MaintenancePolicy.humanSize(2 * 1024 * 1024))
    }
}
