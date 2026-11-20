#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跨端金标准语料（P2-7）——桌面侧指纹生成与 Android 侧对照。

指纹定义（两侧必须完全一致，见 docs/ANDROID_STAGE_STATUS.md §5.2 P2-7）：

    fp = { "text": 正文纯文本（全部空白折叠为单个空格并去首尾）,
           "counts": { 规范标签名: 出现次数 } }

标签白名单 CANON 只取「语义块 + 语义强调 + 链接/图片/分隔线」，刻意排除
`span`/`div`/`br`/`class`/`id` 这类引擎实现差异（Python-Markdown 的 codehilite
会多包一层 div+span，markdown-it 不会），因此指纹比较的是**结构与文本**，
不是字节级 HTML。

用法：
    python scripts/golden_fingerprint.py            # 打印桌面指纹 + 写 android 语料 JSON
    python scripts/golden_fingerprint.py --compare tmp/golden_log.txt
"""

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
CORPUS = ROOT / "tests" / "golden" / "corpus"
ANDROID_CORPUS_JSON = ROOT / "android" / "app" / "src" / "main" / "assets" / "golden" / "corpus.json"

CANON = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "ul", "ol", "pre", "blockquote",
    "table", "tr", "th", "td",
    "strong", "em", "code", "a", "img", "hr",
]


def _md():
    sys.path.insert(0, str(VENDOR))
    import markdown  # noqa: WPS433  (vendored, same version the desktop app ships)
    return markdown


def render_desktop(text: str) -> str:
    """与桌面 src/scratchpad/markdown_render.py 的 _MD 配置一致。"""
    md = _md()
    engine = md.Markdown(
        extensions=["extra", "sane_lists", "nl2br", "admonition", "codehilite", "toc"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite", "linenums": False},
            "toc": {"permalink": False},
        },
        output_format="html5",
    )
    return engine.convert(text)


class _Fp(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = {}
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in CANON:
            self.counts[tag] = self.counts.get(tag, 0) + 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        self.text.append(data)


def fingerprint(html_text: str) -> dict:
    parser = _Fp()
    parser.feed(html_text)
    text = re.sub(r"\s+", " ", "".join(parser.text))
    return {"text": text.strip(), "counts": dict(sorted(parser.counts.items()))}


def desktop_fingerprint(md_text: str) -> dict:
    return fingerprint(render_desktop(md_text))


def load_corpus():
    cases = []
    for path in sorted(CORPUS.glob("*.md")):
        cases.append((path.stem, path.read_text(encoding="utf-8")))
    return cases


def write_android_corpus(cases):
    ANDROID_CORPUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"name": name, "md": text} for name, text in cases]
    ANDROID_CORPUS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return ANDROID_CORPUS_JSON


def compare(log_path: Path, cases):
    expected = {name: desktop_fingerprint(text) for name, text in cases}
    seen = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        marker = "golden|"
        idx = line.find(marker)
        if idx < 0:
            continue
        payload = line[idx + len(marker):].strip()
        if "|" not in payload:
            continue
        name, raw = payload.split("|", 1)
        try:
            seen[name.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            continue

    ok, bad, missing = [], [], []
    for name, _ in cases:
        if name not in seen:
            missing.append(name)
            continue
        got = seen[name]
        if got.get("text") == expected[name]["text"] and got.get("counts") == expected[name]["counts"]:
            ok.append(name)
        else:
            diffs = []
            if got.get("text") != expected[name]["text"]:
                diffs.append("text")
            if got.get("counts") != expected[name]["counts"]:
                diffs.append("counts")
            bad.append((name, diffs, expected[name], got))

    print(f"golden: {len(ok)}/{len(cases)} 一致")
    if bad:
        print("差异用例：")
        for name, diffs, exp, got in bad:
            print(f"  - {name}: {','.join(diffs)}")
            if "text" in diffs:
                print(f"    桌面: {exp['text'][:120]!r}")
                print(f"    Android: {got.get('text', '')[:120]!r}")
            if "counts" in diffs:
                print(f"    桌面: {exp['counts']}")
                print(f"    Android: {got.get('counts')}")
    if missing:
        print("未采到（Android 未上报）：" + ", ".join(missing))
    return 0 if (not bad and not missing) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default=None, help="adb logcat 输出文件，按 golden|<name>|<json> 解析")
    args = ap.parse_args()
    cases = load_corpus()
    if not cases:
        print(f"语料目录为空：{CORPUS}")
        return 2
    if args.compare:
        return compare(Path(args.compare), cases)
    out = write_android_corpus(cases)
    for name, text in cases:
        fp = desktop_fingerprint(text)
        print(f"{name}\t{json.dumps(fp, ensure_ascii=False)}")
    print(f"\nAndroid 语料已写入 {out}（{len(cases)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
