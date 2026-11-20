package io.github.gscratchpad.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction

/**
 * 原始 SQLite 建库（ADR-01：不用 Room）。
 *
 * - WAL + synchronous=FULL：提交是原子的，进程被杀后由 SQLite 自行回放。
 * - schema v3 与桌面逐字段一致，v1→v2→v3 迁移逻辑照搬 `store._migrate`。
 */
class DbHelper(context: Context, appPaths: AppPaths) : SQLiteOpenHelper(
    context,
    appPaths.dbFile.absolutePath,
    null,
    Schema.VERSION,
) {
    init {
        setWriteAheadLoggingEnabled(true)
    }

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onOpen(db: SQLiteDatabase) {
        if (!db.isReadOnly) {
            db.rawQuery("PRAGMA synchronous=FULL", null).use { it.moveToFirst() }
            db.rawQuery("PRAGMA busy_timeout=10000", null).use { it.moveToFirst() }
        }
    }

    override fun onCreate(db: SQLiteDatabase) {
        Schema.statements(Schema.DDL).forEach { db.execSQL(it) }
        db.execSQL(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            arrayOf(MetaKeys.SCHEMA_VERSION, Schema.VERSION.toString()),
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.transaction {
                Schema.statements(Schema.V1_TO_V2).forEach { execSQL(it) }
            }
        }
        if (oldVersion < 3) {
            db.transaction {
                val columns = db.rawQuery("PRAGMA table_info(documents)", null).use { cursor ->
                    val names = mutableSetOf<String>()
                    while (cursor.moveToNext()) names.add(cursor.getString(cursor.getColumnIndexOrThrow("name")))
                    names
                }
                if ("folder" !in columns) {
                    db.execSQL("ALTER TABLE documents ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
                }
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS folders (" +
                        " name TEXT PRIMARY KEY, created_at REAL NOT NULL DEFAULT 0)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at)",
                )
                db.execSQL(
                    "INSERT OR IGNORE INTO folders(name, created_at) " +
                        "SELECT DISTINCT folder, 0 FROM documents WHERE folder <> ''",
                )
            }
        }
        if (oldVersion < 4) {
            // v4：最近列表「清除记录」标记（只隐藏列表条目，不动正文与镜像）
            val columns = db.rawQuery("PRAGMA table_info(documents)", null).use { cursor ->
                val names = mutableSetOf<String>()
                while (cursor.moveToNext()) names.add(cursor.getString(cursor.getColumnIndexOrThrow("name")))
                names
            }
            if ("recent_hidden" !in columns) {
                Schema.statements(Schema.V3_TO_V4).forEach { db.execSQL(it) }
            }
        }
        if (oldVersion < 5) {
            // v5：最近打开时间（首页最近列表按 opened_at DESC 排序）
            val columns = db.rawQuery("PRAGMA table_info(documents)", null).use { cursor ->
                val names = mutableSetOf<String>()
                while (cursor.moveToNext()) names.add(cursor.getString(cursor.getColumnIndexOrThrow("name")))
                names
            }
            if ("opened_at" !in columns) {
                Schema.statements(Schema.V4_TO_V5).forEach { db.execSQL(it) }
            }
        }
        db.execSQL(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            arrayOf(MetaKeys.SCHEMA_VERSION, Schema.VERSION.toString()),
        )
    }
}
