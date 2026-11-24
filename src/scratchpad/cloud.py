"""云备份 / 云同步管理器（sync v1）。

职责：配置读取（meta + libsecret）、后台线程调度（自动备份 / 自动同步）、
远端备份包上传。不含 UI；GTK 接线在 window.py（CloudDialog / 定时器 /
关闭钩子）。

调度策略（docs/SYNC_PROTOCOL.md §9）：
- 自动备份：默认 30 分钟 + 关闭时；仅 fingerprint 变化时上传
  `gscratchpad-cloud-<device-id>.zip`（R50 起双端统一命名）。
- 自动同步：默认 5 分钟；启动延迟 15s、内容变更防抖 10s、关闭时 flush。
- Android 端仅应用打开时同步（无后台调度）。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import backupzip
from .syncengine import SyncEngine, SyncState
from .webdav import WebDavClient, WebDavError, parse_base_url

# R50 起双端统一命名；旧固定名仅作为只读恢复候选。
BACKUP_PREFIX = "gscratchpad-cloud-"
BACKUP_LEGACY_DESKTOP = "gscratchpad-desktop.zip"
BACKUP_LEGACY_ANDROID = "gscratchpad-cloud.zip"
BACKUP_REMOTE = BACKUP_LEGACY_DESKTOP  # 兼容旧引用；上传不再使用


def backup_remote_name(device_id: str) -> str:
    return f"{BACKUP_PREFIX}{device_id}.zip"


def is_backup_zip(name: str) -> bool:
    return (
        name in (BACKUP_LEGACY_DESKTOP, BACKUP_LEGACY_ANDROID)
        or (name.startswith(BACKUP_PREFIX) and name.endswith(".zip") and len(name) > len(BACKUP_PREFIX) + 4)
    )


@dataclass(frozen=True)
class RemoteBackup:
    name: str
    size: int = -1
    modified: str = ""
BACKUP_INTERVAL_DEFAULT = 30 * 60
SYNC_INTERVAL_DEFAULT = 5 * 60
STARTUP_DELAY = 15.0
CHANGE_DEBOUNCE = 10.0


# ---------------------------------------------------------------------- 密码

def _secret_schema():
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    return Secret.Schema.new(
        "io.github.gscratchpad.CloudPassword",
        Secret.SchemaFlags.NONE,
        {"app": "gscratchpad", "user": "s"},
    )


def load_password(user: str, store=None) -> str:
    """libsecret 优先，失败/缺失回退 meta 明文（与 Android 现状一致的兜底）。"""
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        secret = Secret.password_lookup_sync(
            _secret_schema(), {"app": "gscratchpad", "user": user}, None
        )
        if secret:
            return secret
    except Exception:  # noqa: BLE001 - keyring 不可用时静默回退
        pass
    if store is not None:
        return store.get_meta("webdav_pass", "") or ""
    return ""


def save_password(user: str, password: str) -> bool:
    """写 libsecret；返回是否成功（失败由调用方回退 meta）。"""
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        return Secret.password_store_sync(
            _secret_schema(),
            {"app": "gscratchpad", "user": user},
            Secret.COLLECTION_DEFAULT,
            "gscratchpad WebDAV 密码",
            password,
            None,
        )
    except Exception:  # noqa: BLE001
        return False


def clear_password(user: str) -> None:
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        Secret.password_clear_sync(
            _secret_schema(), {"app": "gscratchpad", "user": user}, None
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------- 管理器

class CloudManager:
    """备份/同步调度与执行。线程安全：任务串行化（单飞行守卫）。"""

    def __init__(self, store) -> None:
        self.store = store
        self._backup_busy = threading.Lock()
        self._sync_busy = threading.Lock()
        self.on_status = None  # callable(str)
        self.on_error = None  # callable(str)

        # 删除事件 → 墓碑集合（无论同步开关与否都记录，启用后才能正确传播）
        store.on_deleted(self._on_docs_deleted)
        # 迁移旧 libsecret 密码到新 schema 无需处理：schema 自 v1 起即本模块管理

    # ---------------------------------------------------------------- 配置

    def config_url(self) -> str:
        return self.store.get_meta("webdav_url", "") or ""

    def config_user(self) -> str:
        url = self.config_url()
        try:
            _, embedded = parse_base_url(url)
        except WebDavError:
            embedded = ""
        explicit = self.store.get_meta("webdav_user", "") or ""
        return explicit or embedded

    def config_password(self) -> str:
        user = self.config_user()
        password = load_password(user)
        if not password:
            password = self.store.get_meta("webdav_pass", "") or ""
        return password

    def _client(self) -> WebDavClient | None:
        url = self.config_url()
        if not url:
            return None
        return WebDavClient(
            url,
            self.store.get_meta("webdav_user", "") or "",
            self.config_password(),
        )

    # ---------------------------------------------------------------- 备份文件

    def backup_device_id(self) -> str:
        """复用同步 device_id；未启用同步的设备也生成并落盘一次。"""
        state_path = Path(self.store.root) / "sync-state.json"
        state = SyncState.load(state_path)
        raw = ""
        try:
            if state_path.exists():
                raw = state_path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        if '"device_id"' not in raw:
            try:
                state.save(state_path)
            except OSError:
                pass
        return state.device_id

    def backup_remote_name(self) -> str:
        return backup_remote_name(self.backup_device_id())

    def list_remote_backups(self) -> list[RemoteBackup]:
        """列远端备份 zip（新格式 + 旧名），按修改时间倒序。"""
        client = self._client()
        if client is None:
            return []
        return [
            RemoteBackup(name=name, size=size, modified=modified)
            for name, size, modified in client.propfind_entries("")
            if is_backup_zip(name)
        ]

    def download_backup(self, name: str, target: Path) -> int:
        """下载指定远端备份 zip 到本地，返回字节数。"""
        client = self._client()
        if client is None:
            raise WebDavError("未配置 WebDAV 地址")
        data = client.get(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    def save_config(
        self,
        url: str,
        user: str,
        password: str,
        remember_in_meta: bool,
    ) -> None:
        """保存地址与用户到 meta；密码入 libsecret，失败且 remember 时入 meta。"""
        self.store.set_meta("webdav_url", url.strip(), wait=True)
        self.store.set_meta("webdav_user", user.strip(), wait=True)
        self.store.set_meta("webdav_pass", "", wait=True)  # 清残留明文
        if password:
            if not save_password(user.strip(), password):
                if remember_in_meta:
                    self.store.set_meta("webdav_pass", password, wait=True)
        else:
            clear_password(user.strip())

    def set_enabled(self, *, autobackup: bool | None = None, autosync: bool | None = None) -> None:
        if autobackup is not None:
            self.store.set_meta("cloud_autobackup", "1" if autobackup else "0", wait=True)
        if autosync is not None:
            self.store.set_meta("cloud_autosync", "1" if autosync else "0", wait=True)

    @staticmethod
    def autobackup_enabled(store) -> bool:
        return (store.get_meta("cloud_autobackup", "0") or "0") == "1"

    @staticmethod
    def autosync_enabled(store) -> bool:
        return (store.get_meta("cloud_autosync", "0") or "0") == "1"

    # ---------------------------------------------------------------- 墓碑

    def _on_docs_deleted(self, ids: list[str]) -> None:
        try:
            state = SyncState.load(Path(self.store.root) / "sync-state.json")
            changed = False
            for doc_id in ids:
                if doc_id not in state.deleted:
                    state.add_deleted(doc_id)
                    changed = True
            if changed:
                state.save(Path(self.store.root) / "sync-state.json")
        except Exception:  # noqa: BLE001 - 墓碑记录失败不阻断删除
            pass

    # ---------------------------------------------------------------- 备份

    def run_backup(self) -> str:
        """执行一次远端备份。返回状态消息（后台线程中调用）。"""
        client = self._client()
        if client is None:
            return "未配置 WebDAV 地址"
        fp = self.store.fingerprint()
        if fp == (self.store.get_meta("cloud_backup_fp", "") or ""):
            return "备份跳过：内容无变化"
        with self._backup_busy:
            tmp = Path(tempfile.mkdtemp(prefix="gsp-backup-"))
            try:
                snapshot = tmp / "snapshot.db"
                if not self.store.snapshot_db_to(snapshot):
                    return "备份失败：数据库快照未生成"
                report = backupzip.export_backup_zip(
                    tmp / "out.zip",
                    app_version=_app_version(),
                    snapshot_db=snapshot,
                    notes_dir=Path(self.store.root) / "notes",
                    assets_dir=Path(self.store.root) / "assets",
                )
                if report.errors:
                    return f"备份失败：{report.errors[0]}"
                name = self.backup_remote_name()
                client.put(name, (tmp / "out.zip").read_bytes(), "application/zip")
                self.store.set_meta("cloud_backup_fp", fp)
                self.store.set_meta("cloud_backup_at", str(time.time()))
                return f"备份完成：{report.bytes_written} B → {name}"
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------------- 同步

    def run_sync(self) -> str:
        """执行一次同步。返回状态消息（后台线程中调用）。"""
        client = self._client()
        if client is None:
            return "未配置 WebDAV 地址"
        with self._sync_busy:
            engine = SyncEngine(self.store, client, status_cb=self._emit_status)
            result = engine.run()
            self.store.set_meta("cloud_sync_at", str(time.time()))
            return result.message

    # ---------------------------------------------------------------- 后台封装

    def backup_async(self, done=None) -> None:
        if not self.config_url():
            return

        def worker() -> None:
            try:
                message = self.run_backup()
            except Exception as exc:  # noqa: BLE001
                message = f"备份失败：{exc}"
            self._emit_status(message)
            if done is not None:
                done(message)

        threading.Thread(target=worker, name="gsp-backup", daemon=True).start()

    def sync_async(self, done=None) -> None:
        if not self.config_url():
            return

        def worker() -> None:
            try:
                message = self.run_sync()
            except Exception as exc:  # noqa: BLE001
                message = f"同步失败：{exc}"
            self._emit_status(message)
            if done is not None:
                done(message)

        threading.Thread(target=worker, name="gsp-sync", daemon=True).start()

    def close_flush(self) -> None:
        """窗口关闭前：推送本地变更与备份（尽力而为，限时）。"""
        if not self.config_url():
            return
        try:
            if self.autosync_enabled(self.store):
                self.run_sync()
            if self.autobackup_enabled(self.store):
                self.run_backup()
        except Exception:  # noqa: BLE001 - 关闭路径绝不阻塞退出
            pass

    def _emit_status(self, text: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                pass


def _app_version() -> str:
    from . import paths

    return paths.APP_VERSION
