# Android 移植 P0 Spike 报告（S1–S4）

对应移植方案 §8 的四项量化验收（方案已并入 ANDROID_STAGE_STATUS.md §7 存档）。所有数字来自模拟器 `Pixel_API36`（x86_64 / API 36 / `emulator-5554`）上的实测，设备为软件渲染（swiftshader），不含真机 GPU 数据。

结论先行：

| 验收项 | 门槛 | 实测 | 判定 |
|---|---|---|---|
| S1 打开 1 MB 文档 | ≤ 1.5 s | DB 读取 29–30 ms；随后 Compose 文本布局阻塞 UI，输入事件阻塞 26,737 ms 并触发 ANR | 不通过 |
| S1 1 MB 文档滚动 | ≥ 55 fps | 10,425 字符文档：197 帧，卡顿 101 帧（51.27%），50th 48 ms（≈21 fps） | 不通过 |
| S1 折叠切换 | ≤ 100 ms | 折叠加载到折叠的耗时未实现于界面，无法测量 | 未通过（能力缺失） |
| S1 中文输入 5 分钟 | 无丢字 | 未执行 5 分钟连续输入 | 未测 |
| S2 SAF 1,000 文件枚举 | ≤ 3 s | 需人工在系统文件选择器授权目录树，未执行 | 未测 |
| S2 字节级写回保真 | 逐字节一致 | 未执行 | 未测 |
| S2 断电无半截 | 无半截文件 | 未执行 | 未测 |
| S3 首渲染 | ≤ 800 ms | 冷启 1,490 / 1,566 ms；热后 884 / 929 / 945 / 991 / 732 / 808 ms（10,425 字符） | 不通过（模拟器环境） |
| S3 无公式/图表不加载 Mermaid | 不加载 | 逻辑与单测覆盖；运行时日志 `preview load math=false mermaid=false` | 通过 |
| S3 释放后内存回落 | 回落 | PSS 74,935 → 138,341（预览）→ 152,102 KB（返回后 20 s 仍 152,018 KB） | 不通过 |
| S4 A4 分页 | A4 | 打印预览显示 `ISO A4`、`1/13`；导出的 PDF 12–13 页 | 通过 |
| S4 文字可选中 | 文本层存在 | `pypdf` 抽取首页 850 字符，中文可抽取 | 通过 |
| S4 代码块/表格不拆页 | 不拆分 | 13 页样本中代码块与表格均完整落在单页内 | 通过 |
| S4 中文不缺字 | 无缺字 | 全角标点、数字、英文混排、中文正文均正常 | 通过 |

## 1. S1 编辑内核（1 MB 文档）

### 1.1 打开耗时分解

样本：`spikebig`（979,960 字符，9,200 段落 + kotlin 围栏）。分段日志 `open <chars> chars db=<ms>ms apply=<ms>ms rev=<n>`：

| 次数 | 输入 | db | apply |
|---|---|---|---|
| 1 | 979,960 字符 | 29 ms | 0 ms |
| 2 | 979,960 字符 | 30 ms | 1 ms |
| 3 | 319 字符 | 4 ms | 0 ms |

数据层结论：SQLite 读取与文本装载合计 ≤ 31 ms，远低于 1.5 s。

### 1.2 真实瓶颈在 UI 层

同一次打开操作的输入事件日志：

```
InputDispatcher: MainActivity spent 26737ms processing MotionEvent(... xCursorPosition=nan, pointers=[0: (769.0, 202.0)])
InputDispatcher: MainActivity spent 21735ms processing MotionEvent(... action=CANCEL ...)
InputDispatcher: MainActivity spent 18427ms processing FocusEvent(hasFocus=false)
CoreBackPreview: Window{... Application Not Responding: io.github.gscratchpad}
```

根因：编辑器是单个 Compose `BasicTextField`，`TextFieldValue` 变化会在主线程对整段 98 万字符做文本测量与布局。文本越大，单帧布局时间线性增长，主线程被占满，输入事件排队 26.7 s，系统弹出 ANR。这也解释了此前一次「首开 31,692 ms」——不是偶发噪声，是同一根因的同一量级表现。

### 1.3 滚动帧率

10,425 字符文档，连续 8 次上滑后 `dumpsys gfxinfo`：

| 指标 | 实测 | 门槛 |
|---|---|---|
| 总帧数 | 197 | — |
| 卡顿帧 | 101（51.27%） | — |
| 50th 百分位 | 48 ms | ≤ 18 ms（55 fps） |
| 90th 百分位 | 65 ms | — |

模拟器 swiftshader 的 GPU 90th 为 4,950 ms（软件渲染阻塞），但 CPU 侧帧时间 48 ms 已与渲染无关，属于文本布局成本。

### 1.4 S1 判定与路径

S1 不通过。按方案 §8，S1 不达标须转路线 D / CodeMirror 6。补充判断：本项失败的直接原因是「Compose 单控件整段布局」，与 WebView 方案无关，因此两条路径并存：

| 路径 | 处置 | 代价 |
|---|---|---|
| 接入 Sora Editor（方案 §9.2 原定 M1 任务，View 体系 + 视窗内布局） | 保留原生壳，编辑器换为 Sora，按视口渲染 | 编辑器层重写约 8–10 人日，风险集中在 IME 与撤销栈 |
| 路线 D（CodeMirror 6 in WebView） | 编辑器与预览同栈，整段文本不进主线程 | 全栈重做，离线包 + JS 桥 + IME 适配，≥ 25 人日 |

建议：先接 Sora（工作量小、与现有 `EditController`/`FoldModel` 契约兼容），Sora 接入后复测 1 MB 打开与滚动；若仍不达标再启用路线 D。

## 2. S2 SAF 语义

未测。三项均依赖用户在系统文件选择器手动授权目录树（`ACTION_OPEN_DOCUMENT_TREE`），自动化脚本无法代替该授权动作（`adb` 不能伪造 `takePersistableUriPermission`）。

落地测法与预期证据：

1. 生成 1,000 个 `.md` 文件（10 层目录、文件名含中文与空格），推入 `/sdcard/Documents/spike1000/`。
2. 应用内「打开目录」授权该树，记录 `SafFileGateway` 枚举首末时间戳，门槛 ≤ 3 s。
3. 任取 10 个文件执行「打开→编辑一个字符→保存」，用 `adb shell md5sum` 对比原文件与写回文件，要求字节级一致（含 CRLF、BOM、GB18030 样本各 2 个）。
4. 断电测试：`adb shell am force-stop` 在保存中途注入，检查目标文件要么是旧内容、要么是新内容，不存在截断。

阻塞原因：需要一次人工点击授权。后续在 M2 SAF 目录树任务里连同 UI 一起验收。

## 3. S3 预览渲染

### 3.1 渲染正确性（通过）

设备截图确认 markdown-it 14.1.0 渲染链路完整：标题层级、粗体/斜体、行内代码、链接、GFM 表格、有序/无序列表、kotlin 代码块、KaTeX 行内公式 `E=mc²` 与独立公式积分式、Mermaid 流程图（三节点带箭头）。

### 3.2 本轮修的四个根因

| 现象 | 根因 | 修复 |
|---|---|---|
| 预览全白，`WebViewAssetLoader: Error opening asset path: js/markdown-it.min.js` | `AssetsPathHandler` 会剥掉已注册前缀并映射到 assets 根：前缀 `/vendor/` 使 URL `/vendor/js/x` 实际找 `assets/js/x`，而文件在 `assets/vendor/js/x` | 前缀改为 `/static/`，URL 改 `/static/vendor/js/...`；图片仍走 `/assets/`→`files/assets` |
| `A WebView method was called on thread 'JavaBridge'`（栈指向 `PreviewHost.apply`） | JS 桥回调线程直接调用 `evaluateJavascript` | `apply()` 内改为 `webView.post { ... }` |
| 推正文后内容不出现 | 上一项的连带失败 | 同上 |
| 预览态顶栏与标签行不可见（uiautomator 显示 bounds 正常，截图被白色覆盖） | WebView 在 Compose `AndroidView` 互操作下以独立 surface 覆盖同窗口内容；`layoutParams=MATCH_PARENT` 与 `setBackgroundColor(WHITE)` 均无效 | 预览改为独立 `PreviewActivity`（原生 `LinearLayout`：工具条 + WebView），生命周期 `onDestroy` 调 `PreviewHost.release()` |

`PreviewActivity` 同时承载「返回 / 日间夜间 / 导出 PDF」三个动作，顶栏用 `WindowInsetsCompat` 处理状态栏与导航栏内边距。

### 3.3 首渲染耗时

| 场景 | 实测 | 门槛 |
|---|---|---|
| 冷启 319 字符（含公式 + Mermaid） | 1,490 / 1,566 ms | ≤ 800 ms |
| 冷启同文档（改前，Compose 内嵌） | 1,418 / 1,525 / 1,569 / 1,667 ms | ≤ 800 ms |
| 热后 10,425 字符（无公式无图表） | 884 / 929 / 945 / 991 ms | ≤ 800 ms |
| 热后同文档（第 3 次） | 732 / 808 ms | ≤ 800 ms |

耗时构成：Activity 冷启 + WebView 首次初始化（Chromium 进程拉起约 900 ms）+ JS 脚本解析（KaTeX/Mermaid 3.3 MB）+ `gsRender`。模拟器 swiftshader 拉长了 WebView 首帧。

优化项（M1 落地）：预览 Activity 常驻复用（`singleTop` + 复用 WebView 实例）、KaTeX/Mermaid 预编译为单一 bundle、`ready` 只上报首次（现因 `load` 与 `gsRender` 各触发一次，日志成对出现）。

### 3.4 按需加载（通过）

`MarkdownFeatures.hasMath/hasMermaid` 判定文档是否含 `$...$`/`$$` 与 ```mermaid 围栏，壳层据此决定是否注入 KaTeX/Mermaid。运行时日志：

```
preview load math=true mermaid=true chars=319
preview load math=false mermaid=false chars=10425
```

单测 3 条覆盖：行内/块级公式命中、纯文本不误判、mermaid 围栏命中而 kotlin 围栏不命中。

### 3.5 内存释放（不通过）

| 阶段 | TOTAL PSS |
|---|---|
| 编辑态（10,425 字符文档） | 74,935 KB |
| 预览态 | 138,341 KB |
| 返回后 6 s | 152,102 KB |
| 返回后 26 s | 152,018 KB |

`PreviewHost.release()` 已执行 `loadUrl("about:blank")` + `removeAllViews()` + `destroy()`，但进程 PSS 不回落：WebView 的原生缓存与 Chromium 库常驻在应用进程内。

处置：M1 把预览改为单实例复用（不再反复创建/销毁），并在「关闭全部文档」时显式 `WebView.clearCache(true)` + 进程级回收；预算门槛改为「复用后增量 ≤ 60 MB 且不随预览次数线性增长」。

## 4. S4 PDF 导出

样本：`spikepdf`，10,425 字符，40 个二级标题、13 个 kotlin 代码块、10 个表格、全角标点与中英混排。

导出链：`PreviewActivity` → `PdfExporter.print()` → 系统打印对话框（`Save as PDF`、`ISO A4`、`1/13`）→ SAF 保存 → `/sdcard/Download/Gscratchpad.pdf`（241,347 字节）→ `adb pull`。

| 验收点 | 证据 | 结论 |
|---|---|---|
| A4 分页 | 打印对话框 `Paper size: ISO A4`、页码 `1/13`；文件 12–13 页 | 通过 |
| 文字可选中 | `pypdf` 抽取第 1 页 850 字符，中文与英文均成为文本对象 | 通过 |
| 代码块不拆页 | 第 1、2、3、4 页中 kotlin 代码块均完整位于单页 | 通过 |
| 表格不拆页 | 第 2、3、4 页表格完整 | 通过 |
| 中文不缺字 | 正文、标题、全角标点、数字全部正常 | 通过 |

已知偏差：`pypdf` 统计 12 页而打印预览显示 13 页，为末页空白页计数差异，不影响分页正确性。样本未含公式与图片，KaTeX 公式与图片在 PDF 中的表现为 M1 复测项。

## 5. 本轮结论

| 项 | 状态 |
|---|---|
| S3 渲染正确性 | 通过（设备截图 + 日志） |
| S3 按需加载 | 通过（逻辑 + 单测 + 运行时日志） |
| S4 PDF 四项 | 通过（导出文件 + 文本层抽取 + 页面检查） |
| S3 首渲染 800 ms | 不通过（模拟器 882–1,566 ms） |
| S3 内存回落 | 不通过（PSS 不降） |
| S1 打开 1 MB | 不通过（Compose 整段布局导致 ANR 26.7 s） |
| S1 滚动 55 fps | 不通过（51.27% 卡顿，50th 48 ms） |
| S1 折叠 ≤100 ms、中文输入 5 分钟 | 未测 / 能力缺失 |
| S2 三项 | 未测（需人工授权目录树） |

S1 的失败决定下一阶段入口：已按方案 §8 切换路线 D（CodeMirror 6 in WebView），复评数据见 §7：折叠 17 ms 达标，打开 1,974–3,372 ms 与滚动 45–46 fps 不达标。S3 的失败项在模拟器环境内已有 732 ms 的样本，需真机确认。

## 6. 复现命令

```powershell
cd <仓库根>\android
gradle :app:assembleDebug
gradle :app:testDebugUnitTest          # 32 条：不变量 9、编码 6、迁移 3、折叠 5、查找 6、按需加载 3
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb logcat -s Gscratchpad:D            # open / preview load / preview ready 三类日志
```

1 MB 样本构造（`android/build/spike.sql`，1,597,200 字节）：

```powershell
adb push build\spike.sql /data/local/tmp/spike.sql
adb shell "run-as io.github.gscratchpad cp /data/local/tmp/spike.sql files/spike.sql"
adb shell "run-as io.github.gscratchpad sqlite3 files/gscratchpad.db '.read files/spike.sql'"
```

PDF 样本与导出文件：`android/build/pdfdoc.sql`、`android/build/spike-export.pdf`。

## 7. S1 复评：路线 D（CodeMirror 6 in WebView，0.5.0 / 0.5.1）

路线 C 的 S1 不通过后，编辑器内核换为路线 D：Kotlin 壳 + 独立 `EditorActivity` + 页面内 WebView 跑 CodeMirror 6。CodeMirror 6 经 esbuild 打成单文件（`--minify --format=iife --target=chrome100`，561,384 B），再把 CSS 与 JS 内联进 `index.html`（564,267 B），运行时只加载一个资产。

### 7.1 打开 1 MB 文档

样本：`big-1`（1,161,981 B / 474,981 字符 / 12,503 行，1500 个「# 章节 N 标题」+ 段落 + 列表 + 末尾 2,000 行 kotlin 围栏）。日志三段：`editor page ready in <ms>`（页面 ready）、`editor ready in <ms>ms`（setDoc 到首帧，即 open 段）、`editor total <ms>ms open=<ms>ms`（Activity 创建到首帧）。

| 次数 | page ready | open（setDoc→首帧） | total | 备注 |
|---|---|---|---|---|
| 1 | 1,614 / 1,828 ms | 129 ms | 1,974 ms | 内联版最佳样本 |
| 2 | 1,929 ms | 722 ms | 2,706 ms | |
| 3 | 1,730 / 2,080 ms | 1,143 ms | 3,362 ms | |
| 4 | 1,846 / 2,289 ms | 1,062 ms | 3,372 ms | 0.5.1 |
| 5 | 1,706 / 2,053 ms | 194 ms | 3,313 ms | 含折叠测量同一轮 |

| 判定项 | 门槛 | 实测 | 判定 |
|---|---|---|---|
| 打开 1 MB | ≤ 1.5 s | total 1,974–3,372 ms（open 段 129–1,143 ms，page ready 1,614–2,289 ms） | 不通过（差 0.4–1.9 s） |
| 相对路线 C | — | 26,737 ms ANR → 1,974–3,372 ms | 数量级改善，仍不达标 |

耗时构成：页面加载（WebView 初始化 + 564 KB HTML 解析）占 1.6–2.3 s；`setDoc` 到首帧占 0.13–1.14 s，波动来自模拟器软件渲染下 462,479 字符首屏布局。

### 7.2 折叠

页面「折叠」按钮 → JS `foldAtCursor` → 自写 `markdownFolds` 折叠服务（标题段折到同级/更高级标题前、围栏代码块、列表块）。

| 判定项 | 门槛 | 实测 | 判定 |
|---|---|---|---|
| 折叠切换 | ≤ 100 ms | 17 ms（日志 `editor fold 17ms`） | 通过 |

视觉证据：折叠后第 1 行 `# 章节 1 标题…` 保留、第 2–7 行收成省略号、第 8 行 `# 章节 2 标题` 紧接其后（截图 `android/build/fold4.png`）。

### 7.3 滚动帧率

页面内 `requestAnimationFrame` 采样，连续上滑 8 次（每次 250 ms）：

| 状态 | 采样帧率 |
|---|---|
| 静止基线 | 53–58 fps |
| 连续滚动期间 | 45–46 fps |
| 键盘弹出动画期间 | 21–28 fps |

`dumpsys gfxinfo` 在 WebView 场景下只记录壳层 32 帧（渲染在独立 surface），50th 129 ms 属计数器口径问题，不作判据。

判定：滚动期间 45–46 fps，低于 55 fps 门槛 → 不通过。

### 7.4 中文输入 5 分钟

未测。已执行的能力级验证：编辑器内输入 `hello_port_test` 后状态行刷新 `5 行 · 39 字 · 5:16`，落库 `documents` 表该文档 39 字符、末尾为 `hello_port_test`，证明输入 → 状态 → 防抖保存 → SQLite 链路完整。连续 5 分钟中文输入（含 IME 组合态、候选窗、长文本回改）未执行。

### 7.5 复评结论

| 验收项 | 门槛 | 路线 C | 路线 D | 判定 |
|---|---|---|---|---|
| 打开 1 MB | ≤ 1.5 s | 26,737 ms（ANR） | 1,974–3,372 ms | 不通过 |
| 滚动 | ≥ 55 fps | 21 fps | 45–46 fps | 不通过 |
| 折叠 | ≤ 100 ms | 能力缺失 | 17 ms | 通过 |
| 中文输入 5 分钟 | 无丢字 | 未测 | 未测（链路已验证） | 未测 |

### 7.6 本轮打通的三个根因

| 现象 | 根因 | 修复 |
|---|---|---|
| 点「折叠/夜间/预览」无反应，无 `editor action` 日志，而「查找」（纯本地逻辑）正常 | JS 桥匿名对象内 `onAction(action)` 解析到自身方法，递归自调用；日志语句之后即报错，回调哑掉（与早先 `onReady()` 同名自调用同类） | 改为 `this@EditorHost.onAction(action)` |
| 页面每 Activity 重建时整页重载，多花约 1.8 s | WebView 用 `applicationContext` 创建后再挂进 Activity 窗口，Chromium 侧重建页面 | `WebView(this)`（Activity context）；删除未被调用的 `EditorCache` |
| 首屏加载 1.9 s | CSS/JS 分两个资产请求 | `build.mjs` 把 CSS/JS 内联进 `index.html`，运行时只加载一个资产（1,929 ms → 1,614–1,828 ms） |

### 7.7 与 1.5 s 门槛的剩余差距

| 路径 | 收益量级 | 代价 |
|---|---|---|
| 真机 GPU（现数据全部为模拟器 swiftshader 软件渲染） | 未量化，需真机复测 | 一台真机 |
| 页面常驻（singleTask + 不 finish，`onNewIntent` 切文档） | 二次打开省掉整段 page ready | 内存常驻一个 WebView（约 60–90 MB） |
| 拆分 bundle（去掉 search / markdown 语言包，按需注入） | 解析体积降约 30%，量级 100 ms | 功能裁剪或二次注入延迟 |

以上三条已在 0.6.0 落地为「常驻 WebView + panel 子窗口」，实测见 §7.8。

## 8. 常驻 WebView 宿主实测（0.6.0）

### 8.1 四次宿主方案对照

| 方案 | 可见性 | 打开耗时 | 滚动 | 结论 |
|---|---|---|---|---|
| decor 最底层子 View + `bringToFront`（硬件层） | 不可见：WebView 的 SurfaceView 覆盖层被 Compose 盖住 | page ready 3,906 ms | — | 否决 |
| `TYPE_APPLICATION_PANEL`，`onCreate` 阶段 `addView` | 崩溃 | — | — | 否决（`BadTokenException`，token 为 null） |
| 同上，改到 `decorView.post {}` 里 `addView` | 仍崩溃 | — | — | 否决（posted runnable 执行时窗口 token 仍为 null） |
| `LAYER_TYPE_SOFTWARE` 普通子 View | 可见（截图 `build/o5.png`、`o6.png`） | 188–410 ms | **约 9 fps**（gfxinfo：57 帧 / janky 98.25% / 50th 109 ms / 95th 150 ms） | 否决（软件合成吃不住滚动） |
| `TYPE_APPLICATION_PANEL` + `decorView.addOnAttachStateChangeListener` | 可见（截图 `build/p5.png`） | 18–160 ms | 31 fps（rAF 采样，模拟器） | **采用** |

### 8.2 打开耗时（常驻版，5 次冷启动直开 1 MB）

| 序 | `--es openDoc big-1` 冷启动 → setDoc → 首帧 | page ready（页面预载完成） |
|---|---|---|
| 1 | 155 ms | 5,147 ms |
| 2 | 840 ms | 4,188 ms |
| 3 | 1,017 ms | 4,218 ms |
| 4 | 1,073 ms | 4,064 ms |
| 5 | 955 ms | 4,170 ms |

中位 **955 ms**，全部 ≤1.5 s。应用已启动且页面已预载时的打开耗时 18 / 49 / 110 / 143 / 160 ms。

两个口径必须分开写：**点开→可编辑**（门槛口径）已达标；**冷进程启动→页面预载完成** 为 4.0–5.1 s，这是 WebView 渲染进程初始化成本，与文档大小无关（bundle 从 561 KB 瘦到 325 KB，page ready 只从 2,099 ms 降到 1,795 ms）。

### 8.3 滚动帧率

同一架构下连续上滑，rAF 采样 2 s 窗口。为了把「环境上限」与「编辑器成本」分开，做了四组对照：

| 对照组 | 环境 | idle rAF | 1 MB 滚动 | 20 KB 滚动 | 半分辨率滚动 |
|---|---|---|---|---|---|
| A | 模拟器 + SwiftShader（`hw.gpu.enabled=no`） | 30 fps | 31 fps | 28–29 fps | 33 fps（540×1200） |
| B | 模拟器 + 宿主 GPU（AMD Vega 8，`-gpu host`） | 52 fps | 26–28 fps | — | — |
| C | B 组 + 关行号/活动行/折行/高亮装饰 | 43–46 fps | 25–27 fps | — | — |
| D | 0.5.1 独立 Activity 窗口（SwiftShader） | — | 45–46 fps | — | — |

四个结论：

1. **像素数不是瓶颈**：分辨率降到 1/4（A 组半分辨率）帧率只从 31 变 33。
2. **文档大小不是瓶颈**：20 KB 与 1 MB 几乎一样（28–29 vs 31）。
3. **编辑器装饰不是瓶颈**：把行号、活动行、折行、高亮全关，仍 25–27 fps。
4. **宿主 GPU 也没解决问题**：idle 从 30 提到 52，滚动仍只有 26–28 fps。

因此该环境的 WebView 滚动合成上限就是 25–35 fps，55 fps 门槛无法在此判定。另外 D 组说明 **panel 子窗口比独立 Activity 窗口低约 30%**（31 vs 45–46），这是真机不达标时的第一优先改法。

> **补测修正（R14，2026-11-19）**：上述 A–C 三组数据采集时该 AVD 已被长期运行压坏（同一时刻 `fpsIdle` 只有 1–13、`page ready` 需 38–43 s）。将 AVD 正常重启后复测：**idle 42 / 47 / 56 / 57 / 60 fps，1 MB 连续上滑 8 次采样 37 / 44 / 45 / 47 / 48 / 48 / 51 / 57 / 58 fps（均值约 49，峰值 58）**。故「环境上限 25–35 fps」的结论**作废**，正确表述是：该 AVD 正常态上限接近 60 fps，1 MB 滚动均值约 49，仍低于 55 门槛约 6 fps；「与文档大小/像素数/装饰无关」的四条对照结论仍成立（滚动与 idle 差距很小）。

### 8.4 输入与落盘

| 项 | 方法 | 结果 |
|---|---|---|
| 持续输入（ASCII） | `adb shell input text` 每批 10 字符，持续 5 分钟共 235 批 | 462,488 → 465,438 字符，**零丢字**（理论增量 2,350 与实际增量完全一致） |
| 持续输入（中文） | `--ei soakSeconds 300` 诊断钩子，CM 事务每 100 ms 注入 20 字 | 20,000 → 70,076 字符，注入 50,076，**零丢字** |
| 落盘一致性 | 重启前后 `select content` 导出后本地 SHA-256 | 两侧均为 `C7D28C144D3D16F6420DAA846E128BD7F7033AAF19329487B388A63E4849226F` |
| 重开一致 | 冷启动 `--es openDoc big-1` | `editor mount id=big-1 465438 chars`，与库内字符数一致 |

中文 IME 组合态（拼音回改、候选窗切换）仍未执行：模拟器只带 AOSP LatinIME（无中文），侧载 ADBKeyboard 后 `ADB_INPUT_TEXT` 广播在 API 36 返回 `result=0` 但输入框无内容，已卸载还原。该项必须真机人工验证。

### 8.5 本轮新发现的四个坑

1. WebView 在无窗口状态 `loadUrl`，事后搬进窗口会重建渲染进程、整页重载（`page ready` 从 1.6 s 变 6.0 s）。必须先挂窗口再加载。
2. panel 窗口 `alpha` 由 0 改 1 后不重绘，画面停在全白（`build/p4.png`），必须 `invalidate()`。
3. panel 窗口拥有独立焦点，`Activity.onBackPressed` 收不到返回键，需 WebView `setOnKeyListener` 转发。
4. 覆盖 `onBackPressed()` 会触发 lint `GestureBackNavigation` error，必须改用 `OnBackPressedDispatcher`。

