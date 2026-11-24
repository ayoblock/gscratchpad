"""路径解析：数据目录、资源目录、vendor 资源定位。

运行期不访问网络，所有前端资源（mermaid / KaTeX）均由本地 vendor 目录提供。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ID = "io.github.gscratchpad.Gscratchpad"
APP_NAME = "Gscratchpad"
APP_VERSION = "1.16.5"
DATA_DIR_NAME = "gscratchpad"
LEGACY_DATA_DIR_NAME = "gnome-scratchpad"

# 安装布局：/usr/lib/gscratchpad/scratchpad/*.py
_INSTALLED_PKG_DIR = Path("/usr/lib/gscratchpad")
_SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent


def data_root() -> Path:
    """~/.local/share/gscratchpad（遵守 XDG_DATA_HOME）。"""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / DATA_DIR_NAME


def db_path() -> Path:
    return data_root() / "gscratchpad.db"


def notes_dir() -> Path:
    return data_root() / "notes"


def assets_dir() -> Path:
    return data_root() / "assets"


def recovery_dir() -> Path:
    return data_root() / "recovery"


def _vendor_candidates() -> list[Path]:
    return [
        Path("/usr/share/gscratchpad/vendor"),
        _SOURCE_ROOT / "vendor",
        _INSTALLED_PKG_DIR / "vendor",
    ]


def vendor_root() -> Path:
    for candidate in _vendor_candidates():
        if (candidate / "js" / "mermaid.min.js").is_file():
            return candidate
    # 返回首选路径，调用方据此报错
    return Path("/usr/share/gscratchpad/vendor")


def vendor_js(name: str) -> Path:
    return vendor_root() / "js" / name


def ensure_layout() -> None:
    migrate_legacy_data_dir()
    for directory in (data_root(), notes_dir(), assets_dir(), recovery_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data_dir() -> None:
    """旧版数据目录 gnome-scratchpad → gscratchpad 自动迁移（须在建目录之前调用）。"""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    legacy = Path(base) / LEGACY_DATA_DIR_NAME
    if DATA_DIR_NAME == LEGACY_DATA_DIR_NAME or not legacy.is_dir():
        return
    new_root = Path(base) / DATA_DIR_NAME
    if new_root.exists():
        return
    try:
        legacy.rename(new_root)
        old_db = new_root / "scratchpad.db"
        new_db = new_root / "gscratchpad.db"
        if old_db.is_file() and not new_db.exists():
            old_db.rename(new_db)
    except OSError:
        # 迁移失败不阻塞启动，旧目录保持原样
        pass


def doc_file_path(doc_id: str, fmt: str) -> Path:
    return notes_dir() / f"{doc_id}.{fmt}"


def doc_asset_dir(doc_id: str) -> Path:
    return assets_dir() / doc_id
