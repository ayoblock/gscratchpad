# Android 移植实现说明（§1–6 落地）

> 对应方案：移植方案 v1.0 §1–§6（已并入 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §7 存档）。
> 工程：`android/`（Gradle，单 `:app` 模块，namespace `io.github.gscratchpad`）。
> 版本：0.9.8（versionCode 55）。日期：2026-11-27。R46–R55 的逐轮演进见权威看板。编辑器内核为路线 D（CodeMirror 6 in WebView）；宿主为「Activity 内常驻 WebView + `TYPE_APPLICATION_PANEL` 子窗口」，界面归一为「Compose 文档列表 + WebView 编辑器」两屏；0.7.0 完成 P2 收尾，0.7.14 起编辑器↔预览同页互斥切换，0.7.20–0.7.22 收敛 SAF 打开/另存链路并落地 My folders 页，0.7.23 文档切换改弹出式列表 + 本地文件夹工作目录绑定，0.7.24 长按菜单与 WebDAV 对话框统一为 App 深色卡片风格。**逐轮变更史以 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §5.4 为唯一权威记录**，本文不重复维护流水账。S1 复评与常驻版实测见 [ANDROID_SPIKE_REPORT.md](ANDROID_SPIKE_REPORT.md) §7。

## 1. 交付范围

| 方案章节 | 落地内容 | 状态 |
|---|---|---|
| §1 目标与范围 | 目标矩阵、非目标（不做 GIR/GTK、不做 WeasyPrint、不做 Python 运行时）作为决策基线沿用 | 基线，无代码 |
| §2 可行性 | JDK/SDK/AGP/Compose/WebView 工具链在本机实测打通（见 §2） | 验证完成 |
| §3 路线 C 与 ADR-01–07 | 全部按方案执行；补 ADR-08（存储驱动抽象） | 完成 |
| §4 架构与包结构 | `data/domain/platform/capture/importlib/feature` 六层 + 单 Activity + 手写 `AppContainer` | 完成 |
| §5.1–5.2 存储/仓库/保存队列 | schema v3 逐字段对齐桌面、WAL、单写线程、journal、镜像、revision 单调 | 完成（I1–I7 单测通过） |
| §5.3 SAF 网关 | 打开/另存/建树/持久授权/目录枚举，编码与换行保真，原子替换 | 完成 |
| §5.4 预览 | WebView + `WebViewAssetLoader`（`/vendor/`→assets、`/assets/`→私有图片），KaTeX/Mermaid 按需注入，外链外跳 | 完成（Markdown→HTML 管线属 M1） |
| §5.5 PDF | `WebView.createPrintDocumentAdapter` + `PrintManager`（A4），打印版 CSS | 完成（直接写 SAF 受限，见 §6.3） |
| §5.6 capture | 契约、校验、幂等 key、追加 `---`、标题回退、EXIT 码 | 完成（设备实测） |
| §5.7 编辑器控制与折叠 | `EditorController` 接口 + `FoldModel`（markdown/brace/indent 策略 1:1 转写） | 完成（5 条单测） |
| §5.8 不变量 I1–I8 | I1–I7 有 JVM 回归；I8 未实现（依赖 M2 批量替换器） | 部分 |
| §6 桌面备份导入 | zip 解压（含 zip-slip 校验）、`integrity_check`、冲突策略、图片重写、source_path 映射、校验报告 | 完成（3 条单测） |

## 2. 工具链（本机实测）

| 项 | 值 | 说明 |
|---|---|---|
| JDK | 21 | Gradle 9.9.1 |
| Android SDK | `<Android SDK>`，platform/build-tools 36 | compileSdk/targetSdk 36，minSdk 26 |
| AGP | 9.5.1 | 已内置 Kotlin 支持，禁止再 apply `org.jetbrains.kotlin.android` |
| Compose | `org.jetbrains.kotlin.plugin.compose` 2.2.10 + `compose-bom:2025.10.01` | BOM 2026.09 需 compileSdk 37，本机无 |
| WebView | androidx.webkit 1.12.1 | 模拟器 API 36 自带 WebView |
| 构建命令 | `gradle :app:assembleDebug` / `gradle :app:testDebugUnitTest` | 在 `android/` 下执行 |
| 构建耗时 | 增量 3–4 s，冷构建 41 s（探针工程实测） | — |
| APK | `app/build/outputs/apk/debug/app-debug.apk`，12.11 MB | 含 KaTeX+Mermaid 资产 4.71 MB |

## 3. 包结构与文件清单

```
android/app/src/main/java/io/github/gscratchpad/
├── MainActivity.kt              单 Activity：标签、编辑、预览、打开/另存、PDF、导入、CAPTURE/SEND
├── GscratchpadApp.kt            持有 AppContainer
├── AppContainer.kt              手写 DI + bootstrap + saveAndFlush（进程级）
├── data/  Schema / SqlDb / AndroidSqlDb / DbHelper / DocumentDao /
│          MirrorStore / RecoveryManager / AssetStore / SaveQueue / DocumentRepository
├── domain/model/                 Document / Format / Folder / DocState / SaveState
├── domain/fold/FoldModel.kt      折叠区间（markdown / brace / indent）
├── platform/ TextCodec / SafFileGateway / PreviewHost(+PreviewHtml) / PdfExporter
├── capture/ CaptureContract / CaptureValidator / CaptureService
├── importlib/ DesktopImporter.kt
└── feature/editor/EditorController.kt
```

测试（JVM，无模拟器）：`test/.../testing/{JdbcSqlDb,TestHarness}.kt`、`InvariantsTest`、`TextCodecTest`、`MigrationTest`、`FoldModelTest`。

### 3.1 关键实现要点

| 模块 | 要点 |
|---|---|
| `Schema` | v3 DDL 与桌面 `store._SCHEMA` 逐字段一致；`statements()` 按 `;` 拆分（`execSQL`/JDBC 都不接受多语句） |
| `SqlDb` | 驱动无关接口：Android 用 `SQLiteDatabase`，JVM 测试用 sqlite-jdbc；ADR-08 |
| `DbHelper` | WAL + `synchronous=FULL` + `busy_timeout=10000`；PRAGMA 用 `rawQuery` 执行 |
| `SaveQueue` | 300 ms 防抖合并、`Dispatchers.IO.limitedParallelism(1)` 串行、journal→DB→删 journal→镜像；DB 失败 3 次退避重试；旧快照 `applied=false` 丢弃并记 SAVED |
| `RecoveryManager` | 启动回放：journal revision > 库内才回填并重写镜像 |
| `MirrorStore` | `notes/<id>.<ext>` 原子写（`.tmp`→`fsync`→rename），清另一扩展名 |
| `AssetStore` | SHA-256 前 12 位去重，`assets/<docId>/<sha>.<ext>` |
| `TextCodec` | BOM 识别、严格 UTF-8 失败回退 GB18030、CRLF→LF 归一、写回按原 style 还原 |
| `SafFileGateway` | 同目录临时文件 + 读回校验 + 替换；不可行时 truncate 覆盖，返回 `ATOMIC_RENAME`/`IN_PLACE` |
| `PreviewHost` | `appassets.androidplatform.net` 域名隔离；`/vendor/` 走 assets，`/assets/` 走私有目录；JS 接口只收 `ready` |
| `DesktopImporter` | manifest.schema 必须为 3；事务导入；冲突 revision 大者胜，相同比 `updated_at`，败者写 `conflicts/<id>.md`；过滤 `window_*`、`source_path:*`、`SKIP_ON_IMPORT` |

### 3.2 与方案的三处实现偏差（均记录在案）

| 项 | 方案 | 实现 | 原因 |
|---|---|---|---|
| PDF 导出 | `onLayout/onWrite` 直接写 SAF `ParcelFileDescriptor` | `PrintManager.print()` 走系统打印（可“另存为 PDF”） | `PrintDocumentAdapter.LayoutResultCallback/WriteResultCallback` 在 android.jar 中构造器为包私有，Kotlin 无法实例化；平台打印框架内部使用同一 adapter，分页与矢量输出一致 |
| 折叠 | 区间装饰 | 只算区间，界面层隐藏 | 与 ADR-05 一致，落盘恒全文 |
| 存储驱动 | 方案未单列 | 抽出 `SqlDb`（ADR-08） | 让 I1–I7 在无模拟器 JVM 上可回归 |

## 4. 测试与实测数据

| 套件 | 条数 | 结果 |
|---|---|---|
| `InvariantsTest`（I1–I7） | 9 | 通过 |
| `TextCodecTest` | 6 | 通过 |
| `MigrationTest` | 3 | 通过 |
| `FoldModelTest` | 5 | 通过 |
| `FoldModelExtraTest` | 10 | 通过 |
| `TextSearchTest` | 6 | 通过 |
| `MarkdownFeaturesTest` | 3 | 通过 |
| `DomainModelTest` | 6 | 通过 |
| `DesktopBackupContractTest` | 5 | 通过 |
| **总计** | **53** | **53 通过，0 失败** |

不变量覆盖：

| 编号 | 内容 | 测试 |
|---|---|---|
| I1 | 全文落盘与镜像一致 | `InvariantsTest` + 设备实测（编辑后 `notes/<id>.md` 与 `documents.content` 同为 `SmokeEditOK`） |
| I2 | revision 单调，旧快照不覆盖 | 乱序提交 99 次 |
| I3 | journal 回填、旧 journal 不覆盖 | — |
| I4 | 无 `.tmp` 残留 | — |
| I5 | 并发 8 路串行写入 | — |
| I6 | 关闭标签保留文档 | — |
| I7 | capture 幂等与追加不覆盖 | 单测 + 设备两次 `am start` 实测 |
| I8 | 批量替换编码/换行保真 | 未实现（M2 `fssearch` 替换器） |

### 4.1 模拟器冒烟（Pixel_API36，x86_64，API 36）

| 步骤 | 结果 |
|---|---|
| `adb install -r app-debug.apk` | Success |
| `am start -n io.github.gscratchpad/.MainActivity` | `Status: ok`，冷启动 3.7 s |
| 首启建库 | `files/gscratchpad.db`（+`-wal`/`-shm`），`meta.schema_version=3` |
| 输入 `SmokeEditOK` | `documents.revision=12`，`length=11`，镜像同内容 |
| CAPTURE 首次（key=smokeA） | 新建《测试书》笔记，`revision=2`，`length=39`，写 `ext:smokeA` |
| CAPTURE 二次（同 key） | 追加块，`length=83`，含 `---` 分隔与引用行 |
| 应用运行中再投递 CAPTURE | `onNewIntent` 处理成功，笔记 `revision=4`、`length=127`，无崩溃 |
| 预览切换 | WebView 渲染，无崩溃日志 |
| 版本号 | `dumpsys package` → `versionName=0.2.0` |
| `AndroidRuntime:E` | 空 |

冒烟截图：`android/build/smoke-main.png`、`smoke-edit.png`、`smoke-preview.png`。

## 5. 未实现项（不得视为通过）

| 项 | 归属 | 说明 |
|---|---|---|
| Markdown→HTML 管线（markdown-it） | 已完成（0.3.0） | `vendor/js/markdown-it.min.js` 14.1.0 + JS 内渲染，见 §8 |
| I8 批量替换 | M2 | 依赖 SAF 目录写回与备份策略 |
| 侧栏/搜索/片段/设置页 | M2 | `feature/` 仅建 `editor` |
| SAF 目录导入在设备上的端到端 | M2 | JVM 已覆盖导入逻辑；设备侧需人工选择 zip |
| 1 MB 文档 30 分钟连续编辑 | M1 退出标准 | 1 MB 打开即触发 ANR，见 [ANDROID_SPIKE_REPORT.md](ANDROID_SPIKE_REPORT.md) §1 |

## 6. 故障与根因记录

| 现象 | 根因 | 修复 |
|---|---|---|
| 首启崩溃 `SQLiteException: Queries can be performed using ... rawQuery only` | `SQLiteDatabase.execSQL` 执行会返回结果集的 `PRAGMA`（`journal_mode`、`synchronous`、`busy_timeout`） | `AndroidSqlDb.exec` 识别 `PRAGMA` 改走 `rawQuery`；`DbHelper.onOpen` 同改 |
| 再次投递 CAPTURE 无效 | `singleTask` 复用已有 Activity，`onCreate` 分支不再执行 | 增加 `onNewIntent`，处理 CAPTURE 与 SEND |
| 首启空白无标签 | 空库不自动建文档 | `reload()` 在无打开文档时创建一篇 MD |
| 界面顶栏被状态栏覆盖 | targetSdk 36 强制 edge-to-edge，`setDecorFitsSystemWindows` 不生效 | 根布局加 `systemBarsPadding()` |
| 运行 `execSQL` 建表失败 | 多语句一次执行 | `Schema.statements()` 拆分后逐条执行 |

## 7. 下一轮入口

1. 编辑器接入 Sora Editor（View 体系、视窗内布局），替换 Compose `BasicTextField`，复测 1 MB 打开与滚动；S1 数据见 [ANDROID_SPIKE_REPORT.md](ANDROID_SPIKE_REPORT.md)。
2. 预览 Activity 单实例复用 + 资源合并打包，把首渲染压到 800 ms 内，并解决 PSS 不回落。
3. 实现 I8：SAF 批量替换 + 备份，补 `InvariantsTest` 用例。
4. SAF 三项量化验收（千文件枚举、字节保真、断电无半截），需人工授权目录树。
5. 侧栏（全部/最近/文件夹/格式分组）、搜索、片段、设置页。

## 8. 预览管线与查找替换（0.3.0 引入，0.4.0 沿用）

### 8.1 预览架构

预览走「JS 内渲染」：原生只向 WebView 推 Markdown 源文，不做整页 HTML 拼接。

| 层 | 实现 |
|---|---|
| 资源托管 | `WebViewAssetLoader`：`/static/` → assets 根（`/static/vendor/js/...` 对应 `assets/vendor/js/...`）；`/assets/` → `files/assets`（文档内图片） |
| 壳层 | `PreviewHtml.buildShell(dark, needsMath, needsMermaid)`：CSS + 按需注入 KaTeX / Mermaid + markdown-it，输出空壳 |
| 渲染 | `window.gsRender(src)`：`md.render` → 标题补 `id=hN` → `renderMath()`（TreeWalker 遍历文本节点，跳过 `CODE`/`PRE`，`$$...$$`/`$...$` 调 `katex.renderToString`）→ `renderMermaid()`（`code.language-mermaid` 转 `.mermaid` 后 `mermaid.run()`）→ 通知原生 `ready` |
| 推送 | 原生 `evaluateJavascript("window.gsRender(" + JSONObject.quote(md) + ")")`，且必须 `webView.post { }`（JS 桥线程不能直接调 WebView 方法） |
| 载体 | 独立 `PreviewActivity`（原生 `LinearLayout`：返回 / 日间夜间 / 导出 PDF + WebView）。Compose `AndroidView` 内嵌 WebView 会以独立 surface 覆盖同窗口控件，故不采用 |

`markdown-it.min.js` 14.1.0（123,618 字节，MIT），来源 `https://cdn.jsdelivr.net/npm/markdown-it@14.1.0/dist/markdown-it.min.js`。

### 8.2 按需加载

`platform/MarkdownFeatures.kt`：`hasMath`（`$...$`、`$$`）、`hasMermaid`（```mermaid 围栏）。为 false 时不注入对应资源。运行时日志 `preview load math=<b> mermaid=<b> chars=<n>` 可直接核对。

### 8.3 查找替换

`domain/search/TextSearch.kt`：`SearchOptions(regex, caseSensitive)`、`ReplaceOutcome(text, count)`、`findAll`、`replaceAll`（正则分组 `$1`、`\$` 转义、零宽匹配跳过）。界面为工具栏「查找」按钮展开的替换栏：查询框、替换框、`.*` 正则开关、`Aa` 大小写开关、命中计数、「全部替换」。

### 8.4 版本

版本号唯一来源 `appVersionName`/`appVersionCode`（见 `app/build.gradle.kts`）；**当前版本与每轮测试数字以 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) 头部及 §5.4 为准**，本文不重复维护历史版本与测试计数。golden 语料位于 `src/debug/assets/golden/`（仅 debug 包合并，release 不携带测试资产）；出包前必跑 `scripts/verify_apk_sanitize.ps1` 脱敏校验（ENGINEERING §10.3.1）。release 产物按规范命名 `scratchpad-<abi>-release-<versionName>.apk`，经 `stageRelease` 汇入 `android/dist/` 并清旧包。R21–R22 的界面、SAF 与测量改动以真机自检钩子兜底：`selfCheckFind / golden / cloudSelfCheck / safSelfCheck / safPowerWrite / safPowerVerify`。

### 8.5 路线 D 编辑器宿主（0.6.0）

编辑器不再是独立 Activity，而是 Activity 内的常驻 WebView，挂成 `TYPE_APPLICATION_PANEL` 子窗口：

| 环节 | 实现与理由 |
|---|---|
| 载体 | `MainActivity.setupEditorOverlay()` 只创建 `WebView` 与 `EditorHost`，不 `loadUrl`；`attachEditorPanelIfNeeded()` 在 `decorView` attach 回调里挂窗口，挂上后才 `host.attach()` |
| 为什么用 panel 子窗口 | WebView 默认独立 surface 合成，作为普通子 View 会被 Compose 盖住；`TYPE_APPLICATION_PANEL` 的 Z 序在应用窗口之上，且保留硬件合成 |
| 为什么不用 `LAYER_TYPE_SOFTWARE` | 软件层能让 Z 序正确（截图 `build/o6.png`），但合成走 CPU：`gfxinfo` 57 帧 / janky 98.25% / 50th 109 ms ≈ 9 fps，滚动不可能达标 |
| 必须先挂窗口再加载 | WebView 在无窗口状态下 `loadUrl` 后再搬进窗口会重建渲染进程，实测整页重载多花 1.4 s（`page ready` 从 1.6 s 变成 6.0 s） |
| 窗口 token | `onCreate` 阶段 `decorView.windowToken` 为 null，直接 `addView` 必崩 `BadTokenException`；改用 `decorView.addOnAttachStateChangeListener`（并保留 `onResume`/`showPanel` 兜底重试） |
| 显隐 | 常驻窗口用 `alpha 0/1` + `FLAG_NOT_TOUCHABLE` 切换；alpha 从 0 变 1 后 SurfaceFlinger 不会重绘旧内容，必须 `invalidate()`（否则白屏，截图 `build/p4.png` 为故障态，`p5.png` 为修复后） |
| 返回键 | panel 窗口有自己的焦点，`Activity.onBackPressed` 收不到；`EditorHost.attach()` 里给 WebView 加 `setOnKeyListener` 转发 `onAction("back")`，Activity 侧改用 `OnBackPressedDispatcher`（lint `GestureBackNavigation` 因此清零） |
| 页内安全区 | `index.template.html` 加 `viewport-fit=cover`，`editor.css` 加 `body{padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}`，避免工具栏压状态栏 |
| 自动化入口 | `am start -n io.github.gscratchpad/.MainActivity --es openDoc <docId>`：页面就绪后直达指定文档，免去点标签的坐标依赖 |
| 帧率探针 | `editor.js` 内置 rAF 采样：滚动后 2 s 窗口内统计帧数上报 `fps`，空闲时每 4 s 上报 `fpsIdle`（用于把「环境上限」与「编辑器成本」分开），日志 `editor metric fps=/fpsIdle=` |
| 中文 soak 钩子 | `am start … --ei soakSeconds <n>`：页面就绪后调 `NativeEditor.soakChinese(n)`，每 100 ms 经 CM 事务注入 20 个中文字符，结束时上报注入总量 `editor metric soak=` |
| 页内覆盖层（0.6.1） | 命令面板 / 大纲 / 设置三个面板做在 WebView 页内（panel 会盖住 Compose，Dialog 不可见）。`#palette/#outline/#settings` 放在 `#host` 之后、`position:absolute` + `z-index:20`；动作表由 Kotlin 单源下发（`EditorActions.all` → `NativeEditor.setActions()`），页内只负责检索与渲染 |
| 面板自动化入口（0.6.1） | `--es openPanel palette\|outline\|settings` 页面就绪后直接开面板；`--es runAction share\|saveAs\|foldAll\|…` 直接执行动作，绕开工具栏坐标（每次滑动后位置都会漂） |
| 偏好回传（0.6.1） | 页内改字号/行高/折行 → `AndroidEditor.onPrefsChanged(json)` → `SharedPreferences("editor-prefs")`；下次 `onReady` 由 `applyEditorPrefs()` 回灌 |
| 主页纯列表化（0.6.2） | `AppScreen()` 只剩「顶栏（应用名 + 日/夜）+ 动作行（新建 / 打开文件 / 导入备份 / 导出备份）+ 最近文档卡片列表」；Compose 侧的编辑器工具栏、查找替换栏、标签胶囊、状态行、「点标签进入编辑器」「编辑当前文档」全部删除，`findOpenFlow` 与 `applyReplaceAll` 一并删除 |
| panel 初始透明（0.6.2） | `attachEditorPanelIfNeeded()` 在 `addView` **之前**设 `lp.alpha=0f` + `FLAG_NOT_TOUCHABLE`；`showPanel()` 才置 1 并清 flag。此前在 `addView` 之后改本地 `lp` 未回写窗口，导致 panel 挂载即整屏不透明（`ANDROID_ENGINEERING.md` §9.3） |
| 子窗口 BACK 转发（0.6.2） | `editorView.setOnKeyListener`：`KEYCODE_BACK` + `ACTION_UP` → `onBackPressedDispatcher.onBackPressed()`；panel 有焦点时 `Activity.dispatchKeyEvent` 收不到键 |
| 会话状态语义（0.6.2） | 列表读 `dao.allDocuments()`（含 `closed`）；`openEditor` 置 `state=open`、`closeEditor` 置 `state=closed`；`reload()` 不再自动建文档；「新建」创建后直接进编辑器 |
| 查找入口统一（0.6.2） | `Ctrl+F` / `KeyAction.FIND\|REPLACE` → `EditorHost.openFind()` → `window.NativeEditor.openFind()`（展开页内 `#findbar` 并聚焦 `#findq`） |
| 主页设置入口（0.6.3） | 顶栏「设置」→ Compose `AlertDialog`（字号 11–32、行高 1.20–2.20、折行开关）→ `SharedPreferences("editor-prefs")` + `editorHost?.setPrefs()` 即时生效；与页内设置共用同一份键 |
| 文档重命名 / 删除（0.6.3） | 卡片 `combinedClickable` 长按 → `DropdownMenu`；重命名 = `AlertDialog` + `OutlinedTextField` → `repository.rename(id, title)` → `reload(id)`；删除 = 二次确认（标注不可撤销）→ `repository.delete(id)`，若为当前文档清 `activeId` |
| 每轮出包（0.6.3） | `gradle :app:assembleRelease :app:verifyReleaseBudget`；真机装 `app-arm64-v8a-release.apk`，debug 包仅用于模拟器 |
| 编辑器图标栏 + 面包屑（0.6.4） | 页内 `#bar` 六个 inline SVG 按钮（brand=`data-act="palette"`、`find`、`outline`、`preview`、`more`（切 `#moremenu`）、`close`），44×44 触摸目标；`#crumb` = 文档图标 + `#doc-title` + `›` + `#status`（`N 行 · M 字 · L:C`，800 ms 刷新）；`#bar button[data-act]` 与 `#findbar button[data-find]` 两套选择器独立，改一处须同步 DOM |
| 溢出菜单（0.6.4） | `#moremenu` 10 项（`data-more=save/saveAs/share/snippets/fold/foldAll/unfoldAll/settings/theme/new`）→ `runAction(dataset.more)` → 本地处理或 `bridge().onAction(id)`；`position:absolute; top:52px; right:8px; z-index:21`；document 捕获阶段 `closest('#moremenu,#bar button[data-act="more"]')` 判断外点收起，`hideOverlays()` 一并 `closeMore()` |
| 标题下发（0.6.4） | `EditorHost.pendingTitle` + `setTitle(title)` → `window.NativeEditor.setDocTitle`；`MainActivity.openEditor()` 在 `setTheme` 后调用，`onReady` 回放 `pendingTitle`，保证重挂/翻页后面包屑标题不丢 |
| 主页重排（0.6.4） | hero（30sp 粗体 + 副标题）+ `SlidersIcon`（Canvas 自绘）进设置 + 「夜间/日间」`TextButton` + 实心「打开文件」54 dp（`ButtonDefaults.buttonColors` 随主题反转）+ 描边「新建文档」50 dp + 文字链「浏览全部文件」→ `*/*` + 导入/导出备份并排 + 「最近文档 / N 个文件」+ 行内 `md · relativeTime(updatedAt)` + ×；长按 `DropdownMenu` 保留 |
| 相对时间（0.6.4） | `relativeTime(updatedAt: Double)`：`<60 s` 刚刚、`<1 h` N 分钟前、`<1 d` N 小时前、`<30 d` N 天前、否则 `YYYY-MM-DD`（`Calendar` 按本地时区） |
| 动作 id 复数修正（0.6.4） | `onEditorAction` 原仅匹配 `"snippet"`，而 `EditorActions` 为复数 `snippets` → 「插入片段」静默无响应；改 `"snippet", "snippets"` 两支 |
| 预览页归一（0.7.0） | `PreviewActivity` 重写：纵向 56 dp 图标栏（`paintBar()` 绘制 BACK / 标题 / 日夜间 / PDF / 关闭，`PanelIconView` Canvas 自绘四图标 + `contentDescription`）+ WebView `weight 1`；`exported=false`，仅能由应用内 `--es runAction preview` 进入；600 ms `syncTick` 轮询 `ScrollSync.pullFromEditor()` 与 `currentScrollY()` |
| 双向滚动同步（0.7.0） | `HeadingIndex`（`^(#{1,6})\s+(.*)$`、跳过 ``` / ~~~ 围栏、`indexForLine`、≤500 条）+ `ScrollSync`（`editor`/`headings` 均 `@Volatile`；`onPreviewScrolled` / `pullFromEditor`；900 ms 双向抑制窗防抖回弹）；`PreviewHost` 增 `scrollListener`、`topHeadingIndex`、`scrollToHeading`、`scrollTo`、`currentScrollY` 与 `gsScrollToHeading/gsTopHeadingIndex/gsScrollY/gsScrollTo` |
| 平板双栏（0.7.0） | `MainActivity`：`panelContainer`（横向容器）+ `setSplit(on, auto)` + `startSplitSync/stopSplitSync`（600 ms 协程轮询）+ `scheduleSplitRender`（800 ms 节流）；`smallestScreenWidthDp ≥ 600` 自动开启；`--es split true` 走 `pendingSplit` + 1.5 s 延迟，窄屏也可验 |
| 插图（0.7.0） | `importImage(uri)`：读字节 → MIME 映射扩展名 → `AssetStore.importBytes` 落 `files/assets/<docId>/<sha12>.<ext>` → 编辑器插入 `![](assets/<docId>/<file>)`；`GetContent` 选取 `image/*` |
| 净化口径（0.7.0） | 预览渲染把相对 `assets/…` 改写为 `/assets/…`（`WebViewAssetLoader` 的 `addPathHandler("/assets/", InternalStoragePathHandler(context, assetsDir))`），并移除 `javascript:` / `data:` 等非法协议 `src`；`securityLevel:'strict'` + `html:false` 保持 |
| 云备份（0.7.0） | `CloudBackup`：WebDAV PUT / HEAD / GET + Basic auth，12 s / 30 s 超时；`showCloudDialog()`（URL / 账号 / 密码 + 保存配置 / 上传 / 从云端恢复）+ `buildBackupZip()`（复用 `BackupExporter`，`appVersion=0.7.0`）+ `importBackupZip(zip, cache)`；清单新增 `INTERNET` 权限（与「纯本地」旧口径冲突，已在注释写明取舍） |
| 物理键盘（0.7.0） | `Shortcuts` 15 个 `KeyAction`（新增 SAVE / SAVE_AS / OPEN / TOGGLE_SPLIT / HELP / IMAGE / RENAME）+ `resolve()`（Ctrl+S / Ctrl+Shift+S / Ctrl+O / Ctrl+D / Ctrl+I / Ctrl+Shift+/）+ `resolvePlain()`（F1→HELP、F2→RENAME、F9→TOGGLE_SPLIT）；`dispatchKeyEvent` 扩键码；页内 keymap 同步 `Mod-s/Mod-Shift-s/Mod-o/Mod-d/Mod-i/Mod-Shift-/` 与 `F1/F2/F9`；新增 `#help` 遮罩（14 条）与 `renameCurrentDialog()` |
| 幂等渲染短路（0.7.0） | `PreviewHost.renderMarkdown()`：`markdown == lastMarkdown && key == shellKey` 即 return，杜绝「渲染→再渲染」自激循环（真机 12 s 内渲染次数从数十降到 1） |
| 热日志（0.7.1） | `data/DraftJournal.kt`：`AtomicReference<Entry>` + `AtomicBoolean scheduled` + 单线程守护执行器 `gs-draft-journal`；`offer(docId, revision, content, ts)` 只保留最新快照（同 docId+revision 同引用内容去重），`drain()` 原子写 `files/recovery/<docId>.json`（json：`id/revision/content/ts`），`drop(docId)` 关文档即清；只写 journal 不做 DB 提交。`AppContainer` 注入 `val draftJournal by lazy { DraftJournal(recovery) }`；`MainActivity.onDocChanged` 递增 `editorRevision` 后立即 `offer`，`closeEditor()` 调 `drop` |
| 恢复语义（0.7.1） | `RecoveryManager.recover()`：逐条读 journal，`journal.revision > db.revision` → `UPDATE documents SET content=?, revision=?, updated_at=?` + `mirror.write` + note「已从恢复日志还原文档 …（revision N）」+ 删日志，否则直接删日志；日志 `recover restored …` / `recover discards …` |
| 跨端金标准（0.7.1） | `scripts/golden_fingerprint.py`（桌面侧 vendored Python-Markdown 3.10.2，`extensions=[extra, sane_lists, nl2br, admonition, codehilite, toc]`）+ 页内 `window.gsFingerprint()`（Android 侧 markdown-it）；指纹 = 折叠空白后的正文纯文本 + 白名单标签计数（`h1–h6/p/li/ul/ol/pre/blockquote/table/tr/th/td/strong/em/code/a/img/hr`，刻意不含 `span/div/br`）；`MainActivity.runGoldenCorpus()` 在 `alpha=0f` 的 2×2 隐藏 WebView 里逐条渲染 → `PreviewHost.evaluate(script, onResult)` → `Log.d("golden|<name>|<json>")` |
| 云备份自检（0.7.1） | `cloudSelfCheck()`：读 `--es cloudUrl/cloudUser/cloudPass` → `saveCloudConfig` → `flushEditor` → `buildBackupZip` → `CloudBackup.upload` → HEAD 取 `remoteSize` → `download` → `ZipFile` 校验（`hasDb/hasManifest/sizeMatch`）→ `Log.d("cloudSelfCheck result=<json>")` |
| 清除记录（0.7.2） | 语义：本工程「文档」= DB 行 + `files/notes/<id>.md` 镜像，删行即真丢内容。故不删行，只加可见性标记：`Schema.VERSION 3→4`、`documents.recent_hidden INTEGER NOT NULL DEFAULT 0`、`V3_TO_V4 = ALTER TABLE documents ADD COLUMN recent_hidden …`，`DbHelper.onUpgrade` 先 `PRAGMA table_info(documents)` 查列再执行（幂等）；DAO 增 `recentDocuments()`（`WHERE recent_hidden=0 ORDER BY sort_index`）、`setRecentHidden(id,h)`、`setAllRecentHidden()`；Repository 增 `clearRecent/clearAllRecent/restoreRecent`（均 `withContext(io)` + `bump()`）。主页：非全部视图只列 `!recentHidden`，表头 `clear` 调 `clearAllRecent()`，行尾 × 调 `clearRecent()`，长按菜单仍是唯一删除入口；全部视图里隐藏项显示「· 已清除记录」+「恢复」 |
| 编辑器 A/B 串内容竞态（0.7.2） | 两个结构性根因：① `closeEditor()` 在协程里 `flushEditor()`，而 `flushEditor()` 读实时字段 `editingDocId/editorLatest`——「关 A 后立刻点 B」时 B 已把字段覆盖，A 的正文被写进 B；② `activate()` 无条件 `editorHost?.setDocument(doc.content)`，即使面板已隐藏，关闭后的 `reload()` 会把 A 塞回隐藏 WebView，再开 B 仍见 A。修法：新增 `editorEpoch`（开/关各 +1），`openEditor` 取 `myEpoch`，`repository.get` 回来 `if (myEpoch != editorEpoch) return`；`closeEditor` 改为先同步取 `id/snapshot/snapshotRev` 再 `editorEpoch++`、`hidePanel`、清 `editingDocId/editorOpen`，协程里 `saveNow(id, snapshot, snapshotRev)`；`activate()` 的 `setDocument` 加 `if (editorOpen)` 守卫 |
| 全屏设置页（0.7.2） | `Dialog(onDismissRequest, DialogProperties(usePlatformDefaultWidth=false, decorFitsSystemWindows=false))` 承载 `SettingsScreen`（`fillMaxSize` + `verticalScroll` + `systemBarsPadding`）：标题/副标题/圆形 ×、`SettingLabel` 小标题、`SettingCard`（16 dp 圆角 + `cardBg`）、`SegmentPill`（40 dp 分段按钮）、`SettingRow`（标题+副标题+`›`）、`SettingDivider`；Theme 分段、字号/行高 `Slider`（`sliderColors(foreground)` 覆盖 Material 默认紫）、自动折行 `Switch`、DATA 三行（导入/导出/云端备份）、ABOUT 两行；字号/行高/折行改动即时 `persistPrefs` 并下发 `editorHost.setPrefs` |
| 系统栏随主题（0.7.2） | `setDark(on)`：写 `dark.value` + `editor-prefs.dark` + `editorHost.setTheme` + `applySystemBars`；`applySystemBars(isDark)`：`WindowCompat.getInsetsController(getWindow(), getWindow().decorView)` 设 `isAppearanceLightStatusBars/NavigationBars = !isDark`；**`statusBarColor` 必须填主题底色（深 `#1F2328` / 浅白），不能填 TRANSPARENT**——`decorFitsSystemWindows=true` 时内容不绘制到状态栏下方，透明会露出窗口白底；导航栏同色，API≥29 关 `isNavigationBarContrastEnforced`；`onCreate` 从偏好回灌后 `post { applySystemBars(dark) }`；`PreviewActivity` 同实现并在主题切换时调用 |
| 弹窗空白关闭（0.7.2，0.7.13 修正） | `android/tools/editor/src/editor.js` 增 document 级 click 监听：命中 `closest(".sheet")`（0.7.13 起白名单改为面板卡片本体；旧口径 `closest(".overlay")` 是全屏遮罩，会把「点遮罩空白」判成「点在面板内」，导致只能用「关闭」按钮退出） / `closest("#moremenu")` / `closest("#findbar")` 或 `closest("#bar")` / `closest("#crumb")` 时放行（否则刚点开就被自己关掉），其余一律 `hideOverlays()`，并在 `findbar` 可见时收起查找条；`node build.mjs` 重建 `assets/editor/index.html`（346,181 B @ 0.7.13） |
| 应用图标（0.7.2） | 源为桌面 `data/icons/hicolor/scalable/apps/io.github.gscratchpad.Gscratchpad.svg`；`res/drawable/ic_launcher_foreground.xml` 按 108 viewport 重绘：白纸圆角 + 左侧蓝脊 `#1C71D8`（顶段 `#3584E4`）+ 白扣环 + 四条 `#C8C5C0` 横线 + `<group rotation="38" pivot(78,76)>` 铅笔（`#F5C211` 身 / `#E66100` 上端 / `#DEDDDA` 笔尖 / `#241F31` 芯 / `#E01B24` 橡皮）；`mipmap-anydpi-v26/ic_launcher.xml` 同时用于 `icon` 与 `roundIcon`，背景 `@color/ic_launcher_background` = `#1F2933` |
| 图标按参考图复刻（0.7.5） | 蓝本 `android/tmp/图标设计.png`（深藏青底 + 米白圆角卡 + 三行手写波浪、中行橙光晕 + 右下橙光标条）。`ic_launcher_foreground.xml` 重绘：108 viewport 米白渐变圆角卡 `#F8F2E8→#EFE9DF`、中行光晕线性渐变带 `#F7B267` 上下淡出、三行波浪 stroke `#1E2A3A/#223042` round cap + 双短划、右下 `#F5A623` 光标条 3.4 宽；`ic_launcher_background` 改 `#17293C`。cursive 笔迹以波浪 stroke 路径近似（矢量近似，非逐像素）；真机桌面核验渲染 |
| 打开文件直开（0.7.4） | `openExternal()` 语义定为「导入副本进库（保留 `sourcePath`）+ `saveNow` + `setMeta` + `reload` + `openEditor(doc.id)` 直接进编辑器」；此前只 `setMeta + reload` 造成「打开文件只加最近记录不打开」 |
| 最近文档按打开时间排序（0.7.4） | schema v4→v5：`documents.opened_at REAL NOT NULL DEFAULT 0` + `idx_documents_opened`；`V4_TO_V5` 先 `PRAGMA table_info` 查列再幂等 ALTER；`Document.openedAt`；三个列表查询改 `ORDER BY opened_at DESC, updated_at DESC, sort_index ASC`；`touchOpened(id, at)` 同时 `SET opened_at=?, recent_hidden=0`（打开自动恢复已清除记录） |
| 预览不回顶（0.7.4） | 根因：预览页里编辑器 WebView 已暂停，`syncTick` 轮询 `pullFromEditor()` 拿到旧 topLine，按标题反推把预览拽回顶部。修复：`PreviewActivity.syncTick` 只监听预览自身滚动 `ScrollSync.onPreviewScrolled(y)`（位移 >6 触发），不再轮询编辑器；编辑器→预览推送只在同屏双栏由 `MainActivity` 驱动；`ScrollSync.attach` 加同 host 重复 attach 保留位置；`pullFromEditor` 加「顶行距标题 ≤3 行视为已对齐」防漂移 |
| 设置页补齐（0.7.4） | `SettingsScreen` 新增：Theme 三段 夜间/AMOLED（`onAmoled`）/日间、字体三段 sans/mono/serif（`fontFamily`）、编辑字号 Slider 11–32 + 阅读字号 Slider 12–28（`readingSize`）、全屏阅读 Switch（`fullRead`，预览页隐藏顶栏）、PDF 深色导出 Switch（`pdfDark`）、FEEDBACK 两行（GitHub 仓库 / 邮件反馈）；`PreviewHost.renderMarkdown(content, dark, fontSize, amoled)` 新签名；偏好键都在 `editor-prefs` |
| 表头双态（0.7.4） | 主页列表头常驻「最近 / 全部」双态文字切换（半粗体高亮当前态），`clear` 仅在最近视图显示，「查看全部文档（N）」保留兜底 |
| `documentTreeRoots()` tree 过滤（0.7.6） | 历史持久化的单文件授权（OpenDocument 结果）混入目录树列表，`DocumentFile.fromTreeUri` 对非 tree URI 抛 `IllegalArgumentException`（导入备份路径可复现崩溃）；修复：只返回 `uri.pathSegments.firstOrNull()=="tree"` 的授权 |
| SAF 原子换名（0.7.10/0.7.11） | 根因一：OPPO externalstorage provider 拒绝「扩展名与 MIME 不一致」的 `createDocument`（`power.md.tmp` + `text/markdown` → `Failed to create unique file`），旧链路从未生效、全部静默退化 IN_PLACE——tmp 改 `application/octet-stream` + `"$base.tmp$ext"`。根因二：旧「tmp 写入校验后原文件 truncate 重写」仍非原子——改为两步 `renameDocument` 原子换名：旧文件 rename → `.old`、tmp rename 回原名，任意时刻断电目标名下都是完整旧版或新版；rename 失败回滚 `.old` 再退化 IN_PLACE。实测同 provider `deleteDocument` 不可用（新建/改名 URI 均抛 `Delete not supported`），`.old` 清理改尽力而为、失败不影响保存结果（留冗余备份）；同目标第二次起保存因 `.old` 已存在退化为 IN_PLACE。探针日志 tag `SafGW` |
| 预览栏图标重绘（0.7.13） | `PanelIconView` 重写为 24 单位网格自绘（unit=min(w,h)/24×0.86，1.7 单位线宽、圆头描边），五种 Kind：BACK 长箭头、OUTLINE「圆点+文本线」三行（与编辑器大纲图标同构）、THEME 双圆弧求交月牙 + 小星、PDF 折角文档 + 两行正文线、CLOSE X；按压 `isPressed` 画 alpha 26 圆角底色；`PreviewActivity.paintBar()` 顺序改为 BACK/标题/OUTLINE/THEME/PDF/CLOSE |
| 预览大纲浮层（0.7.13） | `PreviewHtml.buildShell` 注入 `#gs-outline` 全屏遮罩 + `.gs-sheet` 卡片（主题色随 dark/amoled）；`gsOpenOutline()` 扫渲染结果标题（`#content h1–h6`，id 由 `gsRender` 统一赋 `h+i`），点条目 `gsCloseOutline + gsScrollToHeading(i)`；document click 白名单用 `.gs-sheet`（不能用 `#gs-outline`，与编辑器 R24 同根因）；`PreviewHost.openOutline()` evaluate 调用；`PreviewActivity` 顶栏标题后新增 `OUTLINE` 图标按钮（`PanelIconView.Kind.OUTLINE`，40 dp + 2 dp 间距） |
| SAF 自检钩子（0.7.5+） | `runAction safSelfCheck`（A 字节保真：GB18030+CRLF 原始字节 open→save 往返 SHA 比对；B 千文件枚举计时；C 写 power.md V1 基线）、`safPowerWrite`（单次 findFile 后连续 12 轮覆写 V2）、`safPowerVerify`（power.md 必须为完整 V1/V2，报告 `.tmp` 残留）；千文件目录由 adb 预置 `/sdcard/Download/saf1000`（1000 个 5 B 文件） |

## 9. 测试策略落地（§11，0.3.0）

| 层 | 手段 | 实测 |
|---|---|---|
| 单元 | JUnit（JVM） | 72 条全绿（13 套件 / 0 失败）；domain 行覆盖 279/307 = 90.9%（fold 94.4%、search 96.9%、model 71.4%） |
| 契约 | `DesktopBackupContractTest`：现场构造 §6.1 备份包（`manifest.json` + `gscratchpad.db` + `assets/pic.png`），5 篇文档 / 2 个文件夹 / closed 态 / 窗口几何 meta / `source_path` | 5 条全绿：导入 5/5、0 errors、verified、标题与正文 SHA-256 一致、`sort_index` 顺序保留、`window_w` 未导入、`view_mode` 保留、`source_path` 置空且 `deadPaths=1`；另覆盖图片重写、revision 冲突留败者副本、zip-slip 拒绝、schema 不匹配不动目标库 |
| UI | `EditorUiSmokeTest`（`createAndroidComposeRule<MainActivity>`） | 3/3 通过，29.189 s（首轮 15.869 s），`test-result-exit-code=0` |
| 性能 / 输入法 / 兼容矩阵 | Macrobenchmark、`adb shell ime`、云真机 | 未执行，见 `ANDROID_ENGINEERING.md` §9 |

覆盖率生成：`gradle :app:jacocoDebugUnitTest`，报告在 `app/build/reports/jacoco/jacocoDebugUnitTest/`。门禁用 `gradle :app:coverageGate`（domain <80% 直接失败）。

## 10. 工程化与发布（§12，0.3.0）

| 项 | 实测 |
|---|---|
| release 包体 | `app-arm64-v8a-release.apk` 2.94 MB、`app-x86_64-release.apk` 2.94 MB（预算 12 MB） |
| R8 | `minifyEnabled` + `shrinkResources` 打开；release 包在 Pixel_API36 上安装、启动、预览正常（`preview ready in 1020 ms`） |
| Lint | `:app:lintRelease` 0 error、1 issue（`ObsoleteLintCustomCheck`，外部库 `lint.jar` 失效 API；修注解后须 `--rerun-tasks` 才会重算报告） |
| 签名 | `keystore.properties` 存在则用 upload key，否则 debug 签名 |
| 备份策略 | `allowBackup=false`，`dataExtractionRules` / `fullBackupContent` 全库排除 |
| CI | `.github/workflows/android-ci.yml`（单测 + 覆盖门禁 + lint + release + 包体预算；模拟器仪器测试） |

细节（含 APK 内部分组、R8 保留规则、门禁任务、未完成项）见 [ANDROID_ENGINEERING.md](ANDROID_ENGINEERING.md)；风险登记见 [ANDROID_RISK_REGISTER.md](ANDROID_RISK_REGISTER.md)。

## 11. 本轮新增根因记录

| 现象 | 根因 | 修复 |
|---|---|---|
| JaCoCo 报告为空 `<report/>`（`package.Count=0`） | 报告任务的 class 目录写成 `tmp/kotlin-classes/debug`，AGP 9.x 内置 Kotlin 的实际输出在 `intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes` | `build.gradle.kts` 改 fileTree 路径 |
| `kotlin` 语法的括号折叠区间算成 `(0,3)/(1,2)`（应为 `(0,4)/(1,3)`） | `FoldModel.strategy` 的 BRACE 语言集合漏了 `kotlin`/`kts`，落进 INDENT 分支按缩进算 | 补 `kotlin`/`kts`，并在 `FoldModelExtraTest` 中断言策略与区间 |
| `mipmap-anydpi` 无版本目录导致 `resource mipmap/ic_launcher not found` | AAPT 只在 `mipmap-anydpi-v26` 识别 `<adaptive-icon>` | 目录改回 `-v26`，用 `app/lint.xml` 忽略 `ObsoleteSdkInt` |
