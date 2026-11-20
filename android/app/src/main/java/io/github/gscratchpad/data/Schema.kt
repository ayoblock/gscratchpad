package io.github.gscratchpad.data

/** 桌面 `store._SCHEMA` 的逐字段同构版本（schema v3），Android 侧追加 v4 `recent_hidden`、v5 `opened_at`。 */
object Schema {
    const val VERSION = 5

    const val DDL = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('txt','md','html')),
    content     TEXT NOT NULL DEFAULT '',
    sort_index  INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','closed')),
    revision    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0,
    folder      TEXT NOT NULL DEFAULT '',
    recent_hidden INTEGER NOT NULL DEFAULT 0,
    opened_at   REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_state_order ON documents(state, sort_index);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at);
CREATE INDEX IF NOT EXISTS idx_documents_opened ON documents(opened_at);

CREATE TABLE IF NOT EXISTS folders (
    name       TEXT PRIMARY KEY,
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

    /** v1 → v2：format CHECK 放宽加入 'html'，SQLite 不支持改 CHECK，需重建表。 */
    const val V1_TO_V2 = """
CREATE TABLE documents_v2 (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('txt','md','html')),
    content     TEXT NOT NULL DEFAULT '',
    sort_index  INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','closed')),
    revision    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0
);
INSERT INTO documents_v2
    (id, title, format, content, sort_index, state, revision, created_at, updated_at)
SELECT id, title, format, content, sort_index, state, revision, created_at, updated_at
FROM documents;
DROP TABLE documents;
ALTER TABLE documents_v2 RENAME TO documents;
CREATE INDEX IF NOT EXISTS idx_documents_state_order ON documents(state, sort_index);
"""

    const val V2_TO_V3 = """
ALTER TABLE documents ADD COLUMN folder TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS folders (
    name TEXT PRIMARY KEY,
    created_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at);
INSERT OR IGNORE INTO folders(name, created_at)
    SELECT DISTINCT folder, 0 FROM documents WHERE folder <> '';
"""

    const val V3_TO_V4 = """
ALTER TABLE documents ADD COLUMN recent_hidden INTEGER NOT NULL DEFAULT 0;
"""

    /** v4 → v5：记录「最近打开」时间，供首页最近列表按打开时间倒序（R20 修复排序）。 */
    const val V4_TO_V5 = """
ALTER TABLE documents ADD COLUMN opened_at REAL NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_documents_opened ON documents(opened_at);
"""

    /**
     * 把多语句脚本拆成单条：`SQLiteDatabase.execSQL` 与 JDBC PreparedStatement
     * 都不接受一次多语句（前者报语法错，后者只执行第一条）。
     */
    fun statements(script: String): List<String> =
        script.split(';').map { it.trim() }.filter { it.isNotEmpty() }
}

/** meta 键位（与桌面版同名，导入后行为一致）。 */
object MetaKeys {
    const val SCHEMA_VERSION = "schema_version"
    const val ACTIVE_DOC = "active_doc"
    const val VIEW_MODE = "view_mode"
    const val COLOR_SCHEME = "color_scheme"
    const val SIDEBAR_VISIBLE = "sidebar_visible"
    const val SIDEBAR_WIDTH = "sidebar_width"
    const val SIDEBAR_AUTOHIDE = "sidebar_autohide"
    const val SIDEBAR_SORT = "sidebar_sort"
    const val DISK_SORT = "disk_sort"
    const val WRITING_WIDTH = "writing_width"
    const val WINDOW_W = "window_w"
    const val WINDOW_H = "window_h"
    const val MAXIMIZED = "maximized"
    const val FS_ROOT = "fs_root"
    const val SNIPPETS = "snippets"
    const val ACCEL_OVERRIDES = "accel_overrides"

    fun ext(key: String) = "ext:$key"
    fun cursor(docId: String) = "cursor:$docId"
    fun sourcePath(docId: String) = "source_path:$docId"

    /** 桌面版在导入时需要跳过的窗口几何与磁盘根键（方案 §6.2 第 2 步）。 */
    val SKIP_ON_IMPORT = setOf(WINDOW_W, WINDOW_H, MAXIMIZED, FS_ROOT)
}
