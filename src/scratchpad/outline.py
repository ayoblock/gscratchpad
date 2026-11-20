"""Markdown 大纲解析（纯逻辑，不依赖 GTK，便于单测）。

只认 CommonMark 真正会渲染成标题的写法，保证大纲条目与预览里的标题一一对应：

- ATX：`# 标题`（`#` 后必须是空格/制表符或行尾；`#标题` 不是标题，渲染器同样不认）
- Setext：文字行下面跟一行 `===` / `---`
- 围栏代码块（``` 或 ~~~）、缩进代码块、HTML 注释里的 `#` 一律跳过
- 图片、链接、强调、行内代码等行内标记会被剥掉，只留纯文本
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `#` 最多 3 个前导空格；闭合序列（`## 标题 ##`）在 _strip 里处理
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INDENT_CODE_RE = re.compile(r"^(?: {4,}|\t)")
# 引用块（`> # 标题`）里的标题同样会被渲染成 h1..h6，先剥掉引用前缀再判断
_QUOTE_RE = re.compile(r"^ {0,3}(?:>[ \t]?)+")

_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_CODE_RE = re.compile(r"`([^`]*)`")
_EMPHASIS_RES = (
    re.compile(r"\*\*\*([^*]+)\*\*\*"),
    re.compile(r"\*\*([^*]+)\*\*"),
    re.compile(r"__([^_]+)__"),
    re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"),
    re.compile(r"(?<!_)_([^_]+)_(?!_)"),
    re.compile(r"~~([^~]+)~~"),
)
_TAG_RE = re.compile(r"<[^>]+>")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")


@dataclass(frozen=True)
class Heading:
    """一个标题：`index` 是它在渲染结果中的序号（与 h1..h6 的 DOM 顺序一致）。"""

    index: int
    level: int
    text: str
    line: int  # 1 基行号：ATX 是标题自身所在行，Setext 是文字行


def plain_text(text: str) -> str:
    """剥掉行内标记，得到给人看的标题文字。"""
    value = _LINK_RE.sub(r"\1", text)
    value = _REF_LINK_RE.sub(r"\1", value)
    value = _CODE_RE.sub(r"\1", value)
    for pattern in _EMPHASIS_RES:
        value = pattern.sub(r"\1", value)
    value = _TAG_RE.sub("", value)
    value = _ESCAPE_RE.sub(r"\1", value)
    return " ".join(value.split())


def parse_headings(text: str) -> list[Heading]:
    """按出现顺序返回标题列表；空文本/无标题返回空列表。"""
    if not text:
        return []

    lines = text.splitlines()
    # 行号必须与源码一一对应，所以只做「去引用前缀」而不删除行
    cleaned = [_QUOTE_RE.sub("", line.rstrip("\r")) for line in lines]
    headings: list[Heading] = []
    fence_char: str | None = None
    fence_len = 0
    in_comment = False

    for number, line in enumerate(cleaned, start=1):

        if in_comment:
            if "-->" in line:
                in_comment = False
            continue

        if fence_char is not None:
            match = _FENCE_RE.match(line)
            if match:
                marker, rest = match.group(1), match.group(2)
                # 关闭围栏：同字符、长度不短于开启、后面只能有空白
                if marker[0] == fence_char and len(marker) >= fence_len and not rest.strip():
                    fence_char = None
            continue

        match = _FENCE_RE.match(line)
        if match and match.group(1)[0] in "`~":
            fence_char = match.group(1)[0]
            fence_len = len(match.group(1))
            continue

        stripped = line.strip()
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue

        if not stripped:
            continue
        if _INDENT_CODE_RE.match(line):
            continue

        atx = _ATX_RE.match(line)
        if atx:
            level = len(atx.group(1))
            body = atx.group(2) or ""
            body = re.sub(r"[ \t]+#+[ \t]*$", "", body)
            body = body.strip()
            headings.append(
                Heading(
                    index=len(headings),
                    level=level,
                    text=plain_text(body) or "（无标题）",
                    line=number,
                )
            )
            continue

        setext = _SETEXT_RE.match(line)
        if setext:
            # Setext 的标题文字是上一行（且上一行必须是普通段落文本）
            previous = cleaned[number - 2].strip() if number >= 2 else ""
            if previous and not _is_block_start(previous) and not _SETEXT_RE.match(previous):
                level = 1 if setext.group(1).startswith("=") else 2
                headings.append(
                    Heading(
                        index=len(headings),
                        level=level,
                        text=plain_text(previous) or "（无标题）",
                        line=number - 1,
                    )
                )
                continue

    return headings


def _is_block_start(line: str) -> bool:
    """上一行是否是列表项/引用/标题等，不能作为 Setext 标题文字。"""
    if line.startswith(("- ", "* ", "+ ", "> ", "|")):
        return True
    if re.match(r"^\d+[.)]\s", line):
        return True
    return bool(_ATX_RE.match(line)) or bool(_FENCE_RE.match(line))


def outline_depth(headings: list[Heading]) -> int:
    """给 UI 用的层级跨度（最浅一级为 0）。"""
    if not headings:
        return 0
    return max(h.level for h in headings) - min(h.level for h in headings) + 1
