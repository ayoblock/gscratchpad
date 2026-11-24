"""云同步 / 备份端到端测试：本地 WebDAV stub + 双设备 Store 互同步。

覆盖：
- WebDavClient 对 stub 服务器的 PUT/GET/HEAD/PROPFIND/MKCOL 与 Basic 认证
- 备份包导出/导入往返（schema 3）
- SyncEngine：双端互推互拉、冲突败者保全 recovery/、墓碑删除传播、
  对端重建文档恢复、assets 补缺
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace as _replace  # noqa: E402

from scratchpad import backupzip, cloud as cloud_mod  # noqa: E402
from scratchpad.store import Store  # noqa: E402
from scratchpad.syncengine import SyncEngine, SyncState  # noqa: E402
from scratchpad.webdav import WebDavClient, parse_base_url  # noqa: E402

AUTH = ("admin", "secret123")


def _auth_header() -> str:
    import base64

    token = base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()
    return f"Basic {token}"


class _StubDavHandler(BaseHTTPRequestHandler):
    """内存版 WebDAV：PUT/GET/HEAD/PROPFIND/MKCOL + Basic 认证。"""

    server_version = "StubDAV/1"
    store: dict[str, bytes] = {}
    dirs: set[str] = set()
    lock = threading.Lock()

    def log_message(self, *_a) -> None:  # 静默
        pass

    def _check_auth(self) -> bool:
        return self.headers.get("Authorization") == _auth_header()

    def _deny(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="stub"')
        self.end_headers()

    def _path(self) -> str:
        return urllib.request.url2pathname(self.path.split("?")[0]).lstrip("/")

    def do_MKCOL(self) -> None:
        if not self._check_auth():
            return self._deny()
        path = self._path()
        with self.lock:
            if path in self.dirs:
                self.send_response(405)
            else:
                self.dirs.add(path)
                self.send_response(201)
        self.end_headers()

    def do_PUT(self) -> None:
        if not self._check_auth():
            return self._deny()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        with self.lock:
            self.store[self._path()] = body
            for parent in Path(self._path()).parents:
                self.dirs.add(str(parent))
        self.send_response(201)
        self.end_headers()

    def do_GET(self) -> None:
        if not self._check_auth():
            return self._deny()
        with self.lock:
            body = self.store.get(self._path())
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        if not self._check_auth():
            return self._deny()
        with self.lock:
            body = self.store.get(self._path())
        if body is None:
            self.send_response(404)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()

    def do_PROPFIND(self) -> None:
        if not self._check_auth():
            return self._deny()
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        prefix = self._path().rstrip("/")
        with self.lock:
            names = set(self.dirs) | set(self.store.keys())
        children = set()
        for name in names:
            if prefix and not name.startswith(prefix + "/"):
                continue
            rest = name[len(prefix) + 1 :] if prefix else name
            if rest:
                children.add(rest.split("/")[0])
        responses = []
        for n in sorted(children):
            full = f"{prefix}/{n}" if prefix else n
            with self.lock:
                size = len(self.store.get(full, b""))
            responses.append(
                "<D:response>"
                f"<D:href>/{full}</D:href><D:propstat><D:prop>"
                f"<D:getcontentlength>{size}</D:getcontentlength>"
                "<D:getlastmodified>Tue, 24 Nov 2026 18:00:00 GMT</D:getlastmodified>"
                "</D:prop></D:propstat></D:response>"
            )
        body = (
            '<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
            + "".join(responses)
            + "</D:multistatus>"
        ).encode()
        self.send_response(207)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CloudLocalTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubDavHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://admin@127.0.0.1:{cls.port}/dav/test"
        # 清空 stub 数据
        _StubDavHandler.store = {}
        _StubDavHandler.dirs = {"dav", "dav/test"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="gsp-sync-test-"))
        _StubDavHandler.store = {}
        _StubDavHandler.dirs = {"dav", "dav/test"}

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def _store(self, name: str) -> Store:
        store = Store(self.root / name)
        store.open()
        self.addCleanup(store.close)
        return store

    def _client(self) -> WebDavClient:
        return WebDavClient(self.base_url, "", AUTH[1])

    def _engine(self, store: Store) -> SyncEngine:
        return SyncEngine(
            store, self._client(), state_path=store.root / "sync-state.json"
        )

    # ---------------------------------------------------------- URL / 传输

    def test_parse_base_url_embedded_user(self):
        base, user = parse_base_url("http://admin@10.42.239.55:5244/dav/hdd/test")
        self.assertEqual(user, "admin")
        self.assertEqual(base, "http://10.42.239.55:5244/dav/hdd/test")

    def test_client_put_get_head_propfind(self):
        client = self._client()
        client.put("a/b.txt", b"hello", "text/plain")
        self.assertEqual(client.get("a/b.txt"), b"hello")
        self.assertEqual(client.head_size("a/b.txt"), 5)
        self.assertEqual(client.head_size("missing.txt"), -1)
        self.assertIn("b.txt", client.propfind_children("a"))

    def test_client_unauthorized(self):
        bad = WebDavClient(self.base_url, "admin", "wrong")
        with self.assertRaises(Exception):
            bad.put("x.txt", b"x")

    # ---------------------------------------------------------- 备份往返

    def test_backup_export_import_roundtrip(self):
        store_a = self._store("devA")
        doc = store_a.create_document("md", title="备份测试")
        store_a.submit_save(_replace(doc, content="# 备份正文"), wait=True)
        snapshot = self.root / "snap.db"
        self.assertTrue(store_a.snapshot_db_to(snapshot))
        report = backupzip.export_backup_zip(
            self.root / "out.zip",
            app_version="1.17.0",
            snapshot_db=snapshot,
            notes_dir=store_a.root / "notes",
            assets_dir=store_a.root / "assets",
        )
        self.assertEqual(report.errors, [])
        self.assertGreater(report.bytes_written, 0)

        # 设备 B 合并导入
        store_b = self._store("devB")
        import_report, items = backupzip.import_backup_zip(
            self.root / "out.zip", assets_dir=store_b.root / "assets"
        )
        self.assertEqual(import_report.errors, [])
        doc_items = [i for i in items if "id" in i]
        self.assertEqual(len(doc_items), 1)
        self.assertEqual(doc_items[0]["content"], "# 备份正文")
        store_b.apply_remote(doc_items[0])
        fetched = store_b.get(doc.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.content, "# 备份正文")

    # ---------------------------------------------------------- 同步引擎

    def test_engine_runs_in_worker_thread(self):
        """修订四十回归：reader 连接主线程创建，同步在守护线程跑。

        生产故障：新设备首次同步 toast「SQLite objects created in a thread
        can only be used in that same thread」——引擎从同步线程经 _query 读
        _reader。修复 = check_same_thread=False；本测试在非主线程完整跑一轮
        同步（建文档→推送），跨线程读若仍被拒则 fail。
        """
        store_a = self._store("devA")
        doc = store_a.create_document("md", title="跨线程同步")
        store_a.submit_save(_replace(doc, content="线程外正文"), wait=True)

        result: dict[str, object] = {}

        def worker():
            try:
                result["msg"] = self._engine(store_a).run().message
            except Exception as exc:  # noqa: BLE001
                result["error"] = repr(exc)

        t = threading.Thread(target=worker, name="gsp-sync-test", daemon=True)
        t.start()
        t.join(timeout=30)
        self.assertNotIn("error", result, f"同步线程异常：{result.get('error')}")
        self.assertIn("同步完成", str(result.get("msg")))

    def test_two_device_sync_flow(self):
        store_a = self._store("devA")
        store_b = self._store("devB")

        # 1. A 建文档 → 推送
        doc = store_a.create_document("md", title="同步测试")
        store_a.submit_save(_replace(doc, content="v1 内容"), wait=True)
        self.assertIn("同步完成", self._engine(store_a).run().message)

        # 2. B 拉取
        self._engine(store_b).run()
        got = store_b.get(doc.id)
        self.assertIsNotNone(got)
        self.assertEqual(got.content, "v1 内容")

        # 3. B 修改 → 推送；A 拉取
        doc_b = store_b.get(doc.id)
        store_b.submit_save(
            _replace(doc_b, content="v2 由 B 修改", revision=doc_b.revision + 1), wait=True
        )
        self._engine(store_b).run()
        self._engine(store_a).run()
        self.assertEqual(store_a.get(doc.id).content, "v2 由 B 修改")

        # 4. 双端无变化：再跑一次推送数 0
        result = self._engine(store_a).run()
        self.assertEqual(result.pushed_docs, 0)

    def test_state_only_change_triggers_push_and_peer_sees_closed(self):
        """R51：关闭文档只改 state（内容哈希不变），push 必须仍触发，
        对端应用后 closed_documents 可见——否则对端「清理已关闭文档」清不到。"""
        store_a = self._store("devA")
        store_b = self._store("devB")

        doc = store_a.create_document("md", title="关闭状态同步")
        store_a.submit_save(_replace(doc, content="v1"), wait=True)
        self._engine(store_a).run()
        self._engine(store_b).run()
        self.assertEqual(store_b.get(doc.id).state, "open")

        # A 仅关闭文档（内容不变）再推：states_changed 必须触发重传
        store_a.set_state(doc.id, "closed", wait=True)
        self._engine(store_a).run()

        # B 拉：state=closed 落库，closed_documents 能查到
        self._engine(store_b).run()
        self.assertEqual(store_b.get(doc.id).state, "closed")
        self.assertIn(doc.id, [d.id for d in store_b.closed_documents()])

        # 收敛：双端再跑一轮推送数 0
        self.assertEqual(self._engine(store_a).run().pushed_docs, 0)

    def test_conflict_loser_preserved_in_recovery(self):
        store_a = self._store("devA")
        store_b = self._store("devB")
        doc = store_a.create_document("md", title="冲突测试")
        store_a.submit_save(_replace(doc, content="base"), wait=True)
        self._engine(store_a).run()
        self._engine(store_b).run()

        # 双端各自修改（互不知晓）
        doc_a = store_a.get(doc.id)
        store_a.submit_save(
            _replace(doc_a, content="A 的修改", revision=doc_a.revision + 1), wait=True
        )
        doc_b = store_b.get(doc.id)
        store_b.submit_save(
            _replace(doc_b, content="B 的修改", revision=doc_b.revision + 1,
                     updated_at=doc_b.updated_at + 10),
            wait=True,
        )
        self._engine(store_a).run()  # A 推送自己的版本
        result = self._engine(store_b).run()  # B：冲突，A 的 updated_at 更旧 → B 胜
        self.assertGreaterEqual(result.conflicts, 1)

        # B 本地仍是自己的版本；A 的版本保全在 B 的 recovery/
        self.assertEqual(store_b.get(doc.id).content, "B 的修改")
        recovery_files = list((store_b.root / "recovery").glob("sync-*/**"))
        self.assertTrue(
            any(f.name.startswith(doc.id) for f in recovery_files if f.is_file()),
            "败者内容必须保全到 recovery/sync-*/",
        )

        # 反向：A 同步后拿到 B 的胜出版本 + 自己败者内容也保全
        self._engine(store_a).run()
        self.assertEqual(store_a.get(doc.id).content, "B 的修改")

    def test_delete_propagation_with_preservation(self):
        store_a = self._store("devA")
        store_b = self._store("devB")
        doc = store_a.create_document("md", title="删除测试")
        store_a.submit_save(_replace(doc, content="将被删除"), wait=True)
        self._engine(store_a).run()
        self._engine(store_b).run()
        self.assertIsNotNone(store_b.get(doc.id))

        # A 删除 → 推送墓碑
        store_a.delete_document(doc.id)
        self._engine(store_a).run()
        self.assertIsNone(store_a.get(doc.id))

        # B 拉取 → 本地删除 + 败者保全 + 墓碑记录
        self._engine(store_b).run()
        self.assertIsNone(store_b.get(doc.id))
        preserved = list((store_b.root / "recovery").glob("sync-*/**"))
        self.assertTrue(
            any(f.name.startswith(doc.id) for f in preserved if f.is_file())
        )
        state_b = SyncState.load(store_b.root / "sync-state.json")
        self.assertIn(doc.id, state_b.deleted)
        state_a = SyncState.load(store_a.root / "sync-state.json")
        self.assertIn(doc.id, state_a.deleted)

    def test_peer_recreation_restores_deleted_doc(self):
        store_a = self._store("devA")
        store_b = self._store("devB")
        doc = store_a.create_document("md", title="恢复测试")
        store_a.submit_save(_replace(doc, content="原文"), wait=True)
        self._engine(store_a).run()
        self._engine(store_b).run()
        store_a.delete_document(doc.id)
        self._engine(store_a).run()
        self._engine(store_b).run()
        self.assertIsNone(store_b.get(doc.id))

        # B 从备份恢复同 id 文档（重建）→ 推送
        store_b.apply_remote(
            {
                "id": doc.id,
                "title": "恢复测试",
                "format": "md",
                "content": "重建内容",
                "sort_index": 0,
                "state": "open",
                "revision": 99,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at + 100,
                "folder": "",
            }
        )
        self._engine(store_b).run()

        # A 拉取：墓碑被对端重建压过 → 恢复
        self._engine(store_a).run()
        restored = store_a.get(doc.id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.content, "重建内容")
        state_a = SyncState.load(store_a.root / "sync-state.json")
        self.assertNotIn(doc.id, state_a.deleted)

    def test_assets_sync_between_devices(self):
        store_a = self._store("devA")
        store_b = self._store("devB")
        doc = store_a.create_document("md", title="图片测试")
        store_a.submit_save(_replace(doc, content="v1"), wait=True)
        self._engine(store_a).run()

        # A 本地放一张图片资源
        asset_dir = store_a.root / "assets" / doc.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "abc123def456.png").write_bytes(b"PNGDATA")

        self._engine(store_a).run()  # 推送 manifest（含 assets 列表与文件）
        self._engine(store_b).run()  # B 拉取 + 补缺资源
        downloaded = store_b.root / "assets" / doc.id / "abc123def456.png"
        self.assertTrue(downloaded.is_file())
        self.assertEqual(downloaded.read_bytes(), b"PNGDATA")

    def test_state_file_roundtrip(self):
        state_path = self.root / "state.json"
        state = SyncState.load(state_path)
        self.assertTrue(state.device_id)
        state.add_deleted("x1")
        state.own_pushed["d"] = "H"
        state.save(state_path)
        loaded = SyncState.load(state_path)
        self.assertEqual(loaded.device_id, state.device_id)
        self.assertIn("x1", loaded.deleted)
        self.assertEqual(loaded.own_pushed.get("d"), "H")
        self.assertEqual(json.loads(state_path.read_text())["protocol"], 1)

    # ---------------------------------------------------------- R50 每设备备份名
    def test_backup_remote_names_and_legacy_compat(self):
        a = cloud_mod.backup_remote_name("devA")
        b = cloud_mod.backup_remote_name("devB")
        self.assertEqual(a, "gscratchpad-cloud-devA.zip")
        self.assertNotEqual(a, b)
        for name in (a, cloud_mod.BACKUP_LEGACY_ANDROID, cloud_mod.BACKUP_LEGACY_DESKTOP):
            self.assertTrue(cloud_mod.is_backup_zip(name))
        self.assertFalse(cloud_mod.is_backup_zip("notes.md"))
        self.assertFalse(cloud_mod.is_backup_zip("gscratchpad-cloud-.zip"))

    def test_cloud_manager_backup_list_and_download(self):
        store = self._store("devA")
        store.set_meta("webdav_url", self.base_url, wait=True)
        store.set_meta("webdav_user", "", wait=True)
        store.set_meta("webdav_pass", AUTH[1], wait=True)
        manager = cloud_mod.CloudManager(store)

        message = manager.run_backup()
        self.assertIn("备份完成", message)
        device_id = manager.backup_device_id()
        name = cloud_mod.backup_remote_name(device_id)
        self.assertIn(name, message)
        self.assertIn(f"dav/test/{name}", _StubDavHandler.store)

        # 旧固定名也列为恢复候选（只读兼容）
        _StubDavHandler.store["dav/test/gscratchpad-cloud.zip"] = b"legacy"
        backups = manager.list_remote_backups()
        names = {item.name for item in backups}
        self.assertIn(name, names)
        self.assertIn("gscratchpad-cloud.zip", names)
        fresh = next(item for item in backups if item.name == name)
        self.assertGreater(fresh.size, 0)
        self.assertEqual(fresh.modified, "Tue, 24 Nov 2026 18:00:00 GMT")

        target = self.root / "downloaded.zip"
        self.assertGreater(manager.download_backup(name, target), 0)
        self.assertTrue(target.read_bytes().startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
