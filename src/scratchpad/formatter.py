"""格式化排版：JSON / XML / HTML / Python / Bash。

全部惰性导入 + 复用标准库，启动时间与常驻内存零增加；
Python 优先调用系统 black / ruff，Bash 调用系统 shfmt，缺失时返回可操作提示。
所有函数均为纯函数：输入文本，返回新文本或抛 FormatError。
"""

from __future__ import annotations

import re
import shutil
import subprocess


class FormatError(Exception):
    """格式化失败（含给用户看的提示语）。"""


# ---------------------------------------------------------------- JSON

def _format_json(text: str) -> str:
    import json

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"JSON 解析失败：第 {exc.lineno} 行 {exc.msg}") from exc
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- XML

def _format_xml(text: str) -> str:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FormatError(f"XML 解析失败：{exc}") from exc
    ET.indent(root, space="  ")
    declaration = ""
    stripped = text.lstrip()
    if stripped.startswith("<?"):
        declaration = stripped[: stripped.index("?>") + 2] + "\n"
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return declaration + body + "\n"


# ---------------------------------------------------------------- HTML

_INLINE_TAGS = {
    "a", "span", "b", "strong", "i", "em", "u", "s", "code", "kbd", "mark",
    "small", "sub", "sup", "abbr", "cite", "q", "time", "var", "label",
}


def _format_html(text: str) -> str:
    """HTML 排版：先尝试 XML 路径（XHTML/合法标签），失败降级为 HTMLParser 缩进器。"""
    try:
        return _format_xml(text)
    except FormatError:
        pass
    from html.parser import HTMLParser

    class _Formatter(HTMLParser):
        VOID = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "source", "track", "wbr",
        }
        PRESERVE = {"pre", "textarea", "script", "style"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.out: list[str] = []
            self.depth = 0
            self.skip_until: str | None = None

        def handle_starttag(self, tag, attrs):
            if self.skip_until:
                return
            parts = [f"<{tag}"]
            for k, v in attrs:
                parts.append(f' {k}="{v}"' if v is not None else f" {k}")
            indent = "  " * max(self.depth, 0)
            self.out.append(f"{indent}{' '.join(parts)}>")
            if tag not in self.VOID and tag not in _INLINE_TAGS:
                self.depth += 1
            if tag in self.PRESERVE:
                self.skip_until = tag

        def handle_startendtag(self, tag, attrs):
            if self.skip_until:
                return
            parts = [f"<{tag}"]
            for k, v in attrs:
                parts.append(f' {k}="{v}"' if v is not None else f" {k}")
            indent = "  " * max(self.depth, 0)
            self.out.append(f"{indent}{' '.join(parts)} />")

        def handle_endtag(self, tag):
            if self.skip_until:
                if tag == self.skip_until:
                    self.skip_until = None
                else:
                    return
            if tag not in self.VOID and tag not in _INLINE_TAGS:
                self.depth -= 1
            indent = "  " * max(self.depth, 0)
            self.out.append(f"{indent}</{tag}>")

        def handle_data(self, data):
            if self.skip_until:
                self.out.append(data)
                return
            stripped = data.strip()
            if not stripped:
                return
            indent = "  " * max(self.depth, 0)
            self.out.append(f"{indent}{stripped}")

        def handle_comment(self, data):
            if self.skip_until:
                return
            indent = "  " * max(self.depth, 0)
            self.out.append(f"{indent}<!--{data}-->")

    parser = _Formatter()
    parser.feed(text)
    parser.close()
    if parser.depth > 0 or not parser.out:
        raise FormatError("HTML 结构无法解析（存在未闭合标签），已保留原文")
    return "\n".join(parser.out) + "\n"


# ---------------------------------------------------------------- Python

def _format_python(text: str) -> str:
    """优先系统 black / ruff（质量最好）；缺失时给出安装提示，不做有损兜底。"""
    for cmd in (["black", "-q", "-"], ["ruff", "format", "--stdin-filename", "x.py", "-"]):
        if shutil.which(cmd[0]):
            try:
                proc = subprocess.run(
                    cmd, input=text.encode(), capture_output=True, timeout=20
                )
                if proc.returncode == 0 and proc.stdout:
                    return proc.stdout.decode()
            except (OSError, subprocess.TimeoutExpired):
                continue
    # 先做一次语法预检，给用户更准确的报错
    try:
        compile(text, "<doc>", "exec")
    except SyntaxError as exc:
        raise FormatError(f"Python 语法错误：第 {exc.lineno} 行 {exc.msg}") from exc
    raise FormatError(
        "未检测到 black / ruff，无法完成 Python 排版；请安装：sudo apt install black"
    )


# ---------------------------------------------------------------- Bash

def _format_bash(text: str) -> str:
    shfmt = shutil.which("shfmt")
    if not shfmt:
        raise FormatError(
            "未检测到 shfmt，无法排版 Bash；请安装：sudo apt install shfmt"
        )
    try:
        proc = subprocess.run(
            [shfmt, "-i", "4", "-ci"], input=text.encode(),
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FormatError(f"shfmt 执行失败：{exc}") from exc
    if proc.returncode != 0:
        raise FormatError(f"shfmt 报错：{proc.stderr.decode(errors='replace').strip()[:120]}")
    return proc.stdout.decode()


# ---------------------------------------------------------------- 入口

FORMATTERS = {
    "json": _format_json,
    "xml": _format_xml,
    "svg": _format_xml,
    "html": _format_html,
    "python": _format_python,
    "bash": _format_bash,
}

_EXT_MAP = {
    ".json": "json",
    ".xml": "xml", ".svg": "svg", ".plist": "xml",
    ".html": "html", ".htm": "html",
    ".py": "python", ".pyw": "python",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
}


def format_kind_for_ext(ext: str) -> str | None:
    return _EXT_MAP.get(ext.lower())


_HTML_HINT_RE = re.compile(r"<(!doctype\s+html|html\b|head\b|body\b|div\b|p\b)", re.IGNORECASE)


def sniff_kind(text: str) -> str | None:
    """按内容嗅探可格式化语言（无关联文件时的兜底）。"""
    import json as _json
    import xml.etree.ElementTree as _ET

    s = text.strip()
    if not s:
        return None
    if s[0] in "{[":
        try:
            _json.loads(s)
            return "json"
        except _json.JSONDecodeError:
            return None
    if s.startswith("<"):
        try:
            _ET.fromstring(s)
            return "xml"
        except _ET.ParseError:
            if _HTML_HINT_RE.search(s[:512]):
                return "html"
    return None


def format_text(text: str, kind: str) -> str:
    fn = FORMATTERS.get(kind)
    if fn is None:
        raise FormatError(f"不支持格式化 {kind}")
    return fn(text)
