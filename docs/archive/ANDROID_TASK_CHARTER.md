# Android 版后续任务立项书（Task Charter）

> 版本基线：0.7.22（versionCode 34，T1/T2/T3 三项全部落地；立项于 0.7.19/31）。立项目期：2026-11-20。
> 状态：**T1/T2 已于 R31（v0.7.21）交付，T3 已于 R32（v0.7.22）交付，三项立项全部完成**。本文件保留任务拆解与立项依据，与记录历史轮次的 `ANDROID_STAGE_STATUS.md` 分开维护。
> 范围：本轮立项三项——#2 编辑器/预览内切换文档按钮、#1a 代码块 Copy 按钮、#1b My folders 页。三项均属 P2 之后的功能增量，不改变 M1 十一条任务线取值。
> 事实来源：2026-11-20 三路只读代码探查（编辑器桥接 / 预览渲染 / 文件夹数据层），每条结论均带 `文件:行号` 证据。

---

## 0. 立项总览

| 编号 | 任务 | 优先级 | 预估人日 | 依赖 | 风险 | 建议批次 |
| ---- | ---- | ------ | -------- | ---- | ---- | -------- |
| T1 | #2 编辑器/预览内切换文档按钮 | P1 | 1.5–2 | 无（含子项 T1a/T1b） | 中（竞态 + 构建产物覆盖） | 批次一（与 T2 同版本） |
| T2 | #1a 代码块 Copy 按钮 | P2 | 0.5 | 无 | 低 | 批次一（与 T1 同版本） |
| T3 | #1b My folders 页 | P2 | 1.5–2 | 无（数据层已就绪） | 中（产品语义待定） | 批次二（独立版本） |

- **建议出包策略**：T1 + T2 合并为一个版本（均改预览/编辑器 UI，一次门禁一次出包）；T3 语义需先拍板，独立成版。每批按发版规范出带版本号 release 并走 P4 门禁。
- **共同前置**：三项开工前都不需要版本归因；但 T1 涉及编辑器 assets 重建，必须先核对产物是否被手工改过（见 T1-R1）。

---

## T1 (#2)：编辑器 / 预览内切换文档按钮

### T1-目标
用户在编辑器页或预览页阅读某篇文档时，无需返回主页即可切到上一篇/下一篇文档（或从文档下拉直接选），切换过程不丢未落盘正文、不发生 A/B 串内容、不错位。

### T1-现状事实（探查证据）
1. **切换内核已存在**：`activate(id)`（`MainActivity.kt:1253-1269`）已实现「取 doc → 设 activeId → 若 `editorOpen` 则 `setDocument` 回灌 → 设 revision → 写 ACTIVE_DOC」。
2. **NEXT_TAB 已有但只在物理键盘链路**：`dispatchKeyEvent`（`:1452-1482`）→ `Shortcuts.resolve`（`domain/keys/Shortcuts.kt:32`）→ `runShortcut` 的 NEXT_TAB 分支（`:1496-1503`，取 `docs.value` 算 `(idx+1).mod(size)` 后 `launch { activate(next.id) }`）。
3. **PREV_TAB 完全不存在**：`KeyAction` 枚举无此项（`Shortcuts.kt:9-12`），无 Shift+TAB 映射，`onEditorAction` 无对应字符串，JS keymap 也无 Mod-Tab（但帮助文案写了 Ctrl+Tab——`index.template.html:101`，属文档与实现不一致）。
4. **编辑器 JS 桥单入口**：JS → Kotlin 走 `window.AndroidEditor.onAction(action: String)`（`EditorHost.kt:114-117`、`editor.js:32,345,484`）；动作表真源 `EditorActions.kt:19-40`，经 `pushActions()`（`EditorHost.kt:221-233`）下发；`onEditorAction` 分发在 `MainActivity.kt:507-566`。已支持 new/close/preview/saveAs/openFile/save/split 等约 19 个 action。
5. **编辑器顶栏挂载点**：`tools/editor/src/index.template.html:9-48`（`#bar` 六个 `data-act` 按钮 + `#moremenu`），点击自动经 `editor.js:345` 走 `onAction`，**新增 `data-act` 按钮无需改 JS 点击逻辑**。
6. **预览页不认识文档列表**：`PreviewScreen`（`platform/PreviewScreen.kt:31-39`）是 LinearLayout + WebView，**构造参数仅 context/assetsDir/onClose/onToggleTheme**，无 activeId、无文档列表、无切换回调；顶栏 `paintBar()`（`:147-181`）只有 BACK/标题/大纲/主题/PDF/CLOSE，图标来自 `PanelIconView.Kind`（`:20,44-50,79-85`），无上下篇图标。
7. **预览切换需重置同步状态**：`ScrollSync.attach()` 仅在 host 变化时清位置状态（`ScrollSync.kt:31-39`），同一 WebView 换文档会残留旧位置；`gsRender` 的 `keep = window.scrollY`（`PreviewHost.kt:152,167`）会保留滚动；`PreviewScreen.lastScrollY`（`:49,55`）需清零。

### T1-风险点
- **T1-R1（构建产物覆盖）**：`app/src/main/assets/editor/index.html`（2026-11-20 16:02）晚于模板源码 `tools/editor/src/index.template.html`（11-19 16:42），说明产物被手工改过。改编辑器 UI 后执行 `npm run build`（`tools/editor/build.mjs`）会**覆盖这些手工改动**——开工第一步必须 `diff` 产物与模板重建结果，确认手工差异内容并决定是回灌模板还是保留。
- **T1-R2（丢草稿）**：现有 NEXT_TAB 与 `reload()/activate()` 切换前**不调用 `flushEditor()`**（`flushEditor` 在 `:499-505`），未落盘内容依赖 300ms 防抖 + draftJournal 兜底，快速连点有覆盖风险。
- **T1-R3（竞态）**：`editorEpoch`（`:224`）只保护 openEditor/closeEditor，`activate` 自身无 epoch 防护；异步切换可能与开关编辑器竞态（R20 已定根 A/B 串内容）。
- **T1-R4（动作表漂移）**：新增 action 若不同步 `EditorActions.kt` 与 `onEditorAction`，命令面板与按钮行为不一致（现存 `replace` 在表中却无分支，即先例）。
- **T1-R5（预览入口适配）**：`PreviewActivity.kt:33` 是独立入口（外部 intent 拉起），必须一并适配切换回调，否则外部预览页按钮无响应。

### T1-任务拆解
| 子项 | 内容 | 改动面 | 验收 |
| ---- | ---- | ------ | ---- |
| T1-1 统一切换内核（含 flush + epoch 保护） | 抽 `switchDocument(targetId)`：先 `flushEditor()` → 捕获/校验 `editorEpoch` → `activate(id)` → 预览态则重置 ScrollSync/滚动；NEXT_TAB 与新增 PREV_TAB 都改走它 | `MainActivity.kt`（`:496-566,1244-1269,1452-1518`） | 切换前未落盘内容入库；快速连点不串内容 |
| T1-2 补齐 PREV_TAB | `KeyAction` 枚举 + Shift+TAB 映射 + `runShortcut` 分支；修正帮助文案 | `Shortcuts.kt:9-39`、`MainActivity.kt:1486-1518`、`index.template.html:101` | Ctrl+TAB / Ctrl+Shift+TAB 双向循环正确 |
| T1-3 编辑器页内按钮 | `#bar` 加 `data-act="prevDoc"/"nextDoc"` 按钮（或仿 `#moremenu` 的文档下拉）；`EditorActions` 补条目 + `onEditorAction` 补分支；若做下拉需新增 `NativeEditor.setDocs(json)` 下发 | `index.template.html:9-48`、`editor.css`、`EditorActions.kt:19-40`、`EditorHost.kt:221-233`、`MainActivity.kt:507-566` | 页内按钮/下拉可切换，命令面板可检索 |
| T1-4 预览页内按钮 | `PreviewScreen` 构造加切换回调；`paintBar()` 加按钮或 Spinner；`enterPreview()` 注入回调、传 activeId；切换后 `detach→attach` ScrollSync + `scrollTo(0)` + `lastScrollY=0` | `PreviewScreen.kt:31-181`、`PanelIconView.kt:20,44-50,79-85`、`MainActivity.kt:657-701`、`PreviewActivity.kt:33` | 预览页切换后从顶部起、滚动同步正确对齐 |
| T1-5 assets 重建 + 差异核对 | 先 diff 手工改动，回灌模板后 `npm run build` 重新生成 assets | `tools/editor/src/*` → `app/src/main/assets/editor/*` | 产物含新按钮且不丢既有手工改动 |
| T1-6 测试 | JVM 测切换目标索引计算（纯逻辑，仿 NEXT_TAB 的 mod 算法）；仪器测试测按钮可见/可点（若 panel 焦点允许） | `app/src/test/`、`app/src/androidTest/` | 单测绿；仪器测试尽力覆盖 |

### T1-完成判据（Definition of Done）
编辑器页与预览页均有可见切换控件；页内按钮、下拉（若做）、物理快捷键三入口行为一致；切换不丢草稿、不串内容、不错位；帮助文案与实现一致；P4 门禁全绿 + release 出包。

---

## T2 (#1a)：代码块 Copy 按钮

### T2-目标
预览页渲染的围栏代码块上出现「Copy」按钮，点击复制该代码块纯文本并给出反馈；mermaid 图不出现无意义 Copy；PDF/主题重渲染后按钮不重复叠加。

### T2-现状事实（探查证据）
1. **渲染是 JS 运行时完成**：`renderMarkdown()`（`PreviewHost.kt:350-375`）用 `MarkdownSanitizer.clean()` 清洗副本 → `evaluateJavascript("window.gsRender(...)")`（`:377-383`）；真正渲染在 shell 内嵌 JS `window.gsRender` 的 `content.innerHTML = md.render(source)`（`PreviewHost.kt:153`），引擎是 markdown-it（vendor 引入 `:91`）。
2. **注入点在 shell JS**：Kotlin 不拼代码块 HTML，Copy 按钮须在 `gsRender` 的 `innerHTML` 赋值后（`PreviewHost.kt:149-169`）对 `pre` 做 DOM 后处理；样式加在同一 shell 的 `<style>`（`:47-78`）。
3. **mermaid 需跳过**：`renderMermaid()`（`PreviewHost.kt:136-147`）把 `code.language-mermaid` 换成 `div.mermaid`，注入逻辑应只处理仍在的 `pre`。
4. **剪贴板无现成封装**：全 `app/src/main/java` 无 `ClipboardManager/setPrimaryClip/ClipData`；预览 WebView 桥对象是 `"gscratchpad"`（`PreviewHost.kt:311-320`），目前仅 `@JavascriptInterface postMessage()`（`:312-319`）。
5. **navigator.clipboard 不可用**：PreviewHost 未设 WebChromeClient（对比 `EditorHost.kt:137-141`），无权限授权，纯 JS 方案不可靠。
6. **桌面版无此按钮**：桌面预览用 Python-Markdown + codehilite（`markdown_render.py:116-126`），无 Copy（剪贴板只用于侧栏复制路径）——确认为**纯新功能**。

### T2-风险点
- **T2-R1（重复叠加）**：PDF 导出会临时 `pdfDark` 重渲染再恢复（`PreviewScreen.kt:168-179`），主题切换也重渲染；注入必须幂等（先移除旧按钮或用标记 class）。
- **T2-R2（内容边界）**：复制应取 `code.textContent`（纯代码，不含按钮文字）；转义字符/CJK 需保真。
- **T2-R3（无高亮）**：当前代码块无语法高亮（无 highlight.js/prism 资源），Copy 按钮样式需适配现有 `pre/code` 底色（`PreviewHost.kt:52-53`）。

### T2-任务拆解
| 子项 | 内容 | 改动面 | 验收 |
| ---- | ---- | ------ | ---- |
| T2-1 桥方法 | 在 `"gscratchpad"` 桥对象新增 `@JavascriptInterface copyText(text)`，调 `ClipboardManager.setPrimaryClip` + toast 反馈 | `PreviewHost.kt:311-320`（+ import） | JS 可调、剪贴板内容正确 |
| T2-2 DOM 注入 | `gsRender` 内给每个 `pre` 插入 Copy 按钮（幂等 + 跳过 mermaid），点击取 `code.textContent` 调 `window.gscratchpad.copyText` | `PreviewHost.kt:149-169` | 普通/带 language 围栏均有按钮，mermaid 无 |
| T2-3 样式 | shell `<style>` 加按钮样式（右上角、小号、跟随主题） | `PreviewHost.kt:47-78` | 深浅主题可读、不遮挡代码 |
| T2-4 验证 | 重渲染/主题切换/PDF 后按钮不重复；模拟器 + 真机手动回归 | — | 幂等性通过 |

### T2-完成判据
代码块 Copy 按钮可用、复制内容保真、mermaid 跳过、重渲染幂等、P4 门禁绿 + 随 T1 同版本出包。

---

## T3 (#1b)：My folders 页

### T3-目标
主页提供文件夹视图：按文件夹（含「未归档」虚拟组）分组展示文档，支持新建/重命名/删除文件夹、把文档移入/移出文件夹；删除文件夹时文档回未归档、不删正文。

### T3-关键澄清：数据层已就绪，缺口在 UI 与语义
探查证实 folder 的 CRUD **五方法全部存在**（原立项描述以为缺失，需修正认知）：
- `Document.folder: String = ""`（`domain/model/Document.kt:37`）+ 独立 `Folder` 模型（`:80`）；schema 有 `documents.folder` 列与独立 `folders` 表（`data/Schema.kt:18,26-29`，v2→v3 迁移 `:59-68`）。
- Repository 五方法（`data/DocumentRepository.kt:52-56,208-234`）：`folders()`/`createFolder()`/`renameFolder()`/`deleteFolder()`/`moveToFolder()`——语义完整（删除回未归档、重命名带文档迁移事务）。
- DAO 读侧齐（`data/DocumentDao.kt:69-88`）：`folders()`/`folderCounts()`/`documentsByFolder()`/`docFolderOf()`；写侧 `setFolder()` 自动建目录行（`:159-169`）。
- **真正缺口**：① Repository 未暴露 `documentsInFolder()`/计数（DAO 有但 UI 拿不到）；② `folders()` 丢弃 createdAt 且非 Flow（`:208-210`），folder 变更后 UI 不会自动刷新；③ 名称校验弱（仅 trim+非空，`:213-214,220-221`，桌面版 `_clean_name` 有 ≤60 字/无斜杠限制）；④ `renameFolder` 撞名静默合并（`:219-224`）；⑤ 主页未订阅 Flow，操作后须手动 `reload()`。

### T3-现状事实（主页 UI）
- 主页纯 Compose 单文件（`MainActivity.kt:1738-1942`），**无 Scaffold/TopAppBar/NavHost**，靠布尔状态导航（如 `settingsOpen` `:1691`）；列表用 `Column + verticalScroll`（`:1842-1942`）而非 LazyColumn。
- 「最近/全部」不是 SegmentPill 而是两个 `Text + clickable`（`:1804-1823`），过滤在 UI 层 `visibleDocs = if (showAll) … else filter { !it.recentHidden }`（`:1798`）。
- 文档行 UI 内联在 `:1856-1932`，可抽成 `@Composable DocRow` 供文件夹视图复用。
- 顶栏 `Row`（`:1741-1765`）右侧已有设置图标 + 明暗切换，是文件夹入口的自然挂载点；或把「最近/全部」扩成三态。

### T3-风险点
- **T3-R1（语义待定）**：renameFolder 撞名是静默合并还是拒绝提示、文件夹视图是否显示「已清除记录」文档（`recentHidden` 与 folder 正交）、移动交互用长按菜单还是拖拽——需产品拍板后才能定 UI。
- **T3-R2（校验不对等）**：Android 名称校验弱于桌面，导入路径也绕过校验，需抽纯 policy 统一。
- **T3-R3（刷新）**：folder 操作后必须显式 `reload()`（主页未订阅 Flow），否则列表不更新。
- **T3-R4（单文件膨胀）**：主页已 2404 行且用非惰性列表，新增文件夹视图会进一步膨胀；建议文件夹视图拆独立 Composable 文件。
- **T3-R5（测试空白）**：folders API 五个方法 JaCoCo 全 `missed`，JVM 单测零覆盖；语义复杂度在 SQL 事务（重命名合并、删除回退），须用真实 sqlite 测。

### T3-任务拆解
| 子项 | 内容 | 改动面 | 验收 |
| ---- | ---- | ------ | ---- |
| T3-0 语义拍板 | 定三件事：撞名策略、recentHidden 文档是否显示、移动交互形态 | 产品决策（不写代码） | 用户拍板记录入 OPEN_QUESTIONS |
| T3-1 数据层补强 | Repository 暴露 `documentsInFolder()/folderCounts()`；命名校验抽纯 policy（≤60 字、无 `/` `\`、trim）；定 rename 冲突策略 | `DocumentRepository.kt:52-56,208-234`（+ 可选 `FolderPolicy.kt`） | 单测覆盖校验与冲突 |
| T3-2 文件夹视图 UI | 主页加「文件夹」入口；独立 Composable 渲染分组列表（含未归档、计数、展开收起、空组占位）；抽 `DocRow` 复用 | `MainActivity.kt:1741-1942`（建议拆出新 Composable 文件） | 分组正确、可展开打开文档 |
| T3-3 文件夹操作 | 新建/重命名/删除对话框 + 删除确认文案（"笔记回到未归档、不删除"）；长按文档选目标文件夹移动 | `MainActivity.kt` + 新 Composable 文件 | 五操作正确、删除不丢正文 |
| T3-4 刷新链路 | 所有 folder 操作后显式 `reload()` 刷列表 | `MainActivity.kt` | 操作后列表即时更新 |
| T3-5 测试 | 新增 `FoldersRepositoryTest`（用现成 `TestHarness` + `runTest`，真实 sqlite 验证事务语义）；`FolderPolicy` 纯单测；仪器测试加入口可见性断言 | `app/src/test/`、`app/src/androidTest/` | 单测绿、覆盖 CRUD 与校验 |

### T3-完成判据
文件夹视图可分组浏览、五操作语义正确、删除不丢正文、命名校验生效、刷新即时、单测覆盖 folders API、P4 门禁绿 + 独立 release 出包。

---

## 立项决策记录（2026-11-20 R31 已拍板）

用户指令「Q6–Q9 按建议」，四项全部按建议执行，已记入 `ANDROID_OPEN_QUESTIONS.md`：

- **Q6（T3-R1）**：`renameFolder` 撞名 → **拒绝并提示**（不静默合并），与桌面版语义对齐。
- **Q7（T3-R1）**：文件夹视图 → **不显示** recentHidden 文档，与「最近」口径一致。
- **Q8（T3-R1）**：文档移入文件夹 → **长按菜单选目标文件夹**（不做拖拽）。
- **Q9（批次）**：**T1+T2 合并一版（v0.7.21）、T3 独立一版（v0.7.22）**。

## 变更记录
- 2026-11-20：立项，三路代码探查完成，T1/T2/T3 拆解成型。未开工、未改代码、未出包。
- 2026-11-20 R31：Q6–Q9 全部按建议拍板；T1+T2 开工并合并出 v0.7.21（含 OpenPolicy 白名单放宽）；T3 待后续独立批次。
- 2026-11-20 R32：T3 开工并独立出 v0.7.22——FolderPolicy 命名策略 + 撞名拒绝 + 数据层分组/计数 API + 独立 FoldersScreen 三态视图 + 五操作 + 自重命名 no-op 缺陷修复；FoldersRepositoryTest 10 条 + FolderPolicyTest 8 条，全量 128 单测。立项三项全部交付。
