"""v1 → v2 迁移专项测试。

场景：修订三之前建立的库，documents.format CHECK 约束为 ('txt','md')。
修订四新增 html 格式后，老库写入 html 会触发
"CHECK constraint failed: format IN('txt','md')"。
本测试验证：v1 老库自动迁移到 v2（重建表放宽 CHECK），且既有数据逐字保留。
"""
import sqlite3
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))

from scratchpad.store import Store  # noqa: E402

V1_SCHEMA = """
CREATE TABLE documents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('txt', 'md')),
    content     TEXT NOT NULL DEFAULT '',
    sort_index  INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    revision    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_documents_state_order ON documents(state, sort_index);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mig-test-"))
    db = tmp / "gscratchpad.db"

    # 1) 用 v1 老结构建库并写入数据
    c = sqlite3.connect(db)
    c.executescript(V1_SCHEMA)
    c.execute(
        "INSERT INTO documents(id,title,format,content,sort_index,revision) "
        "VALUES(?,?,?,?,?,?)",
        ("doc1", "笔记一", "md", "# 你好\n\n内容", 0, 3),
    )
    c.execute(
        "INSERT INTO documents(id,title,format,content,sort_index,revision) "
        "VALUES(?,?,?,?,?,?)",
        ("doc2", "plain", "txt", "hello", 1, 1),
    )
    c.execute("INSERT INTO meta(key,value) VALUES('schema_version','1')")
    c.commit()
    c.close()

    # 2) 用新代码打开 → 自动迁移
    st = Store(root=tmp)
    st.open()

    # 3) 迁移后数据逐字完整、schema_version=3、新 CHECK 与 folder 列生效
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM documents ORDER BY sort_index").fetchall()
    assert len(rows) == 2, f"期望 2 行，得到 {len(rows)}"
    assert rows[0]["id"] == "doc1" and rows[0]["format"] == "md"
    assert rows[0]["revision"] == 3 and rows[0]["content"] == "# 你好\n\n内容"
    assert rows[1]["id"] == "doc2" and rows[1]["content"] == "hello"
    ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert ver["value"] == "3", ver["value"]
    cols = conn.execute("SELECT sql FROM sqlite_master WHERE name='documents'").fetchone()
    assert "'html'" in cols["sql"], cols["sql"]
    assert "folder" in cols["sql"], cols["sql"]
    folders_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='folders'"
    ).fetchone()
    assert folders_table is not None, "v3 迁移应创建 folders 表"
    conn.close()

    # 4) html 文档走真实创建流程可正常保存
    doc = st.create_document("html", title="网页")
    doc = replace(doc, content="<h1>hi</h1>", revision=doc.revision + 1)
    st.submit_save(doc, wait=True)
    d3 = st.get(doc.id)
    assert d3 is not None and d3.format == "html" and d3.content == "<h1>hi</h1>", d3

    # 5) v2 → v3 增量：folder 列默认空串，不影响旧数据；folders API 可用
    st.create_folder("工作")
    st.set_folder(doc.id, "工作")
    assert st.get(doc.id).folder == "工作"
    st.rename_folder("工作", "项目")
    assert st.get(doc.id).folder == "项目"
    st.delete_folder("项目")
    assert st.get(doc.id).folder == ""
    assert st.folders() == []
    st.close()
    print("MIGRATION TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
