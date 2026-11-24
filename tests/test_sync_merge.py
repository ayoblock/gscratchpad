"""plan_sync 合并语义夹具测试（sync v1，规约 docs/SYNC_PROTOCOL.md §5–§7）。

夹具编号 SM-01…SM-08 与 Android `SyncEngineTest` 共用同一组场景定义
（Android 侧按相同输入/输出逐字段复刻），保证双端判定一致。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scratchpad.syncengine import PeerManifest, plan_sync  # noqa: E402


def _entry(doc_id, h, rev, updated_at, fmt="md", title="t"):
    return {
        "id": doc_id,
        "content_hash": h,
        "revision": rev,
        "updated_at": updated_at,
        "title": title,
        "format": fmt,
    }


def _peer(device_id, docs, deleted=None):
    return PeerManifest(
        device_id=device_id,
        device_name=device_id,
        docs=docs,
        deleted=deleted or {},
        folders=[],
        exported_at=0.0,
    )


class SyncMergeTestCase(unittest.TestCase):
    def test_sm01_new_doc_from_peer(self):
        plan = plan_sync(
            local={},
            own_pushed={},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "H", 1, 100)})],
            peer_states={},
            now=0,
        )
        self.assertEqual(len(plan.applies), 1)
        self.assertEqual(plan.new_peers["p"]["d1"], "H")

    def test_sm02_unchanged_refresh_baseline_only(self):
        plan = plan_sync(
            local={"d1": {"hash": "H", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H"},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "H", 1, 100)})],
            peer_states={"p": {"d1": "H"}},
            now=0,
        )
        self.assertEqual(plan.applies, [])
        self.assertEqual(plan.new_peers["p"]["d1"], "H")

    def test_sm03_remote_changed_local_clean(self):
        plan = plan_sync(
            local={"d1": {"hash": "H1", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H1"},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "H2", 3, 200)})],
            peer_states={"p": {"d1": "H1"}},
            now=0,
        )
        self.assertEqual(len(plan.applies), 1)
        self.assertEqual(plan.stats.get("conflicts", 0), 0)

    def test_sm04_conflict_peer_newer_wins(self):
        plan = plan_sync(
            local={"d1": {"hash": "Hlocal", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H0"},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "Hpeer", 3, 200)})],
            peer_states={"p": {"d1": "H0"}},
            now=0,
        )
        self.assertEqual(plan.stats.get("conflicts", 0), 1)
        self.assertEqual(len(plan.applies), 1)  # peer 胜 → 应用
        self.assertIn("d1", plan.preserve_local_before_apply)

    def test_sm05_conflict_local_newer_wins(self):
        plan = plan_sync(
            local={"d1": {"hash": "Hlocal", "revision": 2, "updated_at": 300}},
            own_pushed={"d1": "H0"},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "Hpeer", 3, 200)})],
            peer_states={"p": {"d1": "H0"}},
            now=0,
        )
        self.assertEqual(plan.stats.get("conflicts", 0), 1)
        self.assertEqual(plan.applies, [])
        self.assertEqual(plan.preserve_peer, [("p", "d1")])

    def test_sm06_conflict_tie_local_wins(self):
        plan = plan_sync(
            local={"d1": {"hash": "Hlocal", "revision": 2, "updated_at": 200}},
            own_pushed={"d1": "H0"},
            own_deleted={},
            peers=[_peer("p", {"d1": _entry("d1", "Hpeer", 3, 200)})],
            peer_states={"p": {"d1": "H0"}},
            now=0,
        )
        self.assertEqual(plan.applies, [])
        self.assertEqual(plan.preserve_peer, [("p", "d1")])

    def test_sm07_tombstone_deletes_local(self):
        plan = plan_sync(
            local={"d1": {"hash": "H1", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H1"},
            own_deleted={},
            peers=[_peer("p", {}, deleted={"d1": 200.0})],
            peer_states={"p": {"d1": "H1"}},
            now=0,
        )
        self.assertEqual(plan.deletes, ["d1"])
        self.assertEqual(plan.tombstones_learned, {"d1": 200.0})
        self.assertEqual(plan.new_peers["p"], {})

    def test_sm08_local_edit_beats_tombstone(self):
        plan = plan_sync(
            local={"d1": {"hash": "Hedit", "revision": 5, "updated_at": 300}},
            own_pushed={"d1": "H0"},
            own_deleted={},
            peers=[_peer("p", {}, deleted={"d1": 200.0})],
            peer_states={"p": {"d1": "H0"}},
            now=0,
        )
        self.assertEqual(plan.deletes, [])
        self.assertEqual(plan.tombstones_learned, {})
        self.assertEqual(plan.stats.get("delete_vs_edit", 0), 1)

    def test_sm09_restore_deleted_doc_from_peer(self):
        # 本地墓碑 d1，对端 docs 里重新出现 → 恢复 + 移出墓碑
        plan = plan_sync(
            local={},
            own_pushed={},
            own_deleted={"d1": 100.0},
            peers=[_peer("p", {"d1": _entry("d1", "H", 9, 400)})],
            peer_states={},
            now=0,
        )
        self.assertEqual(plan.undelete, ["d1"])
        self.assertEqual(len(plan.applies), 1)

    def test_sm10_tombstone_suppresses_stale_peer_entry(self):
        # p2 的陈旧 manifest 还带 d1，p1 的墓碑必须压过它
        plan = plan_sync(
            local={"d1": {"hash": "H1", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H1"},
            own_deleted={},
            peers=[
                _peer("p1", {}, deleted={"d1": 200.0}),
                _peer("p2", {"d1": _entry("d1", "H2", 9, 150)}),
            ],
            peer_states={"p1": {"d1": "H1"}, "p2": {"d1": "H1"}},
            now=0,
        )
        self.assertEqual(plan.deletes, ["d1"])
        self.assertEqual(
            [a[0] for a in plan.applies], [], "p2 的陈旧条目（150 < 墓碑 200）不得复活 d1"
        )

    def test_sm11_peer_doc_newer_than_tombstone_restores(self):
        # 对端文档（500）新于墓碑（200）→ 恢复
        plan = plan_sync(
            local={"d1": {"hash": "H1", "revision": 2, "updated_at": 100}},
            own_pushed={"d1": "H1"},
            own_deleted={},
            peers=[
                _peer("p1", {}, deleted={"d1": 200.0}),
                _peer("p2", {"d1": _entry("d1", "H2", 9, 500)}),
            ],
            peer_states={"p1": {"d1": "H1"}, "p2": {"d1": "H1"}},
            now=0,
        )
        self.assertEqual(plan.undelete, ["d1"])
        self.assertEqual(len(plan.applies), 1)


if __name__ == "__main__":
    unittest.main()
