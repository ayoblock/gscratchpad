package io.github.gscratchpad.testing

import io.github.gscratchpad.data.Row
import io.github.gscratchpad.data.SqlDb
import java.sql.Connection
import java.sql.DriverManager
import java.sql.PreparedStatement
import java.sql.ResultSet

/** [SqlDb] 的 JVM 驱动（sqlite-jdbc），让 §5.8 不变量在无模拟器环境下可回归。 */
class JdbcSqlDb(private val conn: Connection) : SqlDb {

    companion object {
        fun open(path: String): JdbcSqlDb {
            val conn = DriverManager.getConnection("jdbc:sqlite:$path")
            conn.autoCommit = true
            val db = JdbcSqlDb(conn)
            db.exec("PRAGMA journal_mode=WAL")
            db.exec("PRAGMA synchronous=FULL")
            db.exec("PRAGMA busy_timeout=10000")
            return db
        }
    }

    override fun exec(sql: String, args: List<Any?>) {
        conn.prepareStatement(sql).use { ps ->
            bind(ps, args)
            // PRAGMA 语句会返回结果集，executeUpdate 会抛 "Query returns results"
            val hasResultSet = ps.execute()
            if (hasResultSet) ps.resultSet?.close()
        }
    }

    override fun execMany(sql: String, argRows: List<List<Any?>>) {
        transaction {
            argRows.forEach { exec(sql, it) }
        }
    }

    override fun query(sql: String, args: List<Any?>): List<Row> {
        conn.prepareStatement(sql).use { ps ->
            bind(ps, args)
            ps.executeQuery().use { rs -> return readRows(rs) }
        }
    }

    override fun <T> transaction(work: () -> T): T {
        val previous = conn.autoCommit
        conn.autoCommit = false
        return try {
            val result = work()
            conn.commit()
            result
        } catch (e: Throwable) {
            conn.rollback()
            throw e
        } finally {
            conn.autoCommit = previous
        }
    }

    override fun checkpointTruncate() {
        conn.createStatement().use { it.executeQuery("PRAGMA wal_checkpoint(TRUNCATE)").close() }
    }

    override fun vacuum() {
        conn.createStatement().use { it.execute("VACUUM") }
        checkpointTruncate()
    }

    override fun close() {
        conn.close()
    }

    private fun bind(ps: PreparedStatement, args: List<Any?>) {
        args.forEachIndexed { index, value ->
            when (value) {
                null -> ps.setObject(index + 1, null)
                is ByteArray -> ps.setBytes(index + 1, value)
                else -> ps.setObject(index + 1, value)
            }
        }
    }

    private fun readRows(rs: ResultSet): List<Row> {
        val meta = rs.metaData
        val rows = ArrayList<Row>()
        while (rs.next()) {
            val values = HashMap<String, Any?>(meta.columnCount)
            for (i in 1..meta.columnCount) {
                values[meta.getColumnLabel(i)] = rs.getObject(i)
            }
            rows.add(Row(values))
        }
        return rows
    }
}
