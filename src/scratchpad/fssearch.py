"""目录级搜索与批量替换（面向真实文件系统）。

与 `search_md.py` / `replace_md.py` 的能力对齐，并补上图形化操作需要的安全措施：

1. **编码无损**：读取时探测 UTF-8 / UTF-8-BOM / GB18030，写回时用原编码；
   BOM 与原换行符（CRLF/LF）原样保留。
2. **先预览后执行**：`plan_replace()` 只读不写，返回每个文件将改动多少处；
   `apply_plan()` 才真正落盘。
3. **自动备份**：执行前把原文件复制到备份目录，路径结构保持不变。
4. **并发修改校验**：执行时若磁盘内容已与预览时不同，跳过该文件并在结果里报告。
5. **原子写**：临时文件 + os.replace，避免写到一半损坏源文件。

本模块不依赖 GTK，可直接单测。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

# 可作为纯文本处理的扩展名（覆盖两个脚本的 .md，并顺带支持常用文本类型）
TEXT_EXTS: tuple[str, ...] = (".md", ".markdown", ".mkd", ".txt", ".html", ".htm")

# 体量大且几乎不可能需要改写的目录
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", ".cache", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".obsidian", ".trash",
}

MAX_FILE_BYTES = 8 * 1024 * 1024      # 单文件上限，超过直接跳过
MAX_HITS = 5000                        # 结果上限，防止界面被拖死


# --------------------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Hit:
    """一条命中。行号从 1 开始，列号从 0 开始。

    `excerpt` 仅在模式跨行匹配时非空（已把换行渲染成 ⏎），供界面直接展示。
    """

    line_no: int
    column: int
    line_text: str
    excerpt: str = ""
    # 命中文本长度（字符数）。界面用它打开文件后把关键词选中，
    # 跨行命中时会跨越换行，选中范围同样跨越，视觉上正好覆盖整段匹配。
    length: int = 0


@dataclass
class FileHits:
    path: Path
    rel: str
    hits: list[Hit] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.hits)


@dataclass
class SearchOutcome:
    root: Path
    pattern: str
    files: list[FileHits] = field(default_factory=list)
    scanned: int = 0
    skipped: int = 0
    truncated: bool = False

    @property
    def total_hits(self) -> int:
        return sum(f.count for f in self.files)

    @property
    def matched_files(self) -> int:
        return len(self.files)


@dataclass
class FilePlan:
    """一个文件待执行的替换方案（预览结果）。"""

    path: Path
    rel: str
    encoding: str
    bom: bool
    old_text: str
    new_text: str
    count: int
    error: str = ""


@dataclass
class Plan:
    root: Path
    pattern: str
    replacement: str
    files: list[FilePlan] = field(default_factory=list)
    scanned: int = 0
    skipped: int = 0
    truncated: bool = False

    @property
    def changed_files(self) -> list[FilePlan]:
        return [f for f in self.files if f.count > 0 and not f.error]

    @property
    def total_replacements(self) -> int:
        return sum(f.count for f in self.files if not f.error)


@dataclass
class ApplyResult:
    changed: list[Path] = field(default_factory=list)
    replacements: int = 0
    backup_dir: Path | None = None
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- 编码


def read_text(path: Path) -> tuple[str, str, bool]:
    """读取文本，返回 (内容, 编码, 是否带 BOM)。

    换行符原样保留（newline=""），GB18030 作为 GBK 的超集兜底。
    """
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError("二进制文件")
    bom = data.startswith(b"\xef\xbb\xbf")
    if bom:
        data = data[3:]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return text, encoding, bom
    raise ValueError("无法识别文本编码")


def encode_text(text: str, encoding: str, bom: bool) -> bytes:
    data = text.encode(encoding, errors="strict")
    return (b"\xef\xbb\xbf" + data) if bom else data


def _atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    """同目录临时文件 + os.replace，保证不出现半截文件。"""
    directory = path.parent
    fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".gscratchpad-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- 遍历


def iter_files(
    root: Path,
    *,
    recursive: bool = True,
    exts: Sequence[str] = TEXT_EXTS,
) -> Iterator[Path]:
    """按稳定顺序遍历候选文件（跳过隐藏目录与常见重型目录）。"""
    suffixes = tuple(e.lower() for e in exts)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                if name.lower().endswith(suffixes):
                    yield Path(dirpath) / name
    else:
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file():
                continue
            if entry.name.lower().endswith(suffixes):
                yield Path(entry.path)


def _compile(pattern: str, case_sensitive: bool, regex: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    source = pattern if regex else re.escape(pattern)
    return re.compile(source, flags)


# 界面上允许用反斜杠输入不可见字符（非正则模式）。未知转义原样保留。
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}


def unescape(text: str) -> str:
    r"""把 `\n` `\t` `\r` `\\` 转成实际字符；其它 `\x` 保持原样（含单独结尾的反斜杠）。

    只在**非正则**模式使用：正则模式由 re 自己解释转义，不需要二次处理。
    """
    if "\\" not in text:
        return text
    out: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch == "\\" and i + 1 < length and text[i + 1] in _ESCAPES:
            out.append(_ESCAPES[text[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _line_starts(text: str) -> list[int]:
    """每行起始偏移（行号 = bisect_right(starts, offset)），供全文匹配定位。"""
    starts = [0]
    pos = text.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts


def _short_excerpt(matched: str, limit: int = 120) -> str:
    text = matched.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- 搜索


def search(
    root: Path | str,
    pattern: str,
    *,
    recursive: bool = True,
    case_sensitive: bool = False,
    regex: bool = False,
    exts: Sequence[str] = TEXT_EXTS,
    max_hits: int = MAX_HITS,
    should_stop: Callable[[], bool] | None = None,
) -> SearchOutcome:
    """在目录中搜索关键词，返回按文件分组的结果。"""
    root = Path(root).expanduser()
    outcome = SearchOutcome(root=root, pattern=pattern)
    if not pattern:
        return outcome
    try:
        compiled = _compile(pattern, case_sensitive, regex)
    except re.error as exc:
        raise ValueError(f"正则表达式有误：{exc}") from exc

    stop = should_stop or (lambda: False)
    for path in iter_files(root, recursive=recursive, exts=exts):
        if stop() or outcome.truncated:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                outcome.skipped += 1
                continue
            text, _encoding, _bom = read_text(path)
        except (OSError, ValueError):
            outcome.skipped += 1
            continue
        outcome.scanned += 1
        hits: list[Hit] = []
        starts: list[int] | None = None
        # 在全文上匹配（而不是逐行）：查找内容含 \n 时能命中跨行模式
        for m in compiled.finditer(text):
            if m.start() == m.end():
                continue
            if len(hits) >= max_hits:
                break
            if starts is None:
                starts = _line_starts(text)
            index = max(0, bisect_right(starts, m.start()) - 1)
            line_start = starts[index]
            line_end = starts[index + 1] - 1 if index + 1 < len(starts) else len(text)
            matched = m.group(0)
            hits.append(
                Hit(
                    line_no=index + 1,
                    column=m.start() - line_start,
                    line_text=text[line_start:line_end].strip(),
                    excerpt=_short_excerpt(matched) if "\n" in matched or "\r" in matched else "",
                    length=len(matched),
                )
            )
        if hits:
            outcome.files.append(FileHits(path=path, rel=_rel(path, root), hits=hits))
            if sum(f.count for f in outcome.files) >= max_hits:
                outcome.truncated = True
                break
    return outcome


# --------------------------------------------------------------------------- 替换


def plan_replace(
    root: Path | str,
    pattern: str,
    replacement: str,
    *,
    recursive: bool = True,
    case_sensitive: bool = True,
    regex: bool = False,
    exts: Sequence[str] = TEXT_EXTS,
    max_files: int = MAX_HITS,
    should_stop: Callable[[], bool] | None = None,
) -> Plan:
    """预览替换：只读磁盘，不写任何文件。

    默认区分大小写（与 replace_md.py 的字面量语义一致），避免"顺手把 Hello 也改了"。
    regex=True 时支持 `\\1` 反向引用。
    """
    root = Path(root).expanduser()
    plan = Plan(root=root, pattern=pattern, replacement=replacement)
    if not pattern:
        return plan
    try:
        compiled = _compile(pattern, case_sensitive, regex)
    except re.error as exc:
        raise ValueError(f"正则表达式有误：{exc}") from exc

    stop = should_stop or (lambda: False)
    for path in iter_files(root, recursive=recursive, exts=exts):
        if stop() or plan.truncated:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                plan.skipped += 1
                continue
            text, encoding, bom = read_text(path)
        except (OSError, ValueError) as exc:
            plan.files.append(FilePlan(path, _rel(path, root), "", False, "", "", 0, str(exc)))
            plan.skipped += 1
            continue
        plan.scanned += 1
        count = sum(1 for _ in compiled.finditer(text))
        if count == 0:
            continue
        if regex:
            new_text = compiled.sub(replacement, text)
        else:
            new_text = text.replace(pattern, replacement)
        plan.files.append(
            FilePlan(path, _rel(path, root), encoding, bom, text, new_text, count)
        )
        if len(plan.files) >= max_files:
            plan.truncated = True
            break
    return plan


def apply_plan(
    plan: Plan,
    backup_root: Path | str,
    *,
    only: Iterable[Path] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ApplyResult:
    """执行替换。`only` 非空时只处理其中列出的文件（界面上按勾选过滤）。

    每个文件写入前都会重新读盘并与预览内容比对，若已被外部修改则跳过。
    """
    backup_root = Path(backup_root).expanduser()
    result = ApplyResult(backup_dir=backup_root)
    allowed = set(only) if only is not None else None
    stop = should_stop or (lambda: False)

    for item in plan.files:
        if stop():
            break
        if item.count <= 0 or item.error:
            continue
        if allowed is not None and item.path not in allowed:
            continue
        try:
            current, encoding, bom = read_text(item.path)
        except (OSError, ValueError) as exc:
            result.errors.append(f"{item.rel}：读取失败（{exc}）")
            continue
        if current != item.old_text or encoding != item.encoding or bom != item.bom:
            result.errors.append(f"{item.rel}：预览后文件已被修改，已跳过")
            continue

        # 备份（保留相对路径结构，便于整目录回滚）
        try:
            target = backup_root / item.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.path, target)
        except OSError as exc:
            result.errors.append(f"{item.rel}：备份失败，已跳过（{exc}）")
            continue

        try:
            mode = item.path.stat().st_mode & 0o777
            _atomic_write_bytes(
                item.path, encode_text(item.new_text, item.encoding, item.bom), mode
            )
        except (OSError, UnicodeEncodeError) as exc:
            result.errors.append(f"{item.rel}：写入失败（{exc}）")
            continue

        result.changed.append(item.path)
        result.replacements += item.count

    return result


def make_backup_dir(base: Path | str, stamp: str) -> Path:
    """生成形如 <base>/2026-11-05_215630 的备份目录并创建。"""
    path = Path(base).expanduser() / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_snippet(text: str, pattern: str, case_sensitive: bool, regex: bool,
                    limit: int = 160) -> str:
    """给界面用的一行预览：把命中前后截断到可读长度。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    source = pattern if regex else re.escape(pattern)
    try:
        m = re.search(source, text, flags)
    except re.error:
        m = None
    if m is None:
        return text[:limit]
    start = max(0, m.start() - limit // 3)
    end = min(len(text), start + limit)
    snippet = text[start:end].replace("\n", " ")
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")
