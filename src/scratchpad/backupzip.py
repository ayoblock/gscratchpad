"""备份包（schema 3）导出与合并导入（见 docs/SYNC_PROTOCOL.md §1、§9）。

导出结构与 Android `BackupExporter` 逐字段一致：

```
manifest.json   {"schema":3,"app_version":"1.17.0","exported_at":...}
gscratchpad.db  WAL checkpoint(TRUNCATE) 后的只读快照
notes/          镜像文件
assets/         图片资源（按 docId 分目录）
```

产出的 zip 可被 Android「导入备份」直接消费（`DesktopImporter`）；反之
Android 产出的备份包（含 v5 增量列）由 `import_backup_zip` 合并导入桌面——
读取一律用命名列，对额外列天然免疫。

导入语义 = 事务合并（对齐 Android `DesktopImporter`）：按 id 冲突时
`revision` 高者胜、低者跳过；folders INSERT OR IGNORE；meta 仅导入
`ext:*`（文档外部键），其余（几何/游标/schema_version 等）一律视为设备
本地状态不导入。整库替换不属于本模块（备份导入不破坏本地数据）。
"""

from __future__ import annotations

import json
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 3
_REMOTE_META_SKIP_PREFIXES = ("schema_version",)  # 基础设施键，永不导入
_REMOTE_META_ALLOW_PREFIXES = ("ext:",)  # 仅文档外部键可导入


@dataclass
class BackupReport:
    docs_in_source: int = 0
    docs_imported: int = 0
    docs_skipped: int = 0
    folders_imported: int = 0
    meta_imported: int = 0
    assets_imported: int = 0
    bytes_written: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        base = (
            f"导入 {self.docs_imported}/{self.docs_in_source} 篇"
            f"（冲突跳过 {self.docs_skipped}），"
            f"文件夹 {self.folders_imported}，资源 {self.assets_imported}"
        )
        if self.errors:
            base += f"；{len(self.errors)} 项失败"
        return base


# ---------------------------------------------------------------------- 导出

def export_backup_zip(
    target: Path,
    *,
    app_version: str,
    snapshot_db: Path,
    notes_dir: Path | None,
    assets_dir: Path | None,
) -> BackupReport:
    """把「已 checkpoint 的库快照 + notes + assets」打包为 schema 3 备份 zip。

    `snapshot_db` 由调用方提供（store 工作线程内 checkpoint 后复制出的
    临时文件），本函数不接触数据库。
    """
    report = BackupReport()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = json.dumps(
                {
                    "schema": SCHEMA,
                    "app_version": app_version,
                    "exported_at": time.time(),
                },
                ensure_ascii=False,
            )
            zf.writestr("manifest.json", manifest)
            zf.write(snapshot_db, "gscratchpad.db")
            if notes_dir is not None and notes_dir.is_dir():
                for file in sorted(notes_dir.iterdir()):
                    if file.is_file() and not file.name.startswith("."):
                        zf.write(file, f"notes/{file.name}")
                        report.docs_in_source += 1
            if assets_dir is not None and assets_dir.is_dir():
                for doc_dir in sorted(assets_dir.iterdir()):
                    if not (doc_dir.is_dir() and not doc_dir.is_symlink()):
                        continue
                    for file in sorted(doc_dir.iterdir()):
                        if file.is_file() and not file.name.startswith("."):
                            zf.write(
                                file, f"assets/{doc_dir.name}/{file.name}"
                            )
                            report.assets_imported += 1
        report.bytes_written = target.stat().st_size
    except (OSError, zipfile.BadZipFile) as exc:
        report.errors.append(f"打包失败：{exc}")
    return report


# ---------------------------------------------------------------------- 导入

def import_backup_zip(zip_path: Path, *, assets_dir: Path) -> tuple[BackupReport, list[dict]]:
    """读取备份 zip，返回 (报告, 待应用文档列表)。

    本函数只做「解包 + 快照库读取」，不直接写库——文档落库由调用方经
    store 工作线程 `apply_remote` 执行（保证单线程写入与镜像一致），冲突
    判定（本地 revision >= 备份 revision 则跳过）也在调用方完成。
    `docs` 元素为 store.apply_remote 接受的 dict，另含 `ext:*` meta 键值对
    （{meta_key, meta_value}）供调用方走 set_meta。
    """
    report = BackupReport()
    docs: list[dict] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if int(manifest.get("schema", 0)) != SCHEMA:
                report.errors.append(f"备份 schema 不支持：{manifest.get('schema')}")
                return report, docs
            with _snapshot_connection(zf) as snap:
                rows = snap.execute(
                    "SELECT id, title, format, content, sort_index, state,"
                    " revision, created_at, updated_at, folder FROM documents"
                ).fetchall()
                local_folders = {r[0] for r in snap.execute("SELECT name FROM folders")}
                report.folders_imported = len(local_folders)
                for row in rows:
                    report.docs_in_source += 1
                    docs.append(
                        {
                            "id": row["id"],
                            "title": row["title"],
                            "format": row["format"],
                            "content": row["content"],
                            "sort_index": row["sort_index"],
                            "state": row["state"],
                            "revision": row["revision"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                            "folder": row["folder"],
                            "assets": _zip_asset_names(zf, row["id"]),
                        }
                    )
                meta_rows = snap.execute("SELECT key, value FROM meta").fetchall()
                for row in meta_rows:
                    key = row["key"]
                    if key.startswith(_REMOTE_META_SKIP_PREFIXES):
                        continue
                    if not key.startswith(_REMOTE_META_ALLOW_PREFIXES):
                        continue
                    docs.append({"meta_key": key, "meta_value": row["value"]})
            # 资源解包到本地（内容寻址，同名跳过）
            for info in zf.infolist():
                name = info.filename
                if not name.startswith("assets/") or name.endswith("/"):
                    continue
                parts = name.split("/")
                if len(parts) != 3:
                    continue
                _doc_id, fname = parts[1], parts[2]
                if not fname or fname.startswith("."):
                    continue
                dest_dir = assets_dir / _doc_id
                dest = dest_dir / fname
                if dest.exists() and dest.stat().st_size == info.file_size:
                    continue
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
                report.assets_imported += 1
            # notes 镜像不属于合并导入（由 apply_sync 落库后重新生成）
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
        report.errors.append(f"读取备份失败：{exc}")
    return report, docs


def _zip_asset_names(zf: zipfile.ZipFile, doc_id: str) -> list[str]:
    prefix = f"assets/{doc_id}/"
    return [
        info.filename.split("/", 2)[2]
        for info in zf.infolist()
        if info.filename.startswith(prefix) and not info.filename.endswith("/")
    ]


class _snapshot_connection:
    """把 zip 内的 gscratchpad.db 提取到内存临时文件并打开只读连接。"""

    def __init__(self, zf: zipfile.ZipFile) -> None:
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.write(zf.read("gscratchpad.db"))
        self._tmp.close()
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = sqlite3.connect(self._tmp.name)
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def __exit__(self, *exc) -> None:
        if self._conn is not None:
            self._conn.close()
        Path(self._tmp.name).unlink(missing_ok=True)
