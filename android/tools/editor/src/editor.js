// 编辑器内核（路线 D）：CodeMirror 6 装配 + 与 Android 的桥接。
// 打包：npm run build（esbuild 单文件输出到 app/src/main/assets/editor/editor.js）
import { EditorState, Compartment, EditorSelection } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection,
  rectangularSelection, highlightSpecialChars, placeholder, Decoration, ViewPlugin,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab, undo } from "@codemirror/commands";
import { codeFolding, foldKeymap, foldAll, unfoldAll, foldEffect, foldedRanges, foldService } from "@codemirror/language";
import { searchKeymap, highlightSelectionMatches, SearchCursor } from "@codemirror/search";
import { RangeSetBuilder, Prec } from "@codemirror/state";

const themeCompartment = new Compartment();
const prefsCompartment = new Compartment();

// 阅读偏好（字号 / 行高 / 折行 / 字体族），由设置页写入，通过 Compartment 热替换。
function prefsExtension(prefs) {
  const p = prefs || {};
  const exts = [];
  const content = {};
  if (p.fontSize) content.fontSize = `${p.fontSize}px`;
  if (p.lineHeight) content.lineHeight = String(p.lineHeight);
  if (p.fontFamily === "mono") content.fontFamily = 'ui-monospace, "JetBrains Mono", monospace';
  else if (p.fontFamily === "serif") content.fontFamily = 'Georgia, "Noto Serif CJK SC", serif';
  else if (p.fontFamily === "sans") content.fontFamily = '-apple-system, "Noto Sans CJK SC", sans-serif';
  if (Object.keys(content).length) exts.push(EditorView.theme({ ".cm-content": content }));
  if (p.wrap !== false) exts.push(EditorView.lineWrapping);
  else exts.push(EditorView.theme({ ".cm-scroller": { overflowX: "auto" } }));
  return exts;
}

const bridge = () => (window.AndroidEditor ? window.AndroidEditor : null);

// 轻量高亮：只按行首正则给标题、围栏、列表着色，避免引入 @codemirror/lang-markdown
// （该包会连带 lang-html / lang-css / lezer-javascript / autocomplete，实测约 140 KB）。
const headingDeco = Decoration.line({ class: "cm-md-heading" });
const fenceDeco = Decoration.line({ class: "cm-md-fence" });
const listDeco = Decoration.line({ class: "cm-md-list" });

const markdownHighlighter = ViewPlugin.fromClass(class {
  constructor(view) {
    this.deco = this.build(view);
  }
  update(u) {
    if (u.docChanged || u.viewportChanged) this.deco = this.build(u.view);
  }
  build(view) {
    const b = new RangeSetBuilder();
    const doc = view.state.doc;
    const from = Math.max(1, doc.lineAt(view.viewport.from).number);
    const to = doc.lineAt(view.viewport.to).number;
    for (let n = from; n <= to; n += 1) {
      const line = doc.line(n);
      const text = line.text;
      if (/^#{1,6}\s/.test(text)) b.add(line.from, line.from, headingDeco);
      else if (/^\s*(```|~~~)/.test(text)) b.add(line.from, line.from, fenceDeco);
      else if (/^\s*(-|\*|\d+\.)\s/.test(text)) b.add(line.from, line.from, listDeco);
    }
    return b.finish();
  }
}, { decorations: (v) => v.deco });

const darkTheme = EditorView.theme({
  "&": { backgroundColor: "#1c1c1e", color: "#e6e6e6" },
  ".cm-content": { caretColor: "#e6e6e6" },
  ".cm-gutters": { backgroundColor: "#1c1c1e", color: "#8a8a8e", border: "none" },
  ".cm-activeLine": { backgroundColor: "#2a2a2d" },
  ".cm-activeLineGutter": { backgroundColor: "#2a2a2d", color: "#e6e6e6" },
}, { dark: true });

// 折叠服务：标题段（# .. ###### 起至同级/更高级标题前）、围栏代码块、列表块。
function markdownFolds(state, lineStart, lineEnd) {
  const doc = state.doc;
  const startLine = doc.lineAt(lineStart);
  const text = startLine.text;
  const heading = /^(#{1,6})\s/.exec(text);
  if (heading) {
    const level = heading[1].length;
    let end = startLine.to;
    let n = startLine.number;
    while (n < doc.lines) {
      n += 1;
      const l = doc.line(n);
      const m = /^(#{1,6})\s/.exec(l.text);
      if (m && m[1].length <= level) break;
      end = l.to;
    }
    if (end > startLine.to) return { from: startLine.to, to: end };
    return null;
  }
  const fence = /^\s*(```|~~~)/.exec(text);
  if (fence) {
    let end = null;
    for (let n = startLine.number + 1; n <= doc.lines; n += 1) {
      const l = doc.line(n);
      if (/^\s*(```|~~~)\s*$/.test(l.text)) { end = l.to; break; }
    }
    if (end != null && end > startLine.to) return { from: startLine.to, to: end };
  }
  return null;
}

function metrics(kind, value) {
  const b = bridge();
  if (b && b.onMetric) b.onMetric(kind, String(value));
}

const view = new EditorView({
  parent: document.getElementById("host"),
  state: EditorState.create({
    doc: "",
    extensions: [
      lineNumbers(),
      highlightActiveLine(),
      highlightSpecialChars(),
      drawSelection(),
      rectangularSelection(),
      history(),
      codeFolding({ placeholderText: "…" }),
      foldService.of((state, lineStart) => markdownFolds(state, lineStart, lineStart)),
      markdownHighlighter,
      EditorState.allowMultipleSelections.of(true),
      prefsCompartment.of(prefsExtension({ wrap: true })),
      EditorView.contentAttributes.of({ "data-gramm": "false", autocorrect: "off", autocapitalize: "off", spellcheck: "false" }),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) return;
        const b = bridge();
        if (!b) return;
        clearTimeout(window.__emit);
        window.__emit = setTimeout(() => {
          if (b.onChange) b.onChange(view.state.doc.toString());
        }, 120);
      }),
      keymap.of([
        { key: "Mod-n", run: () => { bridge()?.onShortcut?.("NEW"); return true; } },
        { key: "Mod-w", run: () => { bridge()?.onShortcut?.("CLOSE"); return true; } },
        { key: "Mod-f", run: () => { bridge()?.onShortcut?.("FIND"); return true; } },
        { key: "Mod-Shift-i", run: () => { bridge()?.onAction?.("palette"); return true; } },
        { key: "Mod-Shift-o", run: () => { bridge()?.onAction?.("outline"); return true; } },
        { key: "Mod-h", run: () => { bridge()?.onShortcut?.("REPLACE"); return true; } },
        { key: "Mod-Shift-p", run: () => { bridge()?.onShortcut?.("PREVIEW"); return true; } },
        { key: "Mod-s", run: () => { bridge()?.onAction?.("save"); return true; } },
        { key: "Mod-Shift-s", run: () => { bridge()?.onAction?.("saveAs"); return true; } },
        { key: "Mod-o", run: () => { bridge()?.onAction?.("openFile"); return true; } },
        { key: "Mod-d", run: () => { bridge()?.onAction?.("split"); return true; } },
        { key: "Mod-i", run: () => { bridge()?.onAction?.("image"); return true; } },
        { key: "Mod-Shift-/", run: () => { openHelp(); return true; } },
        { key: "F1", run: () => { openHelp(); return true; } },
        { key: "F9", run: () => { bridge()?.onAction?.("split"); return true; } },
        { key: "F2", run: () => { bridge()?.onShortcut?.("RENAME"); return true; } },
        ...defaultKeymap, ...historyKeymap, ...foldKeymap, ...searchKeymap, indentWithTab,
      ]),
      themeCompartment.of([]),
    ],
  }),
});

// 折叠命令：按光标所在行折叠/展开（区间装饰，内容不变）。
function toggleFoldAtCursor() {
  const sel = view.state.selection.main;
  const line = view.state.doc.lineAt(sel.head);
  const folded = foldedRanges(view.state);
  let hit = null;
  folded.between(line.from, line.to, (from, to) => { hit = { from, to }; });
  if (hit) { view.dispatch({ effects: unfoldAll }); return; }
  const range = markdownFolds(view.state, line.from, line.to);
  if (!range) return;
  view.dispatch({ effects: foldEffect.of(range) });
}

window.NativeEditor = {
  ready() { bridge()?.onReady?.(); },

  setDoc(text) {
    const t0 = performance.now();
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: text || "" },
      selection: EditorSelection.cursor(0),
    });
    // 双 rAF：第一帧完成布局与首屏绘制后才回报，避免只测量 dispatch 时间
    requestAnimationFrame(() => requestAnimationFrame(() => {
      metrics("open", Math.round(performance.now() - t0));
    }));
  },

  getText() { return view.state.doc.toString(); },

  setTheme(dark) {
    view.dispatch({ effects: themeCompartment.reconfigure(dark ? darkTheme : []) });
    document.body.classList.toggle("dark", !!dark);
  },

  focus() { view.focus(); },

  insert(text) {
    const sel = view.state.selection.main;
    view.dispatch({
      changes: { from: sel.from, to: sel.to, insert: text },
      selection: { anchor: sel.from + text.length },
      scrollIntoView: true,
    });
    view.focus();
  },

  foldAtCursor() {
    const t0 = performance.now();
    toggleFoldAtCursor();
    metrics("fold", Math.round(performance.now() - t0));
  },

  foldAll() { view.dispatch({ effects: foldAll }); },
  unfoldAll() { view.dispatch({ effects: unfoldAll }); },

  lineCount() { return view.state.doc.lines; },

  selectionInfo() {
    const sel = view.state.selection.main;
    const line = view.state.doc.lineAt(sel.head);
    return JSON.stringify({ line: line.number, column: sel.head - line.from + 1 });
  },

  scrollToLine(n) {
    const line = view.state.doc.line(Math.min(Math.max(1, n), view.state.doc.lines));
    // 对齐到视口顶端：`center` 会让顶行落到标题上方，预览侧再按顶行反推就会一路向上漂移
    view.dispatch({ effects: EditorView.scrollIntoView(line.from, { y: "start" }) });
    return;
  },

  /** 文档大纲：扫描全文标题行（1 MB 文档实测百毫秒级），供大纲面板与预览对齐使用。 */
  outline() {
    const doc = view.state.doc;
    const items = [];
    for (let n = 1; n <= doc.lines; n += 1) {
      const text = doc.line(n).text;
      const m = /^(#{1,6})\s+(.*)$/.exec(text);
      if (m) items.push({ line: n, level: m[1].length, text: m[2].trim().slice(0, 80) });
      if (items.length >= 500) break;
    }
    return JSON.stringify(items);
  },

  /** 视口顶端所在行（预览滚动对齐用）。 */
  topLine() {
    const pos = view.lineBlockAtHeight(0).from;
    return view.state.doc.lineAt(pos).number;
  },

  setPrefs(json) {
    let prefs = {};
    try { prefs = JSON.parse(json || "{}"); } catch (e) { prefs = {}; }
    view.dispatch({ effects: prefsCompartment.reconfigure(prefsExtension(prefs)) });
  },

  // 诊断用：持续注入中文段落（走 CM 事务，非 IME），验证中文渲染/防抖/落盘链路不丢字。
  soakChinese(seconds) {
    const unit = "中文输入压力测试段落汉字组合候选回改";
    let sent = 0;
    const t0 = performance.now();
    const tick = () => {
      if (performance.now() - t0 >= seconds * 1000) {
        bridge()?.onMetric?.("soak", String(sent));
        return;
      }
      const sel = view.state.selection.main;
      view.dispatch({
        changes: { from: sel.from, to: sel.to, insert: unit },
        selection: { anchor: sel.from + unit.length },
      });
      sent += unit.length;
      setTimeout(tick, 100);
    };
    tick();
  },
};

// 首次渲染完成即回报，Kotlin 侧据此灌入文档。
requestAnimationFrame(() => window.NativeEditor.ready());

// 帧率采样：2 s 窗口统计 rAF 帧数。滚动期间报 fps，其余时间每 4 s 报一次 fpsIdle（用于区分环境上限与编辑成本）。
let fpsStart = 0;
let fpsFrames = 0;
let lastScroll = 0;
let idleStart = performance.now();
let idleFrames = 0;
const countFrame = () => {
  requestAnimationFrame(countFrame);
  const now = performance.now();
  idleFrames += 1;
  if (now - idleStart >= 4000) {
    bridge()?.onMetric?.("fpsIdle", Math.round((idleFrames * 1000) / (now - idleStart)));
    idleStart = now;
    idleFrames = 0;
  }
  if (!lastScroll || now - lastScroll > 2000) {
    fpsStart = 0;
    return;
  }
  if (!fpsStart) {
    fpsStart = now;
    fpsFrames = 0;
  }
  fpsFrames += 1;
  const dt = now - fpsStart;
  if (dt >= 2000) {
    bridge()?.onMetric?.("fps", Math.round((fpsFrames * 1000) / dt));
    fpsStart = 0;
    fpsFrames = 0;
    lastScroll = now;
  }
};
requestAnimationFrame(countFrame);
window.addEventListener("scroll", () => { lastScroll = performance.now(); }, { passive: true, capture: true });
const scroller = document.querySelector(".cm-scroller");
if (scroller) scroller.addEventListener("scroll", () => { lastScroll = performance.now(); }, { passive: true });
bridge()?.onMetric?.("probe", scroller ? "scroller-hooked" : "no-scroller");

// ---------------------------------------------------------------- 页内工具栏
const findbar = document.getElementById("findbar");
const statusEl = document.getElementById("status");

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

const moreMenu = document.getElementById("moremenu");

function closeMore() {
  if (moreMenu) moreMenu.hidden = true;
}

document.querySelectorAll("#bar button").forEach((btn) => {
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    const act = btn.dataset.act;
    if (act === "more") {
      moreMenu.hidden = !moreMenu.hidden;
      return;
    }
    closeMore();
    if (act === "find") {
      findbar.hidden = !findbar.hidden;
      if (!findbar.hidden) document.getElementById("findq").focus();
      return;
    }
    bridge()?.onAction?.(act);
  });
});

// 溢出菜单：低频动作全部走 runAction，与命令面板共用同一套动作 id
document.querySelectorAll("#moremenu button").forEach((btn) => {
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    closeMore();
    runAction(btn.dataset.more);
  });
});

// 点空白处收起溢出菜单（面板是绝对定位，不能依赖 fixed）
document.addEventListener("click", (ev) => {
  if (!moreMenu || moreMenu.hidden) return;
  const t = ev.target;
  if (t && t.closest && (t.closest("#moremenu") || t.closest('[data-act="more"]'))) return;
  moreMenu.hidden = true;
}, true);

function findNext(backwards) {
  const q = document.getElementById("findq").value;
  if (!q) return;
  const sel = view.state.selection.main;
  const from = backwards ? sel.from : sel.to;
  const cur = new SearchCursor(view.state.doc, q, from, view.state.doc.length);
  if (backwards) {
    let last = null;
    while (!cur.next().done) last = { from: cur.value.from, to: cur.value.to };
    if (!last) return;
    view.dispatch({ selection: { anchor: last.from, head: last.to }, scrollIntoView: true });
  } else {
    const r = cur.next();
    if (r.done) {
      // 回绕到文首
      const first = new SearchCursor(view.state.doc, q, 0, view.state.doc.length).next();
      if (first.done) return;
      view.dispatch({ selection: { anchor: first.value.from, head: first.value.to }, scrollIntoView: true });
      return;
    }
    view.dispatch({ selection: { anchor: r.value.from, head: r.value.to }, scrollIntoView: true });
  }
}

let findRegex = false;
let findSelection = false;

function replaceAll() {
  const q = document.getElementById("findq").value;
  if (!q) return 0;
  const r = document.getElementById("findr").value;
  const sel = view.state.selection.main;
  const from = findSelection ? sel.from : 0;
  const to = findSelection ? sel.to : view.state.doc.length;
  const slice = view.state.sliceDoc(from, to);
  let next;
  let count;
  if (findRegex) {
    let re;
    try { re = new RegExp(q, "g"); } catch (e) { return 0; }
    count = 0;
    next = slice.replace(re, () => { count += 1; return r; });
  } else {
    if (slice.indexOf(q) < 0) return 0;
    count = slice.split(q).length - 1;
    next = slice.split(q).join(r);
  }
  // 单次事务写入 → 工具栏「全部」只产生一个撤销步，一次 Ctrl+Z 全量回退
  view.dispatch({ changes: { from, to, insert: next } });
  return count;
}

document.querySelectorAll("#findbar button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const act = btn.dataset.find;
    if (act === "next") findNext(false);
    else if (act === "prev") findNext(true);
    else if (act === "all") setStatus("替换 " + replaceAll() + " 处");
    else if (act === "regex") {
      findRegex = !findRegex;
      btn.classList.toggle("on", findRegex);
    } else if (act === "selection") {
      findSelection = !findSelection;
      btn.classList.toggle("on", findSelection);
    } else if (act === "replace") {
      const q = document.getElementById("findq").value;
      const selText = view.state.sliceDoc(view.state.selection.main.from, view.state.selection.main.to);
      if (q && selText === q) {
        const r = document.getElementById("findr").value;
        view.dispatch({ changes: { from: view.state.selection.main.from, to: view.state.selection.main.to, insert: r } });
        findNext(false);
      } else findNext(false);
    } else if (act === "close") findbar.hidden = true;
  });
});

setInterval(() => {
  const sel = view.state.selection.main;
  const line = view.state.doc.lineAt(sel.head);
  setStatus(`${view.state.doc.lines} 行 · ${view.state.doc.length} 字 · ${line.number}:${sel.head - line.from + 1}`);
}, 800);

// ---------------------------------------------------------------- 覆盖层（命令面板 / 大纲 / 设置）
const paletteEl = document.getElementById("palette");
const paletteQuery = document.getElementById("palette-q");
const paletteList = document.getElementById("palette-list");
const outlineEl = document.getElementById("outline");
const outlineList = document.getElementById("outline-list");
const docsEl = document.getElementById("docs");
const docsList = document.getElementById("docs-list");
const settingsEl = document.getElementById("settings");

// 动作表由 Kotlin 下发（单一真源），这里只负责渲染与检索。
let actionsCache = [];
let prefsState = { fontSize: 15, lineHeight: 1.2, wrap: true };
// 文档列表由 Kotlin 下发：[{id,title,active}]，供「切换文档」浮层渲染。
let docsCache = [];

const LOCAL_ACTIONS = new Set(["find", "fold", "foldAll", "unfoldAll", "outline", "docs", "settings"]);

function hideOverlays() {
  paletteEl.hidden = true;
  outlineEl.hidden = true;
  docsEl.hidden = true;
  settingsEl.hidden = true;
  const helpEl = document.getElementById("help");
  if (helpEl) helpEl.hidden = true;
  if (typeof closeMore === "function") closeMore();
}

function runAction(id) {
  hideOverlays();
  if (id === "find") {
    findbar.hidden = false;
    document.getElementById("findq").focus();
    return;
  }
  if (id === "fold") { toggleFoldAtCursor(); return; }
  if (id === "foldAll") { view.dispatch({ effects: foldAll }); return; }
  if (id === "unfoldAll") { view.dispatch({ effects: unfoldAll }); return; }
  if (id === "outline") { openOutline(); return; }
  if (id === "settings") { openSettings(); return; }
  // docs 走 Kotlin 单入口（onAction）：宿主在打开浮层前先刷新文档列表，保证数据最新。
  if (id === "help") { openHelp(); return; }
  bridge()?.onAction?.(id);
}

/** Q2：页内快捷键面板（物理键盘一等交互的可见入口）。 */
function openHelp() {
  hideOverlays();
  const el = document.getElementById("help");
  if (el) el.hidden = false;
  metrics("help", "open");
}

function filterActions(query) {
  const tokens = query.trim().toLowerCase().split(" ").filter((t) => t.length > 0);
  if (!tokens.length) return actionsCache;
  return actionsCache.filter((a) => {
    const hay = `${a.label} ${a.keywords || ""} ${a.category || ""}`.toLowerCase();
    return tokens.every((t) => hay.includes(t));
  });
}

function renderPalette() {
  const items = filterActions(paletteQuery.value);
  paletteList.innerHTML = "";
  items.forEach((a) => {
    const btn = document.createElement("button");
    btn.className = "item";
    btn.dataset.id = a.id;
    btn.innerHTML = `${a.label}<small>${a.category || ""}</small>`;
    btn.addEventListener("click", () => runAction(a.id));
    paletteList.appendChild(btn);
  });
  if (!items.length) paletteList.innerHTML = '<div class="item">没有匹配的命令</div>';
}

function openPalette() {
  hideOverlays();
  paletteEl.hidden = false;
  paletteQuery.value = "";
  renderPalette();
  paletteQuery.focus();
  metrics("palette", "open");
}

function openOutline() {
  hideOverlays();
  outlineEl.hidden = false;
  const items = JSON.parse(window.NativeEditor.outline());
  outlineList.innerHTML = "";
  if (!items.length) outlineList.innerHTML = '<div class="item">本文档没有标题</div>';
  items.forEach((h) => {
    const btn = document.createElement("button");
    btn.className = `item lvl-${h.level}`;
    btn.textContent = h.text || "(空标题)";
    btn.addEventListener("click", () => {
      hideOverlays();
      window.NativeEditor.scrollToLine(h.line);
      view.focus();
    });
    outlineList.appendChild(btn);
  });
}

/** 切换文档：弹出当前打开的文档列表（与大纲同款浮层），点条目回传 id 给 Kotlin。 */
function openDocs() {
  hideOverlays();
  docsEl.hidden = false;
  let items = [];
  try { items = JSON.parse(window.NativeEditor.docs()); } catch (e) { items = docsCache; }
  docsList.innerHTML = "";
  if (!items.length) {
    docsList.innerHTML = '<div class="item">当前没有打开的文档</div>';
    return;
  }
  items.forEach((d) => {
    const btn = document.createElement("button");
    btn.className = "item" + (d.active ? " on" : "");
    btn.textContent = d.title || "(未命名)";
    if (d.active) btn.setAttribute("aria-current", "true");
    btn.addEventListener("click", () => {
      hideOverlays();
      bridge()?.switchDoc?.(d.id);
    });
    docsList.appendChild(btn);
  });
}

function applyPrefs(next) {
  prefsState = { ...prefsState, ...next };
  window.NativeEditor.setPrefs(JSON.stringify(prefsState));
  const fs = document.getElementById("set-font-size");
  const lh = document.getElementById("set-line-height");
  const wp = document.getElementById("set-wrap");
  fs.value = String(prefsState.fontSize);
  lh.value = String(prefsState.lineHeight);
  wp.checked = !!prefsState.wrap;
  document.getElementById("set-font-size-value").textContent = String(prefsState.fontSize);
  document.getElementById("set-line-height-value").textContent = String(prefsState.lineHeight);
  bridge()?.onPrefsChanged?.(JSON.stringify(prefsState));
  metrics("prefs", `${prefsState.fontSize}/${prefsState.lineHeight}/${prefsState.wrap}`);
}

function openSettings() {
  hideOverlays();
  settingsEl.hidden = false;
  document.getElementById("set-font-size").value = String(prefsState.fontSize);
  document.getElementById("set-line-height").value = String(prefsState.lineHeight);
  document.getElementById("set-wrap").checked = !!prefsState.wrap;
  document.getElementById("set-font-size-value").textContent = String(prefsState.fontSize);
  document.getElementById("set-line-height-value").textContent = String(prefsState.lineHeight);
}

document.getElementById("palette-close").addEventListener("click", hideOverlays);
document.getElementById("outline-close").addEventListener("click", hideOverlays);
document.getElementById("docs-close").addEventListener("click", hideOverlays);
document.getElementById("settings-close").addEventListener("click", hideOverlays);
paletteQuery.addEventListener("input", renderPalette);
document.getElementById("set-font-size").addEventListener("input", (e) => {
  applyPrefs({ fontSize: Number(e.target.value) });
});
document.getElementById("set-line-height").addEventListener("input", (e) => {
  applyPrefs({ lineHeight: Number(e.target.value) });
});
document.getElementById("set-wrap").addEventListener("change", (e) => {
  applyPrefs({ wrap: e.target.checked });
});

// 点击空白处关闭所有浮层：命令面板 / 大纲 / 设置 / 帮助 / 更多菜单 / 查找条
// （工具栏、面包屑与面板卡片内的点击不算空白，否则刚点开就会被自己关掉）
// 注意：白名单必须是 .sheet（面板卡片），不能是 .overlay——.overlay 是全屏遮罩，
// 拿它做白名单会把「点遮罩空白」判成「点在面板内」，导致只能用「关闭」按钮退出（R24 根因）。
document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (!t || typeof t.closest !== "function") return;
  if (t.closest(".sheet") || t.closest("#moremenu") || t.closest("#findbar")) return;
  if (t.closest("#bar") || t.closest("#crumb")) return;
  hideOverlays();
  if (!findbar.hidden) findbar.hidden = true;
});

// 工具栏：命令 / 大纲 / 设置 与查找、折叠同走 Kotlin 单入口（onAction），保证两套 UI 行为一致

// Kotlin 下发的动作表 + 偏好
window.NativeEditor.setActions = (json) => {
  try { actionsCache = JSON.parse(json || "[]"); } catch (e) { actionsCache = []; }
};
window.NativeEditor.openPalette = () => openPalette();
window.NativeEditor.openOutline = () => openOutline();
window.NativeEditor.openDocs = () => openDocs();
window.NativeEditor.openSettings = () => openSettings();

/** 文档列表由 Kotlin 下发（JSON 数组：id/title/active），点选时回传 id。 */
window.NativeEditor.setDocs = (json) => {
  try { docsCache = JSON.parse(json || "[]"); } catch (e) { docsCache = []; }
};
window.NativeEditor.docs = () => JSON.stringify(docsCache);
window.NativeEditor.openFind = () => {
  findbar.hidden = false;
  const q = document.getElementById("findq");
  if (q) q.focus();
};

/** 面包屑标题：由 Kotlin 打开文档时下发。 */
window.NativeEditor.setDocTitle = (title) => {
  const el = document.getElementById("doc-title");
  const text = title || "未命名";
  if (el) {
    el.textContent = text;
    el.title = text;
  }
};
window.NativeEditor.closeOverlays = () => hideOverlays();
window.NativeEditor.openHelp = () => openHelp();
document.getElementById("help-close")?.addEventListener("click", () => {
  const el = document.getElementById("help");
  if (el) el.hidden = true;
});

/**
 * P2-6 自检：全部替换必须只产生一个撤销步，且「仅选区」不触碰选区外文本。
 * 由宿主 `--es runAction selfCheckFind` 触发，结果走 metric 便于 adb logcat 判定。
 */
window.NativeEditor.selfCheckFind = () => {
  const out = {};
  const base = "alpha\nbeta alpha\ngamma\nalpha end\n";
  const saved = view.state.doc.toString();
  // 步骤间隔 650 ms > 历史合并窗口（newGroupDelay 500 ms），确保每步是独立撤销单位
  const GAP = 650;
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: base },
    selection: { anchor: 0 },
    userEvent: "probe.setup",
  });
  setTimeout(() => {
    document.getElementById("findq").value = "alpha";
    document.getElementById("findr").value = "omega";
    findSelection = false;
    out.replaced = replaceAll();
    out.afterReplaceClean = view.state.doc.toString() === "omega\nbeta omega\ngamma\nomega end\n";
    setTimeout(() => {
      undo(view); // historyKeymap 的 undo 命令：一次撤销必须只回退这一次替换
      out.undoRestored = view.state.doc.toString() === base;
      setTimeout(() => {
        // 仅选区：选中首个 alpha，其余 alpha 必须保留
        view.dispatch({ selection: { anchor: 0, head: 5 } });
        findSelection = true;
        document.getElementById("findr").value = "OMEGA";
        const c = replaceAll();
        const full = view.state.doc.toString();
        out.selectionReplaced = c;
        out.selectionOnly = c === 1 &&
          full === "OMEGA" + base.slice(5) &&
          (full.match(/alpha/g) || []).length === 2;
        findSelection = false;
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: saved },
          selection: { anchor: 0 },
          userEvent: "probe.restore",
        });
        metrics("selfCheck", JSON.stringify(out));
        bridge()?.onMetric?.("selfCheck", JSON.stringify(out));
      }, GAP);
    }, GAP);
  }, GAP);
  return "async";
};
window.NativeEditor.paletteItems = () => JSON.stringify(filterActions(paletteQuery.value).map((a) => a.id));
window.NativeEditor.setPrefsFromHost = (json) => {
  try { prefsState = { ...prefsState, ...JSON.parse(json || "{}") }; } catch (e) { /* 保留默认 */ }
  window.NativeEditor.setPrefs(JSON.stringify(prefsState));
};

// 面板打开时先同步一次，供快捷键与诊断使用
setTimeout(() => renderPalette(), 0);
console.log(`panels: palette=${!!paletteEl} outline=${!!outlineEl} settings=${!!settingsEl} actions=${actionsCache.length}`);
metrics("panels", `${!!paletteEl ? 1 : 0}/${actionsCache.length}`);


