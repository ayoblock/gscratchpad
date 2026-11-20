"""Markdown → HTML 渲染（离线，无外部依赖）。

- 公式：先做占位保护，避免 Markdown 把 `_` `*` `\\` 吃掉，再由页面内 KaTeX 渲染。
- Mermaid：把 ```mermaid 代码块转成 <div class="mermaid">，由本地 mermaid.min.js 渲染为 SVG。
- 代码高亮：Pygments 在 Python 侧完成，输出静态 HTML + 内联 CSS，PDF 导出同样有效。
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

import markdown as _markdown
from pygments.formatters import HtmlFormatter

from . import paths

_MATH_TOKEN = "zZmathblock{n}Zz"

# ---------------------------------------------------------------- HTML 净化

_DROP_TAGS = {"script", "iframe", "object", "embed", "style", "link", "meta", "base", "form"}
_VOID_TAGS = {
    "br", "hr", "img", "input", "wbr", "source", "col", "area", "embed", "track",
}


class _Sanitizer(HTMLParser):
    """白名单外的标签丢弃、事件属性剥离、javascript: 链接拦截。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in _DROP_TAGS:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        cleaned: list[str] = []
        for name, value in attrs:
            if name.lower().startswith("on"):
                continue
            if name in ("href", "src") and value and value.strip().lower().startswith("javascript:"):
                continue
            if value is None:
                cleaned.append(name)
            else:
                cleaned.append(f'{name}="{html.escape(value, quote=True)}"')
        attr_text = (" " + " ".join(cleaned)) if cleaned else ""
        if tag in _VOID_TAGS:
            self.out.append(f"<{tag}{attr_text}>")
        else:
            self.out.append(f"<{tag}{attr_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth or tag in _DROP_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth -= 1
            return
        if tag in _DROP_TAGS or tag in _VOID_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.out.append(f"&#{name};")


def sanitize_html(fragment: str) -> str:
    parser = _Sanitizer()
    parser.feed(fragment)
    parser.close()
    return "".join(parser.out)


_FENCE_RE = re.compile(r"(^```[^\n]*\n.*?^```\s*$)", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`+[^`]*`+)")
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<![\\$])\$(?!\s)((?:\\.|[^$\\])+?)(?<!\s)\$(?!\$)")

_LIGHT_STYLE = "xcode"
_DARK_STYLE = "monokai"


def _pygments_css() -> tuple[str, str]:
    light = HtmlFormatter(style=_LIGHT_STYLE, nowrap=False).get_style_defs(".codehilite")
    dark = HtmlFormatter(style=_DARK_STYLE, nowrap=False).get_style_defs(".codehilite")
    return light, dark


_PYGMENTS_LIGHT, _PYGMENTS_DARK = _pygments_css()

_MD = _markdown.Markdown(
    extensions=[
        "extra",
        "sane_lists",
        "nl2br",
        "admonition",
        "codehilite",
        "toc",
    ],
    extension_configs={
        "codehilite": {"guess_lang": False, "css_class": "codehilite", "linenums": False},
        "toc": {"permalink": False},
    },
    output_format="html5",
)


def _preprocess(text: str) -> tuple[str, list[tuple[str, bool]], list[str]]:
    """把围栏代码块之外的数学公式、mermaid 代码块替换为占位符。

    返回 (新文本, 数学公式列表, mermaid 源码列表)。
    必须先于 Markdown 处理执行：否则 Markdown 会吃掉 `_` `*` `\\` 等符号，
    并且 codehilite 会丢掉 ```mermaid 的语言标记。
    """
    store: list[tuple[str, bool]] = []
    diagrams: list[str] = []
    out: list[str] = []

    for chunk in _FENCE_RE.split(text):
        if chunk.startswith("```"):
            lines = chunk.split("\n")
            info = lines[0][3:].strip().lower()
            if info.startswith("mermaid"):
                code = "\n".join(lines[1:])
                code = re.sub(r"\n?```\s*$", "", code).strip("\n")
                token = f"zZmermaiddiagram{len(diagrams)}Zz"
                diagrams.append(code)
                out.append(f"\n\n{token}\n\n")
            else:
                out.append(chunk)
            continue
        for piece in _INLINE_CODE_RE.split(chunk):
            if piece.startswith("`") and piece.endswith("`") and len(piece) >= 2:
                out.append(piece)
                continue

            def repl_display(match: re.Match) -> str:
                token = _MATH_TOKEN.format(n=len(store))
                store.append((match.group(1).strip(), True))
                return token

            def repl_inline(match: re.Match) -> str:
                token = _MATH_TOKEN.format(n=len(store))
                store.append((match.group(1).strip(), False))
                return token

            piece = _DISPLAY_MATH_RE.sub(repl_display, piece)
            piece = _INLINE_MATH_RE.sub(repl_inline, piece)
            out.append(piece)
    return "".join(out), store, diagrams


_MERMAID_PRE_RE = re.compile(
    r'<pre class="codehilite"><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL
)
_MERMAID_FALLBACK_RE = re.compile(
    r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL
)


def _restore_math(body: str, store: list[tuple[str, bool]]) -> str:
    for index, (tex, display) in enumerate(store):
        token = _MATH_TOKEN.format(n=index)
        escaped = html.escape(tex, quote=True)
        mode = "display" if display else "inline"
        replacement = (
            f'<span class="math math-{mode}" data-tex="{escaped}" '
            f'data-display="{"1" if display else "0"}"></span>'
        )
        body = body.replace(token, replacement)
    return body


def _extract_mermaid(body: str, diagrams: list[str]) -> str:
    for index, code in enumerate(diagrams):
        token = f"zZmermaiddiagram{index}Zz"
        block = f'<div class="mermaid">{html.escape(code)}</div>'
        body = body.replace(f"<p>{token}</p>", block)
        body = body.replace(token, block)

    def repl(match: re.Match) -> str:
        code = html.unescape(match.group(1))
        return f'<div class="mermaid">{html.escape(code)}</div>'

    body = _MERMAID_PRE_RE.sub(repl, body)
    body = _MERMAID_FALLBACK_RE.sub(repl, body)
    return body


_HEADING_TAG_RE = re.compile(r"<h([1-6])(\s[^>]*)?>")


def _index_headings(body: str) -> str:
    """给 h1..h6 按 DOM 顺序打上 data-h 序号，供侧栏大纲滚动定位。"""
    counter = iter(range(1 << 30))

    def repl(match: re.Match) -> str:
        attrs = match.group(2) or ""
        return f'<h{match.group(1)}{attrs} data-h="{next(counter)}">'

    return _HEADING_TAG_RE.sub(repl, body)


def render_body(text: str) -> str:
    """Markdown 正文 → HTML 片段（不含 <html> 外壳）。"""
    protected, store, diagrams = _preprocess(text)
    _MD.reset()
    body = _MD.convert(protected)
    body = _extract_mermaid(body, diagrams)
    body = _restore_math(body, store)
    return _index_headings(sanitize_html(body))


_BASE_CSS = """
:root {
  --bg: #ffffff;
  --fg: #1c1c1c;
  --muted: #6b6b6b;
  --border: rgba(0,0,0,0.10);
  --code-bg: #f6f6f6;
  --accent: #1c71d8;
  --quote-bg: rgba(0,0,0,0.035);
}
body.preview-dark {
  --bg: #1d1d20;
  --fg: #ececec;
  --muted: #a6a6ad;
  --border: rgba(255,255,255,0.12);
  --code-bg: #26262b;
  --accent: #78aeed;
  --quote-bg: rgba(255,255,255,0.045);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
body {
  font-family: Cantarell, "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", sans-serif;
  font-size: 15px;
  line-height: 1.68;
  padding: 28px 34px 64px 34px;
  -webkit-font-smoothing: antialiased;
  word-wrap: break-word;
}
body > *:first-child { margin-top: 0; }
h1, h2, h3, h4, h5, h6 { line-height: 1.3; margin: 1.6em 0 0.6em; font-weight: 700; }
h1 { font-size: 1.9em; padding-bottom: .3em; border-bottom: 1px solid var(--border); }
h2 { font-size: 1.5em; padding-bottom: .25em; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.25em; }
h4 { font-size: 1.08em; }
p { margin: 0.75em 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 1.6em; margin: 0.7em 0; }
li { margin: 0.22em 0; }
blockquote {
  margin: 1em 0; padding: 0.2em 1em; color: var(--muted);
  border-left: 3px solid var(--border); background: var(--quote-bg);
  border-radius: 0 8px 8px 0;
}
hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
img { max-width: 100%; height: auto; border-radius: 8px; display: block; margin: 1em 0; }
code {
  font-family: "Source Code Pro", "JetBrains Mono", "DejaVu Sans Mono", monospace;
  font-size: 0.9em; background: var(--code-bg); padding: 0.15em 0.4em; border-radius: 5px;
}
pre {
  background: var(--code-bg); padding: 14px 16px; border-radius: 10px;
  overflow-x: auto; border: 1px solid var(--border);
}
pre code { background: none; padding: 0; font-size: 0.88em; line-height: 1.5; }
.codehilite { margin: 1em 0; }
.codehilite pre { background: var(--code-bg); }
table {
  border-collapse: collapse; width: 100%; margin: 1.1em 0; font-size: 0.95em;
  border-radius: 8px; overflow: hidden;
}
th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
th { background: var(--quote-bg); font-weight: 600; }
tr:nth-child(even) td { background: rgba(127,127,127,0.035); }
.math-display { display: block; text-align: center; margin: 1.1em 0; overflow-x: auto; overflow-y: hidden; }
.math-inline { display: inline-block; }
.mermaid { margin: 1.2em 0; text-align: center; background: transparent; }
.mermaid svg { max-width: 100%; height: auto; }
.math-error { color: #c01c28; font-family: monospace; font-size: 0.9em; }
.task-list-item { list-style: none; margin-left: -1.4em; }
input[type=checkbox] { margin-right: .5em; }
dl { margin: 1em 0; }
dt { font-weight: 600; }
dd { margin: 0 0 .6em 1.4em; color: var(--muted); }
"""

# KaTeX / Mermaid 均为 3 MB 级脚本，只在文档真正用到时才注入：
# 纯文字笔记不再解析这两个库，预览进程内存因此显著下降。
_JS_MATH = """
  const katexOk = typeof katex !== 'undefined';
  document.querySelectorAll('.math').forEach(function (el) {
    const tex = el.getAttribute('data-tex') || '';
    const display = el.getAttribute('data-display') === '1';
    if (!katexOk) { el.textContent = display ? '$$' + tex + '$$' : '$' + tex + '$'; return; }
    try {
      katex.render(tex, el, {displayMode: display, throwOnError: false, strict: false,
                             output: 'htmlAndMathml'});
    } catch (e) {
      el.classList.add('math-error');
      el.textContent = tex;
    }
  });
"""

_JS_MERMAID = """
  const nodes = document.querySelectorAll('.mermaid');
  if (typeof mermaid !== 'undefined' && nodes.length) {
    mermaid.initialize({
      startOnLoad: false,
      theme: dark ? 'dark' : 'neutral',
      securityLevel: 'loose',
      fontFamily: 'Cantarell, Noto Sans CJK SC, sans-serif',
      flowchart: {htmlLabels: true, useMaxWidth: true}
    });
    mermaidDone = mermaid.run({nodes: nodes}).catch(function (e) {
      nodes.forEach(function (n) {
        if (!n.querySelector('svg')) {
          n.innerHTML = '<pre style="color:#c01c28;text-align:left">Mermaid 渲染失败: ' +
                        String(e && e.message || e) + '</pre>';
        }
      });
    });
  }
"""


def _build_scripts(*, dark: bool, has_math: bool, has_mermaid: bool) -> str:
    """按需拼装页面脚本：无公式不注入 KaTeX，无图表不注入 Mermaid。"""
    tags: list[str] = []
    if has_mermaid:
        tags.append(f'<script src="{paths.vendor_js("mermaid.min.js").as_uri()}"></script>')
    if has_math:
        tags.append(f'<script src="{paths.vendor_js("katex/katex.min.js").as_uri()}"></script>')

    body = [
        "<script>",
        "(function () {",
        f"  const dark = {'true' if dark else 'false'};",
        "  if (dark) document.body.classList.add('preview-dark');",
        "  let mermaidDone = Promise.resolve();",
    ]
    if has_math:
        body.append(_JS_MATH)
    if has_mermaid:
        body.append(_JS_MERMAID)
    body.append(
        """
  // 侧栏大纲：按标题序号滚动（序号由 Python 侧写入 data-h，与大纲条目一一对应）
  window.gscratchpadScrollToHeading = function (index) {
    const nodes = document.querySelectorAll('h1,h2,h3,h4,h5,h6');
    if (!nodes.length) return false;
    const el = nodes[Math.max(0, Math.min(index, nodes.length - 1))];
    el.scrollIntoView({block: 'start', behavior: 'auto'});
    el.style.transition = 'background-color .9s';
    const original = el.style.backgroundColor;
    el.style.backgroundColor = 'rgba(255, 200, 60, 0.28)';
    setTimeout(function () { el.style.backgroundColor = original; }, 700);
    return true;
  };
  document.querySelectorAll('a[href]').forEach(function (a) {
    a.setAttribute('target', '_blank');
  });
  Promise.resolve(mermaidDone).then(function () {
    window.__scratchpadReady = true;
    try { window.webkit.messageHandlers.ready.postMessage(1); } catch (e) {}
  });
})();
</script>"""
    )
    return "\n".join(tags) + "\n" + "".join(body)


def wrap_plain(body_html: str, *, dark: bool = False) -> str:
    """把已转义的纯文本包装成与预览一致的样式（用于 TXT 文档）。"""
    pygments_css = _PYGMENTS_DARK if dark else _PYGMENTS_LIGHT
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>{_BASE_CSS}</style><style>{pygments_css}</style></head>
<body class="{'preview-dark' if dark else ''}">{body_html}</body></html>"""


def render_document(
    text: str, *, dark: bool = False, print_mode: bool = False, print_scale: int = 1
) -> str:
    body = render_body(text)
    # 只有正文真的出现公式/图表时才引入对应库
    has_math = 'class="math math-' in body
    has_mermaid = 'class="mermaid"' in body
    katex_css = paths.vendor_js("katex/katex.min.css").as_uri()
    pygments_css = _PYGMENTS_DARK if (dark and not print_mode) else _PYGMENTS_LIGHT

    print_css = ""
    if print_mode:
        print_css = f"""
html {{ zoom: {print_scale}; }}
@page {{ size: A4; margin: 18mm 16mm 18mm 16mm; }}
body {{ padding: 0 !important; font-size: 11pt; background: #fff !important; color: #000 !important; }}
body.preview-dark {{ background: #fff !important; color: #000 !important; }}
pre, .codehilite pre {{ white-space: pre-wrap; word-break: break-word; background: #f6f6f6 !important; }}
h1, h2, h3, h4 {{ page-break-after: avoid; }}
pre, table, img, .mermaid, blockquote {{ page-break-inside: avoid; }}
table {{ font-size: 9.5pt; }}
a {{ color: #000 !important; text-decoration: underline; }}
"""
    # 打印模式同样需要脚本：KaTeX 与 Mermaid 必须渲染完成后才能导出 PDF
    scripts = _build_scripts(
        dark=dark and not print_mode, has_math=has_math, has_mermaid=has_mermaid
    )
    katex_link = f'<link rel="stylesheet" href="{katex_css}">' if has_math else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{katex_link}
<style>{_BASE_CSS}</style>
<style>{pygments_css}</style>
<style>{print_css}</style>
</head>
<body class="{'print-mode' if print_mode else 'preview-mode'}">
{body}
</body>
{scripts}
</html>"""
