"""持久化层。

设计要点（可靠性优先）：

1. SQLite（WAL + synchronous=FULL）是唯一真源。WAL 提交是原子的，进程被 SIGKILL 或
   掉电后由 SQLite 自身回放日志，不会出现半截写入。
2. 每次提交前先写 recovery/<doc>.journal（内容快照 + revision），提交成功后再删除。
   若崩溃发生在「写完 journal、提交未完成」之间，启动时以 journal 为准回填，
   保证不丢失用户已经看到的最新内容。
3. notes/<doc>.<ext> 是供用户直接查看/备份的镜像文件，原子替换写入（temp + rename + fsync）。
   它不参与恢复决策，避免双写冲突。
4. 所有写操作在单一工作线程串行执行，UI 线程只读，避免锁竞争，也保证写入顺序。
5. 每个文档带单调递增 revision，晚到的旧快照会被丢弃，防止乱序覆盖。
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from . import paths

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('txt', 'md', 'html')),
    content     TEXT NOT NULL DEFAULT '',
    sort_index  INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    revision    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0,
    folder      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_documents_state_order
    ON documents(state, sort_index);
CREATE INDEX IF NOT EXISTS idx_documents_updated
    ON documents(updated_at);

CREATE TABLE IF NOT EXISTS folders (
    name       TEXT PRIMARY KEY,
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    format: str
    content: str = ""
    sort_index: int = 0
    state: str = "open"
    revision: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    folder: str = ""

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def word_count(self) -> int:
        """中英混排字数：CJK 字符按字计，其余按空白分隔的词计。"""
        cjk = 0
        latin_chars: list[str] = []
        for ch in self.content:
            code = ord(ch)
            if 0x3040 <= code <= 0x30FF or 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
                cjk += 1
                latin_chars.append(" ")
            else:
                latin_chars.append(ch)
        latin = len("".join(latin_chars).split())
        return cjk + latin


@dataclass
class SaveState:
    """供 UI 展示的保存状态。"""

    doc_id: str
    status: str = "saved"  # saved | saving | error
    message: str = ""
    timestamp: float = 0.0


@dataclass
class MaintenanceReport:
    """批量清除 / 孤儿清理的结果。

    计数为 0 表示「没有该类对象」，不是「未执行」——执行与否由调用方决定。
    errors 只记录可恢复的单项失败（某个文件删不掉），不影响其余项。
    """

    purged_docs: int = 0
    purged_bytes: int = 0
    orphan_notes: int = 0
    orphan_notes_bytes: int = 0
    orphan_assets: int = 0
    orphan_assets_bytes: int = 0
    orphan_journals: int = 0
    stale_meta: int = 0
    db_bytes_before: int = 0
    db_bytes_after: int = 0
    db_free_bytes: int = 0
    vacuumed: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_orphans(self) -> int:
        return self.orphan_notes + self.orphan_assets + self.orphan_journals

    @property
    def orphan_bytes(self) -> int:
        return self.orphan_notes_bytes + self.orphan_assets_bytes

    @property
    def reclaimed_bytes(self) -> int:
        """数据库体积实际减少量（VACUUM 才可能大于 0）。"""
        return max(0, self.db_bytes_before - self.db_bytes_after)


def _file_size(path: Path) -> int:
    """单文件字节数，不跟随符号链接（链接只算链接本身，绝不读目标）。"""
    try:
        return path.lstat().st_size
    except OSError:
        return 0


def _tree_size(path: Path) -> int:
    """目录占用（不跟随符号链接；链接本身按链接大小计）。"""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _db_footprint(db_path: Path) -> int:
    """数据库实际占用 = 主库 + WAL。

    WAL 模式下刚写入的数据可能全在 -wal 里（主库只有 4 KB 头部），
    只看主库会把「压缩前」量成 4 KB，「压缩后」量成 36 KB——数字反向。
    """
    return _file_size(db_path) + _file_size(Path(str(db_path) + "-wal"))


def _stale_temp(path: Path, min_age: float = 600.0) -> bool:
    """原子写的 .tmp 是否为残留（mtime 早于 min_age 秒）。"""
    try:
        return time.time() - path.lstat().st_mtime >= min_age
    except OSError:
        return False


class Store:
    """文档仓库。读写分离：UI 线程读，工作线程写。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.data_root()
        self._notes = self.root / "notes"
        self._assets = self.root / "assets"
        self._recovery = self.root / "recovery"
        self._db_path = self.root / "gscratchpad.db"
        self._read_lock = threading.Lock()
        self._reader: sqlite3.Connection | None = None
        self._writer: sqlite3.Connection | None = None
        self._queue: "queue.Queue[tuple | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._callbacks: list[Callable[[SaveState], None]] = []
        self._callback_lock = threading.Lock()
        self._deleted_callbacks: list[Callable[[list[str]], None]] = []
        self._last_error: str = ""
        self._closing = False

    # ------------------------------------------------------------------ 生命周期

    def open(self) -> list[str]:
        """建库、迁移、执行崩溃恢复，返回恢复说明列表。"""
        paths.migrate_legacy_data_dir()
        for directory in (self.root, self._notes, self._assets, self._recovery):
            directory.mkdir(parents=True, exist_ok=True)
        self._reader = _connect(self._db_path)
        self._reader.executescript(_SCHEMA)
        self._migrate(self._reader)
        self._thread = threading.Thread(target=self._worker, name="scratchpad-writer", daemon=True)
        self._thread.start()
        return self._recover()

    def close(self) -> None:
        self.flush()
        self._closing = True
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def _migrate(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        if current == SCHEMA_VERSION:
            return
        if current == 0:
            pass  # 全新库，_SCHEMA 已是最新结构
        else:
            if current < 2:
                # v1 → v2：format CHECK 放宽加入 'html'。SQLite 不支持 ALTER CHECK，重建表。
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        """
                        CREATE TABLE documents_v2 (
                            id          TEXT PRIMARY KEY,
                            title       TEXT NOT NULL,
                            format      TEXT NOT NULL CHECK (format IN ('txt', 'md', 'html')),
                            content     TEXT NOT NULL DEFAULT '',
                            sort_index  INTEGER NOT NULL DEFAULT 0,
                            state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
                            revision    INTEGER NOT NULL DEFAULT 0,
                            created_at  REAL NOT NULL DEFAULT 0,
                            updated_at  REAL NOT NULL DEFAULT 0
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO documents_v2
                            (id, title, format, content, sort_index, state,
                             revision, created_at, updated_at)
                        SELECT id, title, format, content, sort_index, state,
                               revision, created_at, updated_at
                        FROM documents
                        """
                    )
                    conn.execute("DROP TABLE documents")
                    conn.execute("ALTER TABLE documents_v2 RENAME TO documents")
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_documents_state_order "
                        "ON documents(state, sort_index)"
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            if current < 3:
                # v2 → v3：新增 folder 列与 folders 表（纯增量，可用 ALTER TABLE）
                conn.execute("BEGIN IMMEDIATE")
                try:
                    columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(documents)").fetchall()
                    }
                    if "folder" not in columns:
                        conn.execute(
                            "ALTER TABLE documents ADD COLUMN folder TEXT NOT NULL DEFAULT ''"
                        )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS folders ("
                        " name TEXT PRIMARY KEY,"
                        " created_at REAL NOT NULL DEFAULT 0)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_documents_updated "
                        "ON documents(updated_at)"
                    )
                    # 老库里可能已有非空 folder 值（例如从别处导入），补登到 folders
                    conn.execute(
                        "INSERT OR IGNORE INTO folders(name, created_at) "
                        "SELECT DISTINCT folder, 0 FROM documents WHERE folder <> ''"
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    # ------------------------------------------------------------------ 恢复

    def _recover(self) -> list[str]:
        notes: list[str] = []
        for journal in sorted(self._recovery.glob("*.json")):
            try:
                data = json.loads(journal.read_text(encoding="utf-8"))
                doc_id = data["id"]
                revision = int(data["revision"])
                content = data["content"]
            except (OSError, ValueError, KeyError):
                journal.unlink(missing_ok=True)
                continue
            row = self._reader.execute(
                "SELECT revision FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            if row is None:
                journal.unlink(missing_ok=True)
                continue
            if revision > int(row["revision"]):
                now = time.time()
                self._reader.execute(
                    "UPDATE documents SET content=?, revision=?, updated_at=? WHERE id=?",
                    (content, revision, now, doc_id),
                )
                self._reader.commit()
                self._mirror(doc_id, content, self._format_of(doc_id))
                notes.append(f"已从恢复日志还原文档 {doc_id}（revision {revision}）")
            journal.unlink(missing_ok=True)
        return notes

    def _format_of(self, doc_id: str) -> str:
        row = self._reader.execute(
            "SELECT format FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        return row["format"] if row else "txt"

    # ------------------------------------------------------------------ 读取

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._read_lock:
            assert self._reader is not None
            return self._reader.execute(sql, params).fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _to_doc(row: sqlite3.Row) -> Document:
        keys = row.keys()
        return Document(
            id=row["id"],
            title=row["title"],
            format=row["format"],
            content=row["content"],
            sort_index=row["sort_index"],
            state=row["state"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            folder=(row["folder"] or "") if "folder" in keys else "",
        )

    def open_documents(self) -> list[Document]:
        rows = self._query(
            "SELECT * FROM documents WHERE state='open' ORDER BY sort_index ASC, updated_at ASC"
        )
        return [self._to_doc(r) for r in rows]

    def all_documents(self, include_closed: bool = True) -> list[Document]:
        if include_closed:
            rows = self._query("SELECT * FROM documents ORDER BY sort_index ASC")
        else:
            rows = self._query(
                "SELECT * FROM documents WHERE state='open' ORDER BY sort_index ASC"
            )
        return [self._to_doc(r) for r in rows]

    def get(self, doc_id: str) -> Document | None:
        row = self._query_one("SELECT * FROM documents WHERE id=?", (doc_id,))
        return self._to_doc(row) if row else None

    # ---- 侧栏：最近 / 未关闭 / 按格式 / 文件夹 ----

    def recent_documents(self, limit: int = 60) -> list[Document]:
        """按更新时间倒序（含已关闭的文档，侧栏「最近」用）。"""
        rows = self._query(
            "SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [self._to_doc(r) for r in rows]

    def open_documents_by_recent(self) -> list[Document]:
        rows = self._query(
            "SELECT * FROM documents WHERE state='open' ORDER BY updated_at DESC, sort_index ASC"
        )
        return [self._to_doc(r) for r in rows]

    def documents_grouped_by_format(self) -> dict[str, list[Document]]:
        """按格式分组（顺序固定 txt → md → html → 其他），组内按更新时间倒序。"""
        rows = self._query(
            "SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC"
        )
        grouped: dict[str, list[Document]] = {}
        for row in rows:
            grouped.setdefault(row["format"], []).append(self._to_doc(row))
        order = ["md", "txt", "html"]
        return {fmt: grouped[fmt] for fmt in order if fmt in grouped} | {
            fmt: docs for fmt, docs in grouped.items() if fmt not in order
        }

    def folders(self) -> list[str]:
        rows = self._query("SELECT name FROM folders ORDER BY name COLLATE NOCASE")
        return [r["name"] for r in rows]

    def folder_counts(self) -> dict[str, int]:
        rows = self._query(
            "SELECT folder, COUNT(*) AS n FROM documents WHERE folder <> '' GROUP BY folder"
        )
        return {r["folder"]: int(r["n"]) for r in rows}

    def documents_by_folder(self) -> dict[str, list[Document]]:
        """未归档（folder=''）以空字符串为键，始终存在。"""
        rows = self._query("SELECT * FROM documents ORDER BY updated_at DESC, sort_index ASC")
        grouped: dict[str, list[Document]] = {}
        for row in rows:
            doc = self._to_doc(row)
            grouped.setdefault(doc.folder, []).append(doc)
        grouped.setdefault("", [])
        return grouped

    def doc_folder_of(self, doc_id: str) -> str:
        row = self._query_one("SELECT folder FROM documents WHERE id=?", (doc_id,))
        return (row["folder"] or "") if row else ""

    def create_folder(self, name: str, *, wait: bool = True) -> None:
        name = name.strip()
        if not name:
            raise ValueError("文件夹名不能为空")
        done = threading.Event() if wait else None
        self._enqueue(("folder-create", (name, done)))
        if done is not None:
            done.wait(timeout=5.0)

    def rename_folder(self, old: str, new: str, *, wait: bool = True) -> None:
        new = new.strip()
        if not new:
            raise ValueError("文件夹名不能为空")
        done = threading.Event() if wait else None
        self._enqueue(("folder-rename", (old, new, done)))
        if done is not None:
            done.wait(timeout=5.0)

    def delete_folder(self, name: str, *, wait: bool = True) -> None:
        """删除文件夹：其中的笔记回到「未归档」，笔记本身不删。"""
        done = threading.Event() if wait else None
        self._enqueue(("folder-delete", (name, done)))
        if done is not None:
            done.wait(timeout=5.0)

    def set_folder(self, doc_id: str, folder: str, *, wait: bool = True) -> None:
        done = threading.Event() if wait else None
        self._enqueue(("doc-folder", (doc_id, folder or "", done)))
        if done is not None:
            done.wait(timeout=5.0)

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._query_one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str, *, wait: bool = False) -> None:
        """元数据写入走工作线程，但不影响文档 revision。wait=True 时阻塞到落盘。"""
        done = threading.Event() if wait else None
        self._enqueue(("meta", (key, value, done)))
        if done is not None:
            done.wait(timeout=5.0)

    # ---- 文档 ↔ 本地文件关联（Ctrl+O / Ctrl+S） ----

    @staticmethod
    def _source_key(doc_id: str) -> str:
        return f"source_path:{doc_id}"

    def source_path_of(self, doc_id: str) -> str | None:
        """返回文档关联的本机文件路径；未关联返回 None。"""
        value = self.get_meta(self._source_key(doc_id))
        return value or None

    def set_source_path(self, doc_id: str, path: str | None) -> None:
        self.set_meta(self._source_key(doc_id), path or "", wait=True)

    def max_sort_index(self) -> int:
        row = self._query_one("SELECT MAX(sort_index) AS m FROM documents")
        return int(row["m"]) if row and row["m"] is not None else -1

    # ------------------------------------------------------------------ 写入

    def on_save_state(self, callback: Callable[[SaveState], None]) -> None:
        with self._callback_lock:
            self._callbacks.append(callback)

    def _emit(self, state: SaveState) -> None:
        with self._callback_lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(state)
            except Exception:  # UI 回调异常不得影响持久化
                pass

    def _emit_deleted(self, ids: list[str]) -> None:
        """文档删除事件（工作线程内）。syncstate 用它维护墓碑集合。"""
        with self._callback_lock:
            callbacks = list(self._deleted_callbacks)
        for callback in callbacks:
            try:
                callback(ids)
            except Exception:  # 回调异常不得影响写线程
                pass

    def _enqueue(self, job: tuple) -> None:
        self._queue.put(job)

    def create_document(self, fmt: str = "txt", title: str | None = None) -> Document:
        doc_id = uuid.uuid4().hex
        now = time.time()
        sort_index = self.max_sort_index() + 1
        title = title or self._default_title(fmt)
        doc = Document(
            id=doc_id,
            title=title,
            format=fmt,
            content="",
            sort_index=sort_index,
            state="open",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        done = threading.Event()
        error: list[str] = []
        self._enqueue(("insert", (doc, done, error)))
        done.wait(timeout=5.0)
        if error:
            raise RuntimeError(error[0])
        self._mirror(doc.id, doc.content, doc.format)
        return doc

    @staticmethod
    def _default_title(fmt: str) -> str:
        return "未命名"

    def submit_save(self, doc: Document, *, wait: bool = False) -> None:
        """非阻塞提交内容快照；同一文档的多次提交自动合并为最后一次。"""
        payload = {
            "id": doc.id,
            "title": doc.title,
            "format": doc.format,
            "content": doc.content,
            "revision": doc.revision,
            "updated_at": time.time(),
        }
        done = threading.Event() if wait else None
        with self._pending_lock:
            self._pending[doc.id] = payload
        self._enqueue(("save", (doc.id, done)))
        self._emit(SaveState(doc.id, "saving", "", time.time()))
        if done is not None:
            done.wait(timeout=10.0)

    def rename(self, doc_id: str, title: str, *, wait: bool = True) -> None:
        done = threading.Event() if wait else None
        self._enqueue(("rename", (doc_id, title, done)))
        if done is not None:
            done.wait(timeout=5.0)

    def set_state(self, doc_id: str, state: str, *, wait: bool = True) -> None:
        done = threading.Event() if wait else None
        self._enqueue(("state", (doc_id, state, done)))
        if done is not None:
            done.wait(timeout=5.0)

    def reorder(self, ordered_ids: Iterable[str], *, wait: bool = False) -> None:
        done = threading.Event() if wait else None
        self._enqueue(("order", (list(ordered_ids), done)))
        if done is not None:
            done.wait(timeout=5.0)

    def delete_document(self, doc_id: str, *, wait: bool = True) -> None:
        """永久删除：移除数据库记录、镜像文件与图片资源。"""
        done = threading.Event() if wait else None
        self._enqueue(("delete", (doc_id, done)))
        if done is not None:
            done.wait(timeout=5.0)

    # ------------------------------------------------------------------ 批量清除 / 维护

    def closed_documents(self) -> list[Document]:
        """全部已关闭文档（更新时间倒序），供「清除已关闭笔记」确认与计数。"""
        rows = self._query(
            "SELECT * FROM documents WHERE state='closed' ORDER BY updated_at DESC"
        )
        return [self._to_doc(r) for r in rows]

    def purge_closed_documents(
        self, *, keep_ids: Iterable[str] = (), wait: bool = True
    ) -> MaintenanceReport:
        """永久删除全部 state='closed' 文档。

        等同「逐篇 delete_document」，但在写线程内用单事务完成，且额外清理
        ext: / cursor: / source_path: 中指向已删文档的映射。keep_ids 用于跳过
        当前在标签中打开的文档（防御：正常流程下它们是 state='open'）。
        只删数据库行与本数据目录内的镜像/资源，不触碰任何关联的本机原文件。
        """
        report = MaintenanceReport()
        done = threading.Event() if wait else None
        self._enqueue(("purge_closed", (done, report, set(keep_ids))))
        if done is not None:
            done.wait(timeout=60.0)
        return report

    def scan_orphans(self) -> MaintenanceReport:
        """只统计不删除：本数据目录内无对应文档的镜像/资源/恢复日志与 stale meta。"""
        report = MaintenanceReport()
        ids = {row["id"] for row in self._query("SELECT id FROM documents")}
        report.db_bytes_before = _db_footprint(self._db_path)
        report.db_bytes_after = report.db_bytes_before
        try:
            page = self._query_one("PRAGMA page_size")
            free = self._query_one("PRAGMA freelist_count")
            if page is not None and free is not None:
                report.db_free_bytes = int(page[0]) * int(free[0])
        except sqlite3.Error:
            pass

        for path, is_dir in self._orphan_paths(ids):
            if is_dir:
                report.orphan_assets += 1
                report.orphan_assets_bytes += _tree_size(path)
            elif path.parent == self._recovery:
                report.orphan_journals += 1
            else:
                report.orphan_notes += 1
                report.orphan_notes_bytes += _file_size(path)

        report.stale_meta = len(self._stale_meta_keys(ids))
        return report

    def maintain(self, *, vacuum: bool = True, wait: bool = True) -> MaintenanceReport:
        """清理孤儿文件 + 清理 stale meta，可选 VACUUM 回收空闲页。

        安全边界：只处理 notes/、assets/、recovery/ 三个目录内的条目，
        全部路径由本方法自行枚举；符号链接只删链接本身，绝不跟随。
        """
        report = MaintenanceReport()
        done = threading.Event() if wait else None
        self._enqueue(("maintain", (done, report, vacuum)))
        if done is not None:
            done.wait(timeout=120.0)
        return report

    def _orphan_paths(self, ids: set[str]) -> list[tuple[Path, bool]]:
        """枚举需要清理的路径：[(path, is_dir)]。只扫数据目录第一层，不递归未知目录。"""
        found: list[tuple[Path, bool]] = []
        if self._notes.is_dir():
            for entry in self._notes.iterdir():
                if entry.name.endswith(".tmp"):
                    # 原子写的临时文件：仅在长时间未变动时视为残留（save 在毫秒级完成）
                    if _stale_temp(entry):
                        found.append((entry, False))
                    continue
                if entry.is_symlink() or entry.is_file():
                    if entry.stem not in ids:
                        found.append((entry, False))
                elif entry.is_dir():
                    # notes/ 下不该有子目录：无对应文档即视为垃圾
                    found.append((entry, True))
        if self._assets.is_dir():
            for entry in self._assets.iterdir():
                if entry.name in ids:
                    continue
                found.append((entry, entry.is_dir() and not entry.is_symlink()))
        if self._recovery.is_dir():
            for entry in self._recovery.glob("*.json"):
                if entry.is_symlink() or entry.is_file():
                    if entry.stem not in ids:
                        found.append((entry, False))
        return found

    def _stale_meta_keys(self, ids: set[str]) -> list[str]:
        """meta 中指向已不存在文档的键：ext:<key>（值=doc_id）、source_path:/cursor:。"""
        return self._stale_keys_from_rows(self._query("SELECT key, value FROM meta"), ids)

    @staticmethod
    def _stale_keys_from_rows(rows, ids: set[str]) -> list[str]:
        stale: list[str] = []
        for row in rows:
            key = row["key"]
            value = row["value"]
            if key.startswith("ext:"):
                if value not in ids:
                    stale.append(key)
            elif key.startswith(("source_path:", "cursor:")):
                if key.split(":", 1)[1] not in ids:
                    stale.append(key)
        return stale

    @staticmethod
    def _remove_orphan(path: Path, is_dir: bool, report: MaintenanceReport) -> None:
        """删除孤儿条目。符号链接只删链接本身，绝不跟随到目标。"""
        try:
            if path.is_symlink():
                path.unlink()
            elif is_dir:
                import shutil

                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            report.errors.append(f"{path.name}: {exc}")

    def flush(self, timeout: float = 10.0) -> bool:
        """阻塞直到队列清空（退出、关标签时使用）。"""
        if self._thread is None or not self._thread.is_alive():
            return True
        done = threading.Event()
        self._enqueue(("flush", (done,)))
        return done.wait(timeout=timeout)

    # ---------------------------------------------------------------- 云同步支撑

    def on_deleted(self, callback: Callable[[list[str]], None]) -> None:
        """订阅文档删除事件（delete / purge_closed，工作线程内触发）。"""
        with self._callback_lock:
            self._deleted_callbacks.append(callback)

    def fingerprint(self) -> str:
        """库内容指纹：文档数 + 最大 revision + 内容字节总量。

        用于自动备份/同步的「有无变化」短路，避免无谓上传。
        """
        row = self._query_one(
            "SELECT COUNT(*) AS n, COALESCE(MAX(revision),0) AS r,"
            " COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) AS s FROM documents"
        )
        if row is None:
            return "0"
        folders = self._query_one("SELECT COUNT(*) AS n FROM folders")
        return f"{row['n']}:{row['r']}:{row['s']}:{folders['n'] if folders else 0}"

    def local_revisions(self) -> dict[str, int]:
        return {
            row["id"]: row["revision"]
            for row in self._query("SELECT id, revision FROM documents")
        }

    def snapshot_db_to(self, target: Path, *, wait: bool = True) -> bool:
        """工作线程内 checkpoint(TRUNCATE) 后把库文件复制到 target。"""
        target = Path(target)
        done = threading.Event()
        error: list[str] = []
        self._enqueue(("snapshot", (target, done, error)))
        if wait:
            done.wait(timeout=30.0)
        return not error

    def apply_remote(self, doc: dict, *, wait: bool = True) -> None:
        """应用远端文档（同步/备份导入落库的唯一入口）。

        dict 字段：id/title/format/content/sort_index/state/revision/
        created_at/updated_at/folder。本地已存在时 revision 取
        max(local, incoming)+1，其余字段以 incoming 为准（含 updated_at，
        保持对端时序用于后续冲突判定）；写镜像与 folders 登记。
        """
        doc = dict(doc)
        done = threading.Event()
        error: list[str] = []
        self._enqueue(("apply_sync", (doc, done, error)))
        if wait:
            done.wait(timeout=15.0)
        if error:
            raise RuntimeError(error[0])

    def delete_remote(self, doc_id: str, preserve: Path | None = None, *, wait: bool = True) -> None:
        """同步级删除：可选先把正文保全到 preserve，再删除行/镜像/资源。"""
        done = threading.Event()
        error: list[str] = []
        self._enqueue(("delete_sync", (doc_id, preserve, done, error)))
        if wait:
            done.wait(timeout=15.0)
        if error:
            raise RuntimeError(error[0])

    def merge_folders(self, folders: list[tuple[str, float]], *, wait: bool = True) -> None:
        if not folders:
            return
        done = threading.Event()
        self._enqueue(("folder-merge", (folders, done)))
        if wait:
            done.wait(timeout=10.0)

    # ------------------------------------------------------------------ 工作线程

    def _worker(self) -> None:
        conn = _connect(self._db_path)
        self._writer = conn
        while True:
            job = self._queue.get()
            if job is None:
                break
            kind, payload = job
            try:
                if kind == "save":
                    doc_id, done = payload
                    try:
                        self._do_save(conn, doc_id)
                    finally:
                        if done is not None:
                            done.set()
                elif kind == "insert":
                    doc, done, error = payload
                    try:
                        conn.execute(
                            "INSERT INTO documents(id, title, format, content, sort_index,"
                            " state, revision, created_at, updated_at, folder)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (
                                doc.id,
                                doc.title,
                                doc.format,
                                doc.content,
                                doc.sort_index,
                                doc.state,
                                doc.revision,
                                doc.created_at,
                                doc.updated_at,
                                doc.folder,
                            ),
                        )
                        conn.commit()
                    except sqlite3.Error as exc:
                        error.append(str(exc))
                    finally:
                        done.set()
                elif kind == "rename":
                    doc_id, title, done = payload
                    conn.execute(
                        "UPDATE documents SET title=?, updated_at=? WHERE id=?",
                        (title, time.time(), doc_id),
                    )
                    conn.commit()
                    done.set()
                elif kind == "state":
                    doc_id, state, done = payload
                    conn.execute(
                        "UPDATE documents SET state=?, updated_at=? WHERE id=?",
                        (state, time.time(), doc_id),
                    )
                    conn.commit()
                    done.set()
                elif kind == "order":
                    ordered_ids, done = payload
                    for index, doc_id in enumerate(ordered_ids):
                        conn.execute(
                            "UPDATE documents SET sort_index=? WHERE id=?", (index, doc_id)
                        )
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "meta":
                    key, value, done = payload
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value)
                    )
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "folder-create":
                    name, done = payload
                    conn.execute(
                        "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                        (name, time.time()),
                    )
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "folder-rename":
                    old, new, done = payload
                    conn.execute(
                        "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                        (new, time.time()),
                    )
                    conn.execute(
                        "UPDATE documents SET folder=? WHERE folder=?", (new, old)
                    )
                    conn.execute("DELETE FROM folders WHERE name=?", (old,))
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "folder-delete":
                    name, done = payload
                    conn.execute(
                        "UPDATE documents SET folder='' WHERE folder=?", (name,)
                    )
                    conn.execute("DELETE FROM folders WHERE name=?", (name,))
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "doc-folder":
                    doc_id, folder, done = payload
                    conn.execute(
                        "UPDATE documents SET folder=? WHERE id=?", (folder, doc_id)
                    )
                    if folder:
                        conn.execute(
                            "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                            (folder, time.time()),
                        )
                    conn.commit()
                    if done is not None:
                        done.set()
                elif kind == "delete":
                    doc_id, done = payload
                    row = conn.execute(
                        "SELECT format FROM documents WHERE id=?", (doc_id,)
                    ).fetchone()
                    fmt = row["format"] if row else "txt"
                    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                    conn.commit()
                    (self._notes / f"{doc_id}.{fmt}").unlink(missing_ok=True)
                    (self._notes / f"{doc_id}.{'md' if fmt == 'txt' else 'txt'}").unlink(
                        missing_ok=True
                    )
                    import shutil

                    shutil.rmtree(self._assets / doc_id, ignore_errors=True)
                    self._emit_deleted([doc_id])
                    if done is not None:
                        done.set()
                elif kind == "purge_closed":
                    done, report, keep_ids = payload
                    rows = [
                        r
                        for r in conn.execute(
                            "SELECT id, format, LENGTH(CAST(content AS BLOB)) AS n"
                            " FROM documents WHERE state='closed'"
                        ).fetchall()
                        if r["id"] not in keep_ids
                    ]
                    if rows:
                        ids = [r["id"] for r in rows]
                        id_set = set(ids)
                        report.purged_docs = len(ids)
                        report.purged_bytes = sum(int(r["n"] or 0) for r in rows)
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            conn.executemany(
                                "DELETE FROM documents WHERE id=?",
                                [(doc_id,) for doc_id in ids],
                            )
                            stale: list[str] = []
                            for row in conn.execute("SELECT key, value FROM meta"):
                                key = row["key"]
                                value = row["value"]
                                if key.startswith("ext:"):
                                    if value in id_set:
                                        stale.append(key)
                                elif key.startswith(("source_path:", "cursor:")):
                                    if key.split(":", 1)[1] in id_set:
                                        stale.append(key)
                            if stale:
                                conn.executemany(
                                    "DELETE FROM meta WHERE key=?", [(k,) for k in stale]
                                )
                            conn.execute("COMMIT")
                        except sqlite3.Error:
                            conn.execute("ROLLBACK")
                            raise
                        # 行已提交后再删文件：中途异常只会留下孤儿，之后维护可回收
                        import shutil

                        for doc_id in ids:
                            for mirror in self._notes.glob(f"{doc_id}.*"):
                                try:
                                    mirror.unlink()
                                except OSError as exc:
                                    report.errors.append(f"{mirror.name}: {exc}")
                            target = self._assets / doc_id
                            try:
                                if target.is_symlink():
                                    target.unlink()
                                elif target.is_dir():
                                    shutil.rmtree(target)
                            except OSError as exc:
                                report.errors.append(f"{doc_id}: {exc}")
                        self._emit_deleted(ids)
                    if done is not None:
                        done.set()
                elif kind == "maintain":
                    done, report, vacuum = payload
                    report.db_bytes_before = _db_footprint(self._db_path)
                    ids = {row["id"] for row in conn.execute("SELECT id FROM documents")}
                    for path, is_dir in self._orphan_paths(ids):
                        if is_dir:
                            size = _tree_size(path)
                            report.orphan_assets += 1
                            report.orphan_assets_bytes += size
                        elif path.parent == self._recovery:
                            report.orphan_journals += 1
                        else:
                            report.orphan_notes += 1
                            report.orphan_notes_bytes += _file_size(path)
                        self._remove_orphan(path, is_dir, report)

                    stale = self._stale_keys_from_rows(
                        conn.execute("SELECT key, value FROM meta").fetchall(), ids
                    )
                    if stale:
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            conn.executemany(
                                "DELETE FROM meta WHERE key=?", [(k,) for k in stale]
                            )
                            conn.execute("COMMIT")
                        except sqlite3.Error:
                            conn.execute("ROLLBACK")
                            raise
                        report.stale_meta = len(stale)

                    if vacuum:
                        try:
                            conn.execute("VACUUM")
                            # WAL 模式下 VACUUM 只重写主库，再把 -wal 截断到最小
                            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            report.vacuumed = True
                        except sqlite3.Error as exc:
                            report.errors.append(f"数据库压缩未完成：{exc}")
                    report.db_bytes_after = _db_footprint(self._db_path)
                    if done is not None:
                        done.set()
                elif kind == "flush":
                    done = payload[0]
                    self._drain_pending(conn)
                    done.set()
                elif kind == "snapshot":
                    target, done, error = payload
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        import shutil

                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(self._db_path, target)
                    except (OSError, sqlite3.Error) as exc:
                        error.append(str(exc))
                    finally:
                        done.set()
                elif kind == "apply_sync":
                    doc, done, error = payload
                    try:
                        existing = conn.execute(
                            "SELECT revision FROM documents WHERE id=?", (doc["id"],)
                        ).fetchone()
                        if existing is not None:
                            new_rev = max(existing["revision"], int(doc["revision"])) + 1
                            conn.execute(
                                "UPDATE documents SET title=?, format=?, content=?,"
                                " sort_index=?, state=?, revision=?, created_at=?,"
                                " updated_at=?, folder=? WHERE id=?",
                                (
                                    doc["title"], doc["format"], doc["content"],
                                    doc["sort_index"], doc["state"], new_rev,
                                    doc["created_at"], doc["updated_at"], doc["folder"],
                                    doc["id"],
                                ),
                            )
                        else:
                            conn.execute(
                                "INSERT INTO documents(id, title, format, content,"
                                " sort_index, state, revision, created_at, updated_at, folder)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (
                                    doc["id"], doc["title"], doc["format"], doc["content"],
                                    doc["sort_index"], doc["state"], int(doc["revision"]),
                                    doc["created_at"], doc["updated_at"], doc["folder"],
                                ),
                            )
                            new_rev = int(doc["revision"])
                        if doc.get("folder"):
                            conn.execute(
                                "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                                (doc["folder"], doc["created_at"] or 0),
                            )
                        conn.commit()
                        self._mirror(doc["id"], doc["content"], doc["format"])
                        doc["_applied_revision"] = new_rev
                    except sqlite3.Error as exc:
                        error.append(str(exc))
                    finally:
                        done.set()
                elif kind == "delete_sync":
                    doc_id, preserve, done, error = payload
                    try:
                        row = conn.execute(
                            "SELECT content, format FROM documents WHERE id=?", (doc_id,)
                        ).fetchone()
                        if row is not None and preserve is not None:
                            preserve.parent.mkdir(parents=True, exist_ok=True)
                            _atomic_write(
                                preserve,
                                row["content"].encode("utf-8"),
                            )
                        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                        conn.commit()
                        if row is not None:
                            fmt = row["format"]
                            (self._notes / f"{doc_id}.{fmt}").unlink(missing_ok=True)
                            (
                                self._notes / f"{doc_id}.{'md' if fmt == 'txt' else 'txt'}"
                            ).unlink(missing_ok=True)
                            import shutil

                            shutil.rmtree(self._assets / doc_id, ignore_errors=True)
                    except (OSError, sqlite3.Error) as exc:
                        error.append(str(exc))
                    finally:
                        done.set()
                elif kind == "folder-merge":
                    folders, done = payload
                    try:
                        conn.executemany(
                            "INSERT OR IGNORE INTO folders(name, created_at) VALUES(?,?)",
                            [(name, created_at or 0) for name, created_at in folders],
                        )
                        conn.commit()
                    except sqlite3.Error as exc:
                        self._last_error = str(exc)
                    finally:
                        done.set()
            except sqlite3.Error as exc:
                self._last_error = str(exc)
                if kind == "save":
                    self._emit(SaveState("", "error", f"数据库写入失败：{exc}", time.time()))
                self._set_done(payload, exc)
        conn.close()

    @staticmethod
    def _set_done(payload, exc: Exception) -> None:
        done = None
        if isinstance(payload, tuple):
            for item in payload:
                if isinstance(item, threading.Event):
                    done = item
                    break
        if done is not None:
            done.set()

    def _drain_pending(self, conn: sqlite3.Connection) -> None:
        with self._pending_lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for doc_id, payload in pending:
            self._do_save_with(conn, doc_id, payload)

    def _do_save(self, conn: sqlite3.Connection, doc_id: str | None) -> None:
        with self._pending_lock:
            if doc_id is None:
                doc_id = next(iter(self._pending), None)
            if doc_id is None:
                return
            payload = self._pending.pop(doc_id, None)
        if payload is None:
            return
        self._do_save_with(conn, doc_id, payload)

    def _do_save_with(self, conn: sqlite3.Connection, doc_id: str, payload: dict) -> None:

        journal = self._recovery / f"{doc_id}.json"
        try:
            _atomic_write(
                journal,
                json.dumps(
                    {
                        "id": doc_id,
                        "revision": payload["revision"],
                        "content": payload["content"],
                        "ts": payload["updated_at"],
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        except OSError as exc:
            # 恢复日志写不进去时依然尝试提交，但把问题暴露给 UI
            self._emit(SaveState(doc_id, "error", f"恢复日志写入失败：{exc}", time.time()))

        try:
            conn.execute(
                "UPDATE documents SET title=?, format=?, content=?, revision=?, updated_at=?"
                " WHERE id=? AND revision<=?",
                (
                    payload["title"],
                    payload["format"],
                    payload["content"],
                    payload["revision"],
                    payload["updated_at"],
                    doc_id,
                    payload["revision"],
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            self._emit(SaveState(doc_id, "error", f"保存失败：{exc}", time.time()))
            return

        journal.unlink(missing_ok=True)

        mirror_error = ""
        try:
            self._mirror(doc_id, payload["content"], payload["format"])
        except OSError as exc:
            mirror_error = str(exc)
        if mirror_error:
            self._emit(
                SaveState(doc_id, "error", f"内容已入库，镜像文件写入失败：{mirror_error}", time.time())
            )
        else:
            self._emit(SaveState(doc_id, "saved", "", payload["updated_at"]))

    def _mirror(self, doc_id: str, content: str, fmt: str) -> None:
        path = self._notes / f"{doc_id}.{fmt}"
        _atomic_write(path, content.encode("utf-8"))
        # 切换格式后清掉旧扩展名镜像
        other = self._notes / f"{doc_id}.{'md' if fmt == 'txt' else 'txt'}"
        if other.exists():
            other.unlink(missing_ok=True)
