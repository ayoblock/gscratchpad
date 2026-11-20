"""文本片段：模板渲染、快捷键规范化、触发词展开表。

本模块**不导入 GTK**，全部是可直接单测的纯逻辑；界面层（snippets_ui.py）与
编辑器（editor.py）只负责接线。

模板语法（自研，刻意不用 GtkSourceView 的 `$1` 片段语法）::

    {{cursor}}    插入后光标落点（缺省为文本末尾；多处出现只认第一处）
    {{date}}      2026-11-09
    {{time}}      23:22
    {{datetime}}  2026-11-09 23:22
    {{title}}     当前文档标题
    \\n \\t \\r \\\\   转义；未知转义（如 \\q）原样保留

不用 GtkSourceView snippet 的理由：实测 `Snippet.new_parsed()` 会把 bash 里最常见的
`$VAR`、`$5`、`\\n` 吃掉（`printf "%s\\n" $1` 变成 `printf "%sn" `），
不能用来承载用户自己写的文本。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

META_KEY = "snippets"
OVERRIDES_KEY = "accel_overrides"

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z_]+)\}\}")


# ====================================================================== 数据结构


@dataclass
class Snippet:
    """一条自定义片段。`accel` 为空表示只用命令菜单触发。"""

    name: str
    template: str
    accel: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "template": self.template, "accel": self.accel}

    @classmethod
    def from_dict(cls, data: dict) -> "Snippet":
        return cls(
            name=str(data.get("name") or "未命名"),
            template=str(data.get("template") or ""),
            accel=str(data.get("accel") or ""),
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
        )


@dataclass(frozen=True)
class Rendered:
    text: str
    cursor: int


# ====================================================================== 模板渲染


def render(template: str, *, title: str = "", now: datetime | None = None) -> Rendered:
    """渲染模板，返回 `(文本, 光标偏移)`。光标偏移以字符计，已收敛到文本长度内。"""
    moment = now or datetime.now()
    values = {
        "date": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime("%H:%M"),
        "datetime": moment.strftime("%Y-%m-%d %H:%M"),
        "title": title,
    }

    out: list[str] = []
    cursor: int | None = None
    i = 0
    length = len(template)
    while i < length:
        ch = template[i]
        if ch == "\\" and i + 1 < length:
            nxt = template[i + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            i += 2
            continue
        if ch == "{" and template.startswith("{{", i):
            match = _PLACEHOLDER.match(template, i)
            if match is not None:
                key = match.group(1)
                if key == "cursor":
                    if cursor is None:
                        cursor = len("".join(out))
                elif key in values:
                    out.append(values[key])
                else:
                    out.append(match.group(0))
                i = match.end()
                continue
        out.append(ch)
        i += 1

    text = "".join(out)
    if cursor is None:
        cursor = len(text)
    return Rendered(text, max(0, min(cursor, len(text))))


def plain(template: str, *, title: str = "", now: datetime | None = None) -> str:
    """只取渲染后的文本（预览用）。"""
    return render(template, title=title, now=now).text


# ====================================================================== 快捷键


_MOD_ALIASES = {
    "control": "control",
    "ctrl": "control",
    "primary": "control",
    "shift": "shift",
    "alt": "alt",
    "mod1": "alt",
    "meta": "super",
    "win": "super",
    "super": "super",
}

_KEY_ALIASES = {
    "return": "return",
    "enter": "return",
    "escape": "escape",
    "esc": "escape",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "home": "home",
    "end": "end",
    "pageup": "page-up",
    "pagedown": "page-down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
}

_ACCEL_MODS = ("control", "shift", "alt", "super")
_MOD_DISPLAY = {"control": "Ctrl", "shift": "Shift", "alt": "Alt", "super": "Super"}


def _split_accel(accel: str) -> tuple[set[str], str] | None:
    """`<Control><Shift>P` / `Ctrl+Shift+P` → ({control, shift}, "p")。非法返回 None。"""
    text = (accel or "").strip()
    if not text:
        return None
    mods: set[str] = set()
    key = ""
    while text.startswith("<"):
        end = text.find(">")
        if end < 0:
            return None
        token = text[1:end].lower()
        if token not in _MOD_ALIASES:
            return None
        mods.add(_MOD_ALIASES[token])
        text = text[end + 1:]
    if "+" in text:
        parts = [p for p in text.split("+") if p]
        if len(parts) < 2:
            return None
        for part in parts[:-1]:
            token = part.strip().strip("<>").lower()
            if token not in _MOD_ALIASES:
                return None
            mods.add(_MOD_ALIASES[token])
        key = parts[-1].strip()
    else:
        key = text
    if not key:
        return None
    lowered = key.lower()
    if lowered in _MOD_ALIASES:
        return None  # 只有修饰键，没有真正的按键
    key = _KEY_ALIASES.get(lowered, lowered)
    return mods, key


def canonical_accel(accel: str) -> str:
    """规范化成 `control+shift:p` 形式，仅用于比较是否冲突；非法返回空串。"""
    parsed = _split_accel(accel)
    if parsed is None:
        return ""
    mods, key = parsed
    return "+".join(m for m in _ACCEL_MODS if m in mods) + ":" + key


def normalize_accel(accel: str) -> str:
    """转成 GTK 加速键写法 `<Control><Shift>p`；非法返回空串。"""
    parsed = _split_accel(accel)
    if parsed is None:
        return ""
    mods, key = parsed
    prefix = "".join(f"<{m.capitalize()}>" for m in _ACCEL_MODS if m in mods)
    return prefix + key


def pretty_accel(accel: str) -> str:
    """展示用 `Ctrl+Shift+P`（与 GTK 内部顺序无关）；非法返回空串。"""
    parsed = _split_accel(accel)
    if parsed is None:
        return ""
    mods, key = parsed
    parts = [_MOD_DISPLAY[m] for m in _ACCEL_MODS if m in mods]
    if len(key) == 1:
        parts.append(key.upper())
    elif key.startswith("f") and key[1:].isdigit():
        parts.append(key.upper())
    else:
        parts.append(key.capitalize() if key.isalpha() else key)
    return "+".join(parts)


# ====================================================================== 存取


def loads(raw: str | None) -> list[Snippet]:
    """meta 里的 JSON → 片段列表（容错：坏数据当作空表，不抛异常）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[Snippet] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        snippet = Snippet.from_dict(item)
        if snippet.id in seen:
            snippet.id = uuid.uuid4().hex[:8]
        seen.add(snippet.id)
        out.append(snippet)
    return out


def dumps(snippets: list[Snippet]) -> str:
    return json.dumps([s.to_dict() for s in snippets], ensure_ascii=False)


def find_by_accel(snippets: list[Snippet], accel: str) -> Snippet | None:
    target = canonical_accel(accel)
    if not target:
        return None
    for snippet in snippets:
        if snippet.accel and canonical_accel(snippet.accel) == target:
            return snippet
    return None


# ====================================================================== 触发词展开

# 语言 id → {触发词: 模板}；触发词区分大小写，且要求前面是词边界
TRIGGERS: dict[str, dict[str, str]] = {
    "sh": {
        "shebang": "#!/usr/bin/env bash\nset -euo pipefail\n\n{{cursor}}",
        "sete": "set -euo pipefail",
        "ife": "if [ {{cursor}} ]; then\n\t\nfi",
        "iff": "if [ {{cursor}} ]; then\n\t\nelse\n\t\nfi",
        "fori": "for {{cursor}} in \"$@\"; do\n\t\ndone",
        "while": "while {{cursor}}; do\n\t\ndone",
        "case": "case {{cursor}} in\n\t)\n\t\t;;\nesac",
        "func": "{{cursor}}() {\n\t\n}",
        "heredoc": "cat <<'EOF'\n{{cursor}}\nEOF",
        "trap": "trap '{{cursor}}' EXIT",
        "readf": "while IFS= read -r {{cursor}}; do\n\t\ndone",
        "chk": "if ! command -v {{cursor}} >/dev/null 2>&1; then\n\techo \"缺失依赖\" >&2\n\texit 1\nfi",
    },
    "markdown": {
        "h1": "# {{cursor}}",
        "h2": "## {{cursor}}",
        "h3": "### {{cursor}}",
        "ul": "- {{cursor}}",
        "ol": "1. {{cursor}}",
        "task": "- [ ] {{cursor}}",
        "quote": "> {{cursor}}",
        "code": "```\n{{cursor}}\n```",
        "codebash": "```bash\n{{cursor}}\n```",
        "codepy": "```python\n{{cursor}}\n```",
        "codejson": "```json\n{{cursor}}\n```",
        "table": "| {{cursor}} |  |\n| --- | --- |\n|  |  |",
        "link": "[{{cursor}}](url)",
        "img": "![]({{cursor}})",
        "hr": "\n---\n",
        "foot": "[^{{cursor}}]",
        "front": "---\ntitle: {{cursor}}\ndate: {{date}}\n---\n",
    },
    "html": {
        "html5": (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "\t<meta charset=\"utf-8\">\n\t<title>{{cursor}}</title>\n</head>\n<body>\n\n</body>\n</html>"
        ),
        "div": "<div class=\"{{cursor}}\">\n\t\n</div>",
        "span": "<span class=\"{{cursor}}\"></span>",
        "a": "<a href=\"{{cursor}}\"></a>",
        "img": "<img src=\"{{cursor}}\" alt=\"\">",
        "ul": "<ul>\n\t<li>{{cursor}}</li>\n</ul>",
        "table": "<table>\n\t<tr><th>{{cursor}}</th></tr>\n</table>",
    },
    "python": {
        "def": "def {{cursor}}():\n\tpass",
        "class": "class {{cursor}}:\n\tdef __init__(self):\n\t\tpass",
        "ifmain": "if __name__ == \"__main__\":\n\t{{cursor}}",
        "trye": "try:\n\t{{cursor}}\nexcept Exception as exc:\n\tprint(exc)",
        "fori": "for i in range({{cursor}}):\n\t",
        "withf": "with open({{cursor}}) as f:\n\t",
    },
    "js": {
        "func": "function {{cursor}}() {\n\t\n}",
        "arrow": "const {{cursor}} = () => {\n\t\n};",
        "fetch": "fetch(\"{{cursor}}\")\n\t.then((r) => r.json())\n\t.then((data) => console.log(data));",
        "forof": "for (const item of {{cursor}}) {\n\t\n}",
    },
    "css": {
        "flex": "display: flex;\n{{cursor}}",
        "grid": "display: grid;\ngrid-template-columns: {{cursor}};",
        "media": "@media (max-width: {{cursor}}) {\n\t\n}",
        "root": ":root {\n\t--{{cursor}}: ;\n}",
    },
    "sql": {
        "sel": "SELECT {{cursor}}\nFROM ;",
        "ins": "INSERT INTO  ({{cursor}}) VALUES ();",
        "upd": "UPDATE  SET {{cursor}} =  WHERE ;",
        "crt": "CREATE TABLE {{cursor}} (\n\tid INTEGER PRIMARY KEY\n);",
    },
}

TRIGGER_LANG_NAMES = {
    "sh": "Bash / Shell",
    "markdown": "Markdown",
    "html": "HTML",
    "python": "Python",
    "js": "JavaScript",
    "css": "CSS",
    "sql": "SQL",
}


@dataclass(frozen=True)
class TriggerMatch:
    trigger: str
    template: str
    length: int


def match_trigger(text_before: str, lang: str) -> TriggerMatch | None:
    """判断光标前的文本是否以某个触发词结尾；要求前面是词边界。"""
    table = TRIGGERS.get(lang)
    if not table or not text_before:
        return None
    for trigger in sorted(table, key=len, reverse=True):
        if not text_before.endswith(trigger):
            continue
        index = len(text_before) - len(trigger)
        if index > 0:
            prev = text_before[index - 1]
            if prev.isalnum() or prev == "_":
                continue
        return TriggerMatch(trigger, table[trigger], len(trigger))
    return None


def trigger_rows(lang: str) -> list[tuple[str, str]]:
    """(触发词, 模板首行摘要) 列表，供设置界面参考页展示。"""
    table = TRIGGERS.get(lang) or {}
    rows: list[tuple[str, str]] = []
    for trigger in sorted(table):
        first = plain(table[trigger]).splitlines()
        rows.append((trigger, first[0] if first else ""))
    return rows
