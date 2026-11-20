package io.github.gscratchpad.data

/**
 * SQL 访问抽象。
 *
 * 存在的理由（ADR-08）：桌面版的可靠性语义（WAL、revision 丢弃、journal 回填、镜像原子替换）
 * 全部是「SQL + 文件」的顺序契约，必须在进程内可测。Android 的 [android.database.sqlite.SQLiteDatabase]
 * 与 JVM 测试用的 sqlite-jdbc 都只是这套契约的驱动；把驱动抽出来，§5.8 的不变量才能在
 * 无模拟器的 JVM 上逐条回归，而不是靠人眼读代码。
 */
interface SqlDb {
    fun exec(sql: String, args: List<Any?> = emptyList())
    fun execMany(sql: String, argRows: List<List<Any?>>)
    fun query(sql: String, args: List<Any?> = emptyList()): List<Row>
    fun queryOne(sql: String, args: List<Any?> = emptyList()): Row? = query(sql, args).firstOrNull()

    fun <T> transaction(work: () -> T): T

    /** WAL checkpoint(TRUNCATE)，导入导出前保证快照完整。 */
    fun checkpointTruncate()
    fun vacuum()
    fun close()
}

class Row(private val values: Map<String, Any?>) {
    fun str(name: String): String = (values[name] as? String) ?: ""
    fun long(name: String): Long = when (val v = values[name]) {
        null -> 0L
        is Long -> v
        is Int -> v.toLong()
        is Number -> v.toLong()
        is String -> v.toLongOrNull() ?: 0L
        else -> 0L
    }

    fun int(name: String): Int = long(name).toInt()
    fun double(name: String): Double = when (val v = values[name]) {
        null -> 0.0
        is Double -> v
        is Float -> v.toDouble()
        is Number -> v.toDouble()
        is String -> v.toDoubleOrNull() ?: 0.0
        else -> 0.0
    }

    fun isNull(name: String): Boolean = values[name] == null
}
