# GNOME Scratchpad 功能测试报告

- 测试日期：2026-11-04
- 测试环境：Ubuntu 26.04.1 LTS（resolute），kernel 7.0.0-38-generic，x86_64
- Python 3.14.4（/usr/bin/python3），GTK4 4.22.4，libadwaita 1.9.1，GtkSourceView 5.18.0，WebKitGTK 6.0 2.52.6
- 测试方式：单元测试（unittest）+ 真实 GUI 自动化测试（`tests/gui_test.py`，在真实显示会话中启动应用、驱动缓冲区/界面并采集结果）+ 渲染取证（WebView 内 DOM 查询、PDF 反渲染为 PNG 人工核验）

## 1. 单元测试（23 项，全部通过）

```
$ /usr/bin/python3 -m unittest discover -s tests -p "test_*.py"
Ran 23 tests in 0.073s
OK
```

覆盖范围：
- store.py：创建/恢复、revision 单调性（旧快照丢弃）、关闭标签保留文档、排序、格式切换镜像、journal 崩溃恢复、字数统计、删除文档（含资源清理）
- markdown_render.py：标题/粗斜体、列表、表格、代码高亮、行内与块级公式、公式不被 Markdown 吃掉、代码块内不误判、Mermaid 块、HTML 净化（script 剥离、onclick 剥离、javascript: 链接拦截）、文档 HTML 仅含本地 file:// 资源、打印模式 A4 CSS
- assets.py：导入、SHA-256 去重、非法扩展名拒绝

## 2. GUI 自动化测试（10 项场景）

| # | 场景 | 命令 | 结果 |
| --- | --- | --- | --- |
| G1 | 写入 3 个标签并正常退出 | `write` | 通过。落库：首页笔记(txt)/数学笔记(md)/未命名(txt)，sort_index 0/1/2，revision 递增，notes/ 出现三个镜像文件 |
| G2 | SIGKILL 崩溃后恢复 | `write --kill` + `verify` | 通过。进程被 SIGKILL（exit 137），重启后 3 个标签、标题、格式、顺序、内容全部还原 |
| G3 | 重启恢复与活动标签 | `verify` | 通过。恢复内容与写入内容逐字一致，meta active_doc 命中 |
| G4 | 300ms 防抖自动落盘 | `autosave` | 通过。未显式 flush，输入后 500ms 数据库已含新内容：`"ok": true` |
| G5 | 关闭标签 = 关视图，文档保留、无弹窗 | `closetab` | 通过。`closed_docs_kept: 1`，内容完整，界面无任何保存提示 |
| G6 | Markdown 预览渲染 | `preview` | 通过。WebView DOM：`{"katex":2,"svgs":1}`（2 个公式 + 1 个 Mermaid SVG，无渲染错误文本） |
| G7 | 图片导入与显示 | `image` | 通过。生成 `assets/<docid>/fa3c8ce15afa.png`，插入 `![input](assets/<docid>/….png)`，预览 DOM `{"imgs":1,"loaded":[true]}` |
| G8 | PDF 导出 | `pdf` | 通过。输出 `%PDF-1.7`，pdftoppm 反渲染为 PNG 核验：A4 单页，标题/中文/行内公式 E=mc²/块级公式 Σ/Mermaid A→B/表格甲乙全部正常 |
| G9 | 查找与替换 | `find` | 通过。连续 4 次 find_next 依次选中 4 个「苹果」（跨行、含环绕），replace_all 全部替换为「水果」 |
| G10 | 深色主题预览 | `dark` | 通过。强制深色后预览 DOM `{"dark":true,"katex":1}`，配色随系统主题 |

## 3. 验收标准逐项核对

| # | 验收项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 启动应用后能直接输入 | 通过 | 无文档时自动创建空白标签，光标就绪（G1、G4） |
| 2 | 输入后无需手动保存 | 通过 | G4：不 flush 亦落盘 |
| 3 | 关闭标签页不弹保存提示 | 通过 | G5：无对话框，直接关闭 |
| 4 | 退出应用不弹保存提示 | 通过 | G1：close-request 中静默落盘后退出 |
| 5 | 重启后恢复全部标签页 | 通过 | G2/G3 |
| 6 | TXT 与 Markdown 内容正确恢复 | 通过 | G3：两种格式内容逐字一致 |
| 7 | 多标签页内容互不覆盖 | 通过 | G1/G3：三标签内容、标题、格式一一对应 |
| 8 | 公式和 Mermaid 正常渲染 | 通过 | G6：KaTeX 2、Mermaid SVG 1 |
| 9 | 图片导入后正常显示 | 通过 | G7：naturalWidth > 0 |
| 10 | PDF 导出结果正常 | 通过 | G8 + PNG 反渲染核验 |
| 11 | 强制终止后恢复最近一次持久化内容 | 通过 | G2（SIGKILL）+ 单元测试 journal 恢复用例 |
| 12 | 全部功能不依赖网络服务 | 通过 | 单元测试断言文档 HTML 无任何 http(s) 引用；KaTeX/Mermaid/markdown 均为本地文件；运行期无网络调用 |

## 4. 覆盖不足与已知限制（如实说明）

1. **真实键盘输入未自动化**：测试通过 TextBuffer API 驱动输入（等效于编辑内容），
   未模拟物理按键与输入法事件；快捷键（Ctrl+1…9、Ctrl+Tab 等）通过
   `application.ACCELS` 注册并映射到对应的 win.* 动作，动作为自动化测试中单独驱动
   验证，但未做物理按键级别的端到端模拟。
2. **PDF 为位图文字**：WebKitGTK 6.0 的 `WebKit.PrintOperation.print_()` 在无打印机
   环境实测报 "Printer not found"（已在开发过程中实测），无法用于纯导出；改用
   全文档 2x 快照 + A4 分页切片。排版/公式/图表/中文完整保留，但文字不可选中。
3. **分页切片不感知行边界**：快照切片按页面高度硬切，可能出现一行文字被切到两页
   之间的边缘情况；`page-break` CSS 仅对 WebKit 打印路径有效，对快照路径无效。
4. **标签拖拽排序**依赖 Adw.TabView 内建 DnD（已启用），自动化测试通过
   `_persist_order()` 驱动验证持久化逻辑，未做真实拖拽事件模拟。
5. 测试中曾出现的一次性告警（IBUS surrounding-text、WebProcess 名称释放）为
   Wayland 环境良性告警，不影响功能。

## 5. 结论

12 项验收标准全部通过。核心持久化链路（防抖自动保存 → 恢复日志 → SQLite WAL 提交 →
镜像文件）在正常退出、SIGKILL、提交中断（journal 回放）三种场景下均验证无数据丢失。

## 2026-11-05 修订（v1.0.0-1 重发）

| 问题 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- |
| 标签栏占据窗口一半高度 | `window.py` 给 `Adw.TabBar` 误设 `vexpand=True` | 移除该属性，标签栏恢复自然高度 | 实测 700px 窗口：tabbar=47px，tabview=552px |
| 实时预览不随输入更新 | 缓冲区 changed 事件未联动预览刷新（仅切模式时渲染一次） | editor.py 增加 150ms 防抖预览刷新（`_schedule_preview_refresh`） | 输入后 DOM 检查 `hasNew:true, bold:1`，公式/Mermaid 渲染计数不变 |
| 改名 gscratchpad | — | 应用 ID `io.github.gscratchpad.Gscratchpad`、包名/命令 `gscratchpad`、数据目录 `~/.local/share/gscratchpad`（含旧目录自动迁移） | 迁移测试：旧目录 gnome-scratchpad → gscratchpad，3 个文档完整恢复 |

## 2026-11-05 修订二（预览空白根因）

| 问题 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- |
| 预览区始终空白（真实窗口中） | `PreviewPane` 是垂直 Box，占位 Label 有 `vexpand`，替换后的 WebView 没有 → WebView 被分配高度 0。DOM 内容存在所以自动化 DOM 检查一直通过，但屏幕上什么都没画 | `_ensure_view()` 给 WebView 设置 `hexpand/vexpand` | 实测 `view: 539×552`，真实窗口截图确认标题/公式/表格/代码高亮/Mermaid 全部渲染 |
| 附带发现：`HardwareAccelerationPolicy.NEVER` | 在 WebKitGTK 2.52 上强制软件渲染导致 WebView 不绘制（独立对照实验确认） | 移除该设置，保持默认策略 | 对照截图：plain=正常渲染，never=空白 |
| 教训 | | | GUI 测试必须做像素级截图取证，仅 DOM/JS 检查无法发现布局尺寸为 0 的问题 |

## 2026-11-05 增量：本机文件打开 / 保存 / 拖放

| 功能 | 实现 | 验证 |
| --- | --- | --- |
| Ctrl+O 打开本机文件 | 文件选择器多选 → 每个文件一个新标签；按扩展名识别 txt/md（utf-8→gb18030 降级解码，含 NUL 判为二进制并提示）；同一文件重复打开时切换到既有标签而非重复创建 | openfile 测试：txt/md 双开、格式与内容一致、source_path 关联入库、不存在文件优雅跳过 |
| Ctrl+S 保存到本机文件 | 已关联 → 内容原子写回原文件；未关联 → 另存为对话框，保存后建立关联。内部自动保存链路完全不受影响 | savefile 测试：写回原文件内容逐字一致；另存写盘 + 重新关联成功；状态栏显示「已保存到 xxx」3 秒内不被自动保存状态覆盖 |
| 拖放本机文件 | 图片 → 导入 assets 并插入引用；.md/.txt 及常见文本 → 打开为新标签；未知扩展名探测 NUL 字节判型；二进制 → Toast 提示不打开 | dropfiles 测试：txt/md 双开、图片插入引用、二进制未打开 |

## 2026-11-05 修订三：拖放信号签名修复

| 问题 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- |
| 拖入文件即崩溃：`TypeError: EditorPage._on_drop() missing 1 required positional argument: '_data'` | GTK4 `DropTarget::drop` 信号回调签名为 `(target, value, x, y)` 四参，代码写成五参 | `_on_drop` 改为 4 参数 | 真实信号发射测试：构造 `Gdk.FileList` 后对视图上实际挂载的 DropTarget `emit("drop", fl, x, y)`，回调正常触发 |
| 之前测试未发现该 bug | 此前拖放测试全部直接调用内部方法（`import_images` / `handle_dropped_files`），从未走过真实 GTK 信号路径 | 新增真实信号发射测试（从 `observe_controllers()` 取实际控制器） | 信号路径：md/txt 各开一个新标签、二进制被拦截；一次 emit 即完成，无异常 |
| 附带发现：视图上共存 3 个 DropTarget（我们 1 个 + GtkTextView 内置 2 个），真实拖拽由我们的目标（格式 GdkFileList）优先接住 | | | target_formats 实测：GdkFileList（我们的）/ GdkRGBA / gchararray（内置文本目标，不响应文件拖拽） |
| IBUS-WARNING「no capability of surrounding-text feature」与 Gio g_variant_iter_loop 警告 | IBus 输入法环境下的常见无害警告，不影响功能 | 无需处理 | — |

## 2026-11-05 修订四：行号 / 折叠 / HTML 渲染 / 格式化 / 简繁转换 / Ctrl+F·H 修复

### Ctrl+F / Ctrl+H 不起作用的诊断过程

| 实验 | 结果 | 结论 |
| --- | --- | --- |
| action 注册检查 | `win.find`/`win.replace` 存在、enabled、加速键 `<Control>f/h` 已挂 | 注册层正常 |
| 程序化触发 `win.find` → 搜索栏展开、输入→查找→全部替换全链路 | 查找命中 2 次 "hello"、替换结果逐字正确 | 动作与搜索功能层完全正常 |
| **问题定位** | 坏的是「物理按键 → action」路由；焦点在 WebKit 预览或 IM 干扰时按键可能被吞 | 加速键链路不可靠 |
| 修复 | 双保险：① `SearchBar.set_key_capture_widget(view)` 标准接线；② 窗口顶层 capture 阶段 `EventControllerKey` 直调 `show_search()`，绕开 action muxer | 模拟调用 `_on_window_key(Ctrl+F/Ctrl+H)` 均返回 True 且搜索栏/替换行展开 |

### 折叠的技术选型（关键实验）

| 实验 | 结果 |
| --- | --- |
| GtkSourceView 5.18 typelib 全库搜索 "fold" | 无任何折叠 API（此前记忆有误） |
| GTK4 `GtkTextTag invisible=True` 隐藏 3 行后测 `get_line_yrange` | 布局高度不变（y 差值 68px）——invisible 不折叠布局行，此路不通 |
| 结论 | 真折叠只能"物理移除 + 影子恢复" |

### 折叠实现与安全不变量

- 被折叠文本存于 `Fold.chunk`，同时放置左重力 `GtkTextMark` 标记原位置——插入/删除/撤销由 GTK 自动平移 mark，无需手工行号修正
- 保存/预览/统计/PDF 一律走 `EditorPage.snapshot_text()` → `FoldEngine.expand_text()`（隐藏文本按 mark 位置拼回），**落盘永远是全文**
- 折叠/展开用 `begin_irreversible_action` 包裹，不污染撤销栈；`mutating` 标志使折叠变动不标记 dirty、不触发自动保存
- 搜索前自动全部展开（查找作用于全文）
- 策略：Markdown（标题层级 + 围栏代码块）/ 缩进块（Python、YAML 等）/ 括号深度（JSON、C 系）
- gutter 箭头列 `FoldGutter`（`do_query_data` 兼容 2 参/3 参两种 vfunc 调用形态——实测 GTK 会以两种形态调用）

### 功能验证结果（tests/test_tools_gui.py，13 项断言全过）

| 项 | 验证 |
| --- | --- |
| 行号 | `get_show_line_numbers() == True`，截图可见 |
| 折叠 | md/python/json 三策略 foldable 集合正确；折叠后行数减少、`snapshot_text()` 恒等于原文、unfold 后 buffer 逐字恢复；**像素截图取证**：折叠前第 1/5 行有 ▸，折叠后 ▾ 且函数体消失 |
| 折叠后字数 | 状态栏按全文计算（48 字符，非可见 28） |
| HTML 渲染 | 格式切 html → WebView 原文载入，DOM 检查 `<h1>你好 HTML</h1>`；打开 .html 文件自动 html 格式 + html 语法高亮 + base_uri 指向文件目录（相对资源可用） |
| 格式化 Ctrl+Shift+I | JSON 内容嗅探→排版成功；Python/Bash 优先系统 black/ruff/shfmt，缺失时 Toast 给出 `apt install` 提示（策略与用户确认一致） |
| 简繁转换 | 菜单「工具」两项，子进程调用系统 opencc；缺失时 Toast 提示且内容不变 |
| 持久化回归 | gui_test write→verify 三标签逐字恢复；preview 场景 KaTeX×2 + Mermaid SVG×1；find 场景查找替换正确 |

### 已知限制

- 源码折叠期间，查找/替换前会自动展开全部折叠
- gutter 折叠箭头依赖鼠标点击（真实按键路径无法在无头环境合成验证）；折叠功能另有菜单入口，不依赖 gutter 点击
- 简繁转换/Python/Bash 排版依赖系统工具（opencc/shfmt/black），DEB 已列为 Recommends，缺失时给出安装提示而非静默失败

## 2026-11-05 修订五：schema v2 迁移（修复 html 保存失败）

### 问题

打开 html 文档时提示「自动保存失败：保存失败：CHECK constraint failed: format IN('txt','md')」。
根因：修订四给格式菜单加了 html，但 v1 数据库 documents.format 的 CHECK 约束未更新。

### 修复

- `SCHEMA_VERSION` 1 → 2，`_SCHEMA` CHECK 放宽为 `('txt','md','html')`
- `_migrate()` 新增 v1→v2 迁移：SQLite 不支持 ALTER CHECK，采用「建 documents_v2 → 复制 → drop → rename」事务性重建表；失败 ROLLBACK 保证原子性

### 验证（tests/test_migration.py 新增）

| 场景 | 结果 |
| --- | --- |
| v1 老库（md+txt 各一）→ 打开自动迁移 | schema_version=2，两文档逐字保留，新 CHECK 含 html |
| 迁移后 create_document("html") → submit_save | 保存成功，读回 format=html |
| **用户真实库副本**（12 个文档）迁移 | 迁移前后逐字对比一致，html 保存成功 |
| test_tools_gui.py 端到端 13 断言 ×2 次 | 全过（修复 s2t 断言：原内容纯 ASCII，简→繁后不变导致断言恒假；改为含简体中文内容） |
| 全部单测（unittest） | OK |

### 环境噪音说明（非缺陷）

- `IBUS-WARNING: has no capability of surrounding-text feature`：IBus 输入法与程序能力协商的提示，无功能影响
- `g_variant_iter_loop: assertion ... G_VARIANT_TYPE_ARRAY failed`：PyGObject/GTK 内部噪音警告，此前多轮已确认为无害

## 2026-11-05 修订六：PDF 导出改用 WeasyPrint 真分页（修复行被劈半）

### 问题

位图管线把整篇渲染成一张大位图再按固定像素高度机械切片，切缝落在行中间时一行文字被劈成上下两半分到两页；且文字为位图，不可选中不可搜索。

### 方案（用户确认 A）

WeasyPrint 子进程真分页：离屏 WebKit 渲染（KaTeX/Mermaid 离线渲染完毕）→ `document.documentElement.outerHTML` 提取最终 DOM → 子线程调用 `weasyprint`（--base-url 指向数据目录，保证相对资源可达）→ PDF。weasyprint 缺失或执行失败时自动回退位图管线并 Toast 提示。

### 关键探针结论

| 实验 | 结果 |
| --- | --- |
| WebKit.PrintOperation.print_() + 打印到文件 | API 可调用（finished 信号触发），但本机 CUPS 无打印机，无法产出文件 → 放弃此路径 |
| KaTeX 渲染后 DOM → WeasyPrint（venv 70.0 实测） | 公式完美（∫ 上下限、根号、分数），woff2 经 brotli 解码正常；Mermaid SVG 内联正常 |
| 分页质量 | 页界处行完整（第 1 页末行/第 2 页首行均为完整行，截图取证）；代码块/表格/图片 page-break-inside: avoid 整块不切 |
| 文字 | 矢量、pdftotext 可提取（与预览相同的中文/高亮/表格排版） |

### 实现（pdfexport.py 重构）

- `export_pdf()` 接口不变，新增可选 `on_fallback(reason)`；内部按 `shutil.which("weasyprint")` 分流
- 公共渲染机制提取（`_make_view/_make_holder/_load_and_wait`：script message 优先 + 轮询兜底）
- `_export_weasy`：DOM 提取 → 临时 HTML → 子线程 subprocess（timeout 180s）→ idle 回调；失败回退 `_export_bitmap`
- window.py：fallback Toast「未检测到 weasyprint，已改用兼容模式导出（文字为位图）」
- DEB `Depends` 加 `weasyprint`（apt 包本体 1.3MB，依赖 pango/python3 库桌面基本已有）

### 测试结果（tests/test_pdf_export.py 新增，双场景）

| 场景 | 结果 |
| --- | --- |
| case1 weasyprint 管线 | ok，3 页，pdftotext 含标题（矢量），页界截图取证行完整 |
| case2 位图回退 | ok，`on_fallback` 提示正确，PDF 正常产出（2.4MB vs 矢量 240KB——矢量还小一个数量级） |
| 回归：迁移/单测/test_tools_gui 13 断言/write-verify | 全过 |

## 2026-11-05 修订七：预览内存回收 / KaTeX·Mermaid 按需加载 / Ctrl+F·H 三重绑定

### 一、预览内存回收（优化 1）

**机制**：`PreviewPane` 维护空闲倒计时。面板不可见（源码模式、切到其他标签、窗口最小化）→ `_arm_release()`；
重新可见 → `keep_alive()` 取消倒计时；已被回收则用 `_last_html` 重建视图并载入。

**关键修正（实测发现）**：切走标签后残留的 `_preview_timer` 防抖刷新会调用 `render()`，
原实现在 `render()` 开头无条件 `_disarm_release()` 并 `_ensure_view()`，等于把刚回收的进程立刻拉起来。
现改为：`render()` 先写缓存 `_last_html`；若 `not self.get_mapped()` 则只缓存、不创建/不刷新视图，仅确保倒计时在跑。
另在 `_on_selected_page()` 中显式对未选中标签 `schedule_release()`、选中标签 `keep_alive()`
（实测 Adw.TabView 切走的页面确实 unmapped，但显式调用可避免依赖映射时序）。

### 二、KaTeX / Mermaid 按需加载（优化 2）

`markdown_render.render_document()` 检测正文是否含 `class="math math-*"` / `class="mermaid"`，
仅按需输出 KaTeX 的 `<link>`+`<script>` 与 Mermaid 的 `<script>`；就绪回调 `messageHandlers.ready` 始终存在
（`mermaidDone` 在无 Mermaid 时为已 resolve 的 Promise）。Mermaid 单文件 3.2 MB，未用到时完全不解析。

### 三、内存实测（同源探针，WebKit 子进程按进程树归属过滤）

| 场景 | 主进程 RSS / PSS | WebKit 进程数 | WebKit RSS / PSS |
| --- | --- | --- | --- |
| 启动基线（无预览） | 214.1 / 92.2 MB | 0 | 0 |
| 纯文字预览（无公式图表） | 270.8 / 125.3 MB | 1 | 178.3 / 70.3 MB |
| 含公式 + Mermaid 预览 | 271.2 / 125.0 MB | 1 | 273.4 / 162.0 MB |
| 三标签均开预览（仅当前标签保留） | 278.4 / 132.0 MB | 1 | 278.2 / 167.3 MB |
| 切回源码 2 秒后 | 276.3 / 139.4 MB | 0 | 0 |

- 按需加载带来的单预览差值：178 MB → 273 MB，即含公式图表的文档比纯文字多约 95 MB 的 WebKit 占用
- 回收后 WebKit 占用归零（进程退出，非仅隐藏）
- RSS 会重复计入共享库，PSS 才是物理分摊；「700 MB」类读数是多进程 RSS 相加，实际约为其 40%~60%

### 四、Ctrl+F / Ctrl+H 三重绑定

现象：用户反馈快捷键不生效。排查与改动：

| 验证 | 方法 | 结果 |
| --- | --- | --- |
| 处理函数逻辑 | 直接调用 `_on_window_key(Gdk.KEY_f, CONTROL_MASK)` | 正常，reveal=True |
| **真实物理按键路由** | `GDK_BACKEND=x11` + XTEST 注入 Ctrl+N / Ctrl+F / Ctrl+H（python-xlib） | 源码焦点、预览焦点两种情形均触发 `show_search`，reveal=True |
| 系统级冲突 | `gsettings list-recursively` 检索 `<Control>f` / `<Control>h` | 无冲突；输入源仅 `xkb us`，无输入法拦截 |

结论：应用内链路无误。用户侧最可能的原因是**升级 DEB 后旧进程仍在运行**（单实例应用，再次启动只唤醒旧进程）。
因此增加三项改动：

1. 窗口级 `Gtk.ShortcutController`（GLOBAL scope，`<Control>f`→`win.find`、`<Control>h`→`win.replace`）作为第二通道
2. 标题栏放大镜按钮 + 菜单「编辑与标签页 → 查找…/查找与替换…」作为鼠标通道
3. `GSCRATCHPAD_KEYDEBUG=1` 打印收到的每个按键；`--version` 与「关于」对话框显示当前运行目录，用于确认跑的是哪份代码

### 五、测试结果

| 项目 | 结果 |
| --- | --- |
| `tests/test_memory.py`（新增） | 全过：rich 渲染 / 回收 / 重建 / 标签切换回收与恢复 / 纯文字不加载库 |
| `tests/test_markdown.py` 16 项 | OK（新增"按需加载"用例，替换原"必须含 mermaid.min.js"断言） |
| `tests/test_tools_gui.py` 13 断言 | 全 true |
| `tests/test_pdf_export.py` 双场景 | OK（weasyprint 3 页矢量 / 位图回退） |
| `test_store` 8 项、`test_migration` | OK |
| 真实按键注入（XTEST） | Ctrl+F → reveal=True；Ctrl+H → replace=True，焦点落到搜索框 |

## 2026-11-05 修订八：Ctrl+F / Ctrl+H 真正的根因（搜索栏高度恒为 0）

### 一、用户提供的现场证据

```
GSCRATCHPAD_KEYDEBUG=1 python3 run-dev.py
[keys] keyval=0xffe3 state=0x0     # Control_L 按下
[keys] keyval=0x66 state=0x4       # f + CONTROL_MASK  ← 按键已到达窗口处理函数
[keys] keyval=0xffe3 state=0x0
[keys] keyval=0x68 state=0x4       # h + CONTROL_MASK
```

按键路由完全正常（上一轮的三重绑定也都生效），问题在 `show_search()` 之后界面上什么都没出现。

### 二、根因

`EditorPage._build_search_bar()` 把 `Gtk.SearchBar` 套在 `Gtk.Revealer` 里：

```python
revealer = Gtk.Revealer(reveal_child=False)
revealer.set_child(Gtk.SearchBar())   # ← SearchBar.search_mode 默认 False
```

`Gtk.SearchBar` 在 `search_mode_enabled == False` 时**子控件高度恒为 0**（它本身就是个自适应高度的容器）。
于是 `revealer.set_reveal_child(True)` 只是"展开了一个 0 高度的盒子"，界面毫无变化。

实测（同一窗口内逐阶段测量）：

| 阶段 | reveal_child | SearchBar.search_mode | SearchBar 高度 | 输入框 mapped |
| --- | --- | --- | --- | --- |
| 初始 | False | False | 0 | False |
| `show_search()` 后（旧实现） | **True** | False | **0** | **False** |
| 同上再强制 `set_search_mode(True)` | True | True | **87** | **True** |

**测试为什么一直是绿的**：旧断言是 `page._search_revealer.get_reveal_child()`，这只是内部状态位，
和"用户能否看见"无关。属于典型的假阳性断言。

### 三、修复

`src/scratchpad/editor.py`：

1. 去掉外层 `Gtk.Revealer`，`self.search_bar` 直接 `append` 到页面顶部，用 `set_search_mode()` 控制展开
2. `bar.connect_entry(self.search_entry)` —— 绑定输入框（否则 GTK 报
   `The search bar does not have an entry connected to it`，键入目标也不明确）
3. `notify::search-mode-enabled` → 用户点关闭按钮/按 Esc 时同步 `hide_search()`（清搜索文本与高亮、焦点还给源码视图），
   用 `_syncing_hide` 标志避免自调用递归
4. `show_search()`：`set_search_mode(True)` → 抓焦点 → 带入选中文本；`hide_search()`：`set_search_mode(False)` + 清高亮

### 四、验证（真实按键，非直接调函数）

XTEST 注入物理按键到真实窗口：

| 操作 | 结果 |
| --- | --- |
| Ctrl+F | `search_mode=True`、高度 **87**、焦点在 SearchEntry 内部、替换行隐藏 |
| Ctrl+H | `search_mode=True`、高度 87、**替换行显示** |
| 开查找后直接敲 `world`（不点搜索框） | 输入框内容 `world`，正文中 `occurrences=1`（高亮命中） |
| Esc | `search_mode=False`、高度 **0**、输入框清空、高亮 `occurrences=0` |
| 点关闭按钮（程序置 `search_mode=False`） | 同上，高亮清零 |

`tests/test_tools_gui.py` 的断言同步改为 **`find_bar_height > 0` + `find_entry_mapped`**，
不再依赖 `reveal_child`。

### 五、回归结果

| 项目 | 结果 |
| --- | --- |
| `test_store` 8 项 / `test_migration` / `test_markdown` 16 项 | OK |
| `test_tools_gui` 15 项（新增真实高度断言） | 全 true，`find_bar_height=87` |
| `test_memory` | 全 true（回收/重建/切标签/按需加载） |
| `test_pdf_export` 双场景 | OK（矢量 3 页 / 位图回退） |

### 六、版本

版本号升至 **1.0.1**（`paths.py` / `__init__.py` / 打包脚本 / README 同步），
便于用 `gscratchpad --version` 或「关于」确认跑的是新代码。产物 `dist/gscratchpad_1.0.1-1_all.deb`。

## 2026-11-05 修订九：目录搜索 / 批量替换（v1.1.0，数据源为真实目录）

### 一、需求与取舍

把 `~/shell/search_md.py`（目录内关键词搜索）与 `replace_md.py`（目录内批量替换）的能力搬进图形界面，
数据源明确取**用户选择的真实目录**，不读写应用自己的笔记库。

脚本直译会带来三个致命问题，实现时逐一处理：

| 脚本行为 | 图形化后的问题 | 本实现 |
| --- | --- | --- |
| 直接覆盖写盘 | 用户看不到将改什么，手滑即灾难 | 先 `plan_replace()` 预览（文件+处数），按文件勾选、二次确认后才写 |
| 无备份 | 误操作无法回退 | 执行前复制到 `~/.local/share/gscratchpad/replace-backups/<时间戳>/`，保持相对路径 |
| 只处理磁盘 | 应用内已打开该文件时，内存内容会把替换结果覆盖回去 | 执行后自动刷新未改动过的标签；应用内改过的标签跳过并提示 |

### 二、核心模块 `fssearch.py`（纯逻辑，无 GTK）

- 遍历：递归/单层、扩展名过滤、跳过 `.git`/`node_modules` 等重型目录与隐藏项、>8MB 跳过
- 编码：UTF-8 / UTF-8-BOM / GB18030 探测；**BOM 与 CRLF 原样写回**；含 NUL 视为二进制跳过
- 搜索：字面量或正则，命中带行号与列号，按文件分组，命中数超 5000 截断（带 truncated 标记）
- 替换：`plan_replace()` 只读；`apply_plan()` 写前重新读盘比对预览内容，**不一致则跳过该文件**
- 写入：同目录临时文件 + `fsync` + `os.replace`，保留原文件权限位

### 三、界面 `fssearch_ui.py`

两个 `Adw.Dialog`，共享「文件夹选择 + 递归/大小写/正则」头部，上次目录记在 SQLite `meta` 表：

1. **在目录中搜索**（Ctrl+Shift+F）：输入防抖 280ms，后台线程搜索并可被新输入取消（generation 计数）；
   结果按文件分组（文件行 + 命中行，命中处加粗），点任意命中行 → 关闭对话框 → 打开文件并 `goto_line()`。
2. **目录批量替换**（Ctrl+Shift+H）：查找/替换输入 → 「预览替换」（后台线程）→ 列表每项带勾选框与处数 →
   「执行替换」弹 `Adw.AlertDialog` 二次确认 → 后台写入 → 刷新标签、显示备份路径与错误摘要。
   替换默认**区分大小写**（与脚本字面量语义一致），可切正则并支持 `\1` 反向引用。

### 四、标签同步的判定（踩过的坑）

最初想用 `page.dirty` 判断"有未保存修改"，实测发现 `dirty` 只会被置 True、除加载/关闭外从不复位，
用它会导致**所有打开过的标签都被判为脏**、永不刷新。改为内容比对：把预览时该文件的完整内容
（`FilePlan.old_text`）传给 `reload_source_tabs(paths, previous)`，只有
`page.snapshot_text() == previous` 才刷新——精确表达"应用内没改过这个文件"。

### 五、验证

**单元测试 `tests/test_fssearch.py`（19 项，全过）**

| 覆盖点 | 结果 |
| --- | --- |
| 递归 / 非递归、按文件分组、行号列号 | OK |
| 大小写、正则、空模式、命中截断 | OK |
| 跳过二进制 / 隐藏目录 / node_modules | OK |
| 预览不写盘、执行才写盘、只替换勾选文件 | OK |
| GB18030 文件替换后仍是 GB18030 | OK |
| BOM 文件替换后仍带 BOM | OK |
| CRLF 文件替换后仍是 CRLF | OK |
| 预览后文件被外部修改 → 跳过且不覆盖 | OK |
| 备份失败（路径被文件占用）→ 跳过且不写 | OK |
| 权限位 0640 保留 | OK |

**界面测试 `tests/test_fssearch_gui.py`（真实 GTK + 临时目录）**

```
matched_files=3  total_hits=3  skipped=1  rows=6  dialog_mapped=True
hit_row_found=True  goto_title=a  goto_line=2
plan_files=3  plan_total=3  apply_sensitive=True
a_md="alpha\n关键字\nbeta\n"  gbk_text="关键字\n"  gbk_still_gbk=True
skip_untouched=True  backup_files=3  tab_refreshed=True
dirty_reloaded=0  dirty_skipped=1  local_edit_kept=True
```

即：搜索→点击结果跳行→预览→执行→文件改写（GBK 保持编码、二进制未动、备份 3 份、打开标签刷新）
→ 应用内已改动的标签被正确跳过。

**动作/菜单冒烟**：`win.fs-search` / `win.fs-replace` 均能弹出对话框（1000×700），
菜单新增「目录工具 → 在目录中搜索… / 目录批量替换…」。

### 六、回归

`test_store` 8 项、`test_migration`、`test_markdown` 16 项、`test_tools_gui`（含 `find_bar_height=87`）、
`test_memory`、`test_pdf_export` 双场景 —— 全过。

### 七、版本

1.1.0，产物 `dist/gscratchpad_1.1.0-1_all.deb`；`fssearch_ui` 由菜单动作按需导入，
不增加启动时的常驻开销。

## 2026-11-05 修订十：侧边文件管理器（v1.2.0，schema v3）

### 一、需求与结构

标题栏在「源码编辑 / 分屏预览 / 实时预览」三态按钮旁新增侧栏开关按钮（F9 同效，状态持久化），
主体是 `Adw.OverlaySplitView`（侧栏 + 标签内容区）。侧栏内 `Adw.ViewStack` 三页：

| 视图 | 内容 |
| --- | --- |
| 笔记 | 最近更新（含已关闭，带标注）/ 未关闭 / 按格式分组 + 标题即时筛选；点击打开或重开；右键菜单（打开/重命名/移动/删除） |
| 文件夹 | 应用内归类：未归档（常驻）+ 自建文件夹；展开显示其中笔记；笔记可拖入（G_TYPE_STRING 拖放载荷 = 文档 id）或右键移动；文件夹可重命名/删除（删文件夹不删笔记） |
| 磁盘 | `$HOME` 起步的真实文件树：目录懒加载（展开才枚举）、单目录 400 项截断、跳过隐藏目录/.git/node_modules/二进制，只列文本类扩展名；点击文件即作标签打开 |

### 二、数据层（schema v3）

- `documents` 新增 `folder TEXT NOT NULL DEFAULT ''`（`ALTER TABLE ADD COLUMN`，纯增量迁移），
  新增 `folders` 表 + `idx_documents_updated` 索引
- v2 → v3 迁移会补登已存在的非空 folder 值；v1 → v2 → v3 链式迁移可用
- `Document` 增加 `folder` 字段；`submit_save` 的 UPDATE 不触碰 folder，不会互相覆盖
- 新 API：`recent_documents` / `open_documents_by_recent` / `documents_grouped_by_format` /
  `folders` / `folder_counts` / `documents_by_folder` / `doc_folder_of` / `create_folder` /
  `rename_folder` / `delete_folder` / `set_folder`（全部走既有工作线程写队列）

### 三、自动定位

`Sidebar.reveal_local_path(path)`：主目录之外的路径直接拒绝；主目录内则逐级确保父目录行存在
（懒加载行按需创建）、展开，最后选中目标文件行并聚焦（GTK4 聚焦即滚动到可见）。
调用点：`open_file_paths`（Ctrl+O / 拖放，取最后成功打开的文件）、`open_path_at_line`
（目录搜索跳转）、`_write_doc_to_file(link=True)`（另存为）。

### 四、踩过的坑

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| `Gtk.DropTarget.new("text/...", …)` TypeError | DropTarget 只接受 GType，不接受 MIME 字符串 | 拖拽载荷改用 `Gdk.ContentProvider.new_for_value(doc_id)` + `Gtk.DropTarget.new(GObject.TYPE_STRING)` |
| 搜索框输入无反应 | `Gtk.SearchEntry` 的 `search-changed` 对程序化 `set_text` 不同步触发（探测只发 `changed`） | 改连 `changed` 信号 |
| 侧栏显隐状态读回为 None | `set_meta` 默认异步写 | 显隐写入用 `wait=True` |
| `reveal` 后行不可见 | GTK4 无 `scroll_to` | `row.grab_focus()`（聚焦即滚动） |
| 删除文档时弹「自动保存失败：文档不存在」 | close-page 处理器无条件回写 | `_on_close_page` 先检查文档是否还存在 |

### 五、验证

**真实库副本迁移**：`~/.local/share/gscratchpad` 副本打开 → 迁移 v2→v3，文档内容逐字无损、folder 全为空。

**`tests/test_sidebar_gui.py`（真实 GTK + 临时 HOME + 临时数据目录）关键输出**：

```
recent_has_closed=True  open_titles=[笔记乙,笔记甲,未命名]
format_headers=['Markdown · 2','纯文本 TXT · 2']  filtered_titles=['笔记甲']
hidden=True meta_hidden='0' reshow=True meta_shown='1'
folder_names=['','工作'] work_children=['笔记甲'] inbox_children=[...]
doc_a_folder='工作' disk_root=True outside_rejected=True
reveal_ok=True view_switched=True expanded_dirs=['docs','docs/sub']
file_row_found=True opened_is_b=True reopen_ok=True reopen_state='open'
deleted_gone=True view_folders=True view_notes=True
```

**全量回归**：`test_store` 8、`test_migration`（含 v3 断言与 folders API）、`test_markdown` 16、
`test_fssearch` 19、`test_tools_gui` 15（`find_bar_height=87`）、`test_memory`、`test_fssearch_gui`、
`test_pdf_export` 双场景 —— 全过。

### 六、版本

1.2.0，产物 `dist/gscratchpad_1.2.0-1_all.deb`。

## 修订十一（v1.3.0）：磁盘页修复 + 悬浮侧栏 + Markdown 大纲

### 一、修复：「磁盘」页首次打开为空

**根因**：磁盘树是懒加载的，但加载入口只有 `reveal_local_path()`（自动定位）与
`reset_disk_view()`。用户点 ViewSwitcher 的「磁盘」页时没有任何代码触发
`_ensure_disk_root()`，于是列表一直是空的——上一版测试恰好都走了 reveal 路径，没暴露。

**修复**：

- `Sidebar._build` 连接 `stack.notify::visible-child-name`：切到「磁盘」页即加载根目录；
  `show_view()` 同步兜底（同视图重复调用不触发 notify）
- `_ensure_disk_root` 空结果时显示「主目录下没有可显示的文件夹或文本文件」占位行
- 行缓存注销：`DiskDirRow.clear_children()` 现在会把该目录注册进 `_dir_rows/_file_rows`
  的键一并弹出（此前 refresh 后旧行对象残留在字典里，`reveal()` 可能选中已脱离控件树的行）

### 二、侧边栏改为悬浮式

`Adw.OverlaySplitView`（并排推挤）→ `Gtk.Overlay` + `Gtk.Revealer`：

- 侧栏作为 overlay child 浮在编辑区上方，圆角 16px + 阴影 + 1px 边框（`.sidebar-float`），
  背景用 `@sidebar_bg_color` 不透明填充（试过 alpha 0.97，正文会透出来显得脏）
- 开关只做 180ms 滑入/滑出动画，**编辑区宽度始终不变**，正文不再被推挤重排
- 状态持久化逻辑不变（`sidebar_visible` meta，`wait=True`）；
  窗口侧 API：`set_sidebar_visible()` / `sidebar_visible()` 取代 split_view 依赖

### 三、Markdown 大纲

- 新模块 `outline.py`（纯逻辑）：ATX（`#`–`######`，严格 CommonMark：`#` 后必须有空格，
  `#hashtag` 不算）+ Setext（`===`/`---`）；围栏代码块（```/~~~，含未闭合）、缩进代码、
  HTML 注释、引用前缀（`> # 标题` 会渲染成标题所以要包含）统一处理；
  剥离行内标记（粗体/斜体/行内代码/链接/图片/HTML 标签/转义）
- 与渲染一致性有单元测试背书：`test_matches_rendered_heading_count` 断言
  `parse_headings()` 条目数 == `render_body()` 输出的 h1..h6 数量
- `markdown_render.render_body` 给每个 h 标签按 DOM 顺序注入 `data-h="i"`；
  预览脚本注入 `window.gscratchpadScrollToHeading(i)`（滚动 + 700ms 黄色高亮）
- 侧栏新增第 4 页「大纲」：按层级缩进（h1/h2 加粗实心点，h4+ 变暗），
  点击条目——源码/分屏模式 `goto_line()` 定位；纯预览模式
  `PreviewPane.scroll_to_heading(index)`，页面未 ready（含被回收重建）时挂起 pending，
  `_on_ready` 后补滚
- 刷新时机：切标签 / 编辑（400ms 防抖）/ 切格式 / 显示侧栏；签名比对避免无谓重建；
  非 Markdown 标签显示说明文字

### 四、踩过的坑

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| 截图里正文透出侧栏卡片 | `alpha(@sidebar_bg_color, 0.97)` 半透明叠在正文上 | 背景改不透明，悬浮感靠阴影+圆角 |
| `Sidebar.set_width_request` AttributeError | GTK4 没有这个方法 | `set_size_request(310, -1)` |
| 预览大纲跳转 scrollY=0 | 测试文档太短，整页无滚动条；且页面 ready 前调用会被丢弃 | 测试文档撑出滚动条；`_ready` 标志 + pending 挂起，ready 后补滚 |
| 大纲与渲染条目数不一致风险 | 引用块内的 `# 标题` 也会渲染成标题 | 解析前剥掉 `>` 前缀（保留行号映射） |

### 五、验证

**`tests/test_outline.py`（14 项，纯逻辑）**：层级/行号/索引、空格规则、围栏（含未闭合）、
缩进代码、HTML 注释、Setext 及误判防护（分隔线/列表后）、闭合序列、行内标记剥离、
与渲染数量一致、data-h 顺序 —— 全过。

**`tests/test_sidebar_gui.py`（扩展后）关键输出**：

```
layout='Overlay' floating_frame=True initial_visible=True
disk_rows_on_switch=1 disk_has_docs=True          # 磁盘页切换即有内容（修复点）
outline_texts=['甲','乙 加粗','丙','尾部标题'] outline_levels=[1,2,3,2]
outline_count_label='大纲 · 4'  jumped_line=7      # 源码跳行
outline_non_md_rows=0 outline_hint_non_md='大纲只对 Markdown 文档生效'
preview_scrolled=True preview_scroll_y=1321.0      # 预览滚动跳转
hidden=True meta_hidden='0' reshow=True meta_shown='1'
reveal_ok=True expanded_dirs=['docs','docs/sub'] file_row_found=True
```

**全量回归**：`test_store` 8、`test_migration`、`test_markdown` 16、`test_fssearch` 19、
`test_tools_gui` 15、`test_memory`、`test_fssearch_gui`、`test_pdf_export` 双场景 —— 全过。

**截图取证**（`scripts/shot_sidebar.py`，输出 `docs/screenshots/`）：
01 悬浮侧栏（圆角阴影卡片）、02 大纲 8 条层级缩进、03 磁盘树、04 侧栏隐藏后正文完整。

### 六、版本

1.3.0，产物 `dist/gscratchpad_1.3.0-1_all.deb`。

## 修订十二（v1.4.0）：命令菜单（方案 A） + 侧边栏排序

### 一、命令菜单（菜单重排 + 搜索）

**结构**：抛弃 Gio.Menu 平铺 section，新模块 `command_menu.py` 自建 `Gtk.Popover`：

- 5 个语义分组（文档 / 编辑 / 视图 / 工具 / 其他）+ 动态「已关闭的文档」组，共 30 条命令；
  高频项在各组最前；视图组新增 源码/分屏/预览 三个模式命令、编辑组新增 上/下一标签页、
  其他组新增 退出
- 顶部 `Gtk.SearchEntry`：输入即过滤（匹配 label + action + keywords），回车执行选中项，
  Down/Up 进入列表，Esc 关闭；无结果显示占位行
- 命令右侧显示**真实生效的快捷键**（读 `Gtk.Application.get_accels_for_action` 并格式化
  `<Control><Shift>f` → `Ctrl+Shift+F`）
- `provider()` 回调在每次打开菜单时现算（含已关闭文档），不存在"Gio.Menu 与实际文档不同步"；
  原来的 `_build_menu()` / `_recent_section` / 动态 rebuild 全部删除，`_rebuild_recent_menu()`
  简化为刷新 `_closed_docs` 缓存
- `Ctrl+K`（win.command-menu + ShortcutController GLOBAL）直接弹出并聚焦搜索框；
  新增快捷键「命令菜单」说明

**为什么不用 Gtk.PopoverMenu + add_child**：换 menu model 会把整个 popover 重建，
嵌入的搜索框每次过滤都会失焦，交互不成立，只能自建。

**踩坑**：

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| XTEST 注入的按键进不了搜索框 | `Gtk.Popover.set_can_focus(False)`：popover surface 不参与键盘焦点，内部控件永远拿不到输入 | 删掉这行（popover 默认 can-focus=True 时内部 Entry 可聚焦） |
| 测试断言 `search.has_focus()` 为 False | popover 在 GTK4 中是独立 native surface，`window.get_focus()` 只反映主 surface | 断言改为 `grab_focus()` 返回值；真实按键用 XTEST 验证（注入 "pdf" → 列表只剩「导出为 PDF…」） |
| GUI 测试全挂：`app.window` 为 None | 用户日常开着 gscratchpad，GApplication 单实例让测试进程直接退出 | 所有 GUI 测试/截图脚本加 `Gio.ApplicationFlags.NON_UNIQUE` |

### 二、侧边栏排序

- 笔记页新增第二个下拉（与筛选下拉同行）：最近更新 / 最早更新 / 标题 A→Z / 标题 Z→A
- 排序在 sidebar 层做（`_sort_docs`），store 查询不动；标题排序用 `GLib.utf8_collate_key`
  （跟随 locale，zh_CN 下中文按拼音）
- 三个视图（最近/未关闭/按格式）与文件夹视图组内笔记应用同一排序；
  按标题排序时「最近」视图截断上限从 80 放宽到 500，避免只排了前 80 条
- 选择持久化到 meta `sidebar_sort`，重启恢复

### 三、验证

**`tests/test_sidebar_gui.py`（再扩展）关键输出**：

```
sort_recent   = ['sort-C','sort-A','sort-B']   # C 最后重命名 → 最新
sort_oldest   = ['sort-B','sort-A','sort-C']
sort_title_asc  = ['sort-A','sort-B','sort-C']
sort_title_desc = ['sort-C','sort-B','sort-A']
sort_meta = 'title_desc'                        # 持久化生效
folder_sorted 头部与笔记视图一致
menu_sections = ['文档','编辑','视图','工具','其他']  menu_total = 30
menu_accel_ctrl_f = 'Ctrl+F'  menu_accel_f9 = 'F9'
menu_popup_visible = True  menu_search_mapped = True  menu_search_focusable = True
menu_search_pdf = ['导出为 PDF…']   # 搜索过滤
menu_search_outline = ['侧栏：Markdown 大纲']
menu_search_save = ['保存到本机文件']
menu_search_empty = []                            # 无结果占位行
menu_command_worked = True                        # emit → win.new-tab 真实执行
ctrl_k_opens_menu = True
```

**XTEST 真实按键**（`/tmp/xtest_menu.py`，X11 + python-xlib）：注入 `pdf` 三个键后
`search_text='pdf'`、列表只剩「导出为 PDF…」——键盘输入链路完整可用。

**全量回归**：单测 57（store 8 / migration / markdown 16 / fssearch 19 / outline 14）、
GUI：sidebar（排序+菜单+大纲+磁盘+预览跳转）、tools 15、memory、fssearch_gui、
pdf 双场景 —— 全过。截图：06-sidebar-sort.png 显示筛选+排序双下拉。

### 四、版本

1.4.0，产物 `dist/gscratchpad_1.4.0-1_all.deb`。

## 修订十三（v1.4.1）：文件管理器关联（Nautilus / 命令行打开文件）

### 一、为什么装完还是关联不上

三个叠加原因，前两个各自都足以让功能失效：

| # | 问题 | 证据 |
| --- | --- | --- |
| 1 | `Exec=gscratchpad` 没有 field code | GNOME 按 Exec 模板展开命令行，没有 `%f`/`%U` 就**没有位置塞文件路径**；程序被拉起但参数为空 |
| 2 | 应用没声明 `HANDLES_OPEN`，也没实现 `do_open` | `super().__init__(application_id=...)`，flags 默认 `FLAGS_NONE`；GApplication 遇到非选项参数直接丢弃（只打一行 `This application can not open files.`，桌面启动时不可见） |
| 3 | 打包没有 postinst，不刷新桌面数据库 | `build_deb.sh` 里完全没有 `postinst`/`postrm`；新版 GLib 的 gio 会直扫 `/usr/share/applications` 所以侥幸能列出，但 Nautilus 自身缓存要重启才刷新 |

诊断时的关键事实：`gio mime text/markdown` 的「已注册的应用程序」里**本来就有** `io.github.gscratchpad.Gscratchpad.desktop`——所以问题不是「没注册」，而是「注册了但路径送不进来」。这也解释了用户体验：右键能看到条目，点了只开一个空窗口。

### 二、修改

1. **`data/*.desktop`**：`Exec=gscratchpad %U`（用 `%U` 而不是 `%f`：文件管理器传 URI、终端传路径，`GFile` 两者都能解析；`%U` 还支持一次拖多个）
2. **`application.py`**：
   - flags 加 `Gio.ApplicationFlags.HANDLES_OPEN`
   - 抽出 `_ensure_window()`（幂等建窗口），`do_activate` / `do_open` 共用
   - 实现 `do_open(files, n_files, hint)`：`get_path()` 收集本地路径 → `window.open_file_paths()`；非本地 URI（http/smb）跳过并 toast 提示
3. **`window.py`**：新增 `ensure_placeholder_tab()`；`restore_session()` 空库时不再立即 `new_tab()`，改由 `do_activate` 在窗口建好后兜底
4. **`packaging/build_deb.sh`**：生成 `postinst`/`postrm`，`configure`/`remove` 时跑
   `update-desktop-database -q /usr/share/applications` + `gtk-update-icon-cache -f -t /usr/share/icons/hicolor`

### 三、踩的坑

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 双击文件只出现「空白标签 + 文件标签」两个 | `restore_session()` 空库时先 `new_tab()`，`do_open` 又加一个 | 空库不建空白标签，`do_activate` 末尾 `ensure_placeholder_tab()` 兜底（`do_open` 也会调，防止文件全失败时留空窗口） |
| 测试里 `app.window` 恒为 None、DB 完全不生成 | 既有测试用 `set_flags(NON_UNIQUE)` **覆盖**了 flags，把刚加的 `HANDLES_OPEN` 抹掉；同时用户在跑 gscratchpad，单实例把进程转发走了 | 全部改成 `set_flags(get_flags() \| NON_UNIQUE)`；端到端脚本改独立 APP_ID |
| e2e 里应用 3 秒就退出、DB 没生成 | 同上：remote 到用户正在运行的真实实例后自身 exit 0 | 测试用 `paths.APP_ID = "...E2E"` 隔离 |

### 四、验证

**`tests/test_open_files.py`（新增，进程内驱动真实 do_open）**：

```
flags_has_open=True
window_before_open=True            # 确认测的是「窗口还不存在」的时序
window_created_by_open=True        # do_open 自己把窗口建出来（关键修复）
pages_after_first=1                # 不再有多余空白标签
no_bonus_blank_tab=True
first_text_ok=True                 # 标签内容来自文件
first_source_path='/tmp/.../home/a.md'
activate_no_extra_tab=True         # 紧随其后的 activate 不再加标签
pages_after_second=2  second_text_ok=True
dedup_pages_unchanged=True         # 重复打开同一文件只切标签
dedup_selected_first=True
uri_resolves_to_path=True          # file:// → 本地路径
remote_pages_unchanged=True        # https:// 被拒绝，不崩溃
missing_pages_unchanged=True       # 不存在的文件 → toast，不建脏标签
```

**端到端（真实进程 + 真实 GApplication 命令行解析，检查 SQLite）**：

- `gscratchpad file:///.../关联测试.md`（模拟 desktop 的 `%U`）→
  `source_path:... = /tmp/.../HOME/关联测试.md`、`documents=[('关联测试','md','open',20)]`、正文含文件内容
- `gscratchpad /.../关联测试.md`（路径形式）→ 同上
- **单实例转发**：实例 A 空启动保持运行 → 实例 B 带 URI 启动，`exit code 0`（remote 成功）→
  A 的库里出现 `('已开应用再双击','md','open')`，原有「未命名」标签保留 —— 即「应用开着时双击文件」的正确行为

**desktop 声明有效性**（`GioUnix.DesktopAppInfo`）：

```
commandline   : gscratchpad %U
supports_uris : True      ← 关键；此前是 False，Nautilus 才会丢弃文件
should_show   : True
```

`desktop-file-validate` 无告警。`dpkg-deb -I` 确认 `postinst`(506B) / `postrm`(467B) 已进 control.tar 且权限 755。

**回归**：单测 57 全过；`test_open_files` 全绿；`test_sidebar_gui` 66 项断言全 True；
`test_tools_gui` / `test_memory` / `test_fssearch_gui` / `test_pdf_export`（双管线）全过。

### 五、版本

1.4.1，产物 `dist/gscratchpad_1.4.1-1_all.deb`。

注意：安装后**必须完全退出正在运行的旧进程**（旧代码没有 `do_open`，双击只会弹出窗口），
Nautilus 若仍不显示可 `nautilus -q` 让其重扫应用列表。

## 修订十四（v1.4.2）：磁盘页排序 + 修复「点不开 / 右键无菜单」

### 一、根因：Gtk.ListBox 在 CAPTURE 阶段吞掉鼠标事件

之前的磁盘树是**嵌套 ListBox**：外层 `disk_list`（ListBox）→ `DiskDirRow`（ListBoxRow）
→ 内层 `children_list`（ListBox）→ `DiskFileRow`（ListBoxRow）→ 自己 `connect("activate")`。

GTK4 的 `Gtk.ListBox` 在初始化时挂了一个 `GtkGestureClick`，**传播阶段是 CAPTURE、button=0**，
pressed 时无条件 `set_state(CLAIMED)`。CAPTURE 从根向下传播，祖先先拿到事件，
claim 之后整棵子树再也收不到鼠标事件——于是：

- 单击文件行 → 事件被外层 ListBox 吃掉，只把外层目录行标记为选中，文件不打开
- 双击同理（第二击还是被吃掉）
- 右键 → 行上的 `Gtk.GestureClick` 也收不到，菜单永远不出来
- 而 `emit("activate")` / 键盘激活**正常**，所以单元测试和程序化验证全绿，只有真鼠标失效

这正是「测试通过但用户点不动」的典型形态。

**验证过程**（XTEST 真实鼠标事件 + `Gtk.Widget.pick`）：

```
pick(225,191) = Label            # 该坐标下确实是文件行
点击后 outer_selected = DiskDirRow   # 但事件被外层行吃掉
[probe] PRESSED / RELEASED 从未打印  # 行自己的 gesture 根本没收到
```

### 二、修复：磁盘树改用普通容器

| 之前 | 现在 |
| --- | --- |
| `disk_list: Gtk.ListBox` | `disk_list: Gtk.Box`（ScrolledWindow 的 child） |
| `DiskDirRow(Gtk.ListBoxRow)`，内部 `children_list: Gtk.ListBox` | `DiskDirRow(Gtk.Box)`，`children_list: Gtk.Box` |
| `DiskFileRow(Gtk.ListBoxRow)` + `activate` 信号 | `DiskFileRow(Gtk.Button)` + `clicked` |
| 目录展开靠 header 上的 GestureClick（双击）+ 小按钮 | 整个 header 是 `Gtk.Button`，单击即展开/收起 |
| 选中态来自 ListBoxRow | `.disk-row-current` 类 + 1.4s 后自动清除 |

`Gtk.Button` 自己处理点击，不依赖任何外部 gesture 竞争；右键用独立的
`Gtk.GestureClick(button=3)`（Button 内置手势只吃左键，右键能正常收到）。

保留 `open()` 里的 0.4s 去重：双击的第二击不会再 `goto_line(1)` 把光标拽回顶部。

### 三、顺带修的 bug：「回到主目录」把列表清空

`reset_disk_view()` 清空行之后调的是 `reload_disk()`，而后者只遍历 `_dir_rows` 里**已展开**
的目录——此刻字典刚被清空，等于什么也没做。改为直接 `_ensure_disk_root()` 重扫根目录。

### 四、磁盘页排序

- 路径栏新增排序按钮（图标 `view-sort-descending-symbolic`），弹出 4 个选项，
  当前项打勾：**名称 A→Z / 名称 Z→A / 最近修改 / 按类型**
- 文件夹始终排在文件之前，组内按所选方式排序；名称用 `GLib.utf8_collate_key`
  （zh_CN 下中文按拼音），最近修改用 `st_mtime`，按类型用「后缀 → 名称」
- 选择持久化到 meta `disk_sort`
- 改排序后重建树，并**逐级恢复原先展开的目录**（`_rebuild_disk_keep_expanded` +
  `_expand_to`），不会因为换个排序把目录全收起来

### 五、验证

**`tests/test_disk_sort.py`（新增）**：

```
default_sort='name_asc'
name_asc=['alpha_dir','zeta_dir','A.txt','b.md','c.json']
name_desc=['zeta_dir','alpha_dir','c.json','b.md','A.txt']   # 文件夹仍在前
mtime_files=['b.md','c.json','A.txt'] mtime_dirs_first=True
type_files=['c.json','b.md','A.txt']  meta_sort='type_asc'
expanded_before=True expanded_after=True child_visible=True  # 换排序不丢展开
click_opened=True click_content=True
double_click_dedup=True                # 双击不重复开/不跳回顶部
right_click_no_open=True menu_visible=True
menu_labels=['打开','在文件管理器中显示','复制路径','复制文件名']
clipboard_ok=True
```

**`scripts/xtest_disk_click.py`（新增，真实鼠标事件）**：

```
{"click_opened": true, "content_ok": true, "right_menu_visible": true,
 "right_did_not_open": true,
 "menu_labels": ["打开","在文件管理器中显示","复制路径","复制文件名"]}
XTEST DISK CLICK OK
```

写这个脚本时踩了两个坐标坑，已写进脚本 docstring：
① `compute_bounds()` 给的是相对**父容器**的坐标，跨层级要用 `compute_point(target, …)`；
② GTK4 的 CSD 阴影让 `GdkSurface` 比 `GtkWindow` 大一圈（实测 1150×810 vs 1100×760），
`warp_pointer` 必须加上 `(surface - widget) / 2` 的偏移，否则会点到上一行。

**回归**：单测 57 全过；`test_disk_sort` 全绿；`test_sidebar_gui` 66 项断言无 False；
`test_tools_gui` / `test_memory` / `test_fssearch_gui` 全过。

### 六、版本

1.4.2，产物 `dist/gscratchpad_1.4.2-1_all.deb`。

## 修订十五（v1.4.3）：转义搜索/替换、图片相对引用、主题切换、快捷键崩溃、光标进度

### 一、目录搜索/替换支持 `\n` `\t` `\r` `\\`

原先搜索是**逐行**匹配（`for line in text.splitlines()`），行内不可能出现换行符，
所以输入任何含 `\n` 的模式都查不到东西；替换则是对整篇文本操作，二者语义不一致。

改法：

1. `fssearch.unescape()`：非正则模式下把 `\n` `\t` `\r` `\\` 转成实际字符，
   未知转义（`\q`）与结尾单独的反斜杠原样保留。正则模式不二次处理（re 自己解释转义）。
2. `fssearch.search()` 改为**全文 `finditer` + 行偏移映射**：预计算每行起始偏移，
   命中偏移用 `bisect_right` 反查行号，列号 = 偏移 − 行首偏移。跨行命中在 `Hit.excerpt`
   里给出 `⏎` 形式的一行摘要（界面直接展示，不再做 markup 高亮，避免标记错位）。
3. 界面层（两个对话框）在调用 `search` / `plan_replace` 前对查找与替换内容做 `unescape`，
   并在输入框占位符里标明支持的转义。

注意：`C:\temp` 里的 `\t` 会被解释为制表符（与 C 字符串一致），路径需写成 `C:\\temp`。

### 二、插入图片与拖放改为相对路径引用

- 文档**已关联本机文件**时：`assets.relative_image_ref()` 用 `os.path.relpath`
  算出文档所在目录到图片的相对路径，插入 `![](../024907.png)`（Markdown 用空 alt），
  **不再复制**图片；相对路径中的空格与圆括号做 URL 编码（`%20` `%28` `%29`），
  中文保持原样。预览的 `base_uri` 已指向文档目录，相对引用可直接解析。
- 文档**未关联文件**（还没落盘）时没有基准目录，退回原行为：复制到
  `~/.local/share/gscratchpad/assets/<doc-id>/`（SHA-256 去重）并插入 `assets/...` 引用。
- 「插入图片…」菜单与拖放入口共用 `window.import_images()`，两条路径行为一致。

### 三、日间 / 夜间主题切换

标题栏新增按钮（浅色时显示月亮 `weather-clear-night-symbolic`，深色时显示太阳
`display-brightness-symbolic`），菜单「视图 → 切换日间 / 夜间主题」同一动作
（`win.toggle-theme`）。实现走 `Adw.StyleManager.set_color_scheme(FORCE_LIGHT / FORCE_DARK)`，
选择写入 meta `color_scheme`（`wait=True`），启动时回放；`notify::dark` 已有处理会同步
GtkSource 配色方案与预览配色。

### 四、点「键盘快捷键」导致退出：其实是进程崩溃

复现输出：

```
Gtk-ERROR **: failed to add UI: .:6:40 Invalid property: AdwShortcutsSection.section-name
```

根因：`show_shortcuts()` 用 `Gtk.Builder.new_from_string()` 解析 XML 字符串，而 XML 里用了
`AdwShortcutsSection.section-name` 与 `max-height`——libadwaita 1.9 已把前者改名为 `title`、
删除了后者。GtkBuilder 的属性错误走 `g_error()`，直接 abort 进程，所以用户看到的是
"点一下就退出"，不是应用主动 quit（`Gtk-ERROR` 属致命级别，Python 的异常处理拦不住）。

修复：不再用 XML，改为**代码构建**——模块级 `SHORTCUTS` 表（2 组 16 条）驱动
`Adw.ShortcutsDialog` / `Adw.ShortcutsSection` / `Adw.ShortcutsItem`，每个加速键先用
`Gtk.accelerator_parse()` 校验，非法则不设；对话框保存在 `self._shortcuts_dialog` 防止被 GC。

### 五、编辑进度：重开回到上次行号

- 保存：meta `cursor:<doc-id>` = `"行:列"`（1 基行号）。时机为切换标签（保存上一个）、
  关闭标签、窗口关闭（`_persist_session` 遍历全部标签），以及每次自动保存之后
  （`wait=False`，不阻塞输入）。切换/关闭/退出用 `wait=True`，保证紧接着退出也不丢；
  进程被强杀时最多丢最后 300ms 内的光标移动。
- 恢复：`add_tab()` / `open_document()` 在载入内容后调 `window._restore_cursor()` →
  `EditorPage.place_cursor_at()`。该方法把行号与列号收敛到合法范围、不抢焦点、
  不改内容，滚动放到 `GLib.idle_add` 里执行（视图尚未分配高度时滚动会被丢弃）。
- 顺带避开 GTK 4.22 的坑：`Gtk.TextBuffer.get_iter_at_line()` 经 PyGObject 暴露为
  `(ok, iter)` 元组，不能直接 `.copy()`；统一用 `get_start_iter()` + `set_line()`。

### 六、验证

**单元测试**（70 例，全过）：`test_fssearch.py` 26 例（新增 7 例：转义规则、跨行命中行号/列号、
`\n` 替换、CRLF 列号）；`test_assets.py` 6 例（同目录/上级/子目录/空格括号编码/图片缺失/文档未落盘）；
`test_store` 8、`test_markdown` 16、`test_outline` 14；`test_migration`、`test_pdf_export` 正常。

**`tests/test_features_gui.py`（新增，22 项断言全 true）**：

```
{"start_light": true, "icon_light": true, "toggle_to_dark": true, "meta_dark": true,
 "icon_dark": true, "toggle_back_light": true, "meta_light": true,
 "shortcuts_dialog": true, "shortcuts_alive": true, "shortcuts_sections": 2,
 "shortcut_accels_ok": true, "bad_accels": [], "shortcut_items": 16,
 "cursor_restored": true, "cursor_clamped": true, "cursor_saved": true,
 "cursor_saved_on_switch": true, "img_relative": true, "img_not_copied": true,
 "img_encoded": true, "img_asset_fallback": true, "relative_helper": true}
```

**`tests/test_fssearch_gui.py`（新增 7 项转义断言，原断言全绿）**：

```
escape_hits=1  escape_line=2  escape_excerpt='跨越 ⏎ 换行'  escape_highlight_skipped=True
escape_replace_files=1  escape_replace_total=1  escape_preview_readonly=True
```

**回归**：`test_tools_gui` / `test_disk_sort` / `test_open_files` / `test_sidebar_gui`（66 项）/
`test_memory` 均无 False；启动冒烟（临时数据目录）正常，`--version` 输出 1.4.3。

### 七、版本

1.4.3，产物 `dist/gscratchpad_1.4.3-1_all.deb`（md5 `acf43e3af17e96b7f70c79c380484cbd`）。

## 修订十六（v1.4.4）：搜索结果行改为双击打开 + 补上「替换此内容…」

### 一、交互变更

上轮（v1.4.3）只做了转义与全文匹配，两处交互欠账本轮补齐：

1. **双击打开**：结果行原来是 `Gtk.ListBox` + `row-activated`（单击即激活），浏览结果时
   点一下就跳走，太容易误触。改为与「磁盘」页一致的方案——**不用 Gtk.ListBox**（它在
   CAPTURE 阶段无条件 claim 鼠标序列，行内手势收不到事件），结果容器换成普通 `Gtk.Box`，
   每行 `_HitRow(Gtk.Box)` 挂三个控制器：
   - `GestureClick(button=1)`：`n_press == 1` 只做选中（`.hit-row-current` 高亮），`n_press >= 2` 打开；
   - `GestureClick(button=3)`：右键菜单；
   - `EventControllerKey`：行聚焦后回车等同双击（键盘可达）。
2. **跳转带选中**：`Hit` 增加 `length`（命中文本长度），`editor.goto_line(line, column, length)`
   在定位到行之后把关键词整段选中（`select_range`），打开文件一眼就能看到命中的是哪几个字；
   列号收敛到行尾，错列不会把光标挤到下一行。
3. **右键菜单 / 替换按钮**：结果行右键菜单为
   `['打开并定位到此行', '替换此内容…', '在文件管理器中显示', '复制文件路径']`；
   每个文件分组标题右侧另有替换图标按钮（`edit-find-replace-symbolic`），作用范围是该文件。

### 二、「替换此内容…」的完整流程

`FolderSearchDialog.replace_in_file(path)` → `window.open_folder_replace_for(...)`：
带当前目录、查找原文与三个开关打开 `FolderReplaceDialog`，并：

- 自动预览一次（只读）；
- 预览完成后**只勾选**点中的文件，其余文件列出但不勾选
  （`_select_only_file()`，路径比较用 resolve()，状态行注明「已只勾选…」）；
- 目标文件没有命中时明确提示，未勾选任何文件，不会误执行。

### 三、顺带修掉的预览作废漏洞

`FolderReplaceDialog` 原来只监听查找框的 `changed` 作废预览，**替换内容与三个开关**
改动后旧计划仍然可执行——从搜索结果进来会先自动预览（替换串为空），用户填好替换内容
直接点「执行替换」就会拿空替换串落盘，等于把命中处删掉。修复：

- 替换框 `changed` 与三个开关 `notify::active` 都接入 `_invalidate()`；
- 预览后替换内容为空时，状态行追加「替换内容为空，执行会删除命中的文本」。

### 四、测试

**`tests/test_fssearch_gui.py`（扩展，全绿）**：

```
rows=3  file_heads=3  hit_length=4  hit_column=0
menu_labels=['打开并定位到此行','替换此内容…','在文件管理器中显示','复制文件路径']
single_click_selected=True  single_click_no_open=True
goto_line=2  goto_selected='关键内容'  goto_selected_is_key=True
prefill_find='关键内容'  prefill_folder=<docs>  prefill_case=False  prefill_regex=False
only_checked=['sub/b.md']  only_unchecked=['a.md','gbk.md']  status_mentions_only=True
invalidate_on_replace_change=True  apply_disabled_after_change=True
only_b_replaced='关键字 also\n'  only_a_kept_key=True  only_b_correct=True
（原有转义与整目录替换断言全部保持）
```

**`scripts/xtest_search_click.py`（新增，XTEST 真实鼠标事件，`XTEST SEARCH CLICK OK`）**：
单击只选中不跳转、双击打开且 `goto_line=2`、`double_selected='关键内容'`、
右键菜单可见且含「替换此内容…」、右键不打开文件、双击后对话框确实关闭
（`get_root() is None`，`get_visible()` 在 Adw.Dialog 关闭后仍为 True，不能用它判断）。

**回归**：`test_features_gui`（22 项）、`test_disk_sort`、`test_open_files`、`test_tools_gui`、
`test_sidebar_gui`（66 项）均无 False；单元测试 `test_fssearch` 26 例全过。

### 五、版本

1.4.4，产物 `dist/gscratchpad_1.4.4-1_all.deb`（md5 `5c846d22e103068b8bbccb897d3e3254`）。
截图 `docs/screenshots/07-search-results.png`（`scripts/shot_search.py` 生成）。

## 修订十七（v1.5.0）：文本片段（自定义快捷键输出）+ 触发词展开

按前一轮方案执行：快捷键冲突**允许改绑**；默认片段**完全空白**；功能二接受**只做触发词展开**（不做词表补全弹窗）；数据存 **SQLite meta**。

### 一、文本片段（snippets.py / snippets_ui.py）

- 数据：meta `snippets`（JSON 数组，`{id, name, template, accel}`），随文档库备份；坏 JSON 容错为空表（`snippets.loads`）。
- **模板引擎自研**（不用 GtkSourceView snippet）：`{{cursor}}` 光标落点（缺省文末）、`{{date}} {{time}} {{datetime}} {{title}}` 变量、`\n \t \r \\` 转义、未知转义/占位符原样保留。不用 GtkSourceView 的 `$1` 语法是因为实测 `Snippet.new_parsed()` 会把 bash 里最常见的 `$VAR`、`$5`、`\n` 吃掉（`printf "%s\n" $1` 插入后变成 `printf "%sn" `）。
- **插入**：`EditorPage.insert_snippet()`——删除选区→插入→光标落位→`scroll_to_mark`，整段包在 `begin_user_action` 里，**一次撤销**全部还原。插入点用字符偏移记录（GTK 的 iter 在缓冲区改动后一律失效，复制 iter 再 `forward_chars` 会打出 "Invalid text buffer iterator" 并把光标丢到 0，本轮实测踩到并修复）。
- **动作与快捷键**：每个片段注册 `win.snippet-<id>`，`set_accels_for_action` 绑定录制到的键；命令菜单（Ctrl+K）动态出现「片段」分组，未绑定快捷键也能用。
- **按键录制**：`Gtk.accelerator_name(keyval, mods)` 生成；Esc 取消、只按修饰键继续等、无修饰键只接受 F1–F12、`Gtk.accelerator_valid` 校验。
- **冲突改绑**：`window.accel_owner(accel)` 用规范化形式（`canonical_accel`，`<Shift><Control>p` 与 `Ctrl+Shift+P` 同键）在片段 + 核心动作（keymap.ACCELS 实时查询）里找占用者；冲突时 `Adw.AlertDialog` 询问，选「仍然改绑」则 `release_accel(action)` 解除原绑定并持久化到 meta `accel_overrides`，启动时 `_apply_accel_overrides()` 回放。「恢复默认快捷键」清空 overrides 还原核心键，同时解除与默认键冲突的片段快捷键。
- **焦点守卫**：动作回调检查 `page.view.has_focus()`，焦点不在编辑区（搜索框/侧栏）时不插入并弹 toast——片段快捷键是窗口级 accel，无法"不消费"，用明确提示代替静默丢弃。

### 二、触发词展开（Tab）

- 内置 7 种语言的触发词表：Bash 12、Markdown 17、HTML 7、Python 6、JavaScript 4、CSS 4、SQL 4（`snippets.TRIGGERS`，全部模板有单测保证可渲染非空）。
- `EditorPage` 在 view 上挂 CAPTURE 阶段 `EventControllerKey`：无修饰 Tab 时取光标前行尾 32 字符，`snippets.match_trigger()` 要求**触发词恰在光标前且前面是词边界**（`life` 里的 `ife` 不展开），命中则删除触发词并插入模板（同一撤销组），**未命中一律返回 False**，Tab 仍是普通缩进。
- 长触发词优先：`codebash` 不会先匹配到 `code`。
- 语言来源：已关联文件按扩展名（`.sh/.bash/.zsh`→sh 等），未关联按文档格式（md→markdown、html→html），`typescript` 归并到 js 表。

### 三、设置界面

`Adw.PreferencesDialog` 两个页：「片段」（列表增删改 + 新建 + 恢复默认快捷键）与「自动补全」（7 个 `Adw.ExpanderRow` 按语言折叠列出全部触发词，只读）。片段编辑器含名称行、快捷键录制行、等宽模板编辑区与**实时预览**（`▏` 标出光标落点）。注意：`Adw.ActionRow` 的 subtitle 默认按 Pango 标记解析，模板里的 `<div>`、`&` 会解析失败刷一屏 Gtk-WARNING，必须 `GLib.markup_escape_text` 后再设。

### 四、验证

**`tests/test_snippets.py`（新增，27 例全过）**：模板渲染（光标偏移含变量展开后的正确计数、多 `{{cursor}}` 只认第一处、bash `$VAR`/`\n` 存活、空模板）、加速键（`Ctrl+Shift+P` ≡ `<Control><Shift>P` ≡ `<Shift><Control>p`、裸修饰键非法、pretty 显示顺序）、触发词（词边界、未知语言、最长优先、全表可渲染）、存取（往返、坏 JSON、重复 id 重排、缺字段）。

**`tests/test_snippets_gui.py`（新增，48 项断言全 true）**：

```
action_registered/accel_bound/meta_saved=true  inserted=true cursor_offset=5
undo_single_step=true  view_lost_focus=true guard_blocks_insert=true
conflict_detected=true conflict_label="切换到标签 1"  goto_released=true
override_saved=true override_replayed=true  restore_goto=true
snippet_accel_cleared=true overrides_cleared=true
bash_tab_handled=true bash_expanded=true bash_cursor_after_if=5 bash_undo=true
tab_passthrough=true no_midword=true  md_expanded=true
dialog_built=true editor_built=true editor_preview=true
record_accel="<Control><Alt>5" record_stopped=true modifier_only_ignored=true
plain_letter_rejected=true  action_removed=true accel_cleared=true
menu_has_snippets=true menu_snippet_name=true
```

**`scripts/xtest_snippet_key.py`（新增，XTEST 真实按键，全 true）**：真键盘敲 `ife`+Tab → 展开为 `if [ … ]…` 且光标在第 5 字符；真按 Ctrl+Alt+1 → 插入 `<!--  -->` 光标落位；真按未绑定的 Ctrl+Alt+2 → 无插入。注意：XTEST 输入会触发一个 `g_variant_iter_loop` GLib 警告——已用 30 行纯 GTK 最小程序复现，与本项目代码无关（GTK 输入法桥在此环境的已知噪音）。

**回归**：`test_features_gui`（22 项）、`test_fssearch_gui`（全绿）、`test_disk_sort`、`test_open_files`、`test_tools_gui`、`test_sidebar_gui`（66 项）无 False；单元 `test_fssearch` 26、`test_store` 8、`test_markdown` 16、`test_outline` 14、`test_assets` 6 全过。

### 五、其它改动

- `keymap.py`（新增）：核心快捷键表从 application.py 抽出，window 判断冲突不反向导入。
- `Ctrl+Shift+E` 绑定「片段与自动补全」设置；快捷键说明对话框加 2 行。
- `ACCELS` 在 application.py 保留同名引用，旧测试不受影响。

### 六、版本

1.5.0，产物 `dist/gscratchpad_1.5.0-1_all.deb`。截图 `docs/screenshots/08-snippets.png`（`scripts/shot_snippets.py`）。

## 修订十八（v1.6.0）：捕获接口（capture v1，供其它程序调用）

### 一、需求

外部 PDF/EPUB 阅读器（Lectula）调用本程序做「现场记录」与「笔记导出」：D-Bus 主通道 +
CLI 降级、后台落盘不弹窗不切标签、key 幂等防重复导出。契约 v1.0 与 Lectula 侧锁定，
纯写方向，无读取/更新/删除接口。

### 二、实现

- `capture.py`（新增）：`validate()`（NUL/超 1MB/空文本/mode 白名单/key 空白字符）、
  `capture_document()`（key → meta `ext:<key>` 映射；同 key create 幂等返回、
  append 行首 `---` 分隔 + 引用块《书》· 页码 · 时间；无 key 建新文档；
  meta 指向已删文档时重建；落盘后校验 revision 推进，失败抛 CaptureError 带退出码）、
  `run_capture_cli()`（手工解析 --capture-*、支持 = 内联与 `-` 读 stdin、
  校验先行于转发）。
- `application.py`：flags 增加 HANDLES_COMMAND_LINE（`__init__` 构造时叠加，
  不用 set_flags 覆盖）；`do_command_line`（文件参数自行分派走 do_open，无参 activate）；
  `app.capture` action（参数 `(ssssss)`）；`_ensure_store()` 与开窗解耦
  （服务模式下不开窗也能落库）；`main()` 在进入 GApplication 之前拦截 capture 参数。
- CLI 转发：实例运行中经 `org.gtk.Application.CommandLine`（(o aay a{sv}) → (i)）
  转发并带回真实退出码；未运行时本地直落 data_root，不建窗不常驻。
- `window.on_captured()`：toast + 侧栏刷新；目标文档恰好打开且未修改则就地重载
  （不切标签），有未保存修改仅提示核对。
- `packaging/build_deb.sh`：新增 `/usr/share/dbus-1/services/<APP_ID>.service`
  （`Exec=gscratchpad --gapplication-service`，总线激活常驻不弹窗）。
- 版本 1.6.0（paths.py / build_deb.sh）。

### 三、实测踩坑（全部以最小复现确认）

1. **本机 PyGObject 未绑定 `GApplicationCommandLine.get_files`**——属性不存在直接
   AttributeError；文件参数改从 `get_arguments()` 自行计算。
2. **CommandLine 方法在 `org.gtk.Application` 上**，不在 org.freedesktop.Application
   （后者只有 Activate/Open/ActivateAction，introspect 实测）。
3. **aay 必须用 `Variant.new_bytestring`（带 NUL 终止符）**——手工
   `Variant("ay", bytes)` 不带 NUL，服务端 `^aay` 解出越界垃圾串
   （实收 `['CommandLine', 'dbg4', '', 'm:5']`，取自相邻 D-Bus 内存），静默走错分支。
4. **转发 arguments 必须含 argv[0] 程序名占位**，否则 `args[1:]` 判定与解析错位。
5. `org.gtk.Actions.Activate` 的 platform_data 是必填：签名 `(sava{sv})` 而非 `(sav)`；
   `DescribeAll` 返回 `a{s(bgav)}` 字典（gio 文档旧式 `a(savbg)` 已过时），
   call_sync 的 reply_type 必须写成含出参的元组 `(a{s(bgav)})`。
6. D-Bus 协议 `s` 类型禁止内嵌 NUL（GLib 静默剥离）→ NUL 拒绝路径只对 CLI/stdin 有意义。
7. 测试进程 argv 不能含 `\x00`（subprocess ValueError），NUL 用例改走 stdin。

### 四、验证

- `tests/test_capture.py` 21 例：校验边界、create 默认标题（书名/速记+时间）、
  幂等（同 key 内容不变、book/title 新值忽略）、append 分隔格式与 revision 单调、
  无 key 建档、stale meta 重建、CLI 全部退出码（0/1/3）、stdin utf-8、= 内联参数。
- `tests/test_capture_e2e.py` 5 例（真实实例 + 独立 APP_ID + 临时 XDG_DATA_HOME）：
  DescribeAll 暴露 capture、D-Bus create 幂等 + 镜像文件、append 正则断言格式、
  超限文本不落库、CLI 转发 exit 0 / 预检 exit 3 / 未知参数 exit 1。
- 全量回归：无头 123 例（unittest discover）OK；GUI 8 套（open_files/features/
  fssearch/sidebar/snippets/tools/memory/pdf_export）退出码全 0，断言无 false。

### 五、版本

1.6.0，产物 `dist/gscratchpad_1.6.0-1_all.deb`。

## 修订十九（v1.6.1）：Lectula 回执三项落实

### 一、回执内容

Lectula 实测接入后的三条偏差：①动作名总线层是裸名 `capture`（非 `app.capture`）；
②CLI stdin `-` 在实例运行时静默 exit 1（原因写在实例进程 stderr，调用方管道看不到）；
③book 传 `《书名》` 会落库成 `《《书名》》`。

### 二、处理

- ②为真实缺陷，**代码修复**：`run_capture_cli` 改为调用方侧先读完 stdin，
  转发前把 argv 中 `-` 移除并追加 `--capture-text <文本>`；实例侧永不依赖 stdin。
  保留防御分支：外来客户端直发 `-` 到实例 CommandLine 时 exit 1（该消息仅在实例
  stderr，属防御路径，自身 CLI 不会构造）。
- ①③为契约文档问题，**回写文档**（capture.py 模块 docstring 契约升级 v1.1、README）：
  动作名裸名 `capture`；book/page 传裸内容，书名号由本程序添加。
  不做自动剥壳（静默改写调用方数据比显式约定更危险）。

### 三、验证

- `test_capture.py` 22 例（新增 `test_cli_stdin_forward_rewrites_to_text`：
  断言转发 argv 改写正确、转发路径不本地落库）。
- `test_capture_e2e.py` 5 例（新增回执原始场景回归：实例运行 + stdin `-` → exit 0 落库）。
- 产物 `dist/gscratchpad_1.6.1-1_all.deb`，md5 `8dabc5c0d7378c606ac7c7c761b548df`，
  包内外 capture.py 核对一致。

## 修订二十（v1.7.0）：侧栏交互 + 清除已关闭 + 孤儿清理与 VACUUM

### 一、需求

1. 侧栏选中笔记后自动隐藏（不改变用户偏好）；Esc 关闭侧栏。
2. 「清除已关闭的笔记」，语义不得等同于裸 SQL `DELETE FROM documents WHERE state='closed'`
   （会留孤儿镜像/资源与失效映射）。
3. 孤儿清理 + VACUUM，**严格限定在本应用数据目录内**。

### 二、实现

- 侧栏：`window.hide_sidebar()`（persist=False + `_suppress_sidebar_persist` 防回写偏好）、
  `hide_sidebar_after_pick()`（受 meta `sidebar_autohide` 控制，默认开）；
  侧栏 5 个打开入口（笔记行、笔记右键「打开」、文件夹子项、磁盘右键「打开」、磁盘双击）
  调用该钩子；大纲跳转不触发。Esc 走既有窗口 CAPTURE 键控器，查找栏
  `search_bar.get_search_mode()` 为真时让行，避免抢走 SearchBar 的关闭键。
  命令菜单「视图」新增开关项（标签实时显示当前状态）。
- 仓储：`Store.closed_documents()` / `purge_closed_documents(keep_ids)`（写线程单事务：
  收集 id → 逐 id DELETE → 清理 `ext:`/`cursor:`/`source_path:` 映射 → 提交后再删
  镜像（`notes/<id>.*` glob）与 `assets/<id>`）；`scan_orphans()`（只读统计）；
  `maintain(vacuum)`（写线程内重新枚举、删除、清 stale meta → VACUUM →
  `PRAGMA wal_checkpoint(TRUNCATE)`）。`keep_ids` 跳过标签中打开的文档（防御）。
- 安全边界：只枚举 `notes/`、`assets/`、`recovery/` 第一层；符号链接先判 `is_symlink()`
  只删链接；`.tmp` 仅在 mtime 超过 600 秒时视为残留（避免删掉正在写的临时文件）。
- UI：两处破坏性/维护对话框（体积与条目计数、`DESTRUCTIVE` / `SUGGESTED` 按钮），
  完成后刷新侧栏与最近菜单并 toast 报数。

### 三、实测踩坑

1. **VACUUM 前后的体积不能用主库文件量**：WAL 模式下数据可能全在 `-wal` 里，
   主库只有 4 KB 头部；压缩后主库变成 36 KB，数字反向。改为「主库 + WAL」合计计量
   （`_db_footprint`），压缩后 `wal_checkpoint(TRUNCATE)` 把 WAL 归零。
2. **不能从工作线程调用 `_query`**：`_reader` 连接受 `check_same_thread` 约束，
   写线程内清 meta 必须用自己那条 `conn`；为此把判定逻辑抽成
   `_stale_keys_from_rows()` 供两条路径复用。
3. **自动隐藏不得写 `sidebar_visible`**：那会把一次点击变成持久偏好（下次启动侧栏关着）。
   用 `_suppress_sidebar_persist` 标志让 `_on_sidebar_toggled` 走 persist=False。
4. **Esc 归属**：查找栏打开时 Esc 必须交给 SearchBar，否则「关不掉查找、反而关掉侧栏」。
5. 实测本机数据：`notes/` 30 个文件对 3 条文档（27 个孤儿）、`assets/` 2.5 MB 孤儿、
   数据库 15.8 MB 中 3850/3870 页为空闲页——正是历史裸 SQL 删除与未压缩的遗留。

### 四、验证

- `tests/test_maintenance.py` 9 例：只清 closed、保留 open 与镜像、assets 与三类映射清理、
  keep_ids 跳过、扫描计数（含新/旧 `.tmp`）、维护只删孤儿、符号链接不跟随（目标文件保留）、
  数据目录外文件不受影响、VACUUM 后 freelist 归零且体积不增。
- `tests/test_maintenance_gui.py` 19 项断言全 True：选中后隐藏且偏好不变、开关关闭时不隐藏、
  Esc 关侧栏、查找栏打开时 Esc 让行、开关动作双向、清除后文档与资源消失且打开的文档保留、
  维护删孤儿且保留有效镜像、三个菜单项存在。
- 全量回归：`unittest discover` 133 例 OK；GUI 套件（sidebar/open_files/features/tools/
  fssearch/snippets/memory/pdf_export/disk_sort/maintenance）退出码 0，无 false。
- 产物 `dist/gscratchpad_1.7.0-1_all.deb`。

## 修订二十一（v1.8.0）：列编辑 + 撤销/重做按钮

### 一、需求

1. 列编辑（轻量版，见 2026-11-13 评估结论）：每行加前缀 / 后缀、行排序、去重；
   不做 Notepad++ 式 Alt 拖拽矩形选区（上游 GtkSourceView/GTK4 无支持，bug 96436
   2002 年至今未合并；非等宽字体列语义不成立）。
2. 撤销 / 重做标题栏按钮 + Ctrl+Z / Ctrl+Shift+Z（Ctrl+Y 同重做）。

### 二、实现

- `columnedit.py`：纯函数（add_prefix / add_suffix / sort_lines / dedup_lines /
  transform），排序按 Unicode 码点升序（稳定），去重整行精确匹配保留首次出现；
  不依赖 GTK，可独立单测。
- `editor.apply_line_op(op, arg)`：选区展开为整行（末行停在行首则不计入，与主流
  编辑器一致）；无选区时前缀/后缀作用于光标行，排序/去重要求 ≥2 行；执行前
  `unfold_all()`（折叠是物理移除，选区看不见）；整块替换包进单一 user action
  （一步撤销）；完成后重新选中修改块。返回 False 表示 no-op（窗口层 toast 提示）。
- `window.py`：新增 win.undo / win.redo / win.line-prefix / win.line-suffix /
  win.sort-lines / win.dedup-lines 六个动作；标题栏 edit-undo/edit-redo 按钮
  （灵敏随缓冲区 can-undo / can-redo 属性同步，两处建标签路径都接线）；前缀/后缀
  用 Adw.AlertDialog 输入；命令菜单「编辑」节加撤销/重做、「工具」节加四项列编辑。
- `keymap.py`：Ctrl+Z 撤销、Ctrl+Shift+Z / Ctrl+Y 重做（与既有键位无冲突；
  snippet 改绑机制兼容）。折叠引擎使用 begin_irreversible_action（folding.py 326/345），
  折叠/展开不进撤销栈，撤销不会复活折叠导致的删改。
- 版本 1.7.0 → 1.8.0（paths.py、build_deb.sh）。

### 三、测试证据

- 新增 `tests/test_columnedit.py` 16 例（前缀/后缀含空行与 Unicode 参数、排序稳定性
  与码点序、去重保留首现与空白敏感性、末段空行、未知 op no-op）——OK。
- 新增 `tests/test_lineops_gui.py`（独立 APP_ID + 临时 XDG_DATA_HOME，全部走真实
  `activate_action` 路径）：19 项断言全 true——排序/去重文本、撤销恢复、重做重放、
  部分选区行首截断语义、单行排序 no-op、光标行前缀、按钮灵敏度随编辑/撤销/切换
  标签变化、六个动作注册。退出码 0。
- 全量回归：非 GUI 149 例（133 旧 + 16 新）OK；GUI 套件 features 22 键全 true、
  snippets 套件首跑 3 项 false → 复跑全过 → 与 1.7.0 源码 A/B 对照同现同愈
  （各 3 连跑），判定为窗口焦点时序的环境波动，与本次改动无关。
- 本机 `python3` 为 WorkBuddy 内置 3.13（无 gi），测试必须用 `/usr/bin/python3`；
  zsh 不做单词拆分，模块列表须以数组传给 `-m unittest`。

## 修订二十二（v1.9.0）：编辑区右键菜单 + 选区感知工具

### 一、需求

1. 编辑区右键菜单追加列编辑（子菜单）/格式化排版/简→繁/繁→简/折叠当前区块；
2. 简繁转换支持只转换选定文字；3. 格式化排版支持只排版选中代码块。
评估中同时裁决了菜单折叠化（不做：搜索框已是主导航，折叠需引入跨重建的
折叠状态与键盘导航复杂度，破坏 command_menu「单一数据源」不变式）与内置
右键项「删除/撤销/重做」去留（不移除：extra-menu 只增不减，移除须整体替换
内置弹层重建剪贴板/表情/使能逻辑，成本远大于收益；撤销/重做与新加的标题栏
按钮互补，删除项使能态由 GTK 内建管理且可撤销、无实害）。

### 二、实现

- `window.py`：新增 `_selection_bounds`（GTK4 PyGObject 实测：无选区返回
  空元组、有选区返回 (start, end) 二元组，文档通行的 (has, s, e) 三元组说法
  在本机不成立）、`_replace_region`（左右重力标记对定点替换，单一 user
  action，完成后重新选中替换结果并移除标记）、`_run_tool_async_region`
  （有选区只把选中文本交给 worker，无选区回退既有整篇通道 `_run_tool_async`；
  完成前 unfold_all 保证折叠区不漏改；页面已关闭则直接放弃，错误路径清理标记）。
- `convert_current_doc` / `format_current_doc` 改走选区感知通道。排版选区
  语言的判定顺序：选区内容 sniff → 关联扩展名 → 整篇 sniff；无选区保持原序
  （扩展名 → 整篇 sniff）。
- `editor.py`：`_build_context_menu()` 生成 Gio.Menu（列编辑子菜单 + 4 顶层项，
  全部引用既有 win.* 动作，零新动作），`view.set_extra_menu()` 挂到内置菜单
  之后（GTK 4.22.4 源码核实内置项：剪切/复制/粘贴/删除│撤销/重做│全选/输入表情）。

### 三、测试证据

- 新增 `tests/test_context_gui.py` 8 项断言全 true（真实 activate_action 路径 +
  真实 opencc / formatter 子进程）：extra-menu 已挂且 5 条、选区转换只改选中段
  （前后文零扰动）、结果重新选中 2 字符、一步撤销还原、无选区整篇转换、选区
  JSON 块排版（`data = 1` 与 `tail` 不动）、无选区整篇排版。退出码 0。
- 回归：非 GUI 149 例 OK；GUI 套件 features 22 键全 true、lineops 19 键全 true。
- 过程中两处根因修正（均实证）：① `TextIter` 无 `forward_characters`，应为
  `forward_chars`——曾导致替换成功但重选/保存/toast 全部跳过（idle 回调内异常
  静默中止，表现为"选区丢失"）；② PyGObject `get_selection_bounds` 的返回形态
  以隔离探针实测定案（见上）。
- 版本 1.8.0 → 1.9.0（paths.py、build_deb.sh）。

## 修订二十三（v1.10.0）：仅选区查找替换

### 一、需求

「全部替换」支持只在选区内进行（2026-11-14 评估：与列编辑正交的真实缺口——
同一词在选区外也存在时正则无法表达范围；菜单折叠化维持不做）。

### 二、实现

- `editor.py`：替换面板新增「仅选区」显式开关（不做隐式推断）；打开替换面板时
  多行选区自动勾上、否则回退整篇语义。`_replace_all_in_selection()`：从选区起点
  用 SearchContext.forward 逐个迭代（GtkSource 无范围概念），**完全落在选区内**
  才 replace（Notepad++ 约定；跨界匹配不算）；起点在选区之前的匹配跳过、
  终点越界即终止；检测 `has_wrapped`（wrap-around 开启时 forward 会绕回文档
  开头，不检测则死循环——实测踩中）；空替换前进一个字符防零宽匹配原地循环；
  整批单一 user action（一步撤销）；完成后重新选中修改区域。
- `EditorPage` 新增 `request-toast(str)` 信号，window 两条建页路径接线，
  「已在选区内替换 N 处」经窗口 toast 通道送达；无选区勾着开关 → toast 提示。
- 查找的上一个/下一个维持全文档导航（评估结论：限制导航引入选区内循环语义，
  收益低）。

### 三、测试证据

- 新增 `tests/test_selrepl_gui.py` 11 项断言全 true：开关存在、多行选区自动勾/
  无选区不勾、选区内替换且选区外零扰动、toast 计数「替换 1 处」、一步撤销、
  起点跨界与终点跨界均排除（0 处 toast）、替换后重新选中、开关关闭整篇替换。
  退出码 0。
- 回归：非 GUI 149 例 OK；GUI 套件 lineops 19 键、context 8 键全 true。
  features 套件汇总脚本误报说明：shortcuts_sections/bad_accels/shortcut_items
  三项本就是计数与列表（2 / [] / 22，均健康），此前的汇总过滤条件为
  `is False`、本轮误用 `is not True` 才被标红，应用无回归。
- 过程中三个根因（均实证，已记入日志）：① SearchContext.forward 在 wrap-around
  开启时绕回文档开头 → 选区替换循环不终止（SIGTERM 才杀掉）；②
  Gtk.SearchEntry 的 `search-changed` 是延迟信号，测试同步 `set_text` 后
  SearchSettings 仍为 None，须直接驱动 SearchSettings（真实用户输入无此问题）；
  ③ 整篇 `replace_all` 为异步完成，断言须轮询。
- 版本 1.9.0 → 1.10.0（paths.py、build_deb.sh）。

## 修订二十四（v1.11.0）：「转义」开关（查找 + 替换）

### 一、需求

查找串与替换串都支持转义，如查找 `\n\n`、替换 `\n` 即删除空行。

### 二、上游实测定案（GSV 5.18.0 / GRegex 后端，非 PCRE2）

| 替换串 | `replace()`（单个） | `replace_all()`（批量） |
|---|---|---|
| `\n` | 换行 | 字面 `\n` |
| `\t` | 制表符 | 字面 `\t` |
| `\\` | 一个反斜杠 | 两个反斜杠 |
| `\1` | 展开为分组 | 展开为分组 |
| `$1` | 字面 | 字面 |

结论：同一库两条替换路径语义不一致——`replace_all()` 只展开反向引用、不展开
C 风格转义；这是「替换串写 `\n` 不生效」的根因，不是配置问题。另外替换框是单行
`Gtk.Entry`，物理上无法键入换行，故此前任何模式下都做不到「替换成换行」。

### 三、实现

- 新增 `escapecodec.py`（纯函数，24 例单测）：单遍扫描解码 `\n \r \t \\ \xHH
  \uHHHH`；`\1`–`\9` / `\0` 一律透传（交给上游展开）；未知序列与非法十六进制
  原样保留；`\x00` 与孤立代理项不产出（GtkTextBuffer 无法容纳）。单遍扫描是
  因为两次 `str.replace` 会把 `\\n` 二次解码成换行。
- 查找侧：非正则模式下解码（正则模式由 PCRE 自己解释 `\n`，再解码会破坏 `\\n`
  的字面语义）；切换「正则」「转义」都重放查找串，避免解码条件变更后仍用旧串。
- 替换侧分两条：单个替换交 `replace()`（它自己展开转义与引用，再解码会二次
  解释）；批量替换先解码再交 `replace_all()`（它不展开转义，必须由我们解码）。
- **批量替换的性能根因与修复**：`replace_all()` 在已挂载视图的缓冲区上逐处改动，
  每次触发重高亮 → 实测 3000 处匹配 **52 s**；改为在脱离视图的临时缓冲区完成替换，
  再一次性 `set_text` 写回（单 user action = 一步撤销，恢复光标位置）→ **0.047 s**。
  选区替换同法：选区文本搬进临时缓冲区跑同一套设置，整段一次写回；正则的锚点/
  环视天然只看选区内部，跨界匹配不会命中。
- `_count_matches()` 统一统计处数（零宽匹配前进一格防原地循环），替换处数不再
  依赖上游返回值，整篇与选区两条路径口径一致。

### 四、测试证据

- 新增 `tests/test_escapecodec.py` 24 例（简单转义、`\\n` 字面、非法十六进制、
  NUL/代理项拒绝、反向引用透传与 `\\1` 转字面、路径 `C:\temp` 的已知副作用钉死）——OK。
- 新增 `tests/test_escape_gui.py` 15 项断言全 true（真实 `replace_all` 路径）：
  删空行（2 处）、正则模式无需开关即生效、非正则 + 转义（查找 `\n` 命中换行、
  替换 `\t` 插制表符）、反向引用与转义共存、关闭转义时 `\n` 仍按字面匹配、
  选区路径全量命中 6 处（旧实现按模板长度推进会漏一半）、整篇替换计数、
  空替换不死循环、整篇一步撤销 + 光标保持、**3000 处匹配 0.068 s**（防退回
  二次复杂度）。
- 回归：非 GUI 173 例 OK（149 + 24 新增）；GUI 套件 selrepl 11、lineops 19、
  context 8、features 22 键全 true。
- 版本 1.10.0 → 1.11.0（paths.py、build_deb.sh）。

## 修订二十五（v1.12.0）：保存后标签改名 + 头部新建标签按钮

### 一、需求

1. 新标签保存到磁盘后，标签名未自动改成文件名（缺陷修复）。
2. 在头部「源码 / 分屏 / 预览」三按钮右侧加一个新建标签按钮。

### 二、根因与实现

- **根因**：`_write_doc_to_file()` 的 `link=True` 分支只写了文件、建立了源文件
  关联并更新 tooltip，从未同步 `doc.title` 与 tab 标题——标题与文件名是两条
  独立的数据路径，另存为操作遗漏了标题同步。
- **修复**：在 `link=True` 分支（首次另存 / 另存到新路径）取 `path.stem or
  path.name`（与「打开文件」命名规则一致，window.py:1513），同步 `page.title`、
  `tab.set_title`、`store.rename`，并刷新最近菜单与侧栏。`link=False`（已关联
  文件的 Ctrl+S 路径）不改标题——用户自定义标题不被覆盖。
- **新建标签按钮**：`tab-new-symbolic` 图标（Adwaita 实存），紧贴 `mode_box`
  右侧（prev_sibling 断言钉死位置），点击走 `win.new-tab` 动作（Ctrl+N 不变）。

### 三、测试证据

- 新增 `tests/test_savetitle_gui.py` 14 项断言全 true：按钮存在/位置/点击加页；
  保存后 tab、page、store 三处标题均为「我的笔记」，source_path 正确关联，
  tooltip 含完整路径；自定义标题在 link=False 写入后保持不变，文件内容正常更新。
- 回归：非 GUI 168 例 OK；GUI 套件 lineops 19 项、features 22 项全 true。
- 截图取证：`01-header-newtab.png`（按钮位于三按钮与撤销/重做之间）、
  `02-title-renamed.png`（保存后标签显示「我的笔记」+ toast）。
- 版本 1.11.0 → 1.12.0（paths.py、build_deb.sh）。

## 修订二十六（v1.13.0）：写作模式（居中限宽排版）

### 一、需求

编辑区文本收窄并在窗口中间显示，宽度可调 50% / 75% / 85%（可关闭）。入口为
头部 MenuButton（位于三态模式按钮与新建标签按钮之间、同组样式），Ctrl+Shift+M
循环切换（关闭 → 85% → 75% → 50%），仅作用于源码编辑区。

### 二、实现探针（先证伪再动手）

评估阶段的方案 A（Adw.ClampScrollable）被探针证伪，实测三个上游行为：

1. `Adw.ClampScrollable` 包 `GtkSource.View`：滚动正常，但 View 宽度**不按
   maximum-size 拉伸**（`hexpand` 无效，停在 88 字符自然宽度 792 px）；
2. `Adw.Clamp` 放进 ScrolledWindow：垂直滚动被切断（vadjustment 恒 0）；
3. `Gtk.Box` 子控件 `halign=CENTER` 不产生水平居中（compute_bounds x 恒 0）。

最终实现：`Box(撑满) = [左 hexpand 空白, 固定宽度 ScrolledWindow, 右 hexpand 空白]`，
宽度 `max(360, round(视口×比例))` 且不超过视口；关闭时隐藏空白、滚动区
`hexpand=True + size_request(-1)` 恢复铺满。宽度重算监听 `notify::width`（窗口缩放/
分屏拖拽），idle 落地 + 相等短路；页面未布局（宽 0）不缓存状态，map 后补偿应用。
档位存 meta `writing_width`，两条建页路径均应用。结论已沉淀 knowledge/gtk4-common.md。

### 三、测试证据

- 新增 `tests/test_writing.py` 6 例纯函数单测（百分比、缩放跟随、下限 360、
  不超视口、关闭/未布局、四舍五入）。
- 新增 `tests/test_writing_gui.py` 43 项断言全 true：按钮位置（mode_box 内、
  新建标签之前）；关闭态宽=视口；85/75/50 实际宽度与居中偏移（90/150/300 px，
  左右对称）；窗口 1200→900 缩放跟随（765）；第二个标签页同样受限；
  光标到文末滚动正常（底部余量 ≤ bottom-margin 64 px）；meta 持久化；
  循环顺序 off→85→75→50→off。
- 回归：非 GUI 174 例 OK；GUI 套件 lineops 19、features 22、context 8、
  sidebar 全值型输出无 False；快捷键清单 22 → 23（新增 Ctrl+Shift+M）。
- 截图取证：01-writing-off（铺满）、02-writing-85（居中、行号随内容）、
  03-writing-50（半宽居中）、04 全屏；头部放大图确认写作按钮与三按钮同组无缝。
- 版本 1.12.0 → 1.13.0（paths.py、build_deb.sh）。

## 修订二十七（v1.14.0）：按列提取（切列）+ 矩形列选（Alt 拖拽，决议解除）

### 一、需求与决策

用户给定例子（六行「- 欧洲中世纪全身板甲。」等）要求切出「- 欧洲」等首列。
拍板：③ 交互形态两者都做（命令式对话框 + Alt 拖拽矩形列选，2026-11-14 的
矩形选区否决由用户明确解除）；① 切分依据两种都做（分隔符 + 字符宽度）；
① 缺分隔符行原样保留并提示。

### 二、实测先行（探针证伪）

- 三种切法对用户例子的适配：字符宽 4 字符 6/6 正确（对「- 南北朝的札甲。」
  会切错）；分隔符「：」左半 6/6 正确；语义提取不可靠，不做。
- 现有正则替换已能实现（`^- (.{2}).*$` → `- \1`，GSV 多行锚点实测 6/6），
  故本功能定位为把正则参数化的易用性功能，不经 SearchContext。
- 矩形几何：`get_iter_location()` 返回 buffer 坐标（滚动后不变）；同一像素 x
  在比例字体下不同行落到不同列（几何列选语义成立）；**`get_iter_at_location`
  在 x 超出行末时返回 False**，拖到短行右侧会丢选区 → 改用 `get_line_at_y`
  （named tuple `target_iter`/`line_top`，y 超界自动钳制）定行。

### 三、实现

**切列**：`columnedit.take_column()` 纯函数（`take_column_sep` 多候选分隔符
以 `|` 分隔、`\|` 转义字面竖线；`take_column_width` 按码点截取）；未命中行
原样保留并回报计数。`EditorPage.apply_column_op()` 走与列编辑相同的整块替换
管线（单步撤销 + 替换后重选），块替换逻辑重构为 `_replace_block()` 共用。
对话框 `prompt_column_op()`：模式 radio + 实时预览（前 3 行对照 + 未命中数），
Ctrl+Shift+K，右键菜单「列编辑」子菜单与命令菜单各一条。

**矩形列选**（editor.py 新增区块）：
- 高亮用 TextTag（background_rgba 22% 透明蓝）逐行着色，不自绘覆盖层——
  避免滚动偏移换算；tag 变更不产生 undo、不置 modified。
- Alt+左键拖拽（GestureDrag CAPTURE + EventControllerKey 记录 Alt），
  y 定行、x 定列（`_column_at_pixel` 超行末钳制）；**buffer 坐标与窗口坐标
  之间并非简单平移（实测 buffer y=3 → 窗口 y=17，行 0 窗口区间 8~23），
  在 buffer y 上叠加半行高会跨行 → 行首窗口 y 直接使用、不加偏移**。
- 键盘：Delete/Backspace 删除、Ctrl+C 复制、Ctrl+X 剪切（从后往前删行，
  单步撤销）、Esc 取消；其余按键先退出矩形态再放行（不拦截输入法组字）；
  buffer 变更即失效清除。
- `rect_select_by_columns(l0,c0,l1,c1)` 为可编程入口（测试用）。

**连带修复**：`source_scroller` 默认 `hexpand=False`（Gtk.ScrolledWindow 的
默认值），写作模式关闭态从未被显式打开 → 编辑器宽度退化为最小内容宽 66px。
此为 v1.13.0 遗留缺陷，本次补 `set_hexpand(True)` 修复。

### 四、测试证据

- `tests/test_column_take.py` 19 例单测 OK（多候选/转义/未命中/空行/边界）。
- `tests/test_column_gui.py` 16 断言全 true（宽 4 得到用户期望结果、一步撤销、
  sep 模式未命中行保留、多候选、无选区只作用光标行、对话框预览含总行数与
  未命中数、动作注册、快捷键 Ctrl+Shift+K）。
- `tests/test_rectsel_gui.py` 19 断言全 true（几何路径真实拖拽坐标系 6 行矩形、
  删除结果=用户期望、单步撤销、复制剪贴板、剪切、Esc、其余按键放行、编辑失效）。
- 回归：非 GUI 193 例 OK；GUI column 16 / rectsel 19 / lineops 19 / writing 17 /
  features 19 / context 8 / selrepl 11 / escape 14 / savetitle 9 全 true。
- **真机事件实证**：XWayland 合成输入（xdotool）捕获 `press state=24
  （MOD1|MOD2，含 Alt）` 与 `dragbegin` 到达 view 且矩形逻辑触发——GNOME
  Wayland（mouse-button-modifier=<Alt>）**不拦截 Alt+拖拽的客户端事件**；
  〔**该结论已于修订二十八推翻**：同一环境下 xdotool 注入对普通拖拽同样无事件，
  说明日志不构成到达证据；真人操作的实际结论是「完全没有反应」。〕
  注入坐标受合成器指针管理影响，完整轨迹自动化重现不稳定，属测试工具限制。
- 截图：cmp-rect.png（六行第 5 字符起蓝色矩形高亮、前 4 字符无高亮）、
  cmp-deleted.png（删除后=用户期望的六短行，undo 按钮可用）。
- 版本 1.13.0 → 1.14.0。

## 修订二十八（v1.14.1）：Alt 拖拽矩形列选「毫无反应」根因修复

### 一、现象

v1.14.0 交付后真机操作反馈：按住 Alt + 左键拖拽，编辑器完全无反应
（无高亮、无光标变化、无任何视觉反馈）。但 `tests/test_rectsel_gui.py`
19 条断言全绿——因为那些断言全部走 `rect_select_by_columns()` 这个
**可编程入口**，绕开了真实指针链路。

### 二、根因（两条并存，均需修）

1. **桌面环境抢走了 Alt+左键拖拽**。本机 `XDG_CURRENT_DESKTOP=Unity`、
   `XDG_SESSION_TYPE=wayland`，且
   `org.gnome.desktop.wm.preferences mouse-button-modifier = '<Alt>'`。
   mutter 对「该修饰键 + 左键按下」做窗口移动 grab：grab 期间指针属于
   合成器，motion 不再转发给客户端，客户端侧只能看到一次按下（甚至看不到）。
   这解释了「一点都不动」。
2. **`Gtk.GestureDrag` 在这个场景下本就不可靠**。它在 CAPTURE 阶段注册，
   但 press 时并不接管事件序列；`GtkTextView` 自带的 gesture 先 claim，
   等拖动距离超过阈值、该触发 `drag-begin` 时，我们的 gesture 已被 deny，
   `drag-begin` 永不触发。也就是说即使没有被窗口管理器占用，这条链路
   也是「看运气」的——这是比第 1 条更根本的实现缺陷。

### 三、修复

- **事件接入改为自持**：`Gtk.GestureClick`（CAPTURE，主键）接管按下/松开，
  `Gtk.EventControllerMotion`（CAPTURE）跟踪移动，矩形由我们自己按像素算，
  不再依赖 `GestureDrag` 的阈值与序列归属。
- **3 px 抖动阈值**：按下后位移不足 3 px 不算拖拽，避免 Alt+单击误拉出空矩形。
- **修饰键接受 Shift+Alt 与单独 Alt**：Shift+Alt 是 VS Code 等编辑器在
  Linux 上的通行列选绑定，且 `mods != mouse-button-modifier` 时 mutter 不启动
  窗口移动 grab，因此在 Unity/GNOME 下稳定可用；单独 Alt 保留给未占用它的
  桌面环境。快捷键清单文案同步改为「Shift+Alt + 拖拽」。
- 每次 motion 折叠原生选区（`place_cursor`），避免矩形高亮与 `GtkTextView`
  拖选两套选区并存。

### 四、测试证据

- `tests/test_rectsel_gui.py` 19 → **27 条断言全 true**，新增 8 条专测指针链路：
  `ptr_alt_anchor` / `ptr_alt_rows_six` / `ptr_alt_text_tail` /
  `ptr_kept_after_release` / `ptr_shift_alt_anchor` / `ptr_jitter_ignored` /
  `ptr_shift_alt_rows_six` / `ptr_plain_press_clears`（用 FakeGesture 注入
  press 时的修饰键状态，直接驱动 `_on_rect_press/_on_rect_motion/_on_rect_release`）。
- 回归：非 GUI **198 例 OK**；GUI rectsel 27 / column 16 / lineops 19 /
  writing 17 / features 19 / context 8 / selrepl 11 / escape 14 / savetitle 9
  全 true。
- **注入工具的坑（记录备查）**：xdotool 在本机 Wayland 会话对 XWayland 窗口
  完全不产生事件（普通拖拽与键盘均无）；mutter 的
  `org.gnome.Mutter.RemoteDesktop` 在 GNOME 50 上要求
  Screencast 会话以 `remote-desktop-session-id = SessionId(UUID)` 关联、
  且由 RD 会话的 `Start` 启动，`NotifyPointerMotionAbsolute/NotifyKeyboardKeysym`
  调用可成功返回但事件不落到客户端（v50 已转向 libei/EIS）——因此「真机事件
  自动化注入」目前不可行，回归只能覆盖到 widget 方法层。
- 版本 1.14.0 → 1.14.1。

### 五、残留风险

若用户桌面环境把 **Shift+Alt+左键** 也绑定为窗口操作（少见），则两种组合
都会失效。届时可改为「先按 Ctrl+Shift+K 进入列选择模式，再普通拖拽」的
兜底形态——需用户拍板后实施，本次不做。

## 修订二十九（v1.14.2）：矩形列选的右键复制/剪切失效

### 一、现象

v1.14.1 后拖拽已能拉出蓝色半边透明矩形，但右键菜单里的「复制 / 剪切」是灰的、
点了没反应，用户判断「其实没有真正选中文字」。

### 二、根因

矩形高亮是 `Gtk.TextTag`（`background_rgba`）逐行着色，**不进入
`GtkTextBuffer` 的连续 selection**；而 `GtkTextView` 内置右键菜单的
「复制/剪切」按 `get_selection_bounds()` 计算 enabled——矩形状态下它恒为空，
于是永远是灰的。这是模型差异，不是 bug 修复不了的缺陷：逐行不连续的矩形
本来就没法表达成单一连续区间。

### 三、修复

- 矩形态下右键改弹**自己的** `Gtk.PopoverMenu`：三项「复制列选区 / 剪切列选区 /
  删除列选区」，动作挂在窗口（`win.rect-copy` / `win.rect-cut` / `win.rect-delete`）。
  由 `GestureClick(SECONDARY, CAPTURE)` 触发并 `CLAIMED` 序列，避免内置菜单
  同时弹出；无矩形选区时直接 return，不拦截，内置菜单照常。
- `Window.rect_op(kind)` 统一执行并给 toast 反馈（「已复制 N 行列选区」等），
  无选区时提示「先 Shift+Alt + 拖拽选出一块矩形区域」，不静默。
- 键盘路径不变：Ctrl+C / Ctrl+X / Delete / Esc 仍由 `_on_rect_key_pressed`
  在 CAPTURE 阶段消费（内置复制拿到的是空选区，必须由我们先处理）。

### 四、测试证据

- `tests/test_rectsel_gui.py` 27 → **42 条断言全 true**，新增：
  `ctrl_c_consumed` / `ctrl_x_consumed` / `win_actions_registered` /
  `menu_three_items` / `menu_first_action` / `rectop_keeps_empty` /
  `rectop_delete_shrinks` / `rectop_cleared` / `right_click_popup` /
  `right_click_claimed` / `plain_right_click_passthrough` / `popup_unparented`。
- 回归：非 GUI **198 例 OK**；GUI 九套全 true（rectsel 42 / column 24 /
  lineops 19 / writing 43 / features 22 / context 8 / selrepl 11 /
  escape 15 / savetitle 14；统计口径改为 JSON 解析取键值与 false 计数，
  旧的 `grep ': false'` 计数法对含字符串值的输出会误报）。
- 版本 1.14.1 → 1.14.2。

## 修订三十（v1.14.3）：矩形列选按用户指令整体移除

### 一、决定

v1.14.1（重做事件链路）、v1.14.2（补右键菜单）两次尝试后，用户实测仍不可用，
且反馈**原有的 Shift+点击扩展选区等原生选择行为被破坏**，明确指令：
「将 Shift+Alt、Alt + 左键拖拽及相关菜单一并删除」。

即：该功能从代码库中整体移除，不保留开关、不保留休眠代码。

### 二、移除清单

- `editor.py`：整块矩形列选实现（`_install_rect_selection`、`_rect_tag`、
  `_on_rect_press/_motion/_release`、`_collapse_cursor`、`_update_rect_selection`、
  `_paint_rect_selection`、`rect_select_by_columns`、`clear_rect_selection`、
  `has_rect_selection`、`rect_text`、`rect_copy`、`rect_delete`、
  `_on_rect_key_pressed`、`_rect_menu_model`、`_on_rect_secondary`、
  `_on_rect_menu_closed`、`_alt_down`/`_rect_*` 状态字段、
  `GestureClick(LMB/SECONDARY)` 与 `EventControllerMotion`、`EventControllerKey(Alt)`、
  `rect-selection` TextTag，以及 `_on_buffer_changed` 里的清理调用）。
- `window.py`：`rect_op()` 方法、`win.rect-copy` / `win.rect-cut` /
  `win.rect-delete` 三个动作、快捷键清单中的矩形条目。
- `tests/test_rectsel_gui.py`：整个套件删除（含 pyc）。
- **保留**：按列提取 `take_column`（Ctrl+Shift+K / 菜单「按列提取」）——这是
  另一条功能，与本次移除无关。

### 三、验证

原生选择行为不再被任何自定义控制器干预：`GtkTextView` 的 Shift+点击、
拖拽选词、内置右键菜单（复制/剪切/粘贴）均回到默认链路。

- `tests/test_features_gui.py` 新增 3 条防回归断言（22 → 25）：
  `no_rect_action`（三个动作不存在）、`no_rect_shortcut_text`（快捷键清单无「矩形」）、
  `no_rect_page_api`（页面侧无 rect 相关入口/状态）。
- 回归：非 GUI **198 例 OK**；GUI 八套全 true（column 24 / lineops 19 /
  writing 43 / features 25 / context 8 / selrepl 11 / escape 15 / savetitle 14）。
- 版本 1.14.2 → 1.14.3。

### 四、结论与后续纪律

矩形块选在本项目**不再实现、不再建议、不再排期**（与 2026-11-14 的原始否决
一致，本次是用户主动收回 2026-11-17 的解除令）。若要列操作，走「按列提取」
（切出单列）与「每行加前缀/后缀」等命令式路径。

## 修订三十一（v1.15.0）：打字机模式（光标行垂直居中）

### 一、需求与形态

与写作模式（水平限宽居中）互补的垂直方向：开启后光标所在行始终滚到视口
垂直中点，滚动随光标走。快捷键 `Ctrl+Shift+T`，命令菜单「视图」组有开关项，
状态持久化（meta `typewriter`，写入用 `wait=True`——切换频率极低，换取
重启后状态确定）。仅作用于源码编辑区；与写作模式正交可叠加。

### 二、实现要点

- 监听 `buffer` 的 `notify::cursor-position`，经 `GLib.idle_add` 合并防抖
  （连续打字合并为一帧，与写作模式同一 idle 短路写法）；
- 滚动用 `view.scroll_to_mark(insert, 0.0, use_align=True, 0.0, 0.5)`，
  **不用 `scroll_mark_onscreen`**（写作模式回归实证：它只保证可见、不做对齐）；
  文档头尾由 API 自动钳制；
- 两条抑制路径：`get_has_selection()` 为真（拖选时插入点在选区端点，逐次
  居中会上下抖动）；`_folding.mutating`（折叠/展开重排，避免把上下文滚走）；
- 页面级状态：`EditorPage.set_typewriter()`；窗口级 `win.typewriter-mode`
  stateful action + `win.toggle-typewriter`，`add_tab` 两条建页路径都应用当前状态。

### 三、测试证据

- 新增 `tests/test_typewriter_gui.py` **22 条断言全 true**：动作注册、初始
  关闭态、开启后中部行居中（偏差 ≤ 2 行高）、首行钳制（value==0）、末行
  底差 ∈ [0, 80]、拖选抑制、关闭后不滚、meta 持久化、新建标签页自动带状态、
  与写作模式 75% 叠加后垂直居中仍成立、快捷键加速键可解析。
- 回归：非 GUI **198 例 OK**；GUI 九套全 true（column 24 / lineops 19 /
  writing 43 / features 25 / context 8 / selrepl 11 / escape 15 / savetitle 14 /
  typewriter 22）。
- 版本 1.14.3 → 1.15.0。

## 修订三十二（v1.16.0）：打字机模式固定百分比 + 段落遮罩 + 专用按钮

### 一、需求

在 v1.15.0 打字机模式（固定垂直居中）基础上，按用户拍板：

1. 光标行位置改为**自定义百分比**（默认 33 ≈ SoloMD 截图的 1/3 处）；
2. 当前段落以外的文本加 **TextTag 遮罩**（褪色退后，非真模糊——GTK4
   无法对字形做高斯模糊，评估结论先行说明）；
3. 头部「写作模式」按钮右边加同风格「打字机模式」MenuButton。

### 二、实现

- **editor.py**：`paragraph_bounds(lines, idx)` 纯函数（空行分隔；标题行
  自成一段；` ``` `/`~~~` 围栏块整段含开合行；缩进续行并入所在段）；打字机
  `_typewriter_yalign` 百分比（10~90 钳制）；段落遮罩 `set_paragraph_dim()`
  → idle 重算 → `paragraph-dim` TextTag（主题前景色 0.32 前景透明度 +
  0.05 背景雾面，随主题 `set_scheme` 重算；优先级高于语法高亮，遮罩段整体
  褪色为预期行为）。遮罩与滚动**相互独立**，可只遮罩不滚动。
- **收敛补滚（关键坑）**：远距离跳转或刚换文本时目标行可能落在未校验的
  布局区，GTK 第一拍 `scroll_to_mark(use_align=True)` 只按「确保可见」滚，
  布局校验完成后视口被推离目标行（探针实证：value 随校验渐进漂移直至底
  部）。修复：滚动后测量「光标行中心与视口 target×page_size 的像素距离」，
  偏差 > 2px 且补滚 < 3 拍则下一拍重滚，直至收敛；光标移动时计数复位。
- **window.py**：`win.typewriter-align`（stateful 字符串，25/33/50/66/75，
  meta `typewriter_align`）与 `win.paragraph-dim`（stateful bool，meta
  `paragraph_dim`）两个动作；`_apply_typewriter_state()` 统一建页接线
  （add_tab 与磁盘打开两条路径）；`input-keyboard-symbolic` MenuButton 紧随
  写作模式按钮（同 linked 组），菜单含两个开关 + 「光标行位置」子菜单；
  命令面板新增遮罩与位置命令。
- **keymap.py**：`Ctrl+Shift+T` 描述改为「光标行固定于视口百分比处」。

### 三、测试证据

- 新增 `tests/test_paragraph.py` **12 例**（段落识别纯函数：空行分段、
  空行自成段、标题独立、围栏整块、~~ 围栏、未闭合围栏、越界钳制、空文档、
  缩进续行、连续标题、文末段落）。
- `tests/test_typewriter_gui.py` 重写为 **52 条断言全 true**：四动作注册、
  默认 33、按钮位于写作模式右侧（邻位断言）、align=50 居中（±2 行高）、
  align=33 落点 frac=0.336（0.28~0.42）、首行/末行钳制、拖选抑制（滚动）、
  新标签页带三项状态、遮罩分段正确（段外含段间空行/标题/围栏都打 tag、
  当前段与围栏内不打）、光标进围栏后重刷、**选区冻结遮罩刷新**（sig 保持、
  解除选区后恢复）、关闭后 tag 全清、meta 持久化、与写作模式 75% 叠加、
  Ctrl+Shift+T 可解析。
- 坐标口径修正（探针实证）：`buffer_to_window_coords(TEXT)` 返回的 y 已是
  **视口相对坐标**，占比计算不再减 `adj.value`（旧口径多减导致负值假象）。
- 回归：非 GUI **221 例 OK**（209 旧 + 12 新）；GUI 九套全 true（typewriter
  52 / column 24 / lineops 19 / writing 43 / features 25 / context 8 /
  selrepl 11 / escape 15 / savetitle 14）。
- 截图取证：亮色主题下非当前段落明显褪灰、当前段落清晰（短文档钳制正常）。
- 版本 1.15.0 → 1.16.0。

### 四、残留风险

- 遮罩观感是「褪色退后」而非毛玻璃模糊——如需更强雾感可调
  `_refresh_dim_colors()` 的两个透明度（0.32 / 0.05）。
- 极长文档跨段移动会触发一次全文 `get_text`（重算段落边界），MB 级文档
  有可感知延迟；当前以段界签名短路，光标段内移动零开销。

## 修订三十三（v1.16.1）：全应用复制统一为显式 UTF-8 文本

### 一、需求与根因

用户报告：在编辑区复制 Markdown 表格（源文档
`~/obsidian/RebornMing/04-背景设定/郑居敬关系表.md`）后，GNOME Shell 剪贴板
查看器把中文显示成 `\E4\BA\8C\E5\8D\81...` 形式的反斜杠转义。

- `\XX` 是 GLib 把 UTF-8 字节按 Latin-1 呈现时的回退写法，对应 X11 传统
  `STRING`/裸 `text/plain` 目标被按单字节解读的路径。
- 探针实证：本机 GTK 4.22 的 `Gdk.Clipboard.set(str)` 与内置
  `GtkTextBuffer.copy_clipboard()` 都只提供裸 `text/plain` +
  `text/plain;charset=utf-8`，没有 `UTF8_STRING`。
- 用户指令字面要求 `GdkClipboard.set_text()`；但本机 GIR 把该 API 标为
  `introspectable="0"`，PyGObject 无法调用；且其 C 实现等价于
  `set(clipboard, G_TYPE_STRING, text)`，产生的 targets 与现状相同，改用无效。
  实际等价做法是 `set_content()` + `new_for_bytes("UTF8_STRING", ...)`。

### 二、实现

- 新增 `src/scratchpad/clipboard.py`：统一入口 `set_clipboard_utf8()`，显式
  提供 `UTF8_STRING` 与 `text/plain;charset=utf-8` 目标。
  **注：本版「刻意不提供裸 text/plain」的判断是错的，已在 v1.16.2 纠正，
  详见修订三十四。**
- `window.py`：`_on_window_key()` 在窗口 CAPTURE 阶段拦截 `Ctrl+C`，仅当焦点
  在编辑区且有选区时改走 `copy_as_utf8_text()` 并返回 True（抢在 GtkTextView
  内置 `text.copy-clipboard` 之前）；无选区或焦点在搜索框等控件时交还原生行为。
- `editor.py`：新增 `copy_as_utf8_text()`（无选区则整篇），右键菜单新增
  「复制为 UTF-8 文本」项，绑定 `win.copy-as-utf8-text` 动作。
- `sidebar.py`（复制路径 / 复制文件名）与 `fssearch_ui.py`（复制文件路径）
  两处 `.set()` 写入统一改用同一 helper——全应用所有复制入口归一。

### 三、测试证据

- 新增 `tests/test_copy_utf8_gui.py`：9 组断言全 true，覆盖右键菜单项、
  GAction 选区/整篇复制、Ctrl+C 拦截（含焦点在编辑区/不在编辑区两种）、
  helper 自身写入；中文表格（含 `<br>`、中文、Markdown 管道行）读回逐字节相等。
  **注：当时的 formats 断言写成了「无裸 text/plain」，属错误判据，见修订三十四。**
- 回归：现有非 GUI 测试 **209 例 OK**，无回归。
- 构建：`dist/gscratchpad_1.16.1-1_all.deb`（旧版 1.16.0 按纪律自动清理），
  包内确认含新增 `clipboard.py` 与四个改动模块。
- 版本 1.16.0 → 1.16.1。

### 四、残留风险

- GtkTextView 内置右键菜单里的「复制」条目属于 GTK 内部实现，无法通过
  `set_extra_menu()` 替换；该条目仍走原生 `text.copy-clipboard`（裸
  `text/plain`）。已提供独立的「复制为 UTF-8 文本」菜单项与 Ctrl+C 路径
  作为正确入口。
- 剪切（Ctrl+X）沿用 GTK 内置行为，不在本次「复制行为」范围。

## 修订三十四（v1.16.2）：修复 v1.16.1 复制完全失效的回归

### 一、现象与根因

用户实测：安装 v1.16.1 后，**Ctrl+C 与右键「复制为 UTF-8 文本」都无法复制**。

- 根因：`set_clipboard_utf8()` 只提供 `UTF8_STRING` +
  `text/plain;charset=utf-8`，**没有裸 `text/plain`**。X11 后端虽会在 TARGETS
  里自动声明 `text/plain` / `STRING` / `TEXT` / `COMPOUND_TEXT`，但 provider
  实际没有对应数据；消费者请求 `text/plain` 直接拿到
  `g-io-error-quark: 沒有可傳輸剪貼簿內容的相容格式 (15)`，表现为复制失效。
- 为何测试漏掉：测试用 `read_text_async()` 读回，它挑的是
  `text/plain;charset=utf-8`，恰好绕开了失效的 `text/plain` 路径——**同进程
  读回制造了假通过**。跨进程探针（独立 GTK 进程 / `wl-paste`）在沙箱中因
  X11↔Wayland 桥接整体超时，未能第一时间暴露；最终用「按指定 target 逐项
  `read_async`」才定位到错误 15。

### 二、修正

- `_TARGETS` 改为三项，且把 `UTF8_STRING` 放最前：
  `("UTF8_STRING", "text/plain;charset=utf-8", "text/plain")`。
  兼顾两点：支持 UTF-8 的消费者优先选 UTF8_STRING；只认 text/plain 的消费者
  （GtkTextView、GNOME Shell 等）也能正常读到。X11 TARGETS 顺序随之变成
  `UTF8_STRING` 在前，有利于纠正原先的 Latin-1 误读显示。
- 明确原则：**不能靠「移除 text/plain」规避 Latin-1 误读**——那等于牺牲
  复制可用性，是本末倒置。
- `tests/test_copy_utf8_gui.py` 的错误判据 `no_bare_text_plain` 改为
  `has_text_plain`，防止同类回归再次被测试掩盖。

### 三、测试证据

- 新增 GUI 断言全 true：`formats = ["UTF8_STRING", "text/plain",
  "text/plain;charset=utf-8"]`，`has_text_plain = true`；选区/整篇/Ctrl+C/
  helper 四条路径均逐字节相等，Ctrl+C 拦截与焦点外交还正常。
- 按 target 逐项读取探针：`text/plain` 从错误 15 变为格式匹配可读。
- 回归：现有非 GUI 测试 **209 例 OK**。
- 构建：`dist/gscratchpad_1.16.2-1_all.deb`（旧版按纪律自动清理）。
- 版本 1.16.1 → 1.16.2。

### 四、残留风险

- X11 传统 `STRING` target 仍由后端自动声明但无数据（请求报错误 15）；
  只认 `STRING` 的极老旧消费者仍可能读不到。现代消费者均走
  `UTF8_STRING` / `text/plain` / `text/plain;charset=utf-8`，不受影响。
- GtkTextView 内置右键「复制」与剪切 Ctrl+X 仍未纳入改造（见修订三十三）。

## 修订三十五（v1.16.3）：默认 UTF-8 归一 + 编码子菜单 + 启动收起侧边栏

### 一、需求

1. 所有复制动作默认都应是 UTF-8，右键不再放冗余的「复制为 UTF-8 文本」项；
   用户拍板改为「复制为其它编码」**子菜单**（GBK / UTF-16）。
2. 应用每次启动时默认收起侧边栏，不记忆上次的展开状态。

### 二、实现

- `clipboard.py`：拆出 `set_clipboard_encoded(text, encoding)`，
  `set_clipboard_utf8()` 成为其 utf-8 分支的薄封装（仍走三目标，保持默认
  复制行为不变）。非 UTF-8 编码提供 `text/plain;charset=<enc>` 与裸
  `text/plain`，让认识 charset 的消费方能正确解码。
- `editor.py`：新增模块级 `COPY_ENCODINGS = (("GBK","gbk"),("UTF-16","utf-16"))`
  作为单一事实来源；`copy_as_encoded(encoding)` 复用选区/整篇取值逻辑；
  右键由单条 UTF-8 项换成「复制为其它编码」子菜单。
- `window.py`：`win.copy-as-utf8-text`（无参）换成
  `win.copy-as-encoding`（`s` 参数）；侧边栏 ToggleButton 的初始 `active`
  由读取 `sidebar_visible` 偏好改为固定 `False`，每次启动一律收起，
  应用内仍可用 F9 / 头部按钮展开。

### 三、测试证据

- `tests/test_copy_utf8_gui.py` 全 true：无 UTF-8 冗余项、有编码子菜单、
  GBK/UTF-16 动作存在且写入对应 MIME；默认 Ctrl+C / 整篇 / helper 的
  formats 仍为 `["UTF8_STRING", "text/plain", "text/plain;charset=utf-8"]`；
  启动侧边栏收起为 true。
- 修正两处历史断言：`test_context_gui.py` 的 extra-menu 项数 5→6
  （v1.16.1 加复制项时就该更新），`test_sidebar_gui.py` 的
  `initial_visible` 改为 `initial_hidden`。
- 非 GUI 全量 **209 例 OK**；maintenance / context GUI 全 true。
- 构建 `dist/gscratchpad_1.16.3-1_all.deb`（旧版自动清理）。
- 版本 1.16.2 → 1.16.3。

### 四、残留风险

- 「复制为 GBK / UTF-16」的内容是对应编码的原始字节；按 UTF-8 解读的
  普通消费者会看到乱码，这是用户主动选非默认编码的预期结果。
- X11 传统 `STRING` target 仍无数据（见修订三十四）。

## 修订三十六（v1.16.4）：设置宽度覆盖预览区 + 预览隐藏 frontmatter

### 一、需求（评估后用户拍板：方案 A）

1. 写作模式宽度更名为「设置宽度」，源码与预览两区同时生效（内部
   action `win.writing-mode`、meta key `writing_width` 保留，避免偏好迁移）。
2. 预览不显示 md 文档的 YAML frontmatter。

### 二、实现

- **预览区宽度（方案 A，GTK 布局层）**：`editor.py` 将 `PreviewPane` 包进
  与 `source_box` 同构的居中结构（`preview_box` + 两侧 hexpand pad），
  `Paned` end_child 改为 `preview_box`；`_apply_writing_width` 拆出
  `_apply_pane_width()` 分别按各自视口宽计算源码/预览目标宽。
- **可见性切换根因（实测）**：`set_mode` 切换可见性后的首次宽度分配
  **不触发 `notify::width`**，state 缓存停留旧值导致预览模式宽度不重算
  （实测 412px ≠ 765px）。修复：`set_mode` / `map` 后经
  `_kick_writing_apply()`（20ms timeout）补算；分配未完成（视口宽 0）时
  有限重试（30 次 × 20ms）。另修 `set_mode` 切换对象：原只切
  `self.preview`，顶层 `preview_box` 永远可见，SOURCE 模式下预览区空占
  Paned 分割——现统一切 `preview_box`。
- **UI 文案**：tooltip / 下拉菜单提示 / 命令面板四条 / 快捷键提示
  （Ctrl+Shift+M）/ keymap 说明由「写作模式」改「设置宽度」，命令面板
  keywords 增加「宽度 width」；菜单档位标签不变。
- **frontmatter 隐藏**：`markdown_render._strip_frontmatter()` 在
  `render_body` 入口剥离文档开头 `---` 包围块（或 `...` 收尾），仅当首行
  是 `---` 且存在闭合行才剥离——正文中间 hr、setext 标题（`标题行\n---`）、
  未闭合块均按普通 Markdown 渲染。编辑区原文不动；PDF 导出经
  `render_document` 自动继承。

### 三、测试证据

- `tests/test_markdown.py` 新增 `FrontmatterTestCase` 9 例：标准块、
  `...` 收尾、空块、无尾随空行、未闭合（保留为 hr+文本）、正文 hr、
  setext 不误剥、代码块混排、PDF 导出继承剥离——全过。
- `tests/test_writing_gui.py`：`_check_pct` 扩展预览区断言（可见时）；
  新增预览模式场景——切 MODE_PREVIEW 后预览宽 = round(视口×85%) 且居中
  （实测视口 900、宽 765、居中 true）；仅对可见区域断言，杜绝隐藏控件
  残留分配造成的假失败。全量断言 FAILED KEYS: NONE。
- 回归：非 GUI 全量 **218 例 OK**；`test_typewriter_gui.py` FAILED KEYS: NONE。
- 构建 `dist/gscratchpad_1.16.4-1_all.deb`（旧版自动清理）。
- 版本 1.16.3 → 1.16.4。

### 四、残留风险

- 预览 CSS 左右 padding（34px×2）使预览正文比同档位编辑区文本窄约 68px；
  居中观感一致，未做补偿，实机目视后可再调。
- WebView 未创建时（预览从未加载）`PreviewPane` 自然宽度为 placeholder
  文本宽，设置宽度下 size_request 下限（≥360px）保证布局不塌缩。

## 修订三十七（v1.16.5）：每文档模式持久化 + 启动恢复焦点补偿

### 一、需求

文档在预览/分屏模式关闭应用，重开应回到该模式；且重开后可直接编辑
（用户实测：重开显示编辑模式但打字无效，需切一次模式才能编辑）。

### 二、诊断（两阶段探针，独立进程复现真实「关闭→重启」）

- 探针证实恢复链路本身正常：view_mode=preview 关闭后重开，
  restore_session 正确恢复 preview（page_mode / 按钮 / meta 三者一致）。
- 「不能编辑」未在探针中复现为数据层故障（editable/sensitive/insert 均
  正常）；最可能机制：**启动恢复时窗口尚未显示，grab_focus 无效**，
  重开后焦点不在编辑器，打字没反应；切一次模式时 set_mode 再次
  grab_focus（此时窗口已 map）才生效。
- 探针另核实：关闭流程不覆盖 view_mode；`window.set_mode` 只切当前页
  （各页模式事实上独立），但恢复时被全局 view_mode 统一覆盖。

### 三、实现

- **每文档模式持久化**：meta key `mode:<doc_id>`。
  - 写入：`window.set_mode()` 存当前页；`_persist_session()`（关闭）存
    全部打开页。
  - 恢复：`add_tab()` / `open_document()` 按 `mode:<doc_id>` 恢复各页
    （缺省回退全局）；`restore_session()` 不再用全局 view_mode 覆盖全部
    页，窗口模式/按钮跟随当前选中文档；`_on_selected_page()` 切标签时
    窗口模式跟随该文档自己的模式（handler_block 防回环，不写全局
    view_mode）。
- **焦点补偿**：`restore_session()` 挂 map 信号，窗口首次显示后 idle
  再 grab_focus 一次（`_on_map_focus_restore` / `_focus_current_view`，
  预览模式与关闭中不抢）。

### 四、测试证据

- 两阶段探针（已按纪律用后即删）：恢复后 page_mode=preview、按钮
  preview active；模拟点击编辑按钮后 editable=True、has_focus=True、
  buffer 插入成功；map 后焦点补偿 `win_focus_is_view=True`。
- 非 GUI 全量 **218 例 OK**。
- 版本 1.16.4 → 1.16.5；构建 `dist/gscratchpad_1.16.5-1_all.deb`。

### 五、残留说明

- `window.set_mode` 在预览模式下也无条件 grab_focus（编辑器仍持窗口内
  焦点），属现状行为，未改动。
- 若用户实测仍出现「编辑模式但不可编辑」，下一层排查方向为真机 WM
  焦点时序与 WebView 加载竞态（探针环境无法复现）。

## 修订三十八（v1.17.0 / Android 0.9.0）：WebDAV 备份 + 多端同步 v1

**日期**：2026-11-25　**范围**：桌面 + Android（本次为双端同规约合体发版）

### 一、功能内容

- **桌面 WebDAV 自动备份（方案 B）**：`webdav.py` 传输层（stdlib urllib，PUT/GET/HEAD/
  PROPFIND/MKCOL，Basic 认证，内嵌 `user@host` URL 解析，12s/30s 超时 + 1 次重试）；
  `backupzip.py` schema 3 打包/解包（与 Android `BackupExporter` 字节兼容）；
  `cloud.py` CloudManager（指纹短路、wal_checkpoint 快照、30 分钟备份周期、libsecret
  密钥存储 + meta 明文兜底）；远端文件名 `gscratchpad-desktop.zip`（与 Android
  `gscratchpad-cloud.zip` 区分，互不覆盖）。
- **多端同步 v1（`docs/SYNC_PROTOCOL.md`）**：每设备目录 `sync/<device-id>/` 下
  manifest.json + docs.zip + assets 内容寻址文件；时间戳墓碑（updated_at 新者胜）；
  三态合并规划器（仅远端变→应用；双变冲突→updated_at 新者胜、败者保全、平局本地胜；
  仅本地变→推送）；隐式墓碑发现防陈旧 manifest 复活；meta 永不同步；assets 差量上传。
  桌面 `syncengine.py` + Android `SyncEngine.kt` 逐语义对应，共用 SM-01…SM-11 夹具。
- **Android 接入**：`SyncDav.kt`（HttpURLConnection）+ `SyncEngine.kt` +
  `DocumentDao.applyRemote`（revision=max(local,incoming)+1）+ 删除/清空记录墓碑 +
  云对话框「自动同步（打开应用时）」开关、「立即同步」按钮、最近同步结果显示；
  onResume 触发（无后台调度，用户拍板）。

### 二、测试证据

- 桌面全量 **239 例 OK**（`/usr/bin/python3 -m unittest discover -s tests`），含新增
  `test_sync_merge.py`（SM-01…SM-11 纯规划器夹具）、`test_cloud_local.py`（stub
  WebDAV 双设备 E2E：拉推/冲突保全/删除传播/对端重建恢复/资产同步/状态往返）、
  `test_cloud_gui.py`（对话框构建、删除→墓碑落盘）。
- Android JVM 全量 **223 例 OK**（`gradlew :app:testDebugUnitTest`），含新增
  `SyncEngineTest`（18 例：SM 夹具复刻 + MemoryDav 双设备 E2E + 认证/URL 解析）。
- **真实服务器 E2E 全过**（AList `http://10.42.239.55:5244/dav/hdd/test`，用户开通
  WebDAV 写权限后）：双设备 推→拉→互改→冲突 updated_at 新者胜+败者保全→删除传播
  →删除正文保全，七项断言全部 PASS（e2e 临时目录用后即删，远端已清理）。

### 三、过程中修复的真实缺陷

1. **Android assets 永不同步**：`fetchPeerManifests` 把 manifest 的 `assets` 数组原样
   存 `JSONArray`，`fetchPeerAssets` 的 `as? List<String>` 必失败——manifest 解析时
   转为 `List<String>`。
2. **冲突计数漏计**：双端引擎都只在「本地胜→保全」分支累加 conflicts，「对端胜→应用」
   分支不计数——改为直接取 planner 统计（桌面 `result.conflicts = plan.stats`）。
3. **JVM 测试传输抽象**：桌面 JDK 的 HttpURLConnection 拒绝 MKCOL/PROPFIND 自定义
   方法（Android 运行时无此限制），引擎改依赖 `DavOps` 接口，测试注入 MemoryDav。

### 四、版本与产物

- 桌面 1.16.5 → **1.17.0**；`dist/gscratchpad_1.17.0-1_all.deb`。
- Android 0.8.3/versionCode 46 → **0.9.0/versionCode 47**；双 ABI 正式签名
  release APK（upload key，SHA-256 指纹与登记一致）：
  `scratchpad-arm64-v8a-release-0.9.0.apk`、`scratchpad-x86_64-release-0.9.0.apk`。
- 真机安装回归未执行（无连接设备）；UI 观感（云对话框新开关/按钮）待真机目视。

## 修订三十九（v1.17.1）：标题栏「同步」按钮

**日期**：2026-11-25　**范围**：桌面

### 一、功能内容

- 标题栏右上「主题」与「查找」之间新增「同步」按钮（`emblem-synchronizing-symbolic`），
  点击触发 `win.cloud-sync-now`（与命令菜单「立即同步」同一动作）。
- 最近一次云任务状态（同步/备份结果、错误）除 toast 外同步写入按钮 tooltip，
  悬停即可回看上次结果。
- 打包顺序说明：`pack_end` 从右到左为 菜单 → 查找 → 同步 → 主题，
  视觉左到右即 主题 → 同步 → 查找 → 菜单。

### 二、测试证据

- `tests/test_cloud_gui.py` 新增两条断言：标题栏三按钮 x 坐标
  主题 < 同步 < 查找（`compute_bounds` 元组取 origin_x）；初始 tooltip
  为「立即同步（WebDAV）」。冒烟全项 true（含 dialog_fully_built 等原有项）。
- 全量回归 **239 例 OK**（`/usr/bin/python3 -m unittest discover -s tests`）。

### 三、版本与产物

- 桌面 1.17.0 → **1.17.1**；`dist/gscratchpad_1.17.1-1_all.deb`。
- Android 本轮无代码改动，维持 0.9.0/versionCode 47，不出包。

## 修订四十（v1.17.2）：修复新设备首次同步跨线程 SQLite 崩溃

**日期**：2026-11-25　**范围**：桌面

### 一、故障现象

设备 A（Android）备份到 WebDAV 后，新设备（桌面）配同目录同步时报错 toast：
「同步失敗：SQLite objects created in a thread can only be used in that same
thread. …」，同步整体失败。

### 二、根因

`Store.open()` 在主线程创建 `_reader` 连接（sqlite3 默认
`check_same_thread=True`）；云同步/备份在 `gsp-sync`/`gsp-backup` 守护线程里
运行，引擎与备份的 `all_documents()` / `get()` / `folders()` /
`local_revisions()` / `fingerprint()` 均经 `_query` 直接使用 `_reader` →
跨线程 `ProgrammingError`。此前未暴露：E2E 均在主线程直跑 `engine.run()`，
GUI 冒烟未走真实网络同步。

### 三、修复

`store.py _connect()` 加 `check_same_thread=False`：WAL 模式下 reader 并发读
安全，读侧本就有 `_read_lock` 串行化；writer 连接仍只在 worker 线程内使用。
Android 不受影响（Room 自身线程安全）。

### 四、测试证据

- 新增回归 `test_engine_runs_in_worker_thread`：真实 Store + 非主线程完整跑
  一轮同步。还原修复时该测试精确复现生产错误（FAILED），恢复修复后通过——
  证明覆盖有效。
- 全量回归 **240 例 OK**。

### 五、版本与产物

- 桌面 1.17.1 → **1.17.2**；`dist/gscratchpad_1.17.2-1_all.deb`。
- Android 无改动，维持 0.9.0/47。

## 修订四十一（v1.17.3）：401/403 报错文案可诊断化

**日期**：2026-11-25　**范围**：桌面

### 一、背景

用户桌面端对手机 OpenList（10.42.239.39 /dav/backups/gscratchpad）同步报
「创建目录被拒」，实为**云设置里密码未填**（meta `webdav_pass` 为空，Basic
认证空密码 → 401），但原文案无法区分「密码错」与「服务器拒绝写权限」；
手机端正常（其应用内配置了密码）。凭证本身用正确密码实测全通
（PROPFIND/MKCOL/完整同步均 OK）。

### 二、改动

`webdav.py` 报错文案统一走 `_http_error`：401 明确提示「认证被拒，请检查
用户名与密码（密码未填也会报此错）」；MKCOL 403 提示去 AList/OpenList 管理
页勾选 WebDAV 写入权限。行为逻辑无变化。

### 三、测试证据

全量回归 **240 例 OK**（文案改动，无逻辑分支变化）。

### 四、版本与产物

- 桌面 1.17.2 → **1.17.3**；`dist/gscratchpad_1.17.3-1_all.deb`。
- Android 无改动，维持 0.9.0/47。

## 修订四十二（v1.17.4 / Android 0.9.3）：每设备独立备份 zip + 云端列举恢复

**日期**：2026-11-25　**范围**：桌面 + Android

### 一、背景

多设备共用固定备份名会互相覆盖，且「从云端恢复」写死单一文件。用户拍板
1a/2a/3a/4b：复用 sync `device_id`、PROPFIND 列表点选、旧名只读兼容、双端统一命名。

### 二、改动

两端整包备份改名 `gscratchpad-cloud-<device-id>.zip`；恢复端用 PROPFIND 列候选
（含大小/修改时间），旧固定名 `gscratchpad-cloud.zip` / `gscratchpad-desktop.zip`
保留为只读候选。桌面修 `cloud.py` 缺失的 `tempfile`/`shutil` import。

### 三、测试证据

桌面 **242 例 OK**（新增 2 例：命名兼容、`CloudManager` 备份/列举/下载往返）；
Android **230 例 OK**（新增 `CloudBackupTest` 3 例：命名、上传下载回读、
PROPFIND 大小/时间解析）。真实 WebDAV 双设备复测待用户确认。

### 四、版本与产物

- 桌面 1.17.3 → **1.17.4**；`dist/gscratchpad_1.17.4-1_all.deb`。
- Android 0.9.2/49 → **0.9.3/50**；双 ABI release APK。

## 修订四十三（v1.17.5 / Android 0.9.4）：关闭状态跨设备同步

### 一、结论

- 桌面 243 例 OK（新增 `test_state_only_change_triggers_push_and_peer_sees_closed`：A 仅关闭文档 → push 必触发 → B 拉到 closed → `closed_documents` 可见 → 收敛轮零操作）。
- Android 231 例 / 0 失败（`SyncEngineTest` 新增同名 E2E，语义逐字段对应）。
- 桌面 GUI 冒烟待本轮复跑；真实 WebDAV 双设备复测待用户确认。

### 二、修复内容

- push 变更检测增 `own_states`（docId→state）维度：关闭/打开不改内容哈希，此前判「无变化」不重传 manifest，对端永久 state=open，「清理已关闭文档」清不到。
- planSync 哈希相等分支增 state LWW：state 有差异且对端 updated_at 更新才应用，防对端陈旧 manifest 把本机刚做的关闭改回去（桌面测试实证了该竞态）。
- 墓碑裁决不变。

### 三、版本与产物

- 桌面 1.17.4 → **1.17.5**；Android 0.9.3/50 → **0.9.4/51**；双端 release 产物。

## 修订四十四（Android 0.9.5 / 52）：编辑器选区浮栏、长按选择与撤销重做

### 一、结论

- Android 235 例 / 0 失败（新增 `EditorAssetTest` 3 例锁产物、`EditorActionsTest` 增 6 条动作断言）；桌面本轮无代码改动，仍为 1.17.5 / 243 例。
- 门禁：`testDebugUnitTest`、`coverageGate`、`lintRelease`（0 error）、`verifyReleaseBudget`（两包各约 3.39 MB）全绿；`stageRelease` 输出到 `android/dist/`，自动清 0.9.4 旧包。
- 真机 `192.168.159.245:5555`（arm64-v8a）：`selfCheckEdit` 七项全 true（历史干净、选区区间、浮栏可见、插入、深度、撤销、重做）；`selfCheckFind` 回归全 true。

### 二、实现与验证点

- 选区浮栏 `#selbar` 六按钮（复制/剪切/粘贴/全选/撤销/重做），位置由 `view.coordsAtPos()` 计算；按钮事件阻止冒泡以防被全局收起逻辑隐藏。
- 选区状态 `from/to/empty/text` 经 `AndroidEditor.onSelection` 回传；剪贴板走 `ClipboardManager`，粘贴复用 CM 当前选区。
- `setDoc()` 标注 `Transaction.addToHistory.of(false)`，自检 `historyClean=true`，切断跨文档撤销链。
- A/B 对照：adb 合成长按在 ACTION_UP 时即取消选区，去掉 ActionMode 抑制逻辑后同样崩塌，属注入链路限制而非应用回归；原生手柄拖动与浮栏共存需用户真机目视确认。
- 矩形/列选保持 5A 决议：内核既有 `rectangularSelection()` 不动，新浮栏不加入口。

### 三、产物

- Android 0.9.4/51 → **0.9.5/52**；`android/dist/scratchpad-{arm64-v8a,x86_64}-release-0.9.5.apk`，upload key 签名指纹 `16e2b145…f0aa`。
- 桌面版本不变（1.17.5）。


## 修订四十五（Android 0.9.6 / 53）：R52 浮栏/长按选择真机反馈修复

用户真机实测「长按选择弹出就消失、编辑器浮栏没看见」，指出 R52 三项未真正落地。

### 一、根因（纠正 R52 错误结论）

- R52 在 `MainActivity.onActionModeStarted()` 里 `mode.menu.clear()`。WebView 发现 ActionMode 菜单为空时会**立即 finish 并清空 DOM 选区**，浮栏来不及显示——这正是「弹出就消失」的直接原因。
- R52 测试报告把该做法误记为「已验证的保留手柄路径」，本次明确纠正：`menu.clear()` 会摧毁选区，不可用于隐藏系统菜单。

### 二、修复

1. 删除 Activity 级 `onActionModeStarted { menu.clear() }`。
2. 恢复 `EditorWebView` 子类，覆写 `startActionMode` / `startActionModeForChild`，用 `SelectionMenuCallback` 把菜单项逐个设 `isVisible=false`（保留条目数，WebView 不会结束 ActionMode，原生手柄存活），系统菜单不再绘制、浮栏承载动作。
3. 编辑器 JS 新增 `onDomSelectionChange()` 监听 `document.selectionchange`：原生长按手柄由 WebView 驱动 DOM 选区、CM 的 `updateListener.selectionSet` 未必触发，兜底用 `view.posAtDOM()` 把 DOM 选区换算成 CM 位置再定位浮栏；DOM 选区清空但 CM state 非空时沿用 CM 选区。
4. `selfCheckEdit` 增 `domBarVisible` 项：`createRange()` + `dispatchEvent(selectionchange)` 模拟原生手柄选区，先 `hideSelBar()` 再验证兜底路径能重新显示浮栏——自检不再只覆盖程序化 `setSelection`。

### 三、验证

- 门禁：`testDebugUnitTest` / `coverageGate` / `lintRelease` 0 error / `verifyReleaseBudget` 全绿。
- 真机 `192.168.159.245:5555`（arm64-v8a）自检：`selfCheckEdit={"historyClean":true,"selection":true,"barVisible":true,"domBarVisible":true,"inserted":true,"undoDepth":true,"undo":true,"redo":true}`，八项全 true。
- **验证边界**：adb `input motionevent` 为独立进程、退出即 cancel 触摸，长按住 0.7s 时选区仍在 100ms 后被清空（A/B：去掉抑制逻辑同样崩塌），属注入链路局限而非应用回归。原生手柄拖动、字符级边界与浮栏共存需用户真机目视最终确认；无外接键盘，物理 Ctrl+Z/Y 未逐键实测。

### 四、产物

- Android 0.9.5/52 → **0.9.6/53**；`android/dist/scratchpad-{arm64-v8a,x86_64}-release-0.9.6.apk`，upload key 签名指纹 `16e2b145…f0aa`。
- 桌面版本不变（1.17.5）。

## 修订四十六（Android 0.9.7 / 54）：编辑栏（Obsidian 同款）+ 长按选词自绘手柄

用户指出 R52/R53 根本性理解错误：「编辑器编辑浮栏」是 Markdown 格式编辑工具栏（常驻可见），不是选区上下文浮栏；撤销/重做进命令面板等于不可用。

### 一、落地内容

1. **编辑栏 `#toolbar`**：底部固定、横向滚动；撤销/重做最左（深度置灰）+ H1/H2/H3 循环 + 加粗/斜体/删除线/高亮/行内代码（包裹对称取消）+ 引用/无序/有序（行级前缀整体取消）+ 待办三态 + 链接 + 代码块；覆盖层/查找条打开时隐藏。
2. **命令面板移除 undo/redo**（用户拍板），`EditorActionsTest` 断言其不在动作表。
3. **长按 2A 完全接管**：`user-select:none` 禁系统选择（实测不影响 IME 输入），长按 500ms 选词（`posAtCoords`→`wordAt`）、双击选词、自绘双手柄拖动字符级微调；`#selbar` 改四按钮操作条（复制/剪切/粘贴/全选）。
4. **自检重写**：20 项逐动作断言，长按用合成 TouchEvent 保持按下模拟真实手指（此前「touchstart 后立即 touchend」会取消长按定时器，是自检模拟错误不是产品缺陷）。

### 二、验证

- Android **237 单测 / 0 失败**；`coverageGate` / `lintRelease` / `verifyReleaseBudget`（约 3.39 MB）全绿。
- 真机 `192.168.159.245:5555`：`selfCheckEdit` 20 项全 true（toolbarVisible / undoBtnDisabled / boldInsert / undoBtnEnabledAfterEdit / toolbarUndo / boldWrap / boldUnwrap / h1 / h2 / h1Again / h1Cancel / ul / taskOnUl / taskOff / ulCancel / longPressWord / selbarFourButtons / handleDrag / handlesVisible）；`selfCheckFind` 回归全 true。
- **截图实证**：编辑栏真实可见（键盘顶起随视口上移、不被遮挡）；`input tap` 真实点击 H2 → 正文变 `## hello`；点击撤销 → undoDepth 2→1 且 redo 按钮点亮（诊断日志 `tbState=false/false/d1` 实证）。
- **验证边界**：手柄拖动手感与真实手指长按体验需用户目视确认（adb 合成长按仍不可靠）；`user-select:none` 对个别 ROM 系统 pill 的抑制程度待观察。

### 三、产物

- Android 0.9.6/53 → **0.9.7/54**；`android/dist/scratchpad-{arm64-v8a,x86_64}-release-0.9.7.apk`，upload key 签名指纹 `16e2b145…f0aa`。
- 桌面版本不变（1.17.5）。


## 修订四十七（Android 0.9.8 / 55）：编辑栏浮栏化 + 毛玻璃

- 纯 CSS 视觉改造：`#toolbar` 四周 8px 留白悬浮、16px 圆角、`backdrop-filter: blur(16px) saturate(1.4)` 毛玻璃 + 高光描边 + 投影；`#selbar` 同步毛玻璃化；旧内核 `@supports not` 退化为 96% 不透明底。
- 验证：237 单测 / 0 失败、门禁全绿；真机自检 20 项全 true；截图实证浮栏质感（键盘顶起随视口上移）；真实 tap 撤销按钮 → 正文 hello→空白。
- 产物 `android/dist/scratchpad-{arm64-v8a,x86_64}-release-0.9.8.apk`，upload key 签名。桌面版本不变。
