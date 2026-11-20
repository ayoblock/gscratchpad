"""列编辑（行级批量操作）纯函数。

只处理「一个文本块」：输入是整行列表，输出是整行列表，不做任何 GTK
相关操作——iter 展开、选区保持、撤销分组都在 editor.apply_line_op 里。

语义约定（勿破坏）：
- 前缀/后缀施加于块内**每一行**（含空行）；空 arg 是 no-op；
- 排序按 Unicode 码点升序（Python sorted，稳定），不区分语言排序规则；
- 去重保留首次出现的行，后续重复行删除（整行精确相等才算重复）；
- 所有函数不改传入列表，返回新列表。
"""

from __future__ import annotations

import re

OPS = ("prefix", "suffix", "sort", "dedup")

COLUMN_MODES = ("sep", "width")


def add_prefix(lines: list[str], prefix: str) -> list[str]:
    if not prefix:
        return list(lines)
    return [prefix + line for line in lines]


def add_suffix(lines: list[str], suffix: str) -> list[str]:
    if not suffix:
        return list(lines)
    return [line + suffix for line in lines]


def sort_lines(lines: list[str], *, reverse: bool = False) -> list[str]:
    return sorted(lines, reverse=reverse)


def dedup_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def transform(op: str, text: str, arg: str = "") -> str:
    """对文本块（不含末尾换行）施加操作，返回新块（行间以 \\n 连接）。

    未知 op 或 arg 不满足要求（如 prefix/suffix 传空）时原样返回。
    """
    lines = text.split("\n")
    if op == "prefix":
        new = add_prefix(lines, arg)
    elif op == "suffix":
        new = add_suffix(lines, arg)
    elif op == "sort":
        new = sort_lines(lines)
    elif op == "dedup":
        new = dedup_lines(lines)
    else:
        return text
    return "\n".join(new)


# --------------------------------------------------------------- 切列（取一列）
#
# 与 transform() 的差别：切列需要回报「多少行没命中」，调用方要据此提示用户，
# 所以返回 (新行列表, 未命中行数) 而不是单纯字符串。
#
# 语义约定（勿破坏）：
# - 未命中的行**原样保留**——绝不静默删内容或留空行；
# - 空行不参与判定，原样保留且不计入未命中（空行没有列可言）；
# - sep 模式按候选分隔符集合中**最靠前**出现的那个切分，支持多候选（中英冒号混排）；
# - width 按字符（码点）计数，不做字节/显示宽度换算；中文与 emoji 均算 1 个字符。


def split_seps(raw: str) -> list[str]:
    """把用户输入的候选分隔符串拆成列表（以 | 分隔，去空）。

    单字符输入也走这里，因此「：|:」可同时覆盖全角与半角冒号。
    竖线本身需要写成 \\| 才能作为字面分隔符使用。
    """
    if not raw:
        return []
    placeholder = "\x00"
    parts = raw.replace("\\|", placeholder).split("|")
    return [part.replace(placeholder, "|") for part in parts if part]


def take_column_sep(
    lines: list[str], seps: list[str], index: int = 1
) -> tuple[list[str], int]:
    """按分隔符取第 index 段（1 起）；段数不足的行原样保留并计入未命中。"""
    seps = [s for s in seps if s]
    if not seps or index < 1:
        return list(lines), 0
    pattern = re.compile("|".join(re.escape(s) for s in seps))
    out: list[str] = []
    miss = 0
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        if not pattern.search(line):
            # 该行一个分隔符都没有：原样保留并计入未命中（index=1 也不算命中）
            out.append(line)
            miss += 1
            continue
        parts = pattern.split(line)
        if len(parts) < index:
            out.append(line)
            miss += 1
            continue
        out.append(parts[index - 1])
    return out, miss


def take_column_width(lines: list[str], width: int) -> tuple[list[str], int]:
    """保留每行前 width 个字符；长度不超过 width 的行原样保留并计入未命中。"""
    if width <= 0:
        return list(lines), 0
    out: list[str] = []
    miss = 0
    for line in lines:
        if len(line) <= width:
            out.append(line)
            miss += 1
            continue
        out.append(line[:width])
    return out, miss


def take_column(
    text: str, mode: str, *, sep: str = "：", index: int = 1, width: int = 0
) -> tuple[str, int]:
    """对文本块切列，返回 (新块, 未命中行数)。

    mode="sep" 按分隔符取第 index 段；mode="width" 保留前 width 个字符。
    未知 mode 或参数非法时原样返回、未命中为 0。
    """
    lines = text.split("\n")
    if mode == "sep":
        new, miss = take_column_sep(lines, split_seps(sep), index)
    elif mode == "width":
        new, miss = take_column_width(lines, width)
    else:
        return text, 0
    return "\n".join(new), miss

