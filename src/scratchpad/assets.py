"""图片资源管理：导入、去重、清理、相对引用计算。"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from . import paths

SUPPORTED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif",
}


def import_image(doc_id: str, source: Path) -> tuple[str, str]:
    """把图片复制进应用资源目录，返回 (markdown 相对引用, 显示名)。

    内容按 SHA-256 去重：同一图片重复导入不会产生多份副本，
    因此原始图片被移动或删除后，文档引用仍然有效。
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"文件不存在：{source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXT:
        raise ValueError(f"不支持的图片格式：{suffix}")

    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:12]

    target_dir = paths.doc_asset_dir(doc_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / f"{digest}{suffix}"
    if not target.exists():
        tmp = target_dir / f".tmp-{uuid.uuid4().hex}"
        tmp.write_bytes(data)
        tmp.replace(target)

    rel = f"assets/{doc_id}/{target.name}"
    display_name = source.stem
    return rel, display_name


def _md_url(rel: str) -> str:
    """把相对路径转成可直接写进 Markdown/HTML 的 URL：只处理会破坏链接的字符。"""
    return (
        rel.replace("%", "%25")
        .replace(" ", "%20")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace("<", "%3C")
        .replace(">", "%3E")
        .replace("\n", "")
    )


def relative_image_ref(doc_path: str | Path, image: str | Path) -> tuple[str, str] | None:
    """文档已关联本机文件时，返回 (相对引用, 显示名)，不复制图片。

    例：文档 /notes/2026/a.md + 图片 /notes/024907.png → ("../024907.png", "024907")。
    不适用（图片不存在、跨盘符无法计算相对路径）时返回 None，由调用方回退到资源导入。
    """
    image_path = Path(image).expanduser()
    if not image_path.is_file():
        return None
    try:
        base = Path(doc_path).expanduser().resolve().parent
        rel = os.path.relpath(image_path.resolve(), base)
    except (OSError, ValueError):
        return None
    return _md_url(Path(rel).as_posix()), image_path.stem


def list_assets(doc_id: str) -> list[Path]:
    directory = paths.doc_asset_dir(doc_id)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith("."))


def remove_assets(doc_id: str) -> None:
    shutil.rmtree(paths.doc_asset_dir(doc_id), ignore_errors=True)
