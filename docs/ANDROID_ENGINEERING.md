# Android 工程化与发布（方案 §12 落地）

本文只写已在本机（Linux，JDK 21）实际执行过的取值与数据；早期 Windows 环境安装记录见 [archive/ANDROID_ENV_SETUP.md](archive/ANDROID_ENV_SETUP.md)。命令均在 `android/` 下执行，本地命令形态见 §1「命令执行纪律」。

> 当前版本 **0.9.8（versionCode 55）**，最近一轮 R55（2026-11-27）：编辑栏浮栏化 + 毛玻璃特效（backdrop-filter blur16 悬浮圆角，selbar 同步，旧内核 @supports 退化）；237 单测 / 0 失败，`coverageGate` / `lintRelease` 0 error / `verifyReleaseBudget` 全绿，upload key 出包至 `android/dist/`。逐轮变更史以 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) 为唯一权威记录，本文不重复维护流水账。

## 1. 工具链（实测）

| 项 | 取值 | 说明 |
|---|---|---|
| Gradle | 9.9.1（`gradlew` 已生成，wrapper 锁定同版本） | 方案 §12 写 Gradle 8.x；本机 AGP 9.5.1 要求 Gradle 9.x，取 9.9.1 |
| AGP | 9.5.1 | 内置 Kotlin，禁止再 apply `org.jetbrains.kotlin.android`（会报 `Cannot add extension with name 'kotlin'`） |
| Kotlin | 由 AGP 内置（KGP 随 AGP） | 编译任务落在 `intermediates/built_in_kotlinc/...` |
| Compose | `org.jetbrains.kotlin.plugin.compose` 2.2.10 + `compose-bom 2025.10.01` | BOM 2026.09 需 compileSdk 37，本机只有 36 |
| JDK | 21（`<JDK-21 路径>`） | 编译目标 Java 17 |
| compileSdk / targetSdk / minSdk | 36 / 36 / 26 | |
| 构建工具 | build-tools 36.0.0，platform-tools 含 adb | |
| 覆盖率工具 | JaCoCo 0.8.12 | `JacocoTaskExtension` 开 `isIncludeNoLocationClasses`，排除 `jdk.internal.*` |

**命令执行纪律（务必照此，勿重复试错）**：

- 一律用 `bash gradlew <task>`（或 `sh gradlew`）。直接 `./gradlew` 在本环境被沙箱拒绝（`zsh: 拒絕不符權限的操作`，exit 126），不要再先试 `./gradlew`。
- 所有 gradle 命令显式带 `ANDROID_HOME=<Android SDK 路径> GRADLE_USER_HOME=<Gradle 缓存目录>`（本机 `local.properties` 未落盘，缺 `ANDROID_HOME` 会报 `SDK location not found`）。
- 完整形态：`ANDROID_HOME=<Android SDK 路径> GRADLE_USER_HOME=<Gradle 缓存目录> bash gradlew :app:coverageGate :app:lintRelease`

## 2. 变体与 ABI

| 项 | 取值 |
|---|---|
| 变体 | `debug`、`release` |
| ABI splits | `arm64-v8a`（必选）、`x86_64`（模拟器）；`isUniversalApk = false` |
| `armeabi-v7a` | **已排除（R21 用户拍板）**。32 位设备份额不足，纳入会使矩阵与包体翻倍；`splits.abi.include("arm64-v8a", "x86_64")` |
| `jniLibs.useLegacyPackaging` | `false`（`lib/` 在 APK 内保持未压缩，直接 mmap） |

## 3. Release 构建

| 开关 | 取值 |
|---|---|
| `isMinifyEnabled` | `true`（R8，`proguard-android-optimize.txt` + `app/proguard-rules.pro`） |
| `isShrinkResources` | `true` |
| 签名 | 存在 `android/keystore.properties` 时用 upload key；否则退回 debug 签名（仅本地度量体积） |

`app/proguard-rules.pro` 保留项：

| 保留 | 原因 |
|---|---|
| `@JavascriptInterface` 注解方法 | 预览桥；被 R8 改名后 WebView 调用直接失效 |
| `PreviewHost$attach$2$1` | 匿名内部类承载 `onReady` 回调 |
| `android.webkit.WebView`、`WebSettings` 相关反射面 | 平台 API 反射调用 |
| `SourceFile` / `LineNumberTable` | 崩溃栈可定位（`-keepattributes`） |

Hermetic 验证：release 包在 Pixel_API36 上安装、启动、进入预览，`preview ready in 1020 ms chars=2`，界面正常渲染（截图 `android/build/release-preview2.png`）。说明 R8 未破坏 JS 桥与 asset loader。

## 4. 包体预算（实测）

| 产物 | 体积 |
|---|---|
| `scratchpad-arm64-v8a-release-0.8.3.apk` | 3.5 MB（0.8.3 / versionCode 46，R45 upload key 正式签名） |
| `scratchpad-x86_64-release-0.8.3.apk` | 3.5 MB（0.8.3 / versionCode 46，R45 upload key 正式签名） |
| `app-x86_64-debug.apk` | 12.4 MB |

> R24 起 release 产物按发版规范重命名：`scratchpad-<abi>-release-<versionName>.apk`（abi ∈ arm64-v8a / x86_64）。由 `androidComponents.onVariants` 新版 Variant API 设置 `output.outputFileName`，`stageRelease` task 一站式构建+核验+汇入 `android/dist/` 并清旧包。**交付目录为 `android/dist/`**，debug 包不作交付。

预算 12 MB 用的是 APK 压缩后体积，release 为 3.27 MB，占预算约 27%。

APK 内部构成（arm64-v8a，未压缩条目长度合计）：

| 分组 | 大小 | 主要内容 |
|---|---|---|
| `assets/` | 4,727 KB | `vendor/js/mermaid.min.js` 3,258 KB、`katex.min.js` 269 KB、`markdown-it.min.js` 121 KB、KaTeX 字体（ttf + woff 双份） |
| `classes*.dex` | 1,758 KB | 应用 + Compose + WebKit + androidx |
| `res/` | 82 KB | 自适应图标、主题、规则 XML |
| `lib/` | 10 KB | `libandroidx.graphics.path.so`（未 strip，R8 提示打包原样） |
| `META-INF` / 其他 | 109 KB | 签名与清单 |

控制手段与余量：KaTeX 字体同时存在 `ttf` 与 `woff` 两套，按 `PreviewHtml` 只用 `woff2/woff` 的话可再省约 200 KB；Mermaid 为体积主项，按需加载已实现（`MarkdownFeatures.hasMermaid` 为 false 时不注入），但资源本身仍随包分发。如需进一步压包，改为首次使用时从 `assets` 解压到缓存并删源不成立（APK 只读），因此 Mermaid 体积只能接受或换更小渲染器。

## 5. 权限与隐私

| 项 | 实测 |
|---|---|
| 权限 | `aapt2 dump badging` 只有 `io.github.gscratchpad.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`（androidx 自用）；无 `INTERNET` |
| 备份 | `android:allowBackup="false"` + `dataExtractionRules` / `fullBackupContent` 全库排除（`res/xml/data_extraction_rules.xml`、`res/xml/backup_rules.xml`），云备份与设备迁移都不导出笔记 |
| 导出 | 仅应用内备份（§6.1 格式）与 PDF（`PrintManager.print`） |
| 崩溃监控 | 不接第三方 SDK；`recovery/` 与日志留在私有目录 |

## 6. Lint

| 项 | 结果 |
|---|---|
| 任务 | `gradle :app:lintRelease` |
| 结论 | 0 error，1 issue |
| 唯一 issue | `ObsoleteLintCustomCheck`：`lifecycle-runtime-release/lint.jar` 引用了失效 API，属外部库问题，跳过其检查 |
| 复算注意 | 改注解（如 `@SuppressLint("RestrictedApi")`）后必须 `gradle :app:lintRelease --rerun-tasks`，否则读到上一次的报告（曾因此误判为仍有 3 条 `RestrictedApi`） |
| 已修项 | `DataExtractionRules`（补备份排除规则）、`MonochromeLauncherIcon`（补 `<monochrome>`）、`UnusedResources`（删除未使用的 `Theme.Gscratchpad.Dark`）、`UseKtx` 6 处（`SQLiteDatabase.transaction`、`String.toColorInt`）、`RestrictedApi` 3 处（`dispatchKeyEvent` 补 `@SuppressLint`）、`StaticFieldLeak` 3 处（删除常驻 `EditorCache`） |
| 显式忽略（`app/lint.xml`） | `ObsoleteSdkInt`（`mipmap-anydpi-v26` 目录，AAPT 只在该目录识别 adaptive-icon，minSdk 已是 26）、`OldTargetApi`（最新 37，本机 SDK 36）、`GradleDependency` / `NewerVersionAvailable`（版本升级走季度评审） |

报告：`app/build/reports/lint-results-release.html` 与 `.sarif`。

## 7. 质量门禁（Gradle 任务）

| 任务 | 作用 | 实测输出 |
|---|---|---|
| `:app:testDebugUnitTest` | JVM 单测 | 142/142 通过（23 套件，R36） |
| `:app:jacocoDebugUnitTest` | 覆盖率 HTML/XML | `app/build/reports/jacoco/jacocoDebugUnitTest/` |
| `:app:coverageGate` | domain 层行覆盖 ≥80%，否则构建失败 | `domain 行覆盖 308/342 = 90.1%（门槛 80%）` |
| `:app:lintRelease` | 0 error 才允许发版 | 0 error |
| `:app:assembleRelease` | R8 + 资源收缩 + ABI splits | 2 个 APK |
| `:app:verifyReleaseBudget` | 每个 release APK ≤12 MB | arm64 3.29 MB、x86_64 3.29 MB |
| `:app:connectedDebugAndroidTest` | 仪器 UI 冒烟 | `EditorUiSmokeTest` 3/3，29.189 s（首轮 15.869 s），exit code 0 |

JaCoCo 取类的目录必须是 `intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes`。写 `tmp/kotlin-classes/debug` 会得到空报告（`package.Count=0`，本轮踩过并已修）。

## 8. CI

工作流：[`.github/workflows/android-ci.yml`](../.github/workflows/android-ci.yml)。

| Job | 步骤 |
|---|---|
| `unit-lint-release` | JDK 21 + `setup-android`（platform 36 / build-tools 36.0.0）→ `testDebugUnitTest` + `coverageGate` → `lintRelease` → `assembleRelease` + `verifyReleaseBudget` → 上传 APK、覆盖率、lint、单测结果 |
| `instrumented` | 开 KVM → `reactivecircus/android-emulator-runner`（API 36、x86_64、pixel_6）→ `connectedDebugAndroidTest` → 上传 `androidTest-results` |

发版签名：在 CI secrets 生成 `android/keystore.properties`（`storeFile`/`storePassword`/`keyAlias`/`keyPassword`），`app/build.gradle.kts` 检测到该文件即切换 upload key。本地无该文件时用 debug 签名。

仓库当前没有 `.git`（`Test-Path <仓库根>\.git` 为 False），工作流文件已就位，首次推送后生效；本机未执行过 Actions。

## 9. 未完成（不得视为通过）

| 项 | 状态 |
|---|---|
| Baseline Profile | 未生成。需要 `:baselineprofile` 模块 + Macrobenchmark，本机未建；§12 的 CI 步骤中占位为后续工作 |
| Macrobenchmark 性能用例 | 未建。冷启动/滚动/折叠/预览仍用 Spike 阶段手工测量，见 `ANDROID_SPIKE_REPORT.md` |
| Play 上架材料 | 未准备。upload key、数据安全表单（“不收集”）、隐私政策文本待发版前产出 |
| 真机与厂商矩阵 | 仅 Pixel_API36 模拟器 |
| 模拟器 GPU 模式 | 0.6.0 起 AVD `hw.gpu.enabled=yes` / `hw.gpu.mode=host`（原为 `no`，走 SwiftShader），配置备份在同目录 `config.ini.bak`；改法见 §10 附注 |
| armeabi-v7a | 已排除 splits（R21 用户拍板） |

### 9.1 模拟器渲染后端与帧率上限（R12）

`dumpsys SurfaceFlinger` 的 GLES 行可确认后端：

- 原配置 `hw.gpu.enabled=no` → `Google SwiftShader 4.0.0.1`，idle rAF 30 fps。
- 改为 `-gpu host` → `AMD Radeon(TM) Vega 8 Graphics`，idle rAF 52 fps，但 1 MB 滚动仍 26–28 fps。

四组对照（SwiftShader / 宿主 GPU / 关装饰 / 0.5.1 独立 Activity 窗口）详见 `ANDROID_SPIKE_REPORT.md` §8.3。结论：该模拟器 WebView 滚动合成上限 25–35 fps，与文档大小、像素数、编辑器装饰都无关，55 fps 门槛必须真机判定。

> **R14 补测修正**：上述 25–35 fps 是 AVD 长期未重启、被前序压测拖垮后的读数（同期 `fpsIdle` 仅 1–13、`page ready` 38–43 s）。正常重启 AVD 后复测：`fpsIdle` 42 / 47 / 56 / 57 / 60，1 MB 连续上滑 8 次 37 / 44 / 45 / 47 / 48 / 48 / 51 / 57 / 58（均值约 49）。
> **工程结论不变的两条**：①滚动帧率与文档大小、像素数、装饰无关（滚动与 idle 差距很小）；②55 fps 门槛仍需真机判定。
> **必须新增的纪律**：任何帧率/耗时测量前先确认 AVD 处于正常态（`fpsIdle ≥ 40`、`page ready < 10 s`），否则数据无效并作废。测量前 `adb reboot` 或重启 emulator 一次作为基线校准。

### 9.2 WebView 页内 UI 的三个必踩坑（R14，已实测定位）

panel 子窗口（`TYPE_APPLICATION_PANEL`）会盖住 Compose 层，所以命令面板、大纲、设置页只能做在页内。做页内 UI 时这三条会直接让功能"看起来没实现"：

| 坑 | 现象 | 根因 | 交付口径 |
|---|---|---|---|
| `position: fixed` 覆盖层在 panel WebView 里不绘制 | 点击后有 `editor metric palette=open` 日志，但屏幕上看不到任何浮层、也没有半透明遮罩 | WebView 在该子窗口内的 fixed 定位不被合成 | 改用 `position: absolute; top/right/bottom/left: 0`，并把 `#palette/#outline/#settings` 三个节点放在 `#host` **之后**（z-index 20 才真正压住 CodeMirror） |
| `@JavascriptInterface` 匿名对象内同名调用 = 自调用 | 页内改动设置后 `editor metric prefs=...` 有输出，但 `shared_prefs/editor-prefs.xml` 永不生成 | 匿名 object 里的 `onPrefsChanged(json)` 按成员优先解析成自身，形成递归 `post` | 一律写 `this@EditorHost.onPrefsChanged(json)`（`onReady`/`onAction` 已按此写，`onPrefsChanged` 是漏改的那一处） |
| `install -r` 后 WebView 仍跑旧资产 bundle | 新 HTML 里的 `getElementById("palette")` 返回 null → 尾部绑定抛 TypeError → `window.NativeEditor.openPalette` 未定义；点击静默无反应、`onConsoleMessage` 也不打日志 | WebViewAssetLoader 走 HTTP 缓存 | `loadUrl("…/index.html?t=<attachedAt>")` 每次进程唯一；验证页面版本用 `metrics()` 打点而不是 `console.log`（`onConsoleMessage` 未收到 JS 日志） |
| Compose 侧无 `material-icons` 依赖 | 用 `Icons.Filled.Settings` / `Icons.Filled.Close` 编译直接 `e: Unresolved reference 'icons'`（material3 未传递 icons-core），5 处报错 | 现有 classpath 只有 `material3`，图标库是独立 artifact | 不新增依赖：用 `Canvas` 自绘（`SlidersIcon` = 三条滑轨 + 三旋钮）与 `Text("×")` 承载图标；若确需图标库再显式加 `androidx.compose.material:material-icons-core` 并核对 BOM 版本 |
| 页内工具栏/菜单是两套选择器 | 改了 `#bar` 的按钮 id 或 `data-act`，查找条/溢出菜单仍按旧选择器绑定 → 按钮点了没反应且无报错 | `editor.js` 里 `#bar button[data-act]`、`#moremenu button[data-more]`、`#findbar button[data-find]` 三处独立绑定 | 改 DOM 必须同步三处选择器与 `runAction` 分支；新增页内按钮先确认 `data-*` 与 Kotlin 侧 `EditorActions` 的动作 id 完全一致（`snippets` 复数这一点 R17 曾踩过） |

配套的两个自动化入口（不依赖工具栏坐标，坐标每次滑动后都会漂）：

```powershell
# 页面就绪后直接打开某个面板
adb shell am start -n io.github.gscratchpad/.MainActivity --es openDoc mid-1 --es openPanel palette
# 页面就绪后直接执行某个动作（share / saveAs / foldAll / ...）
adb shell am start -n io.github.gscratchpad/.MainActivity --es openDoc mid-1 --es runAction share
```

### 9.3 宿主界面层的三个结构性坑（R15，已实测定位）

R15 之前应用实际是「路线 C 的 Compose 编辑器壳 + 路线 D 的 WebView 叠加」两套并存：用户每次冷启动、以及每次退出编辑器后看到的都是那层 Compose 编辑器界面，因此判定"界面还停在路线 C"。定根如下：

| 坑 | 现象 | 根因 | 交付口径 |
|---|---|---|---|
| panel 从挂载起整屏不透明 | 冷启动/重启后屏幕直接是编辑器页，Compose 主页任何时刻都看不到；`Compose` 按钮点不动 | `attachEditorPanelIfNeeded()` 在 `wm.addView(view, lp)` **之后**才 `lp.alpha = 0f`，只是改了本地 `WindowManager.LayoutParams`，没有 `updateViewLayout` 回写窗口 → 已合成窗口的 alpha 仍是 1 | `addView` **之前**就设 `lp.alpha = 0f` + `FLAG_NOT_TOUCHABLE`；显示时再 `updateViewLayout` 置 1 并清 flag |
| 子窗口吃掉 BACK | 编辑器打开时按返回无反应，只能杀进程 | panel 是 `TYPE_APPLICATION_PANEL` 独立窗口，焦点在 WebView 时键事件走该窗口的 ViewRootImpl，不进 `Activity.dispatchKeyEvent` / `OnBackPressedDispatcher` | 在 `editorView` 上 `setOnKeyListener`：`KEYCODE_BACK` + `ACTION_UP` → `onBackPressedDispatcher.onBackPressed()` 并 return true |
| 主页保留路线 C 编辑器控件 | 主页出现「新建/关闭/查找/预览/夜间 + 标签 + 状态行 + 编辑当前文档」，视觉即路线 C | 路线 D 迁移只做了 WebView 叠加覆盖，没拆 Compose 编辑器壳；两套 UI 永远并存，panel 一透明就露出旧壳 | 主页只保留列表级动作（新建/打开文件/导入备份/导出备份/日夜间）与文档卡片；编辑器内所有动作（查找/替换/折叠/片段/预览/另存/分享/命令/大纲/设置）只在页内 |

语义配套：列表读 `dao.allDocuments()`（含 `closed`），点开 `setState(open=true)`、关闭 `setState(open=false)`，`reload()` 不再「空列表自动建文档」，「新建」创建后直接 `openEditor()`；`Ctrl+F` / `KeyAction.FIND|REPLACE` 统一走 `EditorHost.openFind()` → `window.NativeEditor.openFind()`。

### 9.4 P2 收尾轮的四个新坑（R18，已实测定位）

| 坑 | 现象 | 根因 | 交付口径 |
|---|---|---|---|
| 分屏预览重复渲染 | 双栏开启后 `preview load …` 每 44 ms 一对，`fpsIdle` 被拖到 13 | 同一份 markdown + 同一外壳被反复请求渲染；渲染越快循环越快（真机小文档比模拟器大文档更严重），说明是「无内容变化的重复渲染」而非渲染慢 | `PreviewHost.renderMarkdown()` 开头做幂等短路：`markdown == lastMarkdown && key == shellKey` 直接 return；新增渲染请求必须先改内容或外壳 |
| 分屏新 WebView 残留旧像素 | 新开的预览区显示上一次分屏的旧页面，滚动后才刷新 | 子 View 加入 `TYPE_APPLICATION_PANEL` 窗口后父窗口未重排/重绘，合成层仍是旧缓冲 | 入窗后 `panel.invalidate() + postInvalidateOnAnimation() + updateWindowLayout`，子 View `post{invalidate(); requestLayout()}` |
| 页内标题在页面未就绪时丢失 | 分屏/重挂后面包屑只剩 `› N 行 · M 字`，标题空白 | `openEditor()` 的 `setTitle` 落在页面 ready 之前，JS 侧无对应元素可写 | `openEditor` 里 400 ms 后重推 `setTitle(editorTitle)`；`onReady` 也回放一次 |
| CodeMirror 撤销单位被合并 | 自检「全替换 → 一次 undo」得到 `undoRestored=false`（直接退回写入语料之前） | 探针在同一 tick 内既写语料又做全替换，`newGroupDelay`（默认 500 ms）把两笔并成一个历史组 | 探针/自检步骤必须间隔 > 500 ms（实际取 650 ms）并带 `userEvent` 标注；跨步骤断言一律分 tick |

另记两条本轮确认的操作事实：**真机 release 包 `not debuggable`，`run-as` 不可用**，DB 校验只能靠 debug 包或应用内导出；**换签名安装会清库**（release keystore ≠ debug keystore，`install -r` 触发卸载重装），跨变体切换前先导出备份。

### 9.5 P2 收尾第二轮的三条操作/环境门槛（R19，已实测定位）

| 坑 | 现象 | 根因 | 交付口径 |
|---|---|---|---|
| 明文 WebDAV 被系统拦截 | `cloudSelfCheck` 首轮 `uploadDetail: "上传失败：Cleartext HTTP traffic to <LAN-IP> not permitted"`，其余字段全为 false/0 | Android 9+ 默认禁 cleartext（`targetSdk 36` 同样受 `networkSecurityConfig` 默认策略约束），`HttpURLConnection` 直接抛 `IOException` | 清单 `<application android:usesCleartextTraffic="true">`（自建/局域网 WebDAV 常为 `http://`）；不引入证书固定、不做代理，改用 https 由用户自行决定 |
| WebDAV 根聚合目录不可写 | `PUT /dav/gscratchpad-cloud.zip → 404`，但 `PROPFIND /dav/ → 207` 正常 | 该服务端是 Alist：`/dav` 是聚合虚拟根，只列出子挂载（`backups/ cherrystudio/ obsidian/ …`），PUT 落到虚拟根无真实存储 → 404 | 应用内 URL 必须指向真实可写子目录（实测 `/dav/backups` → `201`）；`CloudBackup.Config.remoteUrl = baseUrl.trimEnd('/') + "/gscratchpad-cloud.zip"` 只拼接一层，不要传根路径 |
| ADB `input text` 静默丢弃 | 编辑器已显示、无软键盘，`input text "HOTJOURNAL"` 后既无 `draft journal` 日志也无内容变化，误判为「热日志没生效」 | WebView 未获焦点时没有输入连接，`input text` 注入的按键事件无人接收，被系统丢弃 | 注入前先 `input tap <正文区>` 聚焦（模拟器 1080×2400 取 `540 900`，真机 720×1600 取 `360 900`），再 `input text`；判据是软键盘弹出或首个 change 日志出现 |

另记一条易误判的读库现象：冷启动日志里可能出现 `open 465438 chars rev=966` 而库内目标文档已是 `465448/970`。逐层核验后确认不是 stale read——库里存在**同长度的旧副本文档**（`dc896b3c…`、`357afd5c…`），`activate()` 的 target 取 `activeId ?: all.firstOrNull()`，打开的是另一篇。排除方法：先按 `length(content)` 列全部行，再对目标 id 单独查。

### 9.6 界面收敛轮的四个新坑（R20，已实测定位）

| 坑 | 现象 | 根因 | 交付口径 |
|---|---|---|---|
| 深色下状态栏一条白条 | 内容已全黑，但状态栏区域仍是白底 + 白图标（真机 0.7.2 首轮、模拟器同） | `decorFitsSystemWindows=true` 时内容不绘制到状态栏下方，`statusBarColor = TRANSPARENT` 露出的是**窗口默认白底**；`isAppearanceLightStatusBars=false` 只换图标颜色 | `statusBarColor` 必须填主题底色（深 `#1F2328` / 浅白），导航栏同理；不要用 TRANSPARENT 冒充 edge-to-edge |
| `getInsetsController` 传 `this` 编译不过 | `PreviewActivity` 内 `WindowCompat.getInsetsController(this, window.decorView)` 报 `actual type is 'PreviewActivity', but 'Window' was expected` | Kotlin 对 `WindowCompat` 两个重载的实参推断在当前依赖版本下不接受 Activity 隐式 `this` | 两个 Activity 统一写 `getInsetsController(getWindow(), getWindow().decorView)` |
| Material `Slider` 默认紫 | 设置页首轮滑杆是紫色圆点 + 紫轨道，与黑白灰界面冲突 | material3 默认取主题 `primary`，本工程主题未自定义 palette | `SliderDefaults.colors(thumbColor = foreground, activeTrackColor = foreground.copy(0.55f), inactiveTrackColor = foreground.copy(0.14f), activeTickColor/inactiveTickColor = Transparent)`，即 `sliderColors(foreground)` |
| 关闭 A 立刻开 B，B 显示 A 的正文 | 点 B 进入后编辑器内容仍是 A；日志 `editor closed id=A chars=…` 之后 `mount id=B … chars=A 长度` | ① `closeEditor()` 在协程里 `flushEditor()`，读的是**实时字段** `editingDocId/editorLatest`，B 已覆盖 → A 正文写进 B；② `activate()` 无条件 `setDocument`，把 A 塞回隐藏 WebView | `editorEpoch`（开/关各 +1）+ `openEditor` 取 epoch 判失效 + `closeEditor` 先同步取快照再置 epoch + `activate()` 加 `if (editorOpen)` 守卫 |

### 9.7 工作目录绑定：ColorOS 的 SAF 视图过滤与 MANAGE_EXTERNAL_STORAGE 评估（2026-11-20，验证通过待铺开）

**现象**（真机 PFVM10 / OPPO Find X3 Pro，Android 12 / ColorOS `PFVM10_11_C.28`，截图 `android/tmp/01/`）：
- 绑定工作目录时系统目录选择器中「下载 > Obsidian」只显示部分条目（`markdor`/`RebornMing`/`shell`/`untitled_2.txt` 缺失），而「Termux > obsidian」入口显示完整结构；内部存储根 `/storage/emulated/0` 进入后被系统拦为「無法使用此資料夾」，操作按钮灰掉。

**根因（adb 实证，非应用 bug）**：
- adb 直读 `/sdcard/Download/Obsidian/` 上述四项**全部真实存在** → 缺失是 ColorOS DocumentsUI 的**视图层过滤**，不是文件丢失、不是媒体文件规模问题（纯 md 的 `markdor` 同样被藏）。
- 内部存储根被拒是 Android 11+ 平台规则（AOSP `directory_blocked_header_*`，Download 根目录本身也不可作为 tree 选中，但其子目录可选）。
- 应用侧 `pickWorkDir` 用标准 `OpenDocumentTree()` + `launch(null)`，无 MIME 过滤，代码无过错；两个入口同一 app 结果不同即为铁证。

**MANAGE_EXTERNAL_STORAGE 评估结论**（本轮只评估未改代码，未出包）：
- **前提纠正**：Manifest 当前仅声明 `INTERNET`，存储权限开关在设置页根本不出现（"未要求任何权限"）。adb `appops set MANAGE_EXTERNAL_STORAGE allow` 读回仍 `default`，是因为应用未声明该权限而非 ColorOS 拦截。真要验证必须先改 Manifest 出包，无"零代码验证"路径。
- **能解决的**（问题 B：覆写 `.old` 冗余 / 重名改写 / `deleteDocument` 不可用导致无法删本地文件 / 写回退化 IN_PLACE）：根源都是 SAF 把文件系统操作抽象成能力不定的 provider 接口；File API 直读回 POSIX 语义（`File.delete()`、`Files.move(REPLACE_EXISTING/ATOMIC_MOVE)`）可一并根治，比 R16 方案 A 接受 `.old` 的妥协更彻底。
- **解决不了的**（问题 A：绑定目录时选择器看不到 Download 内容）：官方文档明示 MANAGE_EXTERNAL_STORAGE **不拓宽 SAF**（`you can only access a file/directory via SAF if you could do so without the permission`），过滤发生在 DocumentsUI，加权限后选择器仍缺项——问题 A 仍需靠引导用户改用 Termux 等入口（方案甲）绕开。
- **代价**：权限观感重（笔记 app 申请"所有文件访问"）；不上架 Play 故无政策风险但 lint 警告仍在；SAF 链路不能推倒、File API 增量叠加成双轨制；ColorOS 放行与否须出包后在真机设置页确认 `Environment.isExternalStorageManager()` 为 true（未验证）。
- **用户拍板「出验证版」（乙验证版）**：已在 0.7.26/38 落地——Manifest 加 `MANAGE_EXTERNAL_STORAGE`；设置页新增「验证（R37）」卡片（所有文件访问状态 + 跳转授权 + File 直读探针按钮）；`platform/AllFilesProbe` 纯函数 + 5 条单测。SAF 主链路未改，未授予时全量回退 SAF。门禁：147 单测 / 24 套件 / 0 失败、domain 90.1%、lintRelease 0 error。

**真机验证结果（2026-11-20 晚，Android 14 真机，截图 `android/tmp/01/` 5 张）——验证通过**：
- **入口找法纠正**：该权限按规范属 Special app access，在 `设置 → 应用 → 特殊应用权限 → 所有文件访问`（本 ROM 繁中名「所有檔案存取權」），**不在「存储/储存空间」页**；不能运行时弹窗申请，只能跳系统页手动开——「没弹窗」是预期。「取消存取权/取消授权」是普通 `READ/WRITE_EXTERNAL_STORAGE` 的 UI，与本权限无关。
- **权限授予成功**：系统「所有檔案存取權」页开关已打开（蓝色）；app 设置页 R37 卡片显示「所有文件访问：已授予（File 直读可用）」→ `Environment.isExternalStorageManager()` 在 Android 14 真机上返回 true，ColorOS 放行 ✓。
- **File 直读探针通过**：页面文案「探针通过：File 直读到 10 项，SAF 缺失的 4 项全部可见」→ `markdor`/`RebornMing`/`shell`/`untitled_2.txt` 在 File API 直读下全部可见，坐实问题②（视图层过滤）可被 File 直读绕开 ✓。
- **SAF 选择器仍未变（预期，非失败）**：从「下载 > Obsidian」进 SAF 仍只有 6 项（缺上述 4 项），从内部存储根进仍「無法使用此資料夾」+「沒有項目」——这正是早前评估的「MANAGE_EXTERNAL_STORAGE 不拓宽 SAF」，与官方文档一致。问题 A（绑定目录时选择器缺项）依旧只能靠引导用户改用 Termux 等 provider 入口绕开。
- **结论**：方案乙的技术前提全部坐实——权限可授予、File 直读可见全量文件。

**R38 落地（用户拍板「丙」= 甲乙都做，2026-11-20，版本 0.7.27/39）**：
- **问题 B 根治（写回链路）**：新增 `platform/FileDirectPolicy`（纯函数：documentId→真实路径映射，覆盖 `primary:`/`raw:`/SD 卡卷标/Termux 绝对路径四类，`..` 穿越与非共享存储路径拦截）+ `platform/FileGateway`（同目录临时文件 + fsync + 读回校验 + `Files.move(REPLACE_EXISTING, ATOMIC_MOVE)` 原子覆盖，全程无 `.old`）。`SafFileGateway` 构造注入 `FileDirectWriter`，`save()` 在「API≥30 + 已授权 + 路径可映射为合法共享路径」时优先 File 原子写（`WriteMode.FILE_DIRECT`），失败或不可映射原样回退 SAF——「File 通道失败 = 退回原行为」，不破坏既有链路。MainActivity 注入能力判断。open/create/listTree 仍走 SAF 不动。
- **问题 A 引导**：绑定工作目录按钮下加提示「Android 11+ 无法选内部存储根；从『下载』进入目录不全时切到 Termux 等入口」。
- **验证**：161 单测 / 25 套件 / 0 失败（含 FileDirectPolicy 14 条），domain 90.1%，lintRelease 0 error，两包各 3.29 MB upload key 签名。
- **待真机复验（用户侧）**：授权后在已绑定外部文件上编辑保存，核对 logcat `FileGateway atomic-save ok` 与目录里不再新增 `.old`；若 documentId 映射失败（云盘等 provider），日志 `file-direct failed, fallback SAF` 表示自动回退，行为同升级前。

**R40 落地（问题 A 根治，2026-11-20，版本 0.7.29/41）**：R38 的「引导换 Termux 入口」只是绕开，未根治 SAF 视图过滤。R40 弃用 `OpenDocumentTree` 选工作目录，改用 `MANAGE_EXTERNAL_STORAGE` 下的 [java.io.File] 逐级列举真实目录（`FileDirPicker` + `FileDirPolicy`），彻底绕开 DocumentsUI 过滤——模拟器实测目录浏览器列出共享存储根全部真实目录（Alarms/Android/DCIM/Documents/Download…），不再缺项。绑定改存真实路径（`WorkDirPolicy.Binding.path`，`savePath`，`read` 优先 path 回落旧 SAF URI，向后兼容）；path 绑定下新建走 `FileGateway.createEmptyFile`、flush 写回对 `/storage/` sourcePath 走 `FileGateway.saveAtomic`。设置页原「验证（R37）」探针卡片删除，改 STORAGE 组「存储权限（本地文件夹必需）」明确入口；主页「Android 11+ 无法直接选内部存储根」与设置页「外部文件说明」两处过时提示一并移除（File 直读后不再产生 `.old`）。**另存仍走 SAF CreateDocument**（用户主动选位置，非痛点链路），保持不动。

**R42 补完（打开文件也改 File 直读，2026-11-20，版本 0.8.0/43）**：真机 db3809a6（OPPO/Android14/API34）实测 R40 的工作目录浏览器已能列全，用户反馈的「目录缺失」实际发生在主页「打开文件」——该入口仍走 SAF `OpenDocument()`，DocumentsUI 过滤未绕开。R42 用 `platform/FileOpenPicker`（复用 `FileDirPolicy.listSubdirs/listDocFiles`）替代 SAF 作主入口，逐级浏览真实目录并选文档文件；`openLocalFilePath` 读真实路径→建库→绑 `sourcePath`（写回走 FileGateway 原子写）→进编辑器。原 SAF 保留为「从云盘或其它位置打开」次入口（云盘 provider File API 看不到，必须走 SAF）。**更低版本兼容**：华为 YAL-AL10（Android 10/API29）无 MANAGE_EXTERNAL_STORAGE，原 `granted` 恒 false、授权入口守卫返回导致目录永远列不出——补 Manifest 传统 READ/WRITE（maxSdkVersion 29）+ `StorageAccess` 分版本判定 + API29- 动态申请 READ，死结解除。模拟器端到端：文件浏览器列真实目录与 .md/.txt（png 过滤、中文名正常）。

**R43 补完（打开浏览器以工作目录为根，2026-11-20，版本 0.8.1/44）**：R42 的 `FileOpenPicker` 起点仍是共享存储根，绑定工作目录后打开文件仍需多步下钻。R43 改 `startPath = workDir.path ?: ROOT`，并新增 `FileDirPolicy.parentWithin(path, root)`（回到起点返回 null → UI 禁用「上级」，逐级回退不越过起点）；未绑定行为同前。同时删主页底部与「从云盘或其它位置打开」功能重合的「看不到文件？浏览全部文件」入口。pilcrow（github.com/pilcrowmd/pilcrow，纯 SAF 架构）调研结论：它没有「看不到文件/选不了」问题靠的是「OpenDocumentTree 授权 → 应用内列子文件 → 直读 document URI」，从不经过带过滤的 OpenDocument——与本项目 File 直读 + 应用内浏览器路线同构，无需再引入其机制。模拟器实测：绑定 notes 后浏览器直接落在 `/Documents/notes`、上级禁用。

**R44 补完（Android 10 分区存储 legacy 标志，2026-11-20，版本 0.8.2/45）**：R42 补了 READ/WRITE_EXTERNAL_STORAGE（maxSdkVersion 29）后 YAL-AL10 实测权限已授予但两个 File 浏览器仍列空——根因是 targetSdk 36 在 Android 10 设备上分区存储强制生效，传统权限只覆盖 SAF、`File.listFiles()` 对共享存储返回空。修复：`<application android:requestLegacyExternalStorage="true">`（仅 Android 10 生效，Android 11+ 忽略、不受影响）。`aapt2 dump xmltree` 已核验标志入包；列表是否恢复需用户真机确认（若 install -r 后仍空，卸载重装一次让 legacy 授权在安装期生效）。

**R45 补完（切换浮层口径与写回可观测性，2026-11-21，版本 0.8.3/46）**：R41 的「切换文档列同目录」以绑定工作目录为口径，未绑定/旧 SAF 绑定/文档在绑定目录之外三种情况下退化为只列库内文档。R45 改为 `dirForList`：当前文档 sourcePath 父目录优先（共享存储路径校验 + `..` 拒绝），回退绑定目录。同时 `saveAtomicDetailed` 把写回失败细化为五环节原因（共享存储校验/父目录/临时写入/读回校验/原子替换），真机「路径不可写」的具体环节将由新 toast 文案反馈定位。另：上轮文档清洗删除 `gscatchpad/` 误放目录时连带丢失了未入库的 StorageAccessTest.kt（唯一副本），本轮按同一覆盖口径重写恢复 6 条测试。

## 10. 复现命令

```powershell
cd <仓库根>\android

# 单测 + 覆盖门禁
gradle :app:testDebugUnitTest :app:coverageGate

# Lint
gradle :app:lintRelease

# Release（R8 + 资源收缩 + splits）+ 包体预算
gradle :app:assembleRelease :app:verifyReleaseBudget

# 一站式发版（R24 起）：构建 + 包体核验 + 按规范命名汇入 android/dist/ + 清旧包
gradle :app:stageRelease

# 仪器 UI 冒烟（需 emulator-5554 在线）
gradle :app:connectedDebugAndroidTest
```

### 10.1 界面回路手测（R15 起每轮必跑）

```powershell
$adb = "<SDK>/platform-tools/adb"
# 1) 冷启动必须是文档列表（不是编辑器）
& $adb shell am force-stop io.github.gscratchpad
& $adb shell am start -n io.github.gscratchpad/.MainActivity
# 2) 点首个列表项 → 应进 CodeMirror；按返回 → 应回列表且 state=closed
& $adb shell input keyevent KEYCODE_BACK
# 3) 校验列表状态与打开日志
& $adb logcat -d | Select-String "D Gscratchpad"
& $adb shell 'run-as io.github.gscratchpad sqlite3 files/gscratchpad.db "select id,title,state from documents order by updated_at desc limit 5;"'
```

判定：冷启动首屏出现「`Gscratchpad` hero（30sp + 副标题）+ 滑块图标 + 夜间/日间 + 实心「打开文件」+ 描边「新建文档」+ 文字链「浏览全部文件」+ 导入/导出备份并排 + 「最近文档 / N 个文件」+ 行内 `md · 相对时间` + ×」即通过（R17 起）。若首屏直接出现页内图标工具栏（品牌文档图标 + 搜索/大纲/预览/⋮/× 与面包屑行）说明 panel 又被整屏盖上，按 §9.3 第一条排查 `lp.alpha`。返回后若文档仍 `state=open`，查 `editor closed id=…` 日志是否存在。

### 10.2 分屏 / 插图 / 云备份 / 快捷键自检（R18 起）

```powershell
# 双栏（窄屏也能验证：force-stop 后带 split=true，1.5 s 后自动开右栏）
& $adb shell am force-stop io.github.gscratchpad
& $adb shell am start -n io.github.gscratchpad/.MainActivity --es openDoc <id> --es split true
# 平板自动双栏：模拟器改尺寸后重启应用即 auto=true
& $adb -s emulator-5554 shell wm size 1600x2560
& $adb -s emulator-5554 shell wm density 320
# 插图 / 云备份 / 快捷键面板 / 查找替换自检
& $adb shell am start -n io.github.gscratchpad/.MainActivity --es runAction image
& $adb shell am start -n io.github.gscratchpad/.MainActivity --es runAction cloudBackup
& $adb shell am start -n io.github.gscratchpad/.MainActivity --es runAction help
& $adb shell am start -n io.github.gscratchpad/.MainActivity --es runAction selfCheckFind
& $adb logcat -d -s Gscratchpad:D | Select-String "selfCheckFind"
```

### 10.2.1 金标准语料与云备份端到端（R19 起）

```powershell
# P2-7：Android 侧逐条渲染并上报指纹（页内 gsFingerprint，2×2 alpha=0 隐藏 WebView）
& $adb -s emulator-5554 logcat -c
& $adb -s emulator-5554 shell am force-stop io.github.gscratchpad
& $adb -s emulator-5554 shell am start -n io.github.gscratchpad/.MainActivity --es runAction selfCheckGolden
Start-Sleep -Seconds 14      # page ready 6–7 s + 12 条逐条渲染
& $adb -s emulator-5554 logcat -d -s Gscratchpad:D > tmp\golden_log.txt
python scripts\golden_fingerprint.py --compare tmp\golden_log.txt   # 期望 golden: 12/12 一致

# Q5：WebDAV 端到端（URL 必须指向可写子目录，见 §9.5）
& $adb -s emulator-5554 shell am force-stop io.github.gscratchpad
& $adb -s emulator-5554 shell am start -n io.github.gscratchpad/.MainActivity --es runAction cloudSelfCheck --es cloudUrl "http://<LAN-IP>:5244/dav/backups" --es cloudUser admin --es cloudPass 123456
& $adb -s emulator-5554 logcat -d -s Gscratchpad:D | Select-String "cloudSelfCheck result"
# 期望 {"uploadOk":true,"uploadDetail":"HTTP 201 Created","remoteBytes":279569,"downloadOk":true,"sizeMatch":true,"ok":true}
```

### 10.2.2 热日志（镜像级中断恢复）实测（R19 起）

```powershell
# 1) 打开大文档并等编辑器就绪
& $adb -s emulator-5554 shell am force-stop io.github.gscratchpad
& $adb -s emulator-5554 shell am start -n io.github.gscratchpad/.MainActivity --es openDoc big-1
Start-Sleep -Seconds 9
# 2) 必须点一下正文，否则 input text 被系统丢弃（§9.5 第三条）
& $adb -s emulator-5554 shell input tap 540 900
Start-Sleep -Milliseconds 800
& $adb -s emulator-5554 shell input text "HOTJOURNAL"
# 3) 在 300 ms 保存防抖窗口内强杀
Start-Sleep -Milliseconds 150
& $adb -s emulator-5554 shell am force-stop io.github.gscratchpad
# 4) 重开：期望 recover restored doc=… journalRev=<dbRev+1> chars=<+10>
& $adb -s emulator-5554 shell am start -n io.github.gscratchpad/.MainActivity --es openDoc big-1
Start-Sleep -Seconds 10
& $adb -s emulator-5554 logcat -d -s Gscratchpad:D | Select-String "recover restored|mount"
```

注意 `singleTask`：Activity 在栈顶时新 extras 不会走 `onCreate`，**必须先 `am force-stop`**；分屏复测同理。

### 10.3 每轮出包纪律（R16 起强制）

```powershell
# 每轮改动后：debug 供模拟器回归，release 一站式发版（R24 起）
gradle :app:assembleDebug :app:stageRelease
# 产物
#   app\build\outputs\apk\debug\app-x86_64-debug.apk                    （模拟器 install -r，不交付）
#   android\dist\scratchpad-arm64-v8a-release-<versionName>.apk        （真机，交付）
#   android\dist\scratchpad-x86_64-release-<versionName>.apk           （模拟器，交付）
# 真机 / 模拟器安装（绝对路径，交用户自行执行）
adb install -r android\dist\scratchpad-arm64-v8a-release-0.8.3.apk
adb install -r android\dist\scratchpad-x86_64-release-0.8.3.apk
```

判据：交付时给出 `android/dist/` 下两个规范命名 release 包的绝对路径 + 体积 + badging 的 `versionCode/versionName`，并附每个 ABI 的 `adb install -r` 命令（交用户自行执行，不代替安装）。`stageRelease` 自动清理 `dist/` 旧版本包，只保留本次版本。只跑 `assembleDebug` 不算交付——真机装的是 release 包，release 包过期时看到的就是旧界面（R16 前 release 长期停留在 0.6.0）。本地无 `keystore.properties` 时签名回退 Android Debug（可安装；正式发布需 CI 注入 upload key）。

### 10.3.1 打包脱敏纪律（R23 起，用户规范）

**规范：打包 APK 时进行脱敏——不将测试用文档、测试用 WebDAV 地址一起打包。**

- **测试 WebDAV 地址/账号**（内网 Alist 地址、账号口令）只经 `runAction` 意图参数与设备端 SharedPreferences 传入，禁止硬编码进任何源码、资源与打包资产；源码中 WebDAV 示例只允许 `dav.example.com` 占位。
- **测试文档**（真机导入的 `.md`、生成的语料）一律不放 `src/main/assets` 与 `res`；golden 语料放在 `src/debug/assets/golden/`，**只随 debug 包合并，release 天然不含**（release 中 `selfCheckGolden` 读不到语料走提示分支，属预期）。
- **每轮出包必跑脱敏校验**（并入 10.3 流程，未 PASS 不交付）：

```powershell
pwsh scripts\verify_apk_sanitize.ps1 app\build\outputs\apk\release\app-*.apk
# 结构检查：release 内不得存在 golden/ 资产；文本检查：内网地址 / :5244 / 123456（数字边界）/
# dav/backups / chatgpt-qichen / 奇琴伊察 / big-sample / saf1000 / 郑居敬 任一命中即 FAIL（exit 1）。
# assets/vendor/** 三方库跳过文本扫描（数字表会撞 "123456"，且不含本工程数据）。
```

- 0.7.12/23 首轮实测：release 两 ABI 各 144 条目，PASS；未命中任何测试痕迹（本轮前唯一打包在 APK 内的测试资产即 golden 语料，已移 debug sourceSet）。

### 10.4 R20 界面回路的四条必跑用例

```powershell
# 1) 清除记录不删文档：主页行尾 × 与表头 clear
adb shell input tap 640 683            # 行尾 ×（720×1600）
adb shell input tap 180 581            # 表头 clear（clear 全部）
# 判据：字数 6→5 / 0 个文件；「查看全部文档（N）」仍在，N 不变；toast 文案含「文档未删除」

# 2) 全部视图恢复
adb shell input tap 360 1391           # 查看全部文档
adb shell input tap 638 685            # 「恢复」
# 判据：行副标题去掉「· 已清除记录」，回最近列表后可见

# 3) A→关→B 不串内容
adb logcat -c
adb shell input tap 300 1385           # big-sample（548,245 字）
adb shell input tap 672 113            # 编辑器右上 ×
adb shell input tap 300 973            # 郑居敬（1,268 字）
adb logcat -d -s Gscratchpad
# 判据：mount 的第二条 id 为 B、chars=B 长度；界面首行是 B 的内容

# 4) 深色系统栏
adb shell input tap 583 137            # 滑块图标进设置
adb shell input tap 306 636            # Theme → 夜间
# 判据：状态栏区域为 #1F2328 且图标转白，不再是白条；重启后仍保持（editor-prefs.dark）
```

