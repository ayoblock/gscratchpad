package io.github.gscratchpad.data

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase

/** [SqlDb] 的 Android 驱动，包装 [SQLiteDatabase]。 */
class AndroidSqlDb(private val db: SQLiteDatabase) : SqlDb {

    override fun exec(sql: String, args: List<Any?>) {
        val trimmed = sql.trimStart()
        if (args.isEmpty() && trimmed.startsWith("PRAGMA", ignoreCase = true)) {
            // PRAGMA 多数会返回结果集（journal_mode / synchronous / table_info…），
            // execSQL 一律抛 "Queries can be performed using ... rawQuery only"。
            db.rawQuery(sql, null).use { it.moveToFirst() }
            return
        }
        if (args.isEmpty()) db.execSQL(sql) else db.execSQL(sql, args.toTypedArray())
    }

    override fun execMany(sql: String, argRows: List<List<Any?>>) {
        db.beginTransaction()
        try {
            for (row in argRows) db.execSQL(sql, row.toTypedArray())
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    override fun query(sql: String, args: List<Any?>): List<Row> {
        val rawArgs = if (args.isEmpty()) null else args.map { it?.toString() }.toTypedArray()
        return db.rawQuery(sql, rawArgs).use { cursor -> cursor.toRows() }
    }

    override fun <T> transaction(work: () -> T): T {
        db.beginTransaction()
        return try {
            val result = work()
            db.setTransactionSuccessful()
            result
        } finally {
            db.endTransaction()
        }
    }

    override fun checkpointTruncate() {
        db.rawQuery("PRAGMA wal_checkpoint(TRUNCATE)", null).use { it.moveToFirst() }
    }

    override fun vacuum() {
        db.execSQL("VACUUM")
        checkpointTruncate()
    }

    override fun close() {
        db.close()
    }

    private fun Cursor.toRows(): List<Row> {
        val out = ArrayList<Row>(count)
        while (moveToNext()) {
            val values = HashMap<String, Any?>(columnCount)
            for (i in 0 until columnCount) {
                values[getColumnName(i)] = when (getType(i)) {
                    Cursor.FIELD_TYPE_NULL -> null
                    Cursor.FIELD_TYPE_INTEGER -> getLong(i)
                    Cursor.FIELD_TYPE_FLOAT -> getDouble(i)
                    Cursor.FIELD_TYPE_BLOB -> getBlob(i)
                    else -> getString(i)
                }
            }
            out.add(Row(values))
        }
        return out
    }
}

/** 只读打开外部库（导入用）。 */
fun openReadOnlySqlDb(path: String): SqlDb {
    val db = SQLiteDatabase.openDatabase(path, null, SQLiteDatabase.OPEN_READONLY)
    return AndroidSqlDb(db)
}
