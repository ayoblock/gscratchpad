// 编辑器内核（路线 D）：CodeMirror 6 装配 + 与 Android 的桥接。
// 打包：npm run build（esbuild 单文件输出到 app/src/main/assets/editor/editor.js）
import { EditorState, Compartment, EditorSelection, Transaction } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection,
  rectangularSelection, highlightSpecialChars, placeholder, Decoration, ViewPlugin,
} from "@codemirror/view";
import {
  defaultKeymap, history, historyKeymap, indentWithTab,
  undo, redo, undoDepth, redoDepth, selectAll,
} from "@codemirror/commands";
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

// 选区上下文浮栏：CM 内部选区是唯一真源，DOM 手柄拖动经 updateListener 回传到这里。
const selbar = document.getElementById("selbar");
let view = null;
let selectionEmitTimer = 0;

function selectionInfo() {
  if (!view) return { from: 0, to: 0, empty: true, text: "", line: 1, column: 1 };
  const sel = view.state.selection.main;
  const from = Math.min(sel.from, sel.to);
  const to = Math.max(sel.from, sel.to);
  const line = view.state.doc.lineAt(sel.head);
  return {
    from, to, empty: from === to, text: view.state.sliceDoc(from, to),
    line: line.number, column: sel.head - line.from + 1,
  };
}

function overlaysVisible() {
  return ["palette", "outline", "docs", "settings", "help"].some((id) => {
    const el = document.getElementById(id);
    return el && !el.hidden;
  });
}

function hideSelBar() {
  if (selbar) selbar.hidden = true;
}

function positionSelBar(info) {
  if (!selbar || info.empty || overlaysVisible() || !view) { hideSelBar(); return; }
  const headRect = view.coordsAtPos(info.from, 1);
  const tailRect = view.coordsAtPos(info.to, -1);
  if (!headRect || !tailRect) { hideSelBar(); return; }
  selbar.hidden = false;
  selbar.style.visibility = "hidden";
  const w = selbar.offsetWidth || 320;
  const h = selbar.offsetHeight || 44;
  const centerX = (headRect.left + tailRect.right) / 2;
  const x = Math.max(8, Math.min(centerX - w / 2, window.innerWidth - w - 8));
  const above = headRect.top - h - 10;
  const y = above >= 56 ? above : Math.min(tailRect.bottom + 10, window.innerHeight - h - 8);
  selbar.style.left = `${Math.round(x)}px`;
  selbar.style.top = `${Math.round(y)}px`;
  selbar.style.visibility = "";
}

function emitSelection() {
  const info = selectionInfo();
  bridge()?.onSelection?.(JSON.stringify(info));
  positionSelBar(info);
  updateHandles();
  syncToolbar();
}

// R53：原生长按手柄由 WebView 驱动 DOM 选区，CM 的 selectionSet 不一定触发。
// 直接监听 document.selectionchange 作为兜底，把 DOM 选区换算成 CM 位置后再定位浮栏。
let domSelectionTimer = 0;
function onDomSelectionChange() {
  if (!view || overlaysVisible()) { hideSelBar(); return; }
  if (domSelectionTimer) clearTimeout(domSelectionTimer);
  domSelectionTimer = setTimeout(() => {
    domSelectionTimer = 0;
    const domSel = window.getSelection();
    if (!domSel || domSel.rangeCount === 0 || domSel.isCollapsed) {
      // DOM 选区清空时，若 CM state 仍非空（例如手柄刚抬起前的瞬间），沿用 CM 选区
      const info = selectionInfo();
      if (info.empty) { hideSelBar(); return; }
      positionSelBar(info);
      return;
    }
    const range = domSel.getRangeAt(0);
    // 只处理落在 cm-content 内的选区，忽略页面其它输入框
    if (!view.contentDOM.contains(range.startContainer) || !view.contentDOM.contains(range.endContainer)) return;
    try {
      const from = view.posAtDOM(range.startContainer, range.startOffset);
      const to = view.posAtDOM(range.endContainer, range.endOffset);
      if (from == null || to == null || from === to) { hideSelBar(); return; }
      positionSelBar({ from, to, empty: false });
    } catch (_) {
      // 选区落在非文档节点（如 widget）时 posAtDOM 可能抛错，忽略即可
    }
  }, 16);
}

function scheduleSelectionEmit() {
  if (selectionEmitTimer) return;
  selectionEmitTimer = setTimeout(() => {
    selectionEmitTimer = 0;
    emitSelection();
  }, 16);
}

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

view = new EditorView({
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
        if (update.docChanged) {
          const b = bridge();
          if (b) {
            clearTimeout(window.__emit);
            window.__emit = setTimeout(() => {
              if (b.onChange) b.onChange(view.state.doc.toString());
            }, 120);
          }
        }
        if (update.selectionSet || update.docChanged) scheduleSelectionEmit();
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
      // 文档装载不是用户编辑，不能进入撤销历史；否则切文档后一次 undo 会灌回上一篇正文。
      annotations: Transaction.addToHistory.of(false),
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

  /** 选区真源：CM 位置区间（from/to）、是否空选区、选中文本。 */
  selection() { return JSON.stringify(selectionInfo()); },

  setSelection(from, to) {
    const max = view.state.doc.length;
    const a = Math.max(0, Math.min(Number(from) || 0, max));
    const b = Math.max(0, Math.min(Number(to) || a, max));
    view.dispatch({ selection: { anchor: a, head: b }, scrollIntoView: true });
    view.focus();
    return JSON.stringify(selectionInfo());
  },

  undo() { undo(view); view.focus(); return JSON.stringify(selectionInfo()); },
  redo() { redo(view); view.focus(); return JSON.stringify(selectionInfo()); },
  undoDepth() { return undoDepth(view.state); },
  redoDepth() { return redoDepth(view.state); },
  selectAll() { selectAll(view); view.focus(); return JSON.stringify(selectionInfo()); },

  copySelection() {
    const text = selectionInfo().text;
    if (text) bridge()?.copy?.(text);
    view.focus();
    return text.length;
  },

  cutSelection() {
    const info = selectionInfo();
    if (info.empty) return 0;
    bridge()?.copy?.(info.text);
    view.dispatch({
      changes: { from: info.from, to: info.to, insert: "" },
      selection: { anchor: info.from },
    });
    view.focus();
    return info.text.length;
  },

  /** 粘贴必须走宿主剪贴板：JS 侧无可靠读取权限。 */
  pasteSelection() { bridge()?.onAction?.("paste"); return "async"; },

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

// 选区操作条（R54 改为四按钮：复制/剪切/粘贴/全选；撤销重做移入编辑栏）。
if (selbar) {
  selbar.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const btn = ev.target.closest("button[data-sel]");
    if (!btn) return;
    const act = btn.dataset.sel;
    if (act === "copy") window.NativeEditor.copySelection();
    else if (act === "cut") window.NativeEditor.cutSelection();
    else if (act === "paste") window.NativeEditor.pasteSelection();
    else if (act === "selectAll") window.NativeEditor.selectAll();
    scheduleSelectionEmit();
  });
}
if (scroller) scroller.addEventListener("scroll", () => scheduleSelectionEmit(), { passive: true });
window.addEventListener("resize", () => scheduleSelectionEmit(), { passive: true });
// R53：原生手柄拖选的兜底路径——CM 的 updateListener 未必触发时，靠 DOM 选区驱动浮栏。
document.addEventListener("selectionchange", onDomSelectionChange, { passive: true });

// ---------------------------------------------------------------- 编辑栏（R54：Obsidian 移动端同款）
const toolbar = document.getElementById("toolbar");
const handleA = document.getElementById("handle-a");
const handleB = document.getElementById("handle-b");

/** 编辑栏可见性 + 撤销/重做置灰：无覆盖层、查找条收起时显示；深度为 0 时禁用。 */
function syncToolbar() {
  if (!toolbar || !view) return;
  const show = !overlaysVisible() && findbar.hidden;
  toolbar.hidden = !show;
  if (!show) return;
  const u = toolbar.querySelector('[data-tb="undo"]');
  const r = toolbar.querySelector('[data-tb="redo"]');
  if (u) u.disabled = undoDepth(view.state) === 0;
  if (r) r.disabled = redoDepth(view.state) === 0;
}

/** 包裹/取消包裹（对称）：选区内已含语法对 → 取消；选区两侧紧邻语法对 → 剔除；否则包裹。 */
function toggleWrap(mark) {
  const sel = view.state.selection.main;
  const text = view.state.sliceDoc(sel.from, sel.to);
  const m = mark.length;
  if (text.length >= m * 2 && text.startsWith(mark) && text.endsWith(mark)) {
    const inner = text.slice(m, text.length - m);
    view.dispatch({
      changes: { from: sel.from, to: sel.to, insert: inner },
      selection: { anchor: sel.from, head: sel.from + inner.length },
      scrollIntoView: true,
    });
    return;
  }
  const before = view.state.sliceDoc(Math.max(0, sel.from - m), sel.from);
  const after = view.state.sliceDoc(sel.to, Math.min(view.state.doc.length, sel.to + m));
  if (before === mark && after === mark) {
    view.dispatch({
      changes: [
        { from: sel.from - m, to: sel.from, insert: "" },
        { from: sel.to, to: sel.to + m, insert: "" },
      ],
      selection: { anchor: sel.from - m, head: sel.to - m },
      scrollIntoView: true,
    });
    return;
  }
  view.dispatch({
    changes: { from: sel.from, to: sel.to, insert: mark + text + mark },
    selection: { anchor: sel.from + m, head: sel.from + m + text.length },
    scrollIntoView: true,
  });
  view.focus();
}

/** 标题循环：无标题 → 设级；已是该级 → 取消；其它级 → 改为该级。 */
function toggleHeading(level) {
  const sel = view.state.selection.main;
  const line = view.state.doc.lineAt(sel.head);
  const m = /^(#{1,6})(\s+|$)/.exec(line.text);
  let changes;
  let anchor;
  if (m && m[1].length === level) {
    changes = { from: line.from, to: line.from + m[0].length, insert: "" };
    anchor = line.from;
  } else if (m) {
    changes = { from: line.from, to: line.from + m[0].length, insert: "#".repeat(level) + " " };
    anchor = line.from;
  } else {
    const prefix = "#".repeat(level) + " ";
    changes = { from: line.from, to: line.from, insert: prefix };
    anchor = line.from + prefix.length;
  }
  view.dispatch({ changes, selection: { anchor }, scrollIntoView: true });
  view.focus();
}

/** 行级前缀切换（引用/无序/有序）：选区涉及行已全部带前缀 → 整体取消；否则逐行补前缀。 */
function toggleLines(matcher, prefixOf) {
  const sel = view.state.selection.main;
  const first = view.state.doc.lineAt(sel.from).number;
  const last = view.state.doc.lineAt(sel.to).number;
  const lines = [];
  for (let n = first; n <= last; n += 1) lines.push(view.state.doc.line(n));
  const matches = lines.map((l) => matcher(l.text));
  const allMatched = matches.every((m) => m);
  const changes = [];
  let num = 1;
  lines.forEach((line, i) => {
    if (allMatched) {
      changes.push({ from: line.from, to: line.from + matches[i][0].length, insert: "" });
    } else if (!matches[i]) {
      const prefix = prefixOf(num);
      if (prefix != null) {
        changes.push({ from: line.from, to: line.from, insert: prefix });
        num += 1;
      }
    }
  });
  if (!changes.length) return;
  view.dispatch({ changes, selection: { anchor: sel.from }, scrollIntoView: true });
  view.focus();
}

/** 待办三态：已是待办 → 去 [ ]；是无序列表 → 插入 [ ]；普通行 → 插入 - [ ]。 */
function toggleTask() {
  const sel = view.state.selection.main;
  const first = view.state.doc.lineAt(sel.from).number;
  const last = view.state.doc.lineAt(sel.to).number;
  const changes = [];
  for (let n = first; n <= last; n += 1) {
    const line = view.state.doc.line(n);
    const t = /^(\s*[-*]\s)\[([ xX])\]( ?)/.exec(line.text);
    const u = /^(\s*[-*]\s)/.exec(line.text);
    if (t) {
      changes.push({ from: line.from + t[1].length, to: line.from + t[1].length + 4, insert: "" });
    } else if (u) {
      changes.push({ from: line.from + u[0].length, to: line.from + u[0].length, insert: "[ ] " });
    } else {
      changes.push({ from: line.from, to: line.from, insert: "- [ ] " });
    }
  }
  view.dispatch({ changes, selection: { anchor: sel.from }, scrollIntoView: true });
  view.focus();
}

/** 链接：选中文字进 []，光标落在 () 内；无选区则光标落 [] 内。 */
function insertLink() {
  const sel = view.state.selection.main;
  const text = view.state.sliceDoc(sel.from, sel.to);
  view.dispatch({
    changes: { from: sel.from, to: sel.to, insert: `[${text}]()` },
    selection: { anchor: sel.from + (text ? text.length + 3 : 1) },
    scrollIntoView: true,
  });
  view.focus();
}

/** 代码块：多行选区整体包裹；否则插入空围栏，光标居中。 */
function insertCodeBlock() {
  const sel = view.state.selection.main;
  const text = view.state.sliceDoc(sel.from, sel.to);
  if (text && text.includes("\n")) {
    view.dispatch({
      changes: { from: sel.from, to: sel.to, insert: "```\n" + text + "\n```" },
      selection: { anchor: sel.from + 3 },
      scrollIntoView: true,
    });
  } else {
    view.dispatch({
      changes: { from: sel.from, to: sel.to, insert: "```\n\n```" },
      selection: { anchor: sel.from + 4 },
      scrollIntoView: true,
    });
  }
  view.focus();
}

function toolbarAct(id) {
  if (!view) return;
  switch (id) {
    case "undo": window.NativeEditor.undo(); break;
    case "redo": window.NativeEditor.redo(); break;
    case "h1": toggleHeading(1); break;
    case "h2": toggleHeading(2); break;
    case "h3": toggleHeading(3); break;
    case "bold": toggleWrap("**"); break;
    case "italic": toggleWrap("*"); break;
    case "strike": toggleWrap("~~"); break;
    case "hl": toggleWrap("=="); break;
    case "icode": toggleWrap("`"); break;
    case "quote": toggleLines((t) => /^(\s*> ?)/.exec(t), () => "> "); break;
    case "ul": toggleLines((t) => /^(\s*[-*]\s)/.exec(t), () => "- "); break;
    case "ol": toggleLines((t) => /^(\s*\d+\.\s)/.exec(t), (n) => `${n}. `); break;
    case "task": toggleTask(); break;
    case "link": insertLink(); break;
    case "cblock": insertCodeBlock(); break;
    default: break;
  }
  syncToolbar(); // 立即刷新撤销/重做置灰态，不等 16ms 防抖
  scheduleSelectionEmit();
}

if (toolbar) {
  toolbar.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const btn = ev.target.closest("button[data-tb]");
    if (!btn || btn.disabled) return;
    toolbarAct(btn.dataset.tb);
  });
}
window.NativeEditor.toolbarAct = toolbarAct;

// ---------------------------------------------- 长按选词与自绘手柄（R54，2A 完全接管）
// 系统文本选择已被 user-select:none 禁用（editor.css），此处是唯一选择路径：
// 长按 500ms 选词；双击选词；拖手柄字符级微调；选区变化驱动操作条与手柄定位。
let lpTimer = 0;
let lpStart = null;
let dragHandle = null;
let lastTap = 0;
let lastTapX = 0;
let lastTapY = 0;

function selectWordAt(x, y) {
  const pos = view.posAtCoords({ x, y });
  if (pos == null) return false;
  const w = view.state.wordAt(pos);
  if (w && w.from !== w.to) view.dispatch({ selection: { anchor: w.from, head: w.to }, scrollIntoView: true });
  else view.dispatch({ selection: { anchor: pos, head: Math.min(pos + 1, view.state.doc.length) }, scrollIntoView: true });
  return true;
}

function hideHandles() {
  if (handleA) handleA.style.display = "none";
  if (handleB) handleB.style.display = "none";
}

function updateHandles() {
  if (!handleA || !handleB || !view) return;
  const info = selectionInfo();
  if (info.empty || overlaysVisible()) { hideHandles(); return; }
  const a = view.coordsAtPos(info.from, 1);
  const b = view.coordsAtPos(info.to, -1);
  if (!a || !b) { hideHandles(); return; }
  handleA.style.display = "block";
  handleA.style.left = `${Math.max(0, Math.round(a.left - 24))}px`;
  handleA.style.top = `${Math.round(a.bottom)}px`;
  handleB.style.display = "block";
  handleB.style.left = `${Math.min(window.innerWidth - 24, Math.round(b.right))}px`;
  handleB.style.top = `${Math.round(b.bottom)}px`;
}

function onEditorTouchStart(ev) {
  if (overlaysVisible()) return;
  const t = ev.touches[0];
  if (!t) return;
  lpStart = { x: t.clientX, y: t.clientY };
  clearTimeout(lpTimer);
  lpTimer = setTimeout(() => {
    lpTimer = 0;
    if (!lpStart) return;
    if (selectWordAt(lpStart.x, lpStart.y)) scheduleSelectionEmit();
    lpStart = null;
  }, 500);
}

function onEditorTouchMove(ev) {
  if (!dragHandle) {
    if (lpTimer && lpStart) {
      const t = ev.touches[0];
      if (t && (Math.abs(t.clientX - lpStart.x) > 10 || Math.abs(t.clientY - lpStart.y) > 10)) {
        clearTimeout(lpTimer);
        lpTimer = 0;
        lpStart = null;
      }
    }
    return;
  }
  ev.preventDefault(); // 拖手柄期间锁定滚动
  const t = ev.touches[0];
  if (!t) return;
  const pos = view.posAtCoords({ x: t.clientX, y: t.clientY }, true);
  if (pos == null) return;
  const sel = view.state.selection.main;
  if (dragHandle === "a") view.dispatch({ selection: { anchor: pos, head: sel.head }, scrollIntoView: true });
  else view.dispatch({ selection: { anchor: sel.anchor, head: pos }, scrollIntoView: true });
}

function onEditorTouchEnd(ev) {
  clearTimeout(lpTimer);
  lpTimer = 0;
  lpStart = null;
  dragHandle = null;
  // 双击选词（自实现，不依赖原生 dblclick）
  const t = ev.changedTouches[0];
  if (t) {
    const now = performance.now();
    if (now - lastTap < 300 && Math.abs(t.clientX - lastTapX) < 30 && Math.abs(t.clientY - lastTapY) < 30) {
      lastTap = 0;
      setTimeout(() => {
        if (selectWordAt(t.clientX, t.clientY)) scheduleSelectionEmit();
      }, 0);
    } else {
      lastTap = now;
      lastTapX = t.clientX;
      lastTapY = t.clientY;
    }
  }
}

if (view.contentDOM) {
  view.contentDOM.addEventListener("touchstart", onEditorTouchStart, { passive: true });
  view.contentDOM.addEventListener("touchmove", onEditorTouchMove, { passive: false });
  view.contentDOM.addEventListener("touchend", onEditorTouchEnd, { passive: true });
  // 部分 ROM 的长按会触发 contextmenu（系统菜单入口），直接禁掉
  view.contentDOM.addEventListener("contextmenu", (ev) => ev.preventDefault());
}
[["handle-a", "a"], ["handle-b", "b"]].forEach(([id, kind]) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("touchstart", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragHandle = kind;
  }, { passive: false });
  el.addEventListener("touchend", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragHandle = null;
  }, { passive: false });
});

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
  hideSelBar();
  if (typeof hideHandles === "function") hideHandles();
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
  if (t.closest("#bar") || t.closest("#crumb") || t.closest("#selbar")) return;
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
    annotations: Transaction.addToHistory.of(false),
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
          annotations: Transaction.addToHistory.of(false),
        });
        metrics("selfCheck", JSON.stringify(out));
        bridge()?.onMetric?.("selfCheck", JSON.stringify(out));
      }, GAP);
    }, GAP);
  }, GAP);
  return "async";
};
/**
 * R54 自检：编辑栏逐动作（包裹/取消对称、标题循环、列表/待办）、长按选词、手柄拖动、
 * 选区操作条四按钮。宿主用 `--es runAction selfCheckEdit` 触发，结果走 metric 上报。
 */
window.NativeEditor.selfCheckEdit = () => {
  const out = {};
  const saved = view.state.doc.toString();
  const GAP = 620;
  window.NativeEditor.setDoc("alpha beta gamma");
  out.historyClean = undoDepth(view.state) === 0;
  setTimeout(() => {
    const tb = document.getElementById("toolbar");
    out.toolbarVisible = !!tb && !tb.hidden;
    const undoBtn = tb && tb.querySelector('[data-tb="undo"]');
    const redoBtn = tb && tb.querySelector('[data-tb="redo"]');
    out.undoBtnDisabled = !!undoBtn && undoBtn.disabled === true;
    window.NativeEditor.toolbarAct("bold");
    out.boldInsert = view.state.doc.toString() === "****alpha beta gamma";
    // 刚编辑后 redo 栈为空（redo 在 undo 之后才有意义），断言撤销按钮点亮
    out.undoBtnEnabledAfterEdit = !!undoBtn && undoBtn.disabled === false;
    window.NativeEditor.toolbarAct("undo");
    out.toolbarUndo = view.state.doc.toString() === "alpha beta gamma";
    setTimeout(() => {
      window.NativeEditor.setSelection(0, 5);
      window.NativeEditor.toolbarAct("bold");
      out.boldWrap = view.state.doc.toString() === "**alpha** beta gamma";
      window.NativeEditor.toolbarAct("bold");
      out.boldUnwrap = view.state.doc.toString() === "alpha beta gamma";
      setTimeout(() => {
        window.NativeEditor.setSelection(0, 0);
        window.NativeEditor.toolbarAct("h1");
        out.h1 = view.state.doc.toString() === "# alpha beta gamma";
        window.NativeEditor.toolbarAct("h2");
        out.h2 = view.state.doc.toString() === "## alpha beta gamma";
        window.NativeEditor.toolbarAct("h1");
        out.h1Again = view.state.doc.toString() === "# alpha beta gamma";
        window.NativeEditor.toolbarAct("h1");
        out.h1Cancel = view.state.doc.toString() === "alpha beta gamma";
        setTimeout(() => {
          window.NativeEditor.toolbarAct("ul");
          out.ul = view.state.doc.toString() === "- alpha beta gamma";
          window.NativeEditor.toolbarAct("task");
          out.taskOnUl = view.state.doc.toString() === "- [ ] alpha beta gamma";
          window.NativeEditor.toolbarAct("task");
          out.taskOff = view.state.doc.toString() === "- alpha beta gamma";
          window.NativeEditor.toolbarAct("ul");
          out.ulCancel = view.state.doc.toString() === "alpha beta gamma";
          setTimeout(() => {
            // 长按选词：合成 touchstart 后保持按下（不发 touchend，否则会取消长按定时器），
            // 等待 500ms 定时器触发选词后再断言，与真实手指长按一致。
            try {
              const lineDom = view.contentDOM.querySelector(".cm-line");
              const rect = lineDom.getBoundingClientRect();
              const touch = new Touch({
                identifier: 1, target: view.contentDOM,
                clientX: rect.left + 20, clientY: rect.top + rect.height / 2,
              });
              view.contentDOM.dispatchEvent(new TouchEvent("touchstart", {
                touches: [touch], targetTouches: [touch], changedTouches: [touch],
                bubbles: true, cancelable: true,
              }));
              setTimeout(() => {
                view.contentDOM.dispatchEvent(new TouchEvent("touchend", {
                  touches: [], targetTouches: [],
                  changedTouches: [new Touch({
                    identifier: 1, target: view.contentDOM,
                    clientX: rect.left + 20, clientY: rect.top + rect.height / 2,
                  })],
                  bubbles: true, cancelable: true,
                }));
              }, GAP - 60);
            } catch (_) { out.touchSynth = false; }
            setTimeout(() => {
              out.longPressWord = JSON.parse(window.NativeEditor.selection()).text === "alpha";
              out.selbarFourButtons = !!selbar && !selbar.hidden && selbar.querySelectorAll("button").length === 4;
              setTimeout(() => {
                // 手柄拖动：handle-b touchstart → contentDOM touchmove → touchend
                try {
                  const lineDom = view.contentDOM.querySelector(".cm-line");
                  const rect = lineDom.getBoundingClientRect();
                  const hb = document.getElementById("handle-b");
                  const down = new Touch({ identifier: 2, target: hb, clientX: rect.left + 42, clientY: rect.top + rect.height / 2 });
                  hb.dispatchEvent(new TouchEvent("touchstart", {
                    touches: [down], targetTouches: [down], changedTouches: [down],
                    bubbles: true, cancelable: true,
                  }));
                  window.NativeEditor.setSelection(0, 5); // 复位为 alpha 选区再拖
                  const move = new Touch({ identifier: 2, target: view.contentDOM, clientX: rect.left + 60, clientY: rect.top + rect.height / 2 });
                  view.contentDOM.dispatchEvent(new TouchEvent("touchmove", {
                    touches: [move], targetTouches: [move], changedTouches: [move],
                    bubbles: true, cancelable: true,
                  }));
                  const up = new Touch({ identifier: 2, target: hb, clientX: rect.left + 60, clientY: rect.top + rect.height / 2 });
                  hb.dispatchEvent(new TouchEvent("touchend", {
                    touches: [], targetTouches: [], changedTouches: [up],
                    bubbles: true, cancelable: true,
                  }));
                } catch (_) { out.handleSynth = false; }
                setTimeout(() => {
                  const sel = JSON.parse(window.NativeEditor.selection());
                  out.handleDrag = sel.text.startsWith("alpha") && sel.text.length > 5;
                  out.handlesVisible = !!handleA && handleA.style.display === "block" && !!handleB && handleB.style.display === "block";
                  window.NativeEditor.setDoc(saved);
                  bridge()?.onMetric?.("selfCheckEdit", JSON.stringify(out));
                }, 60);
              }, GAP); // 长按 500ms + 余量
            }, GAP);
          }, GAP);
        }, GAP);
      }, GAP);
    }, GAP);
  }, 50);
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


