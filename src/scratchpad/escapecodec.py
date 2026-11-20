"""查找 / 替换框的转义解码。

支持的序列：``\\n`` ``\\r`` ``\\t`` ``\\\\`` ``\\xHH`` ``\\uHHHH``；其余（含
``\\1``–``\\9``、未知字母、位数不足的十六进制）原样保留。

设计要点（均有实测依据，见 docs/TEST_REPORT.md 修订二十四）：

1. **单遍扫描**：不能对同一串连续做两次 ``str.replace``，否则 ``\\\\n``（字面
   反斜杠 + n）会被二次解码成换行。
2. **数字原样透传**：GtkSourceView 的替换串同时是 GLib 正则替换模板，
   ``\\1``–``\\9`` / ``\\0`` 是反向引用；本模块一律不碰，交由上游展开。
3. **不产出 NUL 与孤立代理项**：``\\x00`` 与 ``\\uD800``–``\\uDFFF`` 解码结果是
   GtkTextBuffer 无法容纳的内容，按字面量保留。
"""

from __future__ import annotations

_SIMPLE = {"n": "\n", "r": "\r", "t": "\t"}

_HEX = set("0123456789abcdefABCDEF")


def _is_scalar(cp: int) -> bool:
    """可安全放进 GtkTextBuffer（UTF-8）的码点：非 0、非代理区、不超界。"""
    return 0 < cp <= 0x10FFFF and not 0xD800 <= cp <= 0xDFFF


def decode(text: str) -> str:
    """把文本里的转义序列解码为控制字符；非法/未知序列原样保留。"""
    if "\\" not in text:
        return text

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue

        nxt = text[i + 1]

        # `\\` → 反斜杠（先消费，故 `\\n` 得到字面 `\n` 而非换行）
        if nxt == "\\":
            out.append("\\")
            i += 2
            continue

        # `\n` `\r` `\t`
        if nxt in _SIMPLE:
            out.append(_SIMPLE[nxt])
            i += 2
            continue

        # `\xHH`：必须紧跟两位十六进制
        if nxt == "x" and i + 3 < n:
            digits = text[i + 2:i + 4]
            if set(digits) <= _HEX:
                cp = int(digits, 16)
                if _is_scalar(cp):
                    out.append(chr(cp))
                    i += 4
                    continue

        # `\uHHHH`：必须紧跟四位十六进制
        if nxt == "u" and i + 5 < n:
            digits = text[i + 2:i + 6]
            if set(digits) <= _HEX:
                cp = int(digits, 16)
                if _is_scalar(cp):
                    out.append(chr(cp))
                    i += 6
                    continue

        # 其余（含 \1–\9 反向引用、\0、未知字母、非法十六进制）：原样两字符
        out.append(ch)
        out.append(nxt)
        i += 2

    return "".join(out)
