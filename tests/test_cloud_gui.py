"""云同步 GUI 冒烟测试（离线，无网络依赖）。

覆盖：
- win.cloud-sync-settings 动作打开 Adw.PreferencesWindow 且各行就位
- 配置保存（meta + libsecret 失败回退 meta 的路径不在此测，测 meta 写入）
- store 删除事件 → sync-state.json 墓碑登记（CloudManager 接线）
- win.cloud-import-backup / cloud-sync-now / cloud-backup-now 动作存在
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")

from gi.repository import Gio, GLib  # noqa: E402

from scratchpad.application import ScratchpadApp  # noqa: E402
from scratchpad.syncengine import SyncState  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="gscratchpad-cloudgui-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")


class CloudGuiTest:
    def __init__(self) -> None:
        self.app = ScratchpadApp()
        self.app.set_flags(self.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.out: dict[str, object] = {}

    def run(self) -> None:
        GLib.idle_add(self.s0_setup)
        GLib.timeout_add(30000, self.app.quit)
        self.app.run(["cloud-gui-test"])

    def finish(self) -> None:
        self.w().close()
        print(json.dumps(self.out, ensure_ascii=False), flush=True)

    def w(self):
        return self.app.window

    def at(self, seconds: float, func) -> None:
        GLib.timeout_add(int(seconds * 1000), lambda: (func(), False)[1])

    # ------------------------------------------------------------------ steps

    def s0_setup(self) -> None:
        w = self.w()
        self.doc = w.store.create_document("md", title="墓碑接线测试")
        self.out["actions_exist"] = all(
            w.lookup_action(name) is not None
            for name in (
                "cloud-sync-settings",
                "cloud-sync-now",
                "cloud-backup-now",
                "cloud-import-backup",
            )
        )
        self.at(0.3, self.s1_delete_tombstone)

    def s1_delete_tombstone(self) -> None:
        # 删除文档 → CloudManager 应把墓碑写进 sync-state.json
        w = self.w()
        w.store.delete_document(self.doc.id)
        self.at(0.5, self.s2_check_tombstone)

    def s2_check_tombstone(self) -> None:
        state_path = Path(self.w().store.root) / "sync-state.json"
        try:
            state = SyncState.load(state_path)
            self.out["tombstone_recorded"] = self.doc.id in state.deleted
        except Exception as exc:  # noqa: BLE001
            self.out["tombstone_recorded"] = False
            self.out["tombstone_error"] = str(exc)
        self.at(0.3, self.s3_settings_dialog)

    def s3_settings_dialog(self) -> None:
        self.w().activate_action("win.cloud-sync-settings", None)
        self.at(0.5, self.s4_check_dialog)

    def s4_check_dialog(self) -> None:
        dialog = getattr(self.w(), "_cloud_dialog", None)
        self.out["dialog_opened"] = dialog is not None
        self.out["dialog_fully_built"] = bool(
            getattr(self.w(), "_cloud_dialog_built", False)
        )
        try:
            self.out["dialog_is_prefs"] = isinstance(dialog, __import__(
                "gi.repository.Adw", fromlist=["Adw"]
            ).PreferencesWindow)
        except Exception:  # noqa: BLE001
            self.out["dialog_is_prefs"] = False
        if dialog is not None:
            dialog.close()
        # 配置写入（不含密码 keyring 路径）
        self.w().cloud.save_config("http://user@127.0.0.1:5244/dav/test", "", "", False)
        self.out["url_saved"] = (
            self.w().store.get_meta("webdav_url", "")
            == "http://user@127.0.0.1:5244/dav/test"
        )
        self.out["user_extracted"] = self.w().cloud.config_user() == "user"
        self.at(0.3, self.finish)


if __name__ == "__main__":
    CloudGuiTest().run()
