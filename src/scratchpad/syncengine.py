"""云同步引擎（sync v1，语义规约见 docs/SYNC_PROTOCOL.md）。

结构分两层：

- `plan_sync()`：纯函数合并规划器。输入本地文档状态、上次推送基线、墓碑集合
  与各对端 manifest，输出决策列表（应用/冲突/删除/恢复/合并文件夹）。两侧
  （桌面 Python 与 Android Kotlin）共用同一组夹具验证本函数语义
  （`tests/test_sync_merge.py`）。
- `SyncEngine`：IO 编排。WebDAV 拉推、资源补缺、经 store 工作线程落库、
  冲突/删除败者保全到 `recovery/sync-<ts>/`、本地状态文件读写。

核心语义（详见规约 §4–§7）：

- **墓碑** = 每设备 `deleted: {doc_id: 删除时间戳}` 随 manifest 传播。
  统一裁决规则：`updated_at` 新者胜——文档比墓碑新则文档胜（删除被编辑/
  重建压过），墓碑不旧于文档则删除胜（删除传播）。
- **双变冲突**：`updated_at` 新者胜，败者正文保全；平局本地胜。
- **assets** 内容寻址（sha256 前 12 位），存在即跳过，天然免冲突。
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .webdav import WebDavClient, WebDavError

PROTOCOL = 1
PUSH_INTERVAL_HINT = 300.0  # 默认同步周期（秒），UI 可配


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def folders_hash(folders: list[tuple[str, float]]) -> str:
    joined = "\n".join(f"{name}:{ts}" for name, ts in sorted(folders))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- 状态

@dataclass
class SyncState:
    """本地同步状态（设备本地文件，随引擎读写）。"""

    device_id: str = ""
    device_name: str = ""
    deleted: dict[str, float] = field(default_factory=dict)  # id -> 删除时间戳
    own_pushed: dict[str, str] = field(default_factory=dict)  # id -> content_hash
    own_folders_hash: str = ""
    own_pushed_deleted: dict[str, float] = field(default_factory=dict)
    own_assets_pushed: list[str] = field(default_factory=list)
    peers: dict[str, dict[str, str]] = field(default_factory=dict)
    last_result: str = ""

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        state = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("protocol") == PROTOCOL:
            state.device_id = data.get("device_id", "")
            state.device_name = data.get("device_name", "")
            raw_deleted = data.get("deleted", {})
            if isinstance(raw_deleted, list):  # 兼容无时间戳的早期格式
                state.deleted = {doc_id: time.time() for doc_id in raw_deleted}
            else:
                state.deleted = {str(k): float(v) for k, v in raw_deleted.items()}
            state.own_pushed = dict(data.get("own_pushed", {}))
            state.own_folders_hash = data.get("own_folders_hash", "")
            raw_pd = data.get("own_pushed_deleted", {})
            if isinstance(raw_pd, list):
                state.own_pushed_deleted = {doc_id: 0.0 for doc_id in raw_pd}
            else:
                state.own_pushed_deleted = {str(k): float(v) for k, v in raw_pd.items()}
            state.own_assets_pushed = list(data.get("own_assets_pushed", []))
            state.peers = {k: dict(v) for k, v in data.get("peers", {}).items()}
            state.last_result = data.get("last_result", "")
        if not state.device_id:
            state.device_id = uuid.uuid4().hex
        if not state.device_name:
            try:
                state.device_name = socket.gethostname() or "desktop"
            except OSError:
                state.device_name = "desktop"
        return state

    def save(self, path: Path) -> None:
        from .store import _atomic_write

        payload = {
            "protocol": PROTOCOL,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "deleted": self.deleted,
            "own_pushed": self.own_pushed,
            "own_folders_hash": self.own_folders_hash,
            "own_pushed_deleted": self.own_pushed_deleted,
            "own_assets_pushed": sorted(set(self.own_assets_pushed)),
            "peers": self.peers,
            "last_result": self.last_result,
        }
        _atomic_write(Path(path), json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def add_deleted(self, doc_id: str, ts: float | None = None) -> None:
        """登记墓碑：保留更强（更新）的删除时间。"""
        ts = time.time() if ts is None else float(ts)
        current = self.deleted.get(doc_id)
        if current is None or ts > current:
            self.deleted[doc_id] = ts
        self.own_pushed.pop(doc_id, None)

    def remove_deleted(self, doc_id: str) -> None:
        self.deleted.pop(doc_id, None)
        self.own_pushed_deleted.pop(doc_id, None)


# ---------------------------------------------------------------------- 规划

@dataclass(frozen=True)
class PeerManifest:
    device_id: str
    device_name: str
    docs: dict[str, dict]  # id -> manifest 条目
    deleted: dict[str, float]  # id -> 删除时间戳
    folders: list  # [(name, created_at)]
    exported_at: float


@dataclass
class SyncPlan:
    applies: list[tuple[str, dict]] = field(default_factory=list)
    preserve_local_before_apply: list[str] = field(default_factory=list)
    preserve_peer: list[tuple[str, str]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    folder_merge: list = field(default_factory=list)
    undelete: list[str] = field(default_factory=list)
    tombstones_learned: dict[str, float] = field(default_factory=dict)
    new_peers: dict[str, dict[str, str]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


def plan_sync(
    *,
    local: dict[str, dict],
    own_pushed: dict[str, str],
    own_deleted: dict[str, float],
    peers: list[PeerManifest],
    peer_states: dict[str, dict[str, str]],
    now: float,
) -> SyncPlan:
    """纯函数合并规划。`local` 元素 {hash, revision, updated_at}。

    处理顺序：先收集全部对端墓碑（T），后处理各对端文档条目（D）——防止
    对端陈旧条目复活刚学到的删除。冲突判定以「当前本地」为准（前一对端的
    应用结果会更新模拟状态）。
    """
    plan = SyncPlan()
    working_deleted = dict(own_deleted)
    working_local = {doc_id: dict(info) for doc_id, info in local.items()}

    # ---- T：墓碑收集与删除传播
    for peer in peers:
        for doc_id, del_ts in peer.deleted.items():
            known = working_deleted.get(doc_id)
            if known is not None:
                if del_ts > known:
                    working_deleted[doc_id] = del_ts
                    plan.tombstones_learned[doc_id] = del_ts
                continue
            info = working_local.get(doc_id)
            if info is not None:
                if info["updated_at"] > del_ts:
                    # 本地文档比删除更新：文档胜（规约 §4，编辑/重建压过删除）
                    plan.stats["delete_vs_edit"] = plan.stats.get("delete_vs_edit", 0) + 1
                    continue
                plan.deletes.append(doc_id)
                del working_local[doc_id]
            working_deleted[doc_id] = del_ts
            plan.tombstones_learned[doc_id] = del_ts

    # ---- D：对端文档条目
    for peer in peers:
        baseline = peer_states.get(peer.device_id, {})
        new_baseline: dict[str, str] = {}
        for doc_id, entry in peer.docs.items():
            peer_hash = entry["content_hash"]
            if doc_id in working_deleted:
                if entry["updated_at"] > working_deleted[doc_id]:
                    # 对端文档比墓碑新：对端重建/编辑胜 → 恢复（规约 §4.3）
                    plan.undelete.append(doc_id)
                    plan.applies.append((peer.device_id, entry))
                    working_local[doc_id] = {
                        "hash": peer_hash,
                        "revision": entry["revision"],
                        "updated_at": entry["updated_at"],
                    }
                    working_deleted.pop(doc_id)
                    new_baseline[doc_id] = peer_hash
                # 否则墓碑胜（陈旧条目）：跳过
                continue
            local_info = working_local.get(doc_id)
            if local_info is None:
                plan.applies.append((peer.device_id, entry))
                working_local[doc_id] = {
                    "hash": peer_hash,
                    "revision": entry["revision"],
                    "updated_at": entry["updated_at"],
                }
                new_baseline[doc_id] = peer_hash
                continue
            local_hash = local_info["hash"]
            if peer_hash == local_hash:
                new_baseline[doc_id] = peer_hash
                continue
            peer_changed = peer_hash != baseline.get(doc_id)
            local_changed = local_hash != own_pushed.get(doc_id)
            if peer_changed and local_changed:
                # 冲突：updated_at 新者胜，平局本地胜
                peer_wins = entry["updated_at"] > local_info["updated_at"]
                if peer_wins:
                    plan.preserve_local_before_apply.append(doc_id)
                    plan.applies.append((peer.device_id, entry))
                    working_local[doc_id] = {
                        "hash": peer_hash,
                        "revision": entry["revision"],
                        "updated_at": entry["updated_at"],
                    }
                    new_baseline[doc_id] = peer_hash
                else:
                    plan.preserve_peer.append((peer.device_id, doc_id))
                plan.stats["conflicts"] = plan.stats.get("conflicts", 0) + 1
            elif peer_changed and not local_changed:
                plan.applies.append((peer.device_id, entry))
                working_local[doc_id] = {
                    "hash": peer_hash,
                    "revision": entry["revision"],
                    "updated_at": entry["updated_at"],
                }
                new_baseline[doc_id] = peer_hash
            else:
                # 仅本地变（push 处理）或内容同源：仅刷新基线
                new_baseline[doc_id] = baseline.get(doc_id, local_hash)
        plan.new_peers[peer.device_id] = new_baseline

    # ---- 文件夹合并
    seen_folders: set[str] = set()
    for peer in peers:
        for name, created_at in peer.folders:
            if name not in seen_folders:
                seen_folders.add(name)
                plan.folder_merge.append((name, created_at))

    plan.stats["applies"] = len(plan.applies)
    plan.stats["deletes"] = len(plan.deletes)
    return plan


# ---------------------------------------------------------------------- 引擎

@dataclass
class SyncResult:
    ok: bool = False
    message: str = ""
    applied: int = 0
    deleted: int = 0
    conflicts: int = 0
    pushed_docs: int = 0
    uploaded_assets: int = 0


class SyncEngine:
    """单次同步的 IO 编排。所有网络与 db 操作均为阻塞调用，必须在后台线程运行。"""

    def __init__(
        self,
        store,
        client: WebDavClient,
        state_path: Path | None = None,
        status_cb=None,
    ) -> None:
        self.store = store
        self.client = client
        self.state_path = Path(state_path or (Path(self.store.root) / "sync-state.json"))
        self.status_cb = status_cb

    # ---------------------------------------------------------------- 消息

    def _status(self, text: str) -> None:
        if self.status_cb is not None:
            try:
                self.status_cb(text)
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 入口

    def run(self) -> SyncResult:
        result = SyncResult()
        try:
            self._run_inner(result)
        except WebDavError as exc:
            result.message = f"同步失败：{exc}"
        except (OSError, RuntimeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            result.message = f"同步失败：{exc}"
        return result

    def _run_inner(self, result: SyncResult) -> None:
        state = SyncState.load(self.state_path)
        self.store.flush()
        self._status("同步：读取本地变更…")

        # 本地现状
        docs = self.store.all_documents()
        local: dict[str, dict] = {}
        for doc in docs:
            local[doc.id] = {
                "hash": content_hash(doc.content),
                "revision": doc.revision,
                "updated_at": doc.updated_at,
                "format": doc.format,
            }
        folders = [(f, 0.0) for f in self.store.folders()]

        # ---- 墓碑一致性收敛（必须在 pull 之前）：
        # 1) 隐式墓碑发现：上次推送过但本地已不存在 → 视为本地已删除
        #    （防对端陈旧 manifest 先把它们复活回来）
        # 2) 文档压过墓碑：本地存在且比墓碑新 → 撤销墓碑（重建/恢复场景）
        # 3) 墓碑压过本地文档：本地存在但墓碑更新 → 保全后删除
        now_ts = time.time()
        for doc_id in list(state.own_pushed):
            if doc_id not in local and doc_id not in state.deleted:
                state.add_deleted(doc_id, now_ts)
        for doc_id in list(state.deleted):
            info = local.get(doc_id)
            if info is None:
                continue
            if info["updated_at"] > state.deleted[doc_id]:
                state.remove_deleted(doc_id)
            else:
                preserve_dir = self._preserve_dir()
                self.store.delete_remote(
                    doc_id,
                    preserve_dir / f"{doc_id}-deleted.{info.get('format', 'txt')}",
                )
                local.pop(doc_id, None)
                result.deleted += 1

        # ---- Pull
        self._status("同步：检查远端设备…")
        self._ensure_remote_dirs(state)
        peers = self._fetch_peer_manifests(state)
        plan = plan_sync(
            local={
                k: {k2: v2 for k2, v2 in v.items() if k2 != "format"}
                for k, v in local.items()
            },
            own_pushed=state.own_pushed,
            own_deleted=state.deleted,
            peers=peers,
            peer_states=state.peers,
            now=now_ts,
        )

        preserve_dir = self._preserve_dir()
        # 冲突计数直接取 planner 统计（含「对端胜→应用」与「本地胜→保全」两个方向）
        result.conflicts = plan.stats.get("conflicts", 0)

        # 删除传播（败者保全：被删正文存 recovery/sync-<ts>/）
        for doc_id in plan.deletes:
            ext = local.get(doc_id, {}).get("format", "txt")
            self.store.delete_remote(doc_id, preserve_dir / f"{doc_id}-deleted.{ext}")
            result.deleted += 1

        # 远端文档应用
        peer_docs_cache: dict[str, dict[str, str] | None] = {}
        for peer_id, entry in plan.applies:
            content = self._peer_doc_content(peer_id, entry, peer_docs_cache)
            if content is None:
                result.message = result.message or f"远端正文缺失：{entry['id'][:8]}"
                continue
            doc_id = entry["id"]
            if doc_id in plan.preserve_local_before_apply:
                existing = self.store.get(doc_id)
                if existing is not None:
                    self._preserve(
                        preserve_dir,
                        f"{doc_id}-local.{existing.format}",
                        existing.content,
                    )
            self.store.apply_remote(
                {
                    "id": doc_id,
                    "title": entry["title"],
                    "format": entry["format"],
                    "content": content,
                    "sort_index": entry.get("sort_index", 0),
                    "state": entry.get("state", "open"),
                    "revision": entry.get("revision", 0),
                    "created_at": entry.get("created_at", 0.0),
                    "updated_at": entry.get("updated_at", 0.0),
                    "folder": entry.get("folder", ""),
                }
            )
            self._fetch_peer_assets(peer_id, entry)
            result.applied += 1

        # 冲突败者保全（本地胜时保存对端内容）
        for peer_id, doc_id in plan.preserve_peer:
            entry = self._entry_of(peers, peer_id, doc_id)
            content = (
                self._peer_doc_content(peer_id, entry, peer_docs_cache) if entry else None
            )
            if content is not None:
                fmt = (entry or {}).get("format", "txt")
                self._preserve(preserve_dir, f"{doc_id}-peer.{fmt}", content)

        # 文件夹合并
        if plan.folder_merge:
            self.store.merge_folders(plan.folder_merge)

        # 墓碑与基线更新
        for doc_id, ts in plan.tombstones_learned.items():
            state.add_deleted(doc_id, ts)
        for doc_id in plan.undelete:
            state.remove_deleted(doc_id)
        state.peers = plan.new_peers
        for peer in peers:
            state.peers.setdefault(peer.device_id, {})

        # ---- Push
        self._status("同步：推送本地变更…")
        result.pushed_docs = self._push(state, folders, result)

        result.ok = True
        result.message = (
            f"同步完成：应用 {result.applied}，删除 {result.deleted}，"
            f"冲突 {result.conflicts}，推送 {result.pushed_docs} 篇"
        )
        state.last_result = result.message
        state.save(self.state_path)
        self._status(f"同步：{result.message}")

    def _preserve_dir(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S")
        return Path(self.store.root) / "recovery" / f"sync-{ts}"

    # ---------------------------------------------------------------- Pull 细节

    def _ensure_remote_dirs(self, state: SyncState) -> None:
        self.client.mkcol_deep(f"sync/{state.device_id}")

    def _fetch_peer_manifests(self, state: SyncState) -> list[PeerManifest]:
        peers: list[PeerManifest] = []
        children = self.client.propfind_children("sync")
        for name in children:
            if name == state.device_id:
                continue
            raw = self.client.get_optional(f"sync/{name}/manifest.json")
            if raw is None:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if data.get("protocol") != PROTOCOL:
                continue
            raw_deleted = data.get("deleted", {})
            if isinstance(raw_deleted, list):
                deleted_map = {doc_id: 0.0 for doc_id in raw_deleted}
            else:
                deleted_map = {str(k): float(v) for k, v in raw_deleted.items()}
            peers.append(
                PeerManifest(
                    device_id=data.get("device_id", name),
                    device_name=data.get("device_name", name),
                    docs={d["id"]: d for d in data.get("docs", [])},
                    deleted=deleted_map,
                    folders=[
                        (f["name"], f.get("created_at", 0.0))
                        for f in data.get("folders", [])
                    ],
                    exported_at=data.get("exported_at", 0.0),
                )
            )
        return peers

    @staticmethod
    def _entry_of(peers: list[PeerManifest], peer_id: str, doc_id: str) -> dict | None:
        for peer in peers:
            if peer.device_id == peer_id:
                return peer.docs.get(doc_id)
        return None

    def _peer_doc_content(
        self,
        peer_id: str,
        entry: dict,
        cache: dict[str, dict[str, str] | None],
    ) -> str | None:
        if peer_id not in cache:
            raw = self.client.get_optional(f"sync/{peer_id}/docs.zip")
            if raw is None:
                cache[peer_id] = None
            else:
                contents: dict[str, str] = {}
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for name in zf.namelist():
                        if name.startswith("docs/") and not name.endswith("/"):
                            contents[name.split("/", 1)[1]] = zf.read(name).decode("utf-8")
                cache[peer_id] = contents
        contents = cache.get(peer_id)
        if contents is None:
            return None
        return contents.get(entry["id"])

    def _fetch_peer_assets(self, peer_id: str, entry: dict) -> None:
        doc_id = entry["id"]
        target_dir = Path(self.store.root) / "assets" / doc_id
        for name in entry.get("assets", []):
            dest = target_dir / name
            if dest.is_file():
                continue
            try:
                raw = self.client.get(f"sync/{peer_id}/assets/{doc_id}/{name}")
            except WebDavError:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)

    # ---------------------------------------------------------------- 本地资源

    def _local_assets(self, doc_id: str) -> list[str]:
        return [p.name for p in self._local_asset_paths(doc_id)]

    def _local_asset_paths(self, doc_id: str) -> list[Path]:
        directory = Path(self.store.root) / "assets" / doc_id
        if not directory.is_dir():
            return []
        return sorted(
            p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")
        )

    # ---------------------------------------------------------------- Push 细节

    def _build_manifest(self, state: SyncState, docs, folders) -> tuple[dict, bytes]:
        entries = []
        doc_payloads: dict[str, str] = {}
        for doc in docs:
            entry = {
                "id": doc.id,
                "title": doc.title,
                "format": doc.format,
                "revision": doc.revision,
                "updated_at": doc.updated_at,
                "created_at": doc.created_at,
                "sort_index": doc.sort_index,
                "state": doc.state,
                "folder": doc.folder,
                "content_hash": content_hash(doc.content),
                "assets": self._local_assets(doc.id),
            }
            entries.append(entry)
            doc_payloads[doc.id] = doc.content
        manifest = {
            "protocol": PROTOCOL,
            "device_id": state.device_id,
            "device_name": state.device_name,
            "exported_at": time.time(),
            "docs": entries,
            "deleted": {k: v for k, v in state.deleted.items() if k not in doc_payloads},
            "folders": [{"name": n, "created_at": ts} for n, ts in folders],
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes.decode("utf-8"))
            for doc_id, text in doc_payloads.items():
                zf.writestr(f"docs/{doc_id}", text)
        return manifest, buf.getvalue()

    def _push(self, state: SyncState, folders, result: SyncResult) -> int:
        docs = self.store.all_documents()
        current_hashes = {doc.id: content_hash(doc.content) for doc in docs}
        # 隐式墓碑发现（兜底，回调路径之外的删除）
        for doc_id in state.own_pushed:
            if doc_id not in current_hashes and doc_id not in state.deleted:
                state.add_deleted(doc_id)
        current_folders_hash = folders_hash(folders)
        current_asset_keys = {
            f"{doc.id}/{path.name}"
            for doc in docs
            for path in self._local_asset_paths(doc.id)
        }
        docs_changed = current_hashes != state.own_pushed
        folders_changed = current_folders_hash != state.own_folders_hash
        deleted_changed = state.deleted != state.own_pushed_deleted
        assets_changed = current_asset_keys != set(state.own_assets_pushed)
        if not docs_changed and not folders_changed and not deleted_changed and not assets_changed:
            self._status("同步：本地无变更")
            return 0

        self._ensure_remote_dirs(state)
        manifest, docs_zip = self._build_manifest(state, docs, folders)

        # assets：只上传未推送过的
        uploaded = 0
        pushed_set = set(state.own_assets_pushed)
        for doc in docs:
            for path in self._local_asset_paths(doc.id):
                key = f"{doc.id}/{path.name}"
                if key in pushed_set:
                    continue
                self.client.put(
                    f"sync/{state.device_id}/assets/{doc.id}/{path.name}",
                    path.read_bytes(),
                )
                pushed_set.add(key)
                uploaded += 1
        result.uploaded_assets = uploaded

        self.client.put(f"sync/{state.device_id}/docs.zip", docs_zip, "application/zip")
        self.client.put(
            f"sync/{state.device_id}/manifest.json",
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        state.own_pushed = current_hashes
        state.own_folders_hash = current_folders_hash
        state.own_pushed_deleted = dict(state.deleted)
        state.own_assets_pushed = sorted(pushed_set)
        return len(current_hashes)

    # ---------------------------------------------------------------- 保全

    @staticmethod
    def _preserve(preserve_dir: Path, filename: str, content: str) -> None:
        try:
            preserve_dir.mkdir(parents=True, exist_ok=True)
            from .store import _atomic_write

            _atomic_write(preserve_dir / filename, content.encode("utf-8"))
        except OSError:
            pass  # 保全失败不阻断同步主流程
