"""源码折叠引擎：物理移除 + 影子恢复。

GtkSourceView 5.x 没有内置折叠 API，GTK4 的 invisible 文本标签也不会
折叠布局行（实测 yrange 不变），因此本模块采用"物理移除 + 影子恢复"：

核心不变量（保证不丢内容）：
1. 折叠状态只存在于内存，从不持久化；文档加载即清空。
2. 被折叠的文本保存在 Fold.chunk 中，并放置一个左重力 GtkTextMark
   标记其原位置——任何插入/删除/撤销都会由 GTK 自动平移该 mark。
   header 行号 = mark 所在行 - 1，随编辑自动跟随。
3. 保存、预览、统计一律走 EditorPage.snapshot_text()，它调用
   expand_text() 把隐藏文本按原位置拼回，写入磁盘的永远是全文。
4. 折叠/展开用 begin_irreversible_action 包裹，不污染撤销栈。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")

from gi.repository import Gtk, GtkSource  # noqa: E402

_HEADING_RE = re.compile(r"^(#{1,6})\s")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _indent_of(line: str) -> int:
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4
        else:
            break
    return n


def _line_depth_delta(line: str, opens: str = "([{", closes: str = ")]}") -> int:
    """一行内括号深度增量（粗略跳过引号内容）。"""
    depth = 0
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in opens:
            depth += 1
        elif ch in closes:
            depth -= 1
        i += 1
    return depth


@dataclass
class Fold:
    chunk: str              # 被移除的文本（含行尾换行）
    mark: Gtk.TextMark      # 左重力 mark，位于 chunk 原位置（行首）


class FoldEngine:
    """每个 EditorPage 一个实例。"""

    def __init__(self, buffer: GtkSource.Buffer, view: GtkSource.View, renderer) -> None:
        self._buffer = buffer
        self._view = view
        self._renderer = renderer
        self._folds: list[Fold] = []
        self._foldable: set[int] = set()
        self._strategy = "indent"
        self._lang_id = ""
        self._serial = 0
        self.mutating = False  # True 表示 buffer 变动由折叠/展开引起（外部据此跳过 dirty 标记）
        self.on_fold_changed = None  # 折叠/展开完成后的回调（供 UI 刷新字数等）
        buffer.connect("changed", self._on_changed)

    # ------------------------------------------------------------ 对外

    def set_language(self, lang_id: str) -> None:
        self._lang_id = lang_id or ""
        self.recompute()

    def reset(self) -> None:
        """文档加载/切换时：展开全部并丢弃状态。"""
        self.unfold_all()
        self._foldable.clear()

    def recompute(self) -> None:
        buf = self._buffer
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self._strategy = self._pick_strategy(text)
        lines = text.split("\n")
        if self._strategy == "markdown":
            self._foldable = self._foldable_markdown(lines)
        elif self._strategy == "brace":
            self._foldable = self._foldable_brace(lines)
        else:
            self._foldable = self._foldable_indent(lines)
        self._foldable |= {self._header_line(f) for f in self._folds}
        self._renderer.invalidate()

    def is_foldable(self, line: int) -> bool:
        return line in self._foldable

    def is_folded_at(self, line: int) -> bool:
        return any(self._header_line(f) == line for f in self._folds)

    def toggle_fold(self, line: int) -> bool:
        if self.is_folded_at(line):
            self.unfold_at(line)
            return False
        return self.fold_at(line)

    def has_folds(self) -> bool:
        return bool(self._folds)

    def expand_text(self) -> str:
        """返回展开后的全文（保存 / 预览 / 统计用）。"""
        buf = self._buffer
        full = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        if not self._folds:
            return full
        pieces: list[tuple[int, str]] = []
        for f in self._folds:
            loc = self._mark_iter(f.mark).get_offset()
            pieces.append((loc, f.chunk))
        pieces.sort(key=lambda p: p[0])
        out: list[str] = []
        last = 0
        for pos, chunk in pieces:
            pos = max(0, min(pos, len(full)))
            out.append(full[last:pos])
            out.append(chunk)
            last = pos
        out.append(full[last:])
        return "".join(out)

    # ------------------------------------------------------------ header 行号

    def _header_line(self, fold: Fold) -> int:
        return max(0, self._mark_iter(fold.mark).get_line() - 1)

    # ------------------------------------------------------------ 折叠区间计算

    def _pick_strategy(self, _text: str) -> str:
        if self._lang_id == "markdown":
            return "markdown"
        if self._lang_id in {"json", "c", "cpp", "go", "rust", "java", "js",
                             "typescript", "css", "sql"}:
            return "brace"
        return "indent"

    def _foldable_indent(self, lines: list[str]) -> set[int]:
        result: set[int] = set()
        n = len(lines)
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            ind = _indent_of(line)
            j = i + 1
            last = -1
            while j < n:
                l2 = lines[j]
                if l2.strip():
                    if _indent_of(l2) <= ind:
                        break
                    last = j
                j += 1
            if last > i:
                result.add(i)
        return result

    def _foldable_brace(self, lines: list[str]) -> set[int]:
        result: set[int] = set()
        depth = 0
        n = len(lines)
        for i, line in enumerate(lines):
            before = depth
            depth += _line_depth_delta(line)
            if depth > before:
                # 本行开启了括号：找到回到 before 深度的那一行
                d = depth
                last = None
                for j in range(i + 1, n):
                    d += _line_depth_delta(lines[j])
                    if d <= before:
                        last = j
                        break
                if last is not None and last > i:
                    result.add(i)
        return result

    def _foldable_markdown(self, lines: list[str]) -> set[int]:
        result: set[int] = set()
        headings: list[tuple[int, int]] = []  # (line, level)
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if _FENCE_RE.match(line):
                j = i + 1
                while j < n and not _FENCE_RE.match(lines[j]):
                    j += 1
                if j < n and j > i + 1:
                    result.add(i)
                i = j + 1
                continue
            m = _HEADING_RE.match(line)
            if m:
                headings.append((i, len(m.group(1))))
            i += 1
        for idx, (start, level) in enumerate(headings):
            end = n
            for s2, lv in headings[idx + 1:]:
                if lv <= level:
                    end = s2
                    break
            last = -1
            for j in range(start + 1, min(end, n)):
                if lines[j].strip():
                    last = j
            if last > start:
                result.add(start)
        return result

    # ------------------------------------------------------------ 执行折叠 / 展开

    def _line_start(self, line: int) -> Gtk.TextIter:
        it = self._buffer.get_start_iter()
        it.set_line(line)
        return it

    def _block_end(self, line: int) -> int | None:
        """当前（可能已折叠的）buffer 中，line 的折叠区块结束行。"""
        buf = self._buffer
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        lines = text.split("\n")
        if self._strategy == "markdown":
            return self._md_block_end(lines, line)
        if self._strategy == "brace":
            return self._brace_block_end(lines, line)
        return self._indent_block_end(lines, line)

    def _indent_block_end(self, lines: list[str], start: int) -> int | None:
        ind = _indent_of(lines[start])
        last = None
        for j in range(start + 1, len(lines)):
            if lines[j].strip():
                if _indent_of(lines[j]) <= ind:
                    break
                last = j
        return last

    def _brace_block_end(self, lines: list[str], start: int) -> int | None:
        depth = sum(_line_depth_delta(l) for l in lines[:start])
        for j in range(start, len(lines)):
            depth += _line_depth_delta(lines[j])
            if depth <= 0 and j > start:
                return j
        return len(lines) - 1 if len(lines) - 1 > start else None

    def _md_block_end(self, lines: list[str], start: int) -> int | None:
        n = len(lines)
        if _FENCE_RE.match(lines[start]):
            for j in range(start + 1, n):
                if _FENCE_RE.match(lines[j]):
                    return j
            return n - 1 if n - 1 > start else None
        m = _HEADING_RE.match(lines[start])
        level = len(m.group(1)) if m else 1
        last = None
        j = start + 1
        while j < n:
            l2 = lines[j]
            if l2.strip():
                m2 = _HEADING_RE.match(l2)
                if m2 and len(m2.group(1)) <= level:
                    break
            if _FENCE_RE.match(l2):
                k = j + 1
                while k < n and not _FENCE_RE.match(lines[k]):
                    k += 1
                last = min(k, n - 1)
                j = k + 1
                continue
            if l2.strip():
                last = j
            j += 1
        return last

    def _notify_done(self) -> None:
        if self.on_fold_changed is not None:
            self.on_fold_changed()

    def fold_at(self, line: int) -> bool:
        if self.is_folded_at(line) or line not in self._foldable:
            return False
        buf = self._buffer
        end_line = self._block_end(line)
        if end_line is None or end_line <= line:
            return False
        if line + 1 > buf.get_line_count() - 1:
            return False
        chunk_start = self._line_start(line + 1)
        if end_line + 1 <= buf.get_line_count() - 1:
            chunk_end = self._line_start(end_line + 1)
        else:
            chunk_end = buf.get_end_iter()
        chunk = buf.get_text(chunk_start, chunk_end, True)
        if not chunk:
            return False
        self._serial += 1
        self.mutating = True
        buf.begin_irreversible_action()
        buf.delete(chunk_start, chunk_end)
        mark = buf.create_mark(f"fold-{self._serial}", chunk_start, True)
        buf.end_irreversible_action()
        self.mutating = False
        self._folds.append(Fold(chunk=chunk, mark=mark))
        self.recompute()
        self._notify_done()
        return True

    def unfold_at(self, line: int) -> None:
        fold = next((f for f in self._folds if self._header_line(f) == line), None)
        if fold is not None:
            self.unfold(fold)

    def unfold(self, fold: Fold) -> None:
        buf = self._buffer
        pos = self._mark_iter(fold.mark)
        self.mutating = True
        buf.begin_irreversible_action()
        buf.insert(pos, fold.chunk, len(fold.chunk.encode()))
        buf.end_irreversible_action()
        self.mutating = False
        buf.delete_mark(fold.mark)
        self._folds.remove(fold)
        self.recompute()
        self._notify_done()

    def unfold_all(self) -> None:
        for fold in list(self._folds):
            self.unfold(fold)

    # ------------------------------------------------------------ 内部

    def _mark_iter(self, mark: Gtk.TextMark) -> Gtk.TextIter:
        return self._buffer.get_iter_at_mark(mark)

    def _on_changed(self, _buf) -> None:
        self.recompute()


class FoldGutter(GtkSource.GutterRendererText):
    """行号左侧的折叠箭头列：▸ 可折叠 / ▾ 已折叠。"""

    def __init__(self) -> None:
        super().__init__()
        self._engine: FoldEngine | None = None

    def bind(self, engine: FoldEngine) -> None:
        self._engine = engine
        self.invalidate()

    def invalidate(self) -> None:
        self.queue_draw()

    def do_query_data(self, *args) -> None:
        # 兼容两种 vfunc 调用形态：(lines, line_no[, state]) 或 (iter, area, event)
        line_no = None
        if args and hasattr(args[0], "get_line") and not hasattr(args[0], "line_count"):
            line_no = args[0].get_line()
        elif len(args) >= 2 and isinstance(args[1], int):
            line_no = args[1]
        if line_no is None:
            return
        text = ""
        if self._engine is not None:
            if self._engine.is_folded_at(line_no):
                text = "▾"
            elif self._engine.is_foldable(line_no):
                text = "▸"
        self.set_text(text, len(text.encode()))

    def do_activate(self, iter, _area, _event) -> bool:
        if self._engine is not None:
            self._engine.toggle_fold(iter.get_line())
            return True
        return False
