# Android 移植阶段进度看板

> 本文是阶段状态的唯一权威记录，
> **每轮任务结束后必须更新**
> ：改动 §3 轮次日志、§2 阶段进度、§5 阻塞清单三处。
> 依据：本文 §7（移植方案存档，含 WBS 与 S1–S4 门槛）。
> 最近更新：2026-11-20（R36），版本 0.7.25（versionCode 37）。

## 1. 阶段划分与门槛



| 阶段          | 内容                 | 门槛                                              | 出口判定依据                                                                                |
| ----------- | ------------------ | ----------------------------------------------- | ------------------------------------------------------------------------------------- |
| P0          | S1–S4 Spike 验收     | S1 打开 ≤1.5 s、滚动 ≥55 fps、折叠 ≤100 ms、中文输入 5 分钟无丢字 | `ANDROID_SPIKE_REPORT.md`                                                             |
| P0-Decision | 路线选择               | S1 折叠或大文档不达标 → 路线 D（CodeMirror 6），其余里程碑与接口不变    | 方案 §8 P0 门槛原文                                                                         |
| P1          | 路线 D 编辑器内核替换       | 1 MB 文档可打开、可折叠、可滚动、可输入、可落盘                      | 本文 §2 与 §5；**2026-11-19 经用户裁定出关**：B1/B4 达标，B2 判定为模拟器环境上限（真机复测挂账）、B3 中文链路达标（IME 组合态挂账） |
| P2          | M1 编辑体验对齐（84 人日）   | §13 矩阵中编辑相关项全部落地 + S3 首渲染 / 内存处置                | 矩阵 + Spike §3                                                                         |
| P3          | M2 平台与数据（91 人日）    | SAF 三项（千文件枚举 / 字节保真 / 断电无半截）+ 导入导出契约            | Spike §2 + 风险登记 R1–R10                                                                |
| P4          | M3 双栏、性能与发布（55 人日） | 发布门禁全绿（单测 / 覆盖 /lint/ 包体 / 仪器测试）                | `ANDROID_ENGINEERING.md`                                                              |
| P5          | 报告与收尾（M0 中 2 人日同类） | 交付报告 + 遗留项清单                                    | 本文 §5                                                                                 |

工作量基线：M0 14、M1 84、M2 91、M3 55，合计 244 + 10% = 268 人日 ≈ 12.3 人月（方案 §9）。

## 2. 当前阶段与进度

**当前阶段：P2（M1 编辑体验对齐）已收尾**，人日加权进度 **99%**（85.15 / 86 人日，按 §9.2 十一条任务线的实际人日权重求和）。差额 0.85 人日来自两处未验项：任务线 #7 的并行多窗格（-0.5）与 #9 的重复另存不覆盖（-0.35）。

P2 计分口径：按 M1 的 11 条任务线的人日权重加权，任务线内部按「已落地 / 部分 / 未开始」三档取值（100% / 95% / 85% / 70% / 60% / 0%），数字来自代码与实测核对，不用估算替代。

**R21（0.7.3/15 → 0.7.4/16）已交付并真机验证**，不改变 §9.2 任务线取值，进度仍为 99%。本轮按用户拍板收掉 R20 遗留九项并修复三个真机缺陷：



1. **缺陷①「打开文件只加记录不打开」**：根因是 `openExternal()` 只 `setMeta + reload` 不进编辑器；修复为「导入副本进库（保留 `sourcePath`）+ `openEditor` 直开」。真机实测：SAF 选 `chatgpt-qichen.md`（52.77 KB）→ `open 25405 chars db=23ms`、`editor ready in 140ms` 直接进编辑器。

2. **缺陷②「最近文档不按打开时间排序」**：根因是排序键只有 `updated_at/sort_index`；修复为 schema v4→v5 新增 `documents.opened_at REAL` + `idx_documents_opened`（`PRAGMA table_info` 先查列再幂等 ALTER），三个列表查询改 `ORDER BY opened_at DESC, updated_at DESC, sort_index ASC`，`touchOpened` 同时 `SET opened_at=?, recent_hidden=0`（打开自动恢复已清除记录）。真机实测：打开后该文档在「全部」视图置顶。

3. **缺陷③「复杂文档预览被刷回顶部」**：根因是预览页里编辑器 WebView 已暂停，`syncTick` 轮询 `pullFromEditor()` 拿到旧 topLine，按标题反推把预览逐格拽回顶部；修复为 `PreviewActivity.syncTick` 只监听预览自身滚动（位移 >6 触发），不再轮询编辑器。真机实测：下滚到「2. 武士神庙」后静置 20 s 位置完全一致、logcat 零重渲染。

4. **设置页补齐**（拍板「补齐」）：Theme 三段夜间 / AMOLED / 日间、字体三段无衬线 / 等宽 / 衬线、编辑字号 11–32 + 阅读字号 12–28 双 Slider、全屏阅读（预览页隐藏顶栏）、PDF 深色导出、FEEDBACK 两行（GitHub 仓库 / 邮件反馈）。

5. **表头双态**（拍板「按建议」）：列表头常驻「最近 / 全部」双态切换（半粗体高亮当前态），`clear` 仅在最近视图显示。

6. **应用图标复刻**（拍板「按图标设计.png 复刻」）：按 `android/tmp/图标设计.png` 重写 `ic_launcher_foreground.xml`（深藏青底 `#17293C` + 米白圆角卡 + 三行手写波浪 stroke + 中行暖橙光晕 + 右下橙光标条），真机桌面已核验渲染。

7. **H2 内存回归实测**：10 轮进出编辑器采 PSS—— 关闭态 162–164 MB、打开态 165.5–166.3 MB，抖动～2 MB，无累积增长 → 通过（≤30 MB 判据）。

**R22（0.7.5/17 → 0.7.11/23）已交付并真机验证**，本轮把 P3 的 SAF 三项实测收掉，过程中定根修复两个结构性缺陷：



1. **安全缺陷（0.7.6/18 修复）**：`SafFileGateway.documentTreeRoots()` 把历史持久化的**单文件**授权也当目录树返回，`DocumentFile.fromTreeUri` 对非 tree URI 抛 `IllegalArgumentException` → 导入备份路径可复现崩溃；修复为只返回 `pathSegments.firstOrNull()=="tree"` 的授权。

2. **原子换名缺陷（0.7.10/22 修复）**：OPPO externalstorage provider 拒绝「扩展名与 MIME 不一致」的 `createDocument`（`power.md.tmp` + `text/markdown` → `Failed to create unique file`），整条临时文件 + 替换链路此前**从未生效**，全部静默退化 IN\_PLACE；修复为 tmp 改用 `application/octet-stream` + `"$base.tmp$ext"` 命名，并把最终替换改为「旧文件 rename → `.old`、tmp rename 回原名」的两步原子换名。同一 provider 的 `deleteDocument` 确认不可用（新建 / 改名 URI 均抛 `Delete not supported`，探针已留档），`.old` 清理改为尽力而为（失败不判定保存失败，只留冗余备份）。

3. **SAF 三项实测结论（P3-5）**：

* **字节保真：通过**——GB18030 + CRLF 原始字节经 `gateway.open → save` 往返，SHA-256 `37785b57…` 前后一致（mode=ATOMIC\_RENAME）。

* **千文件枚举：通过**——1000 文件目录经 DocumentsProvider 枚举，按 400 上限截断（与桌面一致），耗时 8.2–8.9 s（DocumentFile 逐项 query 为已知开销）。

* **断电无半截：通过（结构性 + 实测）**—— 换名为文件系统级原子 rename；7 轮不同延迟强杀（含打进写入序列的样本），每次 `safPowerVerify` 均为完整 V1 或完整 V2、`tmpLeftover=0`、零 CORRUPT。已知限制：本 provider `deleteDocument` 不可用 → 同一目标文件第二次起保存退化为 IN\_PLACE（撕裂风险理论上存在，由 tmp 读回校验 + 应用内 `RecoveryManager` 缓解，已如实记录）。

1. **H5 冷开基线**：`am start -W` 三采样 480 / 492 / 467 ms（COLD，中位 480 ms）。

2. **自动化钩子**：新增 `runAction safSelfCheck / safPowerWrite / safPowerVerify`（与 `cloudSelfCheck` 同构），供无界面环境复测 SAF 三项。

**R23（0.7.11/23 → 0.7.12/24）已交付并真机验证**，本轮落实用户打包脱敏规范：

1. **核查**：全工程确认源码 / 资源 / res 中无硬编码测试 WebDAV 地址与账号（只经 `runAction` 意图参数与设备端配置传入）；测试文档只在真机 /sdcard 与运行时 DB；唯一打包在 APK 内的测试资产为 `assets/golden/corpus.json`。

2. **脱敏落地**：golden 语料移至 `src/debug/assets/golden/`（仅 debug 包合并，release 天然不含；release 中 `selfCheckGolden` 走缺语料提示分支，属预期）。

3. **校验固化**：新增 `android/scripts/verify_apk_sanitize.ps1`（结构检查 golden 资产 + 文本扫描测试 WebDAV / 账号 / 测试文档标记，vendor 三方库跳过），写入出包纪律 `ANDROID_ENGINEERING.md` §10.3.1；release 两 ABI 各 144 条目实测 PASS。

> **R24（0.7.12/24 → 0.7.14/26）、R25（0.7.15/27）、R26（0.7.17/29）、R27（0.7.18/30）、R28（0.7.19/31）、R30（0.7.20/32）、R31（0.7.21/33）、R32（0.7.22/34）、R33（0.7.23/35）、R35（0.7.24/36）、R36（0.7.25/37）均已交付**：R24/R25 为 P2 收尾后的界面 / 交互打磨，R26 为 P4 工程化落地，R27/R28/R30 连续修复 SAF 链路缺陷，R31 落地 T1/T2 功能增量 + 白名单放宽，R32 落地 T3 My folders 页，R33 落地文档切换浮层 + 本地文件夹工作目录绑定，R35 为长按菜单与 WebDAV 对话框的视觉统一（无功能增删），R36 为例行维护发版，均不改变 M1 十一条任务线取值，进度仍为 99%。

1. **预览页顶栏 / 图标对齐编辑器（R24）**：编辑器顶栏基准 = 56 px 高 + 1 px 分隔线 rgba(128,128,128,0.22) + 44 dp 触摸区图标 + 22 dp 视觉 + 1.6 网格线宽 + 12 dp 圆角按压。改 `PanelIconView`（unit 系数 0.86→0.5、stroke 1.7→1.6、按压铺满 44 dp / 12 dp 圆角），预览顶栏 padding 对齐、补分隔线、图标 40→44 dp。

2. **编辑器↔预览同页切换（R24）**：编辑器 WebView 本就挂在 `TYPE_APPLICATION_PANEL` 子窗口（非 Compose 同窗口），抽出 `PreviewScreen`（顶栏 + WebView + 滚动同步），编辑器内点预览改为同一 panel 内互斥显隐 editorView/previewScreen（140 ms 淡入），无 Activity 跳转黑屏；返回键先退预览；与分屏互斥（进预览停 splitSync，退出恢复）。`PreviewActivity` 保留仅作外部 intent 薄壳入口。

3. **预览过滤 frontmatter / HTML 注释（R24）**：新增 `MarkdownSanitizer`（platform/），在 `PreviewHost.renderMarkdown` 入口清洗渲染副本；编辑器原文与 ScrollSync 标题行号映射仍用原文；围栏代码块内注释按字面保留。新增 `MarkdownSanitizerTest` 9 条。

4. **发版规范落地（R24）**：版本号唯一来源 `appVersionName`/`appVersionCode`；release 重命名改用 AGP 9.x 新版 Variant API（`androidComponents.onVariants` + `output.outputFileName`，旧 `applicationVariants` 已移除，已用 javap 核实）；新增 `stageRelease` task（依赖 assembleRelease + verifyReleaseBudget，汇入 `android/dist/` 并清旧包）。产物命名 `scratchpad-<abi>-release-<versionName>.apk`。

5. **设置页排版紧密化 + 行高范围（R25）**：外层 padding 16/12→14/8、卡片间距 14→9、Card 圆角 16→12 / padding 16/14→14/10、分段控件高 40→34、主标题 15→14 / 副标题 12→11 / 页面标题 26→22；行高上下限 1.2–2.2 → **0.5–2.5**（step 0.05，steps 19→39，默认 1.55 不变），Compose slider `valueRange` 与编辑器 HTML `<input min/max>` 两处同步（持久化与 JS 无钳制）。模拟器（Pixel_API_36）实测 slider 两端显示 0.50 / 2.50，截图确认布局紧凑、无重叠截断。

6. **版本显示消除漂移（R24）**：设置页版本号由硬编码 0.7.12/v24 改为 PackageManager 动态读取。

**构建（R24/R25）**：81 单测 / 14 套件 / 0 失败；lint 0 error / 8 warning / 3 hints（均既有项）；release 两 ABI 各约 3.27 MB（0.7.15 / versionCode 27，`dist/scratchpad-<abi>-release-0.7.15.apk`）。

**R26（0.7.16/28 → 0.7.17/29）P4 发布门禁收敛**：① 仪器测试补齐——新增 `PersistenceSmokeTest`（启动 Activity → 创建并打开文档 → saveNow + flush → 校验 DB 与 `notes/*.md` 镜像内容一致），重写过时的 `EditorUiSmokeTest` 三条（原引用的「新建 / 查找 / 预览」文案已随版本演进失效），模拟器（Pixel_API_36）实测 **4/4 全通过**；② 本地门禁全绿——`testDebugUnitTest` 81 单测 0 失败、`coverageGate` domain 行覆盖 **89.5%**（290/324，门槛 80%）、`lintRelease` 0 error、`verifyReleaseBudget` 两包各 3.27 MB（≤12 MB）；③ 正式签名出包——upload key 签名的 `dist/scratchpad-<abi>-release-0.7.17.apk`，`stageRelease` 自动清 0.7.16 旧包；真机（真机 C）已安装 v0.7.17 并确认应用可启动、编辑器 Panel 可用。**未闭环**：P2-4「同名重复另存不覆盖」真机全链路需系统 SAF 选择器选目录 / 文件名，且真机 Panel 焦点抢占会导致 `input tap` 误映射（已复现），无法无人值守自动化，作为手动验收步骤交付。

**R27（0.7.17/29 → 0.7.18/30）另存为两项缺陷修复**：① #4 后缀被追加 .txt——SAF `CreateDocument` 的 MIME 由 `text/plain` 改为 `text/markdown`（provider 不再按 text/plain 强补 .txt），文件名经 `SaveAsPolicy.fileName()` 保证恰好一个 .md 后缀；② #5 另存写出空内容——`saveAsExternal()` 内容源由 `text.value` 改为 `editorLatest.ifEmpty { text.value }`（新建文档时 text 仍是空串，只有 editorLatest 是实时正文），与 share/save 路径对齐。两条规则抽为纯对象 `platform/SaveAsPolicy`，新增 `SaveAsPolicyTest` 7 条 JVM 单测锁定；全量 **88 单测 / 15 套件 / 0 失败**。门禁全绿：coverageGate domain 89.5%、lintRelease 0 error、两包各约 3.27 MB。**版本归因**：反编译对比 0.7.16 与 0.7.17 的 `classes.dex` SHA256 完全相同（`b5fbe3bb...ca53f4`），证明 #5 非 0.7.17 引入的回归，而是触发路径差异（打开已有文档→text 非空 vs 新建文档→text 空），按 bug 本身修复。upload key 正式签名出包，`stageRelease` 自动清 0.7.17 旧包。

**R28（0.7.18/30 → 0.7.19/31）另存为链路再修两项**：① 用户手输后缀被改——R27 把 SAF MIME 设为 `text/markdown`，系统对已知文本类型会强制补扩展名，把用户手输的 `.txt` 改回 `.md`；改 `SaveAsPolicy.MIME` 为 `application/octet-stream`（无扩展名推断的中性类型，与 gateway 临时文件同款），后缀完全由文件名决定——既解决原「.md 被补 .txt」，又解决本次「手输 .txt 被改 .md」。② 另存后不进最近列表——`saveAsExternal` 原仅 `setMeta(sourcePath)`，未打点/未刷标题；补齐正文落库 `saveNow` + 标题同步为文件名 stem（`SaveAsPolicy.savedTitle()`，对齐桌面版）+ `touchOpened` 打点 + 刷新 `docs.value`（不用 `reload` 以避免 `setDocument` 重置编辑器丢光标）。`SaveAsPolicyTest` 增至 9 条 JVM 单测锁定 MIME 中性、stem 提取；全量 **90 单测 / 15 套件 / 0 失败**。门禁全绿：domain 89.5%、lintRelease 0 error、两包各约 3.27 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.18 旧包。
**R30（0.7.19/31 → 0.7.20/32）另存文件再打开被 ROM 判为 BIN 无法选中**：用户在华为设备（真机 B（华为 EMUI））反馈——R28 另存的文件再次「打开文件」时类型显示为「BIN 档案」且灰掉不可选，文件本身完好。根因不在正文：R28 为规避系统改写用户后缀把 `CreateDocument` MIME 改为 `application/octet-stream`，华为 EMUI 据此把 .md 登记成 BIN 类二进制并分配非文本 MIME；打开过滤器仍是 `text/plain, text/markdown`（3 处），选择器按 MIME 过滤后 .md 被隐藏。按用户拍板**乙方案**修复：① 新增 `platform/OpenPolicy` 纯策略（与 SaveAsPolicy 成对），`MIME_TYPES` 为全类型通配符，MainActivity 四处 `openFile.launch` 统一改用（键盘动作 / KeyAction.OPEN / 主页「打开文件」/「浏览全部文件」）；② `openExternal()` 读取前用 `gateway.displayName(uri)` + `OpenPolicy.isSupported()` 按扩展名白名单（md / markdown / html / htm / txt）兜底，非白名单 toast 拒绝，不让图片/压缩包混入编辑器，格式分派统一走 `OpenPolicy.extensionOf()`；③ 新增 `OpenPolicyTest` 7 条 JVM 单测（通配 MIME / 白名单命中与大小写 / 二进制后缀拒绝 / 无扩展名拒绝 / 末点取扩展名 / 提示文案），顺手修正 `SaveAsPolicyTest` 头部过时的 text/markdown 注释。全量 **97 单测 / 16 套件 / 0 失败**。门禁全绿：coverageGate domain 89.5%、lintRelease 0 error、两包各 3.27 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.19 旧包。**验证边界**：本轮为代码层修复 + JVM 单测，华为真机（真机 B（华为 EMUI））不在本机 adb 列表，需用户实机确认选择器中 .md 可选。
**R31（0.7.20/32 → 0.7.21/33）Q6–Q9 拍板 + T1/T2 落地 + 打开白名单放宽**：用户指令「放宽扩展名限制（txt/md/html/sh/py/conf 等文档类可选）、Q6–Q9 按建议、开工 T1+T2」。① **拍板**：Q6 renameFolder 撞名拒绝并提示、Q7 文件夹视图不显示 recentHidden、Q8 文档移入用长按菜单、Q9 T1+T2 一版 / T3 一版（已落 OPEN_QUESTIONS + TASK_CHARTER）。② **T1 编辑器/预览内切换文档**：新增纯逻辑 `domain/DocumentSwitch`（循环下标，5 条单测）；`MainActivity.switchDocument(delta)` 统一内核 flush→epoch 校验→activate→预览态重推并重置滚动，NEXT/PREV_TAB 与页内 prevDoc/nextDoc 按钮三入口共用；补 `KeyAction.PREV_TAB`（Ctrl+Shift+TAB）；编辑器 `#bar` 加上下篇按钮 + 帮助文案，预览 `PreviewScreen` 标题两侧加 PREV_DOC/NEXT_DOC 自绘箭头（PanelIconView），外部 `PreviewActivity` 入口无列表上下文故不显示切换按钮（null 回调降级）。**T1-R1 处置**：编辑器产物 `index.html` 曾被手工改过行高 0.5–2.5 而模板仍是 1.2–2.2，先把该改动回灌模板再用 esbuild 重建（补装 Linux 原生二进制），产物含新按钮且不丢行高修复。③ **T2 代码块 Copy**：`PreviewHost` 桥对象加 `@JavascriptInterface copyText` 写系统剪贴板；shell `gsRender` 在 renderMermaid 之后注入 `.gs-copy` 按钮（跳过 mermaid、点击取 code.textContent、即时「已复制」反馈、innerHTML 全量重建天然幂等）；样式跟随主题。新增 `PreviewHtmlCopyTest` 6 条锁定桥/注入/顺序/幂等。④ **白名单放宽**：`OpenPolicy.ALLOWED` 由 5 种扩到 70+ 种文本/标记/脚本/源码/配置后缀，支持无扩展名语义名（Makefile/Dockerfile/.gitignore），二进制仍拒绝；`OpenPolicyTest` 重写为 8 条。全量 **110 单测 / 18 套件 / 0 失败**。门禁全绿：coverageGate domain 89.8%（298/332）、lintRelease 0 error、两包各 3.27 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.20 旧包。模拟器（emulator-5554）冒烟：编辑器/面板正常加载、无崩溃；**验证边界**：页内按钮点击与 Copy 落剪贴板受真机/模拟器 Panel 焦点限制无法无人值守端到端自动化，由 JVM 单测锁定产物与逻辑，需用户实机目视确认。

**R32（0.7.21/33 → 0.7.22/34）T3 My folders 页落地**：用户指令「开工 T3」。① **命名策略**：新增 `platform/FolderPolicy` 纯策略（trim + ≤60 字 + 禁 `/\` + 禁控制字符 + 「未归档」保留名），Repository 新建/重命名接入 policy；Q6 撞名拒绝（不静默合并）——`createFolder`/`renameFolder` 先查 `folderExists` 拒绝同名。② **数据层补强**：DAO 新增 `folderRows()`（保留 createdAt）、`documentsByFolder(folder, includeHidden)`、`folderExists()`；Repository 接口新增 `folderCounts()`/`documentsInFolder()`，`folders()` 保留 createdAt（旧实现丢弃 0.0）。③ **视图**：新建独立 `platform/FoldersScreen.kt`（T3-R4 拆文件），主页「最近/全部」扩为三态「最近/全部/文件夹」；按文件夹分组（含未归档虚拟组、计数、展开收起、空组占位），组头 ⋯ 菜单重命名/删除，Q7 过滤 recentHidden；抽 GroupHeader/GroupBody 复用。④ **五操作**：新建/重命名共用对话框（policy 即时校验 + 撞名错误提示），删除确认强调「笔记回到未归档、正文不删」，长按文档/点 ⋯ 弹出目标文件夹菜单移动（Q8），所有操作后 `reload()` + `reloadFolders()` 即时刷新（T3-4）。⑤ **真实缺陷修复**：`DocumentDao.renameFolder` 自重命名（old==new）时末步 `DELETE WHERE name=old` 会误删同名行——加 `if (old==new) return` no-op（由 `FoldersRepositoryTest` 发现）。⑥ **测试**：新增 `FolderPolicyTest` 8 条 + `FoldersRepositoryTest` 10 条（真实 sqlite 验证 CRUD 事务语义：删除回未归档不删正文、重命名带迁移、撞名拒绝、自重命名 no-op、分组/计数/recentHidden 过滤）；仪器测试 `EditorUiSmokeTest` 加文件夹入口可见性断言。全量 **128 单测 / 20 套件 / 0 失败**。门禁全绿：coverageGate domain 89.8%（298/332）、lintRelease 0 error、两包各 3.27 MB。 upload key 正式签名出包，`stageRelease` 自动清 0.7.21 旧包。模拟器（emulator-5554）安装无崩溃（T1 上下篇按钮在新包正常渲染）；**验证边界**：主页文件夹视图被编辑器 panel 覆盖，Panel 焦点限制无法无人值守端到端自动化（真实返回键被 WebView 消费切文档），由 JVM 单测 + 仪器测试代码锁定，需用户实机目视确认。

**R33（0.7.22/34 → 0.7.23/35）文档切换改弹出列表 + 本地文件夹工作目录绑定**：用户指令「① 编辑器、预览页的文档切换改为类似『大纲』那样的弹出式列表选择；② 打开 folder 的语义应是像『打开文件』一样选择本地文件夹打开，而不是像现在这样」。① **文档切换浮层**：新增纯序列化 `domain/DocListJson`（文档列表编成 `[{id,title,active}]`，激活项高亮）；编辑器侧取消原 PREV_DOC/NEXT_DOC 上下篇按钮，改单一「文档列表」自绘图标（`PanelIconView.Kind.DOCS`），页内 `#docs` overlay + `NativeEditor.setDocs/openDocs` JS 桥，点项 `switchDoc(id)` 走既有 `switchToDoc` 内核；预览侧 `PreviewHost` 加 `pendingDocs`/`onSwitchDocById` 与 shell `#gs-docs` 浮层、`setDocs(json)`/`openDocs()`/`gsOpenDocs()`/`switchDoc(id)` 桥；`PreviewScreen` 改 `onOpenDocs`/`onSelectDoc` 回调 + setDocs/openDocs 转发；`MainActivity` 统一 `pushDocsToEditor/pushDocsToPreview/currentDocsJson()`，切换时把当前列表推给两侧。② **本地文件夹工作目录**：新增 `platform/WorkDirPolicy`（纯函数 `normalizeName/label/isValidUri` + SharedPreferences 读写 tree URI/显示名）与 `platform/WorkDirCreateDocument`（自定义 `ActivityResultContract<Request, Uri?>`，ACTION_CREATE_DOCUMENT + `EXTRA_INITIAL_URI` 初始定位）；`MainActivity` 主页新增「打开本地文件夹」入口与当前目录状态行，`pickWorkDir` launcher 持久授权（复用 `SafFileGateway.takePersistablePermission`）；绑定后新建/另存默认落入该目录（`createDocWithWorkDir()` 用 `gateway.createInTree()` 建同名 .md 并 `setMeta(sourcePath)`），`flushEditor()/closeEditor()` force flush 经 `saveExternalIfBound()` 写回外存（300 ms 防抖仅写内部库）；与 v0.7.22 应用内「虚拟文件夹」相互独立、可共存。③ **测试**：新增 `DocListJsonTest` 5 条 + `PreviewHtmlDocsTest` 4 条 + `WorkDirPolicyTest` 5 条，全量 **142 单测 / 23 套件 / 0 失败**。门禁全绿：coverageGate domain 90.1%（308/342）、lintRelease 0 error、两包各约 3.29 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.22 旧包。**验证边界**：弹出列表与 SAF 目录选择受真机 Panel 焦点 / 系统选择器限制无法无人值守端到端自动化；页内浮层结构由 JVM 单测锁产物、工作目录 URI 语义由纯函数单测覆盖，需用户实机目视确认交互落点。

**R35（0.7.23/35 → 0.7.24/36）长按弹出菜单 + WebDAV 对话框统一为 App 深色卡片风格**：用户指令「美化长按弹出框、webdav 弹出框，尽量与 app 风格统一」。① **长按菜单**：新增 `platform/PopupChrome.kt`（`appMenuColors(foreground,muted)` 统一菜单项文字 / 图标 / 禁用配色 + `RenameIcon/DeleteIcon/MoveIcon/FolderOutlineIcon` 四个自绘线条图标）；MainActivity 文档长按菜单（重命名 / 删除）与「移动到文件夹」菜单、FoldersScreen 文件夹 ⋯ 菜单共三处 `DropdownMenu` 全部定制 `containerColor=cardBg`、`shape=RoundedCornerShape(12.dp)`、`tonalElevation=0.dp`、`shadowElevation=8.dp`，菜单项加 leadingIcon + 统一配色 + 15sp 文字，取代 Material3 默认浅色系统菜单。② **WebDAV 对话框**：`showCloudDialog()` 由原生 `android.app.AlertDialog.Builder` + 系统 EditText 改为 Compose `AlertDialog`——命令式调用改 `cloudDialogTicket` StateFlow +1 触发（编辑器 JS 桥接 `cloudBackup` 与设置页两处入口均可唤起），`LaunchedEffect` 内读 `cloudConfig()` 预填三个输入框；对话框 `containerColor=background`、密码框 `PasswordVisualTransformation`、`OutlinedTextFieldDefaults.colors` 显式设前景 / 弱化色保证深底可读，按钮配色随明暗主题反转；Material3 1.4.0 仅两个按钮槽位，故「上传」「从云端恢复」并入 dismiss 槽。③ **验证**：无功能增删、单测仍 **142 单测 / 23 套件 / 0 失败**；门禁全绿 coverageGate domain 90.1%（308/342）、lintRelease 0 error、两包各 3.29 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.23 旧包。**验证边界**：菜单与对话框视觉受真机 Panel 焦点限制无法无人值守端到端自动化，需用户实机目视确认；编译期已核验 Material3 1.4.0 的 `MenuDefaults.itemColors` / `DropdownMenu.containerColor` / `OutlinedTextFieldDefaults.colors` / `AlertDialog` 双槽位 API。

**R36（0.7.24/36 → 0.7.25/37）例行维护发版**：单测仍 **142 单测 / 23 套件 / 0 失败**；门禁全绿 coverageGate domain 90.1%（308/342）、lintRelease 0 error、两包各 3.29 MB。upload key 正式签名出包，`stageRelease` 自动清 0.7.24 旧包。本轮改动细节按用户要求不记入变更史。

| #  | M1 任务线（方案 §9.2）                            | 人日 | 状态 | 取值  | 证据 / 缺口                                                                                                                                                                                                                                                                                                                         |
| -- | ------------------------------------------ | -- | -- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | 工程骨架、Gradle、DI 容器                          | 3  | 完成 | 100 | `AppContainer`、六层结构；CI 实跑另列 H4                                                                                                                                                                                                                                                                                                  |
| 2  | `DbHelper` + DAO + schema                  | 6  | 完成 | 100 | `data/DbHelper.kt`、`DocumentDao.kt`、`SqlDb.kt`，`Migration`/`DesktopBackupContract` 单测 8 条                                                                                                                                                                                                                                       |
| 3  | `SaveQueue` + `RecoveryManager` + 镜像       | 9  | 完成 | 100 | R18 实测「已落盘不丢」；R19 补上热日志（`DraftJournal`）：输入即刻合并写 `recovery/<docId>.json`，独立守护线程、同快照合并、单次写盘 110 ms（548 KB）。真机 / 模拟器实测：输入 10 字符后 150 ms 内 `am force-stop`，重开 `recover restored journalRev=970 dbRev=966 chars=465448` + `mount 465448 chars` → **最后一批输入零丢失**；单测 `DraftJournalTest` 5 条（立即落盘、合并到最新、恢复回填并重写镜像、同 revision 丢弃、drop 清理） |
| 4  | 编辑器接入（高亮 / 行号 / 撤销 / IME / 选择手柄）           | 12 | 完成 | 100 | CodeMirror 6 单资产内联；IME 组合态真机挂账（B3）                                                                                                                                                                                                                                                                                              |
| 5  | 折叠模型与控件                                    | 8  | 完成 | 100 | 17–28 ms（门槛 ≤100 ms），`FoldModel` 15 条单测                                                                                                                                                                                                                                                                                         |
| 6  | 查找替换                                       | 9  | 完成 | 100 | `TextSearch` 6 条单测；`replaceAll` 单次 `dispatch`（整批一步撤销）+ 正则开关 + 仅选区开关；R18 真机自检 `--es runAction selfCheckFind` 返回 `{"replaced":3,"afterReplaceClean":true,"undoRestored":true,"selectionReplaced":1,"selectionOnly":true}` —— 3 处全替换后一次 undo 完整回退、仅选区只改 1 处且选区外零改动                                                                 |
| 7  | 多标签 + 会话恢复 + 命令面板                          | 10 | 完成 | 95  | R14：页内命令面板 16 条动作 + 空格分词检索 + 执行链路实测（`p2j.png`/`p2k.png`）；`EditorActionsTest` 8 条。R15：主页收敛为纯文档列表（`allDocuments()` 全量 + `open/closed` 语义），会话恢复闭环（冷启动即列表、点项续编、关闭即落）——「多标签」按单编辑器 + 列表切换实现，并行多窗格未做；快捷键按附录 B 取 `Ctrl+Shift+I`（工具菜单），`Ctrl+Shift+P` 仍留给预览切换，S4 全量快捷键实测未做                                                               |
| 8  | 预览管线（markdown-it/KaTeX/Mermaid/ 大纲 / 滚动同步） | 10 | 完成 | 100 | R18：`PreviewActivity` 重写为图标栏 + WebView（`PanelIconView` 自绘 BACK / 日夜间 / PDF / 关闭），600 ms 轮询 `ScrollSync`；新增 `HeadingIndex`（`^#{1,6}`、跳过围栏）与 `ScrollSync`（编辑器顶端行 ↔ 预览标题下标，双向 900 ms 抑制窗）；真机 548,166 字符预览 `preview ready 98→480 ms`；平板上分屏首帧即对齐到编辑器顶端标题；**反向（预览滚动驱动编辑器）仅由同一套 600 ms 轮询覆盖，未做逐条实测**                                   |
| 9  | 单文件打开 / 保存 / 另存 + 分享入口                     | 7  | 完成 | 95  | 另存走 SAF 实测（`p2t.png`，Downloads + 未命名.md + SAVE）；分享走 `ACTION_SEND` chooser 实测（`p2u.png`，Sharing text + 正文预览）；「不覆盖原文件」的重复另存未逐次验证                                                                                                                                                                                                  |
| 10 | 主题与设置                                      | 4  | 完成 | 100 | 设置页字号 15→23 / 行高 / 折行实测热应用（`p2o.png`）；`shared_prefs/editor-prefs.xml` 落盘 `fontSize=23`；重启回灌生效（`p2q.png` 字号仍 23）                                                                                                                                                                                                                 |
| 11 | 单元测试与金标准语料迁移                               | 8  | 完成 | 100 | 72 条 / 13 套件全绿（新增 `DraftJournalTest` 5 条）；R19 新增跨端金标准语料：`tests/golden/corpus/` 12 条语料 + `scripts/golden_fingerprint.py`（桌面侧 Python-Markdown 同配置渲染取指纹）+ 页内 `gsFingerprint()`（Android 侧 markdown-it 渲染取同一指纹），模拟器实跑 `golden: 12/12 一致`                                                                                             |

已关闭的 P1 阻塞项与 P2 承接关系：B1 打开（955 ms 中位）、B4 落盘一致性（SHA-256 一致）已达标；B2 滚动、B3 IME 组合态转为 P2 期间的真机验收项（§5.1），不计入 P1 出关否决。

**R15 结构修复（界面归一到路线 D）**：P2 的界面此前是「路线 C 的 Compose 编辑器壳 + 路线 D 的 WebView 叠加」两套并存。本轮按根因拆除，不做视觉补丁：



1. **根因一：panel 从挂载起就整屏不透明**。`attachEditorPanelIfNeeded()` 在 `wm.addView()` **之后**才把 `lp.alpha` 置 0，但那只是改本地对象、没回写窗口，实际窗口 alpha 仍是 1 → 挂载即盖满全屏，Compose 主页任何时候都看不到，返回键也被子窗口吞掉。修法：`addView` 之前就设 `alpha=0f` + `FLAG_NOT_TOUCHABLE`。

2. **根因二：路线 C 的编辑器 UI 留在主页**。主页同时带着编辑器工具栏（新建 / 关闭 / 查找 / 预览 / 夜间 / 打开 / 另存 / 导入 / 备份 / 片段）、Compose 查找替换栏（两个 `OutlinedTextField` + 全部替换）、横向标签胶囊、状态行、「点标签进入编辑器」+「编辑当前文档」大按钮。重写为**纯文档列表页**：顶栏（应用名 + 日 / 夜）、动作行（新建 / 打开文件 / 导入备份 / 导出备份）、纵向卡片列表（标题 + 格式 + `open/closed`），删除上述全部路线 C 控件与 `findOpenFlow`、`applyReplaceAll`。

3. **根因三：BACK 进不了 Activity**。panel 是 `TYPE_APPLICATION_PANEL` 子窗口、焦点在 WebView 时键事件不经 `Activity.dispatchKeyEvent`。修法：WebView `setOnKeyListener` 捕获 `KEYCODE_BACK` → `onBackPressedDispatcher.onBackPressed()`。

4. **语义修正**：列表改为 `allDocuments()`（含 `closed`，标题即「最近文档」），点开 `setState(open=true)`，关闭 `setState(open=false)`，`reload()` 不再凭空造文档；「新建」创建后直接进编辑器。

5. 查找入口统一：`Ctrl+F` / `KeyAction.FIND|REPLACE` → `EditorHost.openFind()` → 页内 `window.NativeEditor.openFind()`（页内查找条为唯一实现）。

实测闭环（`build/home6.png` → `n1.png` → `n2.png` → `m2.png` → `m3.png` → `m4.png` → `m5.png` → `m6.png`）：冷启动即列表；点列表项进 CodeMirror；BACK 回列表且 `state=closed`；点「大文档 1MB」打开 465,438 字 / 12,503 行（`open=116ms`）；「新建」直接进编辑器（新文档 `state=open`）；页内「关闭」回列表（日志 `editor closed id=…`）；页内「查找」展开查找条（含 `.*` / 选区内 / ↑↓）。

**R16 主页能力补齐 + 出包纪律**（用户三项拍板：主页动作行保留 / 增加设置入口 / 允许重命名与删除）：



1. **主页动作行保留**：「新建 / 打开文件 / 导入备份 / 导出备份」与顶栏「夜间・日间」保持原位，未压缩。

2. **设置入口**：顶栏新增「设置」按钮 → `AlertDialog`（字号 11–32 步进、行高 1.20–2.20 步进、折行开 / 关）→「保存」写 `SharedPreferences("editor-prefs")` 并即时 `editorHost?.setPrefs(...)`，下次进入编辑器由 `applyEditorPrefs()` 回灌。

3. **重命名**：列表卡片长按 → `DropdownMenu`（重命名 / 删除）→「重命名」弹 `AlertDialog` + `OutlinedTextField`，空标题拦截 → `repository.rename(id, title)` → `reload(doc.id)`。

4. **删除**：同一菜单「删除」→ 二次确认（文案含标题、标注无法撤销）→ `repository.delete(id)`，若删的是当前文档同时清 `activeId` → `reload()`。

5. **出包纪律（新增，最高优先）**：此前每轮只 `assembleDebug` 并 `install -r` 到模拟器，`app\build\outputs\apk\release\*` 一直停在 0.6.0（05:22 构建），真机装该包看到的是旧界面 —— 这正是 "界面停在路线 C" 能被复现的另一条路径。自 R16 起，**每轮修改后必须&#x20;**`gradle :app:assembleRelease`**&#x20;产出两个 ABI 的 release APK 并在交付中给出路径**，debug 仅用于模拟器回归。

6. 顺带清理：删除重复的 `LaunchedEffect(isDark)`、删除已无调用方的 `insertSnippet`（片段插入统一由页内 `showEditorSnippets()` 承担）、`SharedPreferences.edit` 改 KTX 形式（lint warning 由 2 降到 1，仅剩外部库那条）。

R16 实测闭环（`build/s1.png` … `s13.png`、`r1.png`、`r2.png`）：主页 = 动作行 + 「设置」+「夜间」；设置对话框把字号 23→25、行高 1.55→1.65，落盘 `editor-prefs.xml` 实测 `fontSize=25`、`lineHeight=1.6499999`，日志 `prefs from home 25/1.55/true`；长按弹「重命名 / 删除」；重命名后 DB `ca726ea3…|renamed-by-r16未命名|closed`；删除后该 id 记录数 0、文档总数 14→13；release 包 `0.6.3 / versionCode 10` 安装后冷启动进列表、点项进编辑器（`editor ready in 284ms`）。

**R17 按钮 / 菜单布局对齐参考截图（PilcrowMD）**（用户四项拍板：① 导入 / 导出备份仍留一级 ② 保留「夜间」文字按钮 ③ 行内 × 与长按菜单并存 ④ 不强制默认深色）。范围严格限定在**按钮与菜单布局**，编辑器内核（CodeMirror 6 / 折叠 / 查找 / 落盘）零改动：



1. **编辑器页工具栏图标化**：`#bar` 由 7 个中文文字按钮改为「左侧品牌文档图标 + 右侧 搜索 / 大纲 / 预览 /⋮/×」共 6 个 inline SVG 按钮（44×44 触摸目标，56 px 条高，无横向滚动）；新增 `#moremenu` 溢出菜单（保存 / 另存为 / 分享 / 插入片段 / 折叠光标块 / 全部折叠 / 全部展开 / 设置 / 日间・夜间 / 新建文档 共 10 项，`position:absolute; top:52px; right:8px; z-index:21`），点空白处由 document 捕获阶段收起，`hideOverlays()` 同步收起。

2. **面包屑行**：`#crumb` = 文档图标 + `#doc-title`（`max-width:46vw` 省略）+ `›` + 右侧 `#status`（`N 行 · M 字 · L:C`，800 ms 刷新）。标题由宿主下发：`EditorHost` 新增 `pendingTitle` 与 `setTitle()`，`openEditor()` 在 `setDocument` 前调用，`onReady` 回放，避免「翻页 / 重挂后标题丢失」。

3. **主页重排**：hero（`Gscratchpad` 30sp 粗体 + 副标题「Markdown 编辑・本地存储」）→ 滑块图标（Canvas 自绘 `SlidersIcon`，不引入 `material-icons` 依赖）进设置 + 「夜间 / 日间」文字按钮 → 主按钮「打开文件」（54 dp，实心底色随主题反转）→ 次按钮「新建文档」（50 dp 描边）→ 文字链「看不到文件？浏览全部文件」→ `*/*` picker → 「导入备份 / 导出备份」并排描边 → 「最近文档 / N 个文件」表头 → 列表行（标题单行省略 + `md · 相对时间` + 右侧 ×）→ 长按 `DropdownMenu`（重命名 / 删除）保留。

4. **相对时间**：新增 `relativeTime(updatedAt)`（epoch 秒 → 刚刚 / N 分钟前 / N 小时前 / N 天前 / `YYYY-MM-DD`），列表行显示由 `state.id` 改为相对时间，`state` 语义仍由 `open/closed` 落库（关闭编辑器后回列表可见刷新）。

5. **顺带修复**：`onEditorAction` 原只匹配 `"snippet"`，而溢出菜单动作 id 为 `snippets`（`EditorActions` 复数）→ 命令面板 / 按钮「插入片段」静默无响应；改为同时接受两者。

6. **编译期踩坑（记为纪律）**：`androidx.compose.material.icons` 不在现有 classpath（material3 未暴露 icons-core），`Icons.Filled.*` 直接报 `Unresolved reference 'icons'`；不新增依赖，改用 `Canvas` 自绘 + `Text("×")`。

R17 实测闭环（`build/u1.png` … `u11.png`）：主页 hero / 主次按钮 / 备份并排 / 相对时间 /× 全部到位（`u1.png`）；编辑器图标栏 + 面包屑「未命名 › 1 行・0 字・1:1」（`u2.png`）、溢出菜单 10 项（`u3.png`）、搜索展开查找条（`u4.png`）、大纲空态（`u5.png`）、预览跳 `PreviewActivity`（`u6.png`）、× 关闭回列表（`u7.png`，日志 `editor closed id=…`）、×/ 长按菜单并存（`u11.png`）；**release 包实测**：`0.6.4 / versionCode 11` 安装后主页（`u8.png`）、深色主页（`u9.png`）、编辑器（`u10.png`，`editor ready in 157ms`）；1 MB 文档 release 包冷开 `page ready 2485ms` / `mount load=33ms`（465,438 字）/ `editor ready 184ms` / `fpsIdle 37 → 58 → 56`。67 条单测全绿，lint 0 error / 1 warning，release 3.20 MB / ABI。

> 进度口径：R17 属界面布局对齐，不改变 §9.2 十一条任务线的取值。

**R18 P2 全量收尾（0.7.0 /versionCode 12）**：本轮把 P2 余项（P2-2 / P2-5 / P2-6 / P2-7 相关代码）与 Q1–Q5 一并落地，并在真机 `真机 A（OPPO A56 5G）`（OPPO A56 5G / 720×1600）实测。



1. **S6 预览页归一**：`PreviewActivity` 整文件重写为纵向「56 dp 图标栏 + WebView（weight 1）」，`paintBar()` 绘制 BACK / 标题 / 日夜间 / PDF / 关闭；新增 `PanelIconView`（Canvas 自绘四种图标，规避 `materialx.compose.material.icons` 不在 classpath 的老坑），600 ms `syncTick` 轮询 `currentScrollY` 与 `ScrollSync.pullFromEditor()`。

2. **P2-2 双向滚动同步**：新增 `HeadingIndex`（`parse()` 支持 `#`–`######`、跳过 \`\`\` / \~\~\~ 围栏、`indexForLine`）与 `ScrollSync`（object，编辑器顶端行 ↔ 预览标题下标互推，两侧各 900 ms 抑制窗防抖回弹）；`PreviewHost` 增 `scrollListener` / `topHeadingIndex` / `gsTopHeadingIndex` / `gsScrollY` / `gsScrollTo`。

3. **Q1 平板双栏**：`MainActivity` 增 `panelContainer`（横向容器，editorView + 可选预览 WebView 各占一半）、`setSplit(on, auto)`、`startSplitSync/stopSplitSync`（600 ms 协程轮询）、`scheduleSplitRender`（800 ms 节流）；`smallestScreenWidthDp ≥ 600` 自动开启。**真机 360 dp 下手工开启可用但面包屑被挤掉（已知窄屏限制）；模拟器改 1600×2560 / 320 dpi 实测&#x20;**`split on auto=true`**，面包屑「大文档 1MB ›」正常，465,438 字两侧同时渲染。**

4. **Q3 插图**：`importImage(uri)` 读字节 → MIME 映射扩展名 → `AssetStore.importBytes` 落 `files/assets/<docId>/<sha12>.<ext>` → 编辑器插入 `![](assets/<docId>/<file>)`。真机实测日志 `image imported assets/8964e953…/70e94f462164.png (197947 B)`，文档字数 548,180→548,243，分屏预览正确渲染该图。

5. **Q4 净化口径**：`PreviewHost` 渲染时把正文相对 `assets/…` 改写为绝对 `/assets/…`（由 `WebViewAssetLoader.InternalStoragePathHandler` 映射到 `files/assets`），并移除 `javascript:` / `data:` 等非法协议 `src`；`securityLevel:'strict'` + `html:false` 保持不变。

6. **Q5 云备份**：新增 `CloudBackup`（WebDAV PUT/HEAD/GET + Basic auth，12 s/30 s 超时）；`MainActivity` 增 `showCloudDialog()`（URL / 账号 / 密码 + 保存配置 / 上传 / 从云端恢复）、`buildBackupZip()`（复用 `BackupExporter`，`appVersion=0.7.0`）、`cloudUpload/cloudDownload`；`importBackupFrom` 拆出共用 `importBackupZip`；新增 `INTERNET` 权限（与旧「纯本地」口径冲突，已在清单注释说明取舍）。

7. **Q2 物理键盘一等交互**：`Shortcuts` 扩到 15 个动作（新增 SAVE/SAVE\_AS/OPEN/TOGGLE\_SPLIT/HELP/IMAGE/RENAME），新增 `resolvePlain()`（F1/F2/F9）；`dispatchKeyEvent` 扩键码（S/O/D/I/SLASH + F1/F2/F9）；页内 keymap 同步新增 `Mod-s / Mod-Shift-s / Mod-o / Mod-d / Mod-i / Mod-Shift-/ / F1 / F2 / F9`；新增 `#help` 遮罩（14 条快捷键清单）与 `/#help-close`；`renameCurrentDialog()` 走 Android `AlertDialog` + `EditText` → `repository.rename`。

8. **P2-6 自检**：新增页内 `window.NativeEditor.selfCheckFind()`（固定语料 3 处全替换 → 一次 undo → 仅选区替换），由 `--es runAction selfCheckFind` 触发。**首轮自检&#x20;**`undoRestored=false`**&#x20;属探针自身缺陷**：写入语料与替换在同一 tick，CodeMirror 历史把两笔合并成一步，一次 undo 直接退到原文；把步骤间隔改为 650 ms（> `newGroupDelay` 500 ms）后复测通过。

9. **渲染循环根因排查（新增纪律）**：分屏时预览曾出现每 44 ms 重渲染。逐层切分后确认「同一内容 + 同一外壳被反复请求渲染」是放大器（真机小文档渲染快、循环频率反而更高），在 `PreviewHost.renderMarkdown()` 加幂等短路（`markdown == lastMarkdown && key == shellKey` 直接返回）；复测真机 12 s 内渲染从数十次降到 1 次，模拟器大文档同样只渲染 1 次。探针（`caller=` / `doc changed` / `activate`）用完即删。

10. **分屏新 WebView 残留像素**：子 View 加入 panel 窗口后父窗口未重排 / 重绘，新预览区显示上一次分屏的旧像素；修法 `panel.invalidate() + postInvalidateOnAnimation() + updateViewLayout` + 子 View `post{invalidate(); requestLayout()}`。

11. **面包屑标题重推**：页面未就绪时下发的标题会丢，`openEditor` 增加 400 ms 后重推 `setTitle(editorTitle)`。

R18 实测闭环（真机 `真机 A（OPPO A56 5G）`）：



* **B1**：1.07 MB / 548,166 字符文档冷启动直开 `page ready 756 ms`、`editor total 809–909 ms`、`open 33–78 ms` → **达标（≤1.5 s）**。

* **B2**：连续 fling 12 次采样 `57 / 56 / 57 / 43`；高频短滑（220 ms swipe + 60 ms 间隔）采样 `48 / 36 / 49 / 39`，idle 56–60 → **稳态 ≥55 达标，极限连续拖动段仍低于 55**。

* **官方样本被清空**：真机此前数据被清过（安装签名变动），`big-1` 已不存在；本轮重新生成 1.07 MB 语料 → SAF 导入为 `8964e953…`（548,166 字符），后续 B1/B2 均基于该文档。

* 其余：P2-6 自检五项全 true；Q3 插图落盘 + 预览渲染；Q5 云备份对话框；页内 `#help` 面板（`build/r18_help.png`）；分屏（`build/r18_split_final.png`）；平板双栏（`build/r18_tablet.png`）。

> 进度口径：R18 把任务线 3（80%）与 6（100%）、8（100%）更新，11 仍为 70%（P2-7 未做）。Σ(人日 × 取值) = 3 + 6 + 7.2 + 12 + 8 + 9 + 9.5 + 10 + 6.65 + 4 + 5.6 = 81.55 / 84 人日 → 
>
> **P2 97%（8,155 / 8,400）**
>
> 。

### 2.1 P1 出关时的能力核账（保留作基线）



| 子项                              | 状态                                                                                          | 证据                                                                         |
| ------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 工程骨架与六层架构（§4–§6）                | 完成                                                                                          | `ANDROID_IMPLEMENTATION.md` §3–§6                                          |
| JVM 单测 59 条                     | 完成                                                                                          | `app/build/test-results/testDebugUnitTest`，11 套件全绿                         |
| domain 行覆盖 90.9%                | 完成                                                                                          | `coverageGate` 通过（279/307）                                                 |
| lint 0 error / 1 issue          | 完成                                                                                          | `lint-results-release.sarif`，仅外部库 `ObsoleteLintCustomCheck`                |
| CodeMirror 6 集成（esbuild 单文件内联）  | 完成                                                                                          | `assets/editor/index.html` 329,106 B，运行时单资产                                |
| 1 MB 文档渲染                       | 完成                                                                                          | `editor mount id=big-1 465438 chars`，12,503 行                              |
| 折叠                              | 完成（17–28 ms，门槛 ≤100 ms）                                                                     | `editor fold X ms` + `build/fold4.png`                                     |
| 查找 / 替换                         | 完成                                                                                          | 查找条展开截图 `build/t2.png`，`TextSearchTest` 6 条                                |
| 输入 → 状态 → 落盘                    | 完成（能力级）                                                                                     | 输入 `hello_port_test`，DB 39 字符末尾命中；1 MB 文档连续输入 2,950 字符零丢字（§4）              |
| 打开 ≤1.5 s                       | **达标**（冷启动直开中位 955 ms，应用内打开 18–160 ms）                                                      | 本文 §4                                                                      |
| 滚动 ≥55 fps                      | **环境不可判定**（AVD 正常态 idle 47–60 fps，1 MB 滚动 37–58 fps、均值约 49；R12 的 25–35 fps 系 AVD 异常负载态，已作废） | 本文 §4                                                                      |
| 中文输入 5 分钟无丢字                    | **链路达标**（ASCII 235 批 + 中文 50,076 字符均零丢字）；IME 组合态待真机                                         | 本文 §4                                                                      |
| 编辑器宿主架构（常驻 WebView + panel 子窗口） | 完成                                                                                          | `MainActivity.setupEditorOverlay/attachEditorPanelIfNeeded`，`build/p5.png` |
| §13 十项不可移植矩阵                    | 完成                                                                                          | `ANDROID_FEATURE_MATRIX.md`                                                |
| §14 待决项 Q1–Q5                   | 完成                                                                                          | `ANDROID_OPEN_QUESTIONS.md`                                                |

P1 出口结论：**已出关（用户裁定，2026-11-19）**。硬门槛上 B1 打开达标、B4 落盘一致达标；B2 与 B3-IME 经四组对照与依赖核查判定为「当前设备条件不可判定」，转为 P2 期间的真机验收项，不作为 P1 否决项。

## 3. 轮次日志（每轮任务后追加一行）



| 轮次  | 日期         | 本轮交付                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | 阶段       | 进度快照                                                                                                                                                              |
| --- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | 2026-11-19 | 方案 §1–§6：工程骨架、六层架构、存储层与不变量、平台接口、capture 与迁移                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | 路线 C 准备  | —                                                                                                                                                                 |
| R2  | 2026-11-19 | §7–§9：P0 Spike 报告、WBS                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 路线 C     | —                                                                                                                                                                 |
| R3  | 2026-11-19 | §10–§12：风险登记 R1–R10、测试策略、工程化与发布                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | 路线 C     | —                                                                                                                                                                 |
| R4  | 2026-11-19 | 路线 C 工作量拆分核对（阶段判断）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | 路线 C     | —                                                                                                                                                                 |
| R5  | 2026-11-19 | S1 判定不通过（Compose 26,737 ms ANR）→ 用户拍板切路线 D                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | P0→P1 切换 | P1 0%                                                                                                                                                             |
| R6  | 2026-11-19 | 路线 D 骨架：`EditorHost`、`EditorActivity`、CodeMirror 6 bundle、1 MB 文档渲染                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | P1       | 45%                                                                                                                                                               |
| R7  | 2026-11-19 | 打开链路优化：Activity context WebView、`singleTask`、返回不 finish；内联 CSS/JS（首屏 1,929→1,614 ms）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | P1       | 55%                                                                                                                                                               |
| R8  | 2026-11-19 | S1 复评实测：打开 1,974 / 2,706 / 3,362 ms，折叠能力排查                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | P1       | 60%                                                                                                                                                               |
| R9  | 2026-11-19 | 折叠根因修复（`onAction` 同名自调用 → `this@EditorHost`）；滚动 45–46 fps 采样；输入→落盘验证                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | P1       | 68%                                                                                                                                                               |
| R10 | 2026-11-19 | 0.5.1 发布：删除负收益 `EditorCache`（lint `StaticFieldLeak` 3 条清零）、`--rerun-tasks` 复算 lint 至 1 issue、59 条单测 + coverageGate 复跑、§13/§14 两份文档落盘、README / 实现 / 工程化文档同步、本文建立                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | P1       | 70%                                                                                                                                                               |
| R11 | 2026-11-19 | 0.6.0：常驻 WebView 宿主定为 `TYPE_APPLICATION_PANEL` 子窗口（硬件合成，Z 序在 Compose 之上）；证明软件层合成只有 9 fps 故弃用；修掉 WebView 跨窗口迁移导致的整页重载（必须先挂窗口再 `loadUrl`）；panel alpha 0→1 需手动 invalidate；返回键改用 `OnBackPressedDispatcher` + WebView 按键转发（lint `GestureBackNavigation` 清零）；新增 `--es openDoc <id>` 自动化入口；B1/B4 关闭、B3 部分关闭                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | P1       | 80%                                                                                                                                                               |
| R12 | 2026-11-19 | 滚动帧率环境定性：模拟器（SwiftShader）idle rAF 30 fps、1 MB 滚动 31、20 KB 滚动 28–29、半分辨率滚动 33 → 与像素数和文档大小均无关；改 AVD 为宿主 GPU（AMD Vega 8）后 idle 52、滚动 26–28；关掉行号 / 活动行 / 折行 / 高亮全部装饰后仍 25–27 → 瓶颈是 WebView 滚动合成本身，不是编辑器内核。中文链路：新增 `--ei soakSeconds` 诊断钩子，5 分钟注入 50,076 个中文字符，库内 20,000→70,076 零丢字；IME 组合态在无中文输入法模拟器上无法自动化（ADBKeyboard 广播在 API 36 无效，已卸载还原）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | P1       | 80%                                                                                                                                                               |
| R13 | 2026-11-19 | 用户裁定进入 P2。P1 出关闭环（B2/B3-IME 转真机挂账）；P2 首个任务 H1 落地：删除路线 C 遗留 `feature/editor/EditorController.kt` 与 4 个未使用 Compose import，构建 / 59 条单测 /lint（0 error）全绿，模拟器冒烟确认 1 MB 文档打开正常（12,503 行 / 465,438 字 / `build/sm.png`）；M1 十一条任务线按人日加权核对为 76%（命令面板、大纲与滚动同步、设置页、另存 / 分享、金标准语料为缺口）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | P2       | 76%                                                                                                                                                               |
| R14 | 2026-11-19 | P2 四条任务线落地并实测：①命令面板（页内覆盖层 + Kotlin 单源 `EditorActions` 16 条动作 + `search` 空格分词 AND + `EditorActionsTest` 8 条；`build/p2j.png` 16 条全列出，点「文档大纲」→ `build/p2k.png` 章节 2–14）②大纲点击跳行（`build/p2l.png` 落在第 65 行「章节 10 标题」）③设置页（字号 15→23 / 行高 / 折行，热应用 `build/p2o.png`，`shared_prefs/editor-prefs.xml` `fontSize=23` 落盘，重启回灌 `build/p2q.png`）④另存 SAF（`build/p2t.png`）与分享 chooser（`build/p2u.png`）。查找替换增正则 / 仅选区开关与 `replaceAll` 单次 dispatch。三个缺陷定根并修复：**(a) 页内覆盖层用&#x20;**`position:fixed`**&#x20;在 panel 子窗口 WebView 里不绘制**（改 `absolute` + 移到 `#host` 之后，z-index 20）；**(b)&#x20;**`@JavascriptInterface`**&#x20;匿名对象内&#x20;**`onPrefsChanged(json)`**&#x20;解析为自调用**（递归 `post`，偏好永不落盘；改 `this@EditorHost.onPrefsChanged(json)`）；**(c)&#x20;**`install -r`**&#x20;后 WebView 命中旧资产 bundle**（`loadUrl` 加 `?t=<attachedAt>`）。另修设置面板 label 与滑块跨行堆叠。新增 \`--es openPanel palette | outline  | settings`与`--es runAction `两个自动化入口（不再依赖工具栏坐标换算）。帧率复核：模拟器重启后 idle 42–60、1 MB 滚动 37–58（旧 26–31 为 AVD 异常态）；1 MB`mount load=454 ms\`。版本 0.6.1 /versionCode 8，67 条单测全绿 |
| R17 | 2026-11-19 | 按钮 / 菜单布局对齐参考截图（PilcrowMD），编辑器内核零改动：① 编辑器 `#bar` 改成「品牌图标 + 搜索 / 大纲 / 预览 /⋮/×」6 个 inline SVG 图标（44 dp 触摸目标），新增 `#moremenu` 10 项溢出菜单（点空白收起）；② 新增 `#crumb` 面包屑（文档图标 + 标题 + `›` + 右侧 `N 行 · M 字 · L:C`），宿主增 `pendingTitle` / `setTitle()` 并在 `onReady` 回放；③ 主页重排为 hero + 滑块设置图标 + 「夜间」 + 实心「打开文件」54 dp + 描边「新建文档」50 dp + 文字链「浏览全部文件」→ `*/*` + 导入 / 导出备份并排 + 「最近文档 / N 个文件」+ 行内标题 /`md · 相对时间`/×，长按菜单保留；④ 新增 `relativeTime()`（刚刚 / 分钟 / 小时 / 天 / 日期）；⑤ 修 `snippet` vs `snippets` 动作 id 不匹配导致「插入片段」静默无响应。**出包**：`assembleRelease` 两 ABI 各 3.20 MB（0.6.4 /versionCode 11，16:20:52），release 包实测主页 / 深色主页 / 编辑器 / 1 MB 冷开（`page ready 2485ms`、`mount load=33ms`、`editor ready 184ms`、`fpsIdle 37→58→56`）。67 条单测全绿，lint 0 error / 1 warning                                                                                                                             | P2       | 89%（7,480/8,400）                                                                                                                                                  |

\| R18 | 2026-11-19 | P2 全量收尾：S6 预览页图标栏归一（`PanelIconView` Canvas 自绘 + 56 dp 栏）、P2-2 双向滚动同步（`HeadingIndex` + `ScrollSync` 900 ms 抑制窗）、Q1 平板双栏（`panelContainer` + `setSplit` + 600 ms 同步 + 800 ms 节流，≥600 dp 自动开启）、Q3 插图（`importImage` → `assets/<docId>/<sha12>.ext`，真机 197,947 B 落盘并在预览渲染）、Q4 净化（相对 `assets/` → `/assets/`、剔除非法协议 src）、Q5 云备份（`CloudBackup` WebDAV + 对话框 + `INTERNET`）、Q2 物理键盘（`Shortcuts` 15 动作 + `resolvePlain` F1/F2/F9 + 页内 keymap + `#help` 面板 + F2 重命名对话框）、P2-6 自检脚本。三个缺陷定根修复：**(a)** 分屏重复渲染（`PreviewHost.renderMarkdown` 内容 + 外壳未变即返回，真机 12 s 渲染数从数十降到 1）；**(b)** 分屏新 WebView 残留像素（父窗口 `invalidate` + `updateViewLayout` + 子 View 重排）；**(c)** 页面未就绪时标题丢失（`openEditor` 400 ms 后重推）。**真机实测**：1.07 MB / 548,166 字符冷开 `page ready 756 ms`、`editor total 809–909 ms`；fling 帧率 57/56/57/43、高频短滑 48/36/49/39；P2-6 自检 `replaced=3 / undoRestored=true / selectionOnly=true`；强杀恢复「已落盘不丢、300 ms 窗口内最后 10 字符未恢复」。**出包**：`assembleRelease` 两 ABI 各 3.20 MB（0.7.0 /versionCode 12，17:19:33），67 条单测全绿，lint 0 error / 8 warning | P2 | 97%（8,155/8,400） |

\| R19 | 2026-11-19 | P2 收尾第三轮（0.7.1 /versionCode 13）：① **P2-5 关闭**—— 新增 `DraftJournal`（输入即刻投递到单线程合并队列，守护线程原子写 `recovery/<docId>.json`，只写日志不做 DB 提交；同 docId 多笔输入只保留最新快照），`AppContainer` 注入、`onDocChanged` 接线、`closeEditor` drop；实测输入 10 字符后 150 ms 内 `am force-stop` → 重开 `recover restored journalRev=970 dbRev=966 chars=465448`、`mount 465448 chars`，**末批输入零丢失**。② **P2-7 关闭**——`tests/golden/corpus/` 12 条语料 + `scripts/golden_fingerprint.py`（桌面 Python-Markdown 3.10.2 同配置出指纹）+ 页内 `gsFingerprint()`（markdown-it 出同一指纹：纯文本折叠 + 白名单标签计数），模拟器实跑 `golden done ok=12/12`、命令行比对 **12/12 一致**。③ **Q5 实测通过**——`admin/123456` 认证 207；Alist 聚合根不可 PUT（404），须落 `http://<LAN-IP>:5244/dav/backups`（PUT 201）；端到端 `uploadOk=201 / remoteBytes=279569 / downloadOk / zipEntries=manifest+db+16 notes / sizeMatch=true`。④ **明文 HTTP 拦截定根**：Android 9+ 默认禁 cleartext，`CloudBackup` 首轮直接 `Cleartext HTTP traffic not permitted` → 清单加 `android:usesCleartextTraffic="true"` 并注明取舍。⑤ **B2 记为通过**（用户裁定）：稳态 fling 中位 56.5 ≥55，高频短滑与极限段不再作为门槛。⑥ B3 中文 IME 组合态、Q2 物理键盘按用户决定跳过；Q1 窄屏面包屑略过。⑦ 单测 67 → **72**（`DraftJournalTest` 5 条）；lint 0 error。**出包**：两 ABI release 见 `app\build\outputs\apk\release\` | P2 | 99%（85.15/86 人日） |

\| R20 | 2026-11-19 | 界面 / 交互收敛（0.7.2 /versionCode 14）：① **主页**—— 删除「导入备份 / 导出备份」并排整块并移入设置页 DATA 段；「夜间 / 日间」文字按钮改为 44 dp 图标按钮（`MoonIcon(tint,bg)` 用背景色圆咬出月牙 / `SunIcon` 圆 + 8 射线，无 icons 依赖）；列表头新增小号 `clear`（`clearAllRecent()`）与「返回最近」；行尾 × 语义改为**只清记录不删文档**（`clearRecent`），删除保留在长按菜单；隐藏项标「・已清除记录」并给「恢复」按钮；底部「查看全部文档（N）」入口兜底可达。② **数据层**——`Schema.VERSION` 3→4，`documents.recent_hidden INTEGER NOT NULL DEFAULT 0`，`onUpgrade` 先查 `PRAGMA table_info` 再 ALTER（幂等）；`Document.recentHidden`、`recentDocuments()`、`setRecentHidden`、`setAllRecentHidden`、Repository `clearRecent/clearAllRecent/restoreRecent`。③ **设置页全屏化**—— 改 `Dialog(usePlatformDefaultWidth=false, decorFitsSystemWindows=false)` 承载 `SettingsScreen`：标题 + 副标题 + 右上圆形 ×、`APPEARANCE`（Theme 分段 夜间 / 日间、字号 Slider + 实时示例、行高 Slider、自动折行 Switch）、`DATA`（导入 / 导出 / 云端备份三行）、`ABOUT`（版本 / 数据目录），全部改动即时 `persistPrefs`。④ **A/B 串内容缺陷定根**——`closeEditor()` 在协程里 `flushEditor()` 读实时字段 `editingDocId/editorLatest`（关闭 A 后立即开 B 会把 A 正文写进 B）；`activate()` 无条件 `setDocument` 把 A 塞回隐藏 WebView。修法：`editorEpoch` + 快照式 `closeEditor` + `activate()` 增加 `if (editorOpen)` 守卫。⑤ **弹窗空白关闭**——`editor.js` 增加 document 级 click，命中 `#bar/#crumb/.overlay/#moremenu/#findbar` 放行，其余 `hideOverlays()` 并收起查找条；`node build.mjs` 重建 bundle 345,945 B。⑥ **系统栏随主题**——`setDark()` 写 `editor-prefs` 并统一驱动 `applySystemBars()`（状态栏 / 导航栏底色取主题色、`isAppearanceLight*Bars=!isDark`、API≥29 关 contrast）；启动即回灌偏好；`PreviewActivity` 同步。⑦ **应用图标**——`ic_launcher_foreground.xml` 按桌面版 `io.github.gscratchpad.Gscratchpad.svg` 重绘（白纸 + 蓝脊 `#1C71D8/#3584E4`+ 白扣环 + 四条 `#C8C5C0` 横线 + 38° 铅笔），`AndroidManifest` 补 `android:roundIcon`。**实测**：真机 `真机 A（OPPO A56 5G）` 装 0.7.2/14 —— clear 单条 6→5 + toast、全部视图「已清除记录 / 恢复」、clear 全部后 `0 个文件` 且 `查看全部文档（6）` 仍在、A（big-sample 548,245 字）→ × → B（郑居敬 1,268 字）内容正确无串；模拟器深色模式状态栏 / 导航栏随主题变黑（修掉首轮「深色下状态栏白条」）、设置页 Slider 由 Material 紫改为主题灰。**构建**：72 单测 / 13 套件 / 0 失败；lint 0 error / 9 warning / 2 hints；release 两 ABI 3.2578 / 3.2584 MB（18:22:11）。 | P2 收尾后 | 99%（口径不变） |

\| R21 | 2026-11-19 | 缺陷修复与设置页补齐（0.7.4 /versionCode 16）：① 缺陷「打开文件只加记录」定根（`openExternal` 无 `openEditor`）→ 导入副本进库 + 直开编辑器，真机 52.77 KB 文档 `open 25405 chars`、`editor ready 140ms`；② 缺陷「最近文档不按打开时间排序」定根（排序键无 `opened_at`）→ schema v4→v5 `opened_at` + 索引 + 幂等迁移 + 三查询改 `ORDER BY opened_at DESC,…` + `touchOpened` 顺带恢复 `recent_hidden`，真机打开后「全部」视图置顶；③ 缺陷「预览被刷回顶部」定根（预览页轮询已暂停 WebView 的旧 topLine）→ `syncTick` 只听预览自身滚动，真机下滚后静置 20 s 位置不变、零重渲染；④ 设置页补齐：Theme 夜间 / AMOLED / 日间、字体三段、编辑 / 阅读字号双 Slider、全屏阅读、PDF 深色导出、FEEDBACK 两行；⑤ 表头常驻「最近 / 全部」双态切换；⑥ 图标按 `图标设计.png` 复刻（藏青底 + 米白卡 + 三行波浪 + 橙光晕 / 光标条），真机桌面核验；⑦ H2 内存回归：10 轮进出 PSS 关闭态 162–164 MB / 打开态 165.5–166.3 MB，抖动～2 MB 无累积 → 通过。**构建**：72 单测 / 13 套件 / 0 失败；lint 0 error / 10 warning / 3 hints；release 两 ABI 3.2590 / 3.2597 MB | P2 收尾后 | 99%（口径不变） |

\| R22 | 2026-11-19 | SAF 三项实测收敛（0.7.5/17 → **0.7.11/23**）：① 新增 `safSelfCheck / safPowerWrite / safPowerVerify` 自动化钩子（与 `cloudSelfCheck` 同构）；② 定根修复 `documentTreeRoots()` 混入单文件授权导致 `DocumentFile.fromTreeUri` 崩溃（0.7.6/18，只返回 tree 型授权）；③ 定根修复原子换名链路从未生效 ——OPPO provider 拒绝「扩展名与 MIME 不一致」的 `createDocument`（`Failed to create unique file`），tmp 改 `application/octet-stream` + `$base.tmp$ext`，最终替换改「rename → `.old`、rename 回原名」两步原子换名（0.7.10/22）；探针确认同 provider `deleteDocument` 不可用（`Delete not supported`），`.old` 清理改尽力而为；④ **SAF 三项结论**：字节保真通过（GB18030+CRLF 往返 SHA `37785b57…` 一致，ATOMIC\_RENAME）；千文件枚举通过（1000 项目录按 400 截断、8.2–8.9 s）；断电无半截通过（7 轮强杀全为完整 V1/V2、tmpLeftover=0、零 CORRUPT；rename 为 FS 级原子操作）。已知限制：同目标第二次起保存退化 IN\_PLACE（`.old` 无法清除），由 tmp 读回校验 + RecoveryManager 缓解；⑤ H5 冷开基线：`am start -W` 三采样 480/492/467 ms（中位 480）。**构建**：72 单测 / 13 套件 / 0 失败；lint 0 error / 10 warning / 3 hints；release 两 ABI 3.2590 / 3.2597 MB；五份文档同步至 0.7.11 口径 | P3（SAF 段） | P2 99%；P3-5 关闭 |

| R23 | 2026-11-19 | 打包脱敏规范落地（**0.7.11/23 → 0.7.12/24**）：落实用户规范「打包 APK 时脱敏，不将测试用文档、测试用 WebDAV 地址一起打包」。① 全工程核查：源码 / 资源 / res 中无硬编码测试 WebDAV 地址与账号（`<LAN-IP>`、`admin/123456` 均只在设备端运行时配置），测试文档只在真机 /sdcard 与运行时 DB；唯一打包在 APK 内的测试资产是 `assets/golden/corpus.json`（金标准语料）。② golden 语料移至 `src/debug/assets/golden/`，release 合并链天然不含（release 中 `selfCheckGolden` 走缺语料提示分支，属预期；golden 对照复验改用模拟器 debug 包）。③ 新增 `scripts/verify_apk_sanitize.ps1` 打包脱敏校验并写入出包纪律（ENGINEERING §10.3.1）：结构检查 golden/ 资产 + 文本扫描内网地址 / `:5244` / `123456`（数字边界防误报）/ `dav/backups` / 测试文档名等标记，vendor 三方库跳过。④ 实测：release 两 ABI 各 144 条目全 PASS；装机 0.7.12/24 后设置页版本行确认、SAF 授权与数据保留。**构建**：72 单测 / 13 套件 / 0 失败；lint 0 error / 10 warning / 3 hints；release 两 ABI 3.2580 / 3.2586 MB | 打包流程 | P2 99%（口径不变） |
| R24 | 2026-11-20 | 预览页三项优化 + 发版规范落地（**0.7.12/24 → 0.7.14/26**）：①顶栏/图标对齐编辑器（56 px + 44 dp 图标 + 1.6 线宽 + 12 dp 圆角按压，`PanelIconView` 系数 0.86→0.5）；②编辑器→预览同页切换（抽 `PreviewScreen`，panel 内互斥显隐 140 ms 淡入，无 Activity 跳转黑屏，返回键先退预览，与分屏互斥）；③预览过滤 frontmatter + HTML 注释（`MarkdownSanitizer` 在 `PreviewHost.renderMarkdown` 入口清洗渲染副本，原文与滚动同步不变，围栏内注释保留）。版本显示改 PackageManager 动态读取。**发版规范**：版本号提为唯一来源 `appVersionName/appVersionCode`，release 重命名改 AGP 9.x Variant API，新增 `stageRelease` 一站式 task。**构建**：81 单测（增 `MarkdownSanitizerTest` 9 条）/ lint 0 error / release 两 ABI 各约 3.27 MB | P2 收尾后打磨 | 99%（口径不变） |
| R25 | 2026-11-20 | 设置页排版紧密化 + 行高范围（**0.7.14/26 → 0.7.15/27**）：外层 padding / 卡片间距 / 圆角 / 分段控件高度 / 主副标题字号全面收紧；行高上下限 1.2–2.2 → **0.5–2.5**（step 0.05，steps 19→39，默认 1.55），Compose slider 与编辑器 HTML `<input min/max>` 两处同步。模拟器（Pixel_API_36）实测 slider 两端显示 0.50 / 2.50，截图确认布局紧凑无重叠截断。`stageRelease` 首次真正跑通（修复 `java.io.File` 在 Kotlin DSL 被解析为 `JavaPluginExtension` 的编译错误）。**构建**：81 单测 / lint 0 error；release 两 ABI 各约 3.27 MB，`dist/` 自动清 0.7.14 旧包只留 0.7.15 | P2 收尾后打磨 | 99%（口径不变） |
| R26 | 2026-11-20 | P4 发布门禁收敛（**0.7.16/28 → 0.7.17/29**）：① 仪器测试补齐——新增 `PersistenceSmokeTest`（Activity 启动 → 打开文档 → saveNow+flush → 校验 DB 与镜像文件一致），重写过时的 `EditorUiSmokeTest` 三条（原「新建/查找/预览」文案已失效，改为「打开文件/新建文档/最近/全部」真实主页入口），`build.gradle.kts` 补 `androidx.test:core` 依赖；模拟器实测 **4/4 全绿**。② 本地门禁全绿：81 单测 0 失败 / domain 覆盖 89.5%（290/324）/ lintRelease 0 error / 两 ABI 各约 3.27 MB（≤12 MB）。③ upload key 正式签名，`stageRelease` 自动清旧包只留 0.7.17；真机 真机 C 装机 v0.7.17 并确认可启动、编辑器 Panel 可用。**未闭环**：同名重复另存真机全链路需 SAF 人工交互（Panel 焦点致 tap 误映射），交付手动验收步骤。 | P4 发布门禁 | 99%（口径不变） |
| R27 | 2026-11-20 | 另存为两项缺陷修复（**0.7.17/29 → 0.7.18/30**）：① 后缀 .txt——SAF MIME 改 text/markdown + `SaveAsPolicy.fileName()` 保证单一 .md；② 空内容——另存内容源改 `editorLatest.ifEmpty { text.value }`。新增 `SaveAsPolicy` 纯策略对象与 `SaveAsPolicyTest` 7 条单测锁定；全量 88 单测 / 15 套件 / 0 失败。反编译证实 0.7.16/0.7.17 classes.dex 逐字节一致，#5 系触发路径差异非版本回归。门禁全绿、upload key 出包并自动清旧包。 | P2 缺陷修复 | 99%（口径不变） |
| R28 | 2026-11-20 | 另存为链路再修两项（**0.7.18/30 → 0.7.19/31**）：① 手输 .txt 被改 .md——SAF MIME 由 text/markdown 改 application/octet-stream（中性类型不推断扩展名，后缀全由文件名决定）；② 另存后不进最近列表——补 saveNow 落库 + 标题同步 stem（`SaveAsPolicy.savedTitle()`）+ touchOpened 打点 + 刷 docs.value（避 reload 丢光标）。`SaveAsPolicyTest` 增至 9 条单测，全量 90 单测 / 15 套件 / 0 失败；门禁全绿、upload key 出包并自动清旧包。 | P2 缺陷修复 | 99%（口径不变） |



| 项                                | 门槛            | 实测（模拟器 Pixel\_API36 /x86\_64 /swiftshader）                                                                                                                                                                                                                                                        | 状态                                              |
| -------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| 打开 1 MB（462,479 字符 / 12,503 行）   | ≤1.5 s        | 冷启动直开 5 次：155 / 840 / 955 / 1,017 / 1,073 ms，**中位 955 ms**；应用已预热后打开 18 / 49 / 110 / 143 / 160 ms；page ready（预载完成）4.0–5.1 s                                                                                                                                                                        | 达标（口径为「点开→可编辑」，预载耗时单列）                          |
| 滚动帧率                             | ≥55 fps       | **R14 复核（AVD 重启后正常态，Pixel\_API36 /x86\_64 /host GPU）**：idle 42 / 47 / 56 / 57 / 60；1 MB 连续上滑 8 次采样 37 / 44 / 45 / 47 / 48 / 48 / 51 / 57 / 58，均值约 49，峰值 58。**R18 真机（OPPO A56 5G）**：连续 fling 12 次 57 / 56 / 57 / 43，**中位 56.5**；高频短滑 48 / 36 / 49 / 39；idle 56–60                                  | 达标（用户裁定，2026-11-19：以稳态中位 ≥55 为口径；极限连续拖动段不再作为门槛） |
| 折叠切换                             | ≤100 ms       | 17 / 28 ms                                                                                                                                                                                                                                                                                        | 达标                                              |
| 中文输入 5 分钟                        | 无丢字           | ASCII 持续输入 5 分钟 235 批 ×10 字符：462,488 → 465,438 字符；中文注入 5 分钟 50,076 字符：20,000 → 70,076 字符，两次增量与理论值完全一致                                                                                                                                                                                             | 链路达标；IME 组合态未测                                  |
| 编辑后落盘一致性                         | 字节一致          | 同一文档重启前后导出内容 SHA-256 均为 `C7D28C14…4849226F`；重开 `editor mount 465438 chars`（与库内一致）                                                                                                                                                                                                                 | 达标                                              |
| 单测                               | 全绿            | 81 条 / 14 套件（R19 增 `DraftJournalTest` 5 条；R24 增 `MarkdownSanitizerTest` 9 条）                                                                                                                                                                                                                                      | 达标                                              |
| domain 覆盖                        | ≥80%          | 279/307 = 90.9%                                                                                                                                                                                                                                                                                   | 达标                                              |
| lint                             | 0 error       | R21/R22：0 error / 10 warning / 3 hints；R24/R25：0 error / 8 warning / 3 hints（均为外部库与既有 Compose API 提示）                                                                                                                                                                                                                                   | 达标                                              |
| release 包体                       | ≤12 MB        | R36 出包 0.7.25 /versionCode 37：`scratchpad-arm64-v8a-release-0.7.25.apk` 3.29 MB、`scratchpad-x86_64-release-0.7.25.apk` 3.29 MB（upload key 正式签名，`dist/` 交付并自动清旧包）                                                                                                                                                              | 达标                                              |
| 真机 B1 打开 1 MB（548,166 字符）        | ≤1.5 s        | 真机 A（OPPO A56 5G）冷启动直开：`page ready 756 ms`、`editor total 809 ms / 909 ms`、`open 33 ms / 78 ms`                                                                                                                                                                                      | 达标                                              |
| 真机 B2 滚动帧率                       | ≥55 fps       | 连续 fling 12 次：**57 / 56 / 57 / 43**；高频短滑（220 ms + 60 ms）：**48 / 36 / 49 / 39**；idle 56–60                                                                                                                                                                                                         | 达标（稳态中位 56.5；用户裁定不再列门槛）                         |
| 云备份端到端（Q5，WebDAV）                | 上传 / 回读一致     | `http://<LAN-IP>:5244/dav/backups`（Alist，`admin/123456`）：`HTTP 201 Created` → HEAD `279,569 B` → GET 回读 `279,569 B`；zip 条目 `manifest.json` + `gscratchpad.db` + 16 个 `notes/*.md`；`hasDb/hasManifest/sizeMatch=true`                                                                          | 达标                                              |
| 跨端渲染指纹（P2-7）                     | 12/12 一致      | 桌面 Python-Markdown 3.10.2（与 `markdown_render.py` 同配置）vs Android markdown-it；指纹 = 折叠后纯文本 + 白名单标签计数；模拟器 `golden done ok=12/12`，`golden_fingerprint.py --compare` → `golden: 12/12 一致`                                                                                                               | 达标                                              |
| 真机 P2-6 替换自检                     | 全项通过          | `{"replaced":3,"afterReplaceClean":true,"undoRestored":true,"selectionReplaced":1,"selectionOnly":true}`                                                                                                                                                                                          | 达标                                              |
| 真机中断恢复（P2-5）                     | 末批输入不丢        | R19：模拟器 / 真机同链路，聚焦后 `input text` 注入 10 字符，**150 ms 内** `am force-stop` → 重开 `recover restored journalRev=970 dbRev=966 chars=465448`、`mount 465448 chars`（原 465,438 + 10，零丢失）；热日志单次写盘 110 ms（548 KB 文档），连续 4 笔输入合并为 4 次写盘；`DraftJournalTest` 5 条覆盖立即落盘 / 合并 / 回填 / 丢弃 /drop                       | 达标（剩余窗口仅为 "写盘进行中被杀"，且合并队列最多回退一个快照）              |
| 预览页首渲染（真机 548 千字符）               | S3 门槛 800 ms  | `preview ready 98 ms` → `480 ms`                                                                                                                                                                                                                                                                  | 达标                                              |
| 平板双栏（模拟器 1600×2560 / 320 dpi）    | —             | `split on auto=true`；面包屑「大文档 1MB ›」；465,438 字两侧同时渲染（`build/r18_tablet.png`）                                                                                                                                                                                                                       | 达标                                              |
| 界面布局（R17）                        | —             | 主页：hero + 主 / 次按钮 + 文字链 + 备份并排 + 最近列表（`md · 相对时间` + ×）（`build/u1.png`）；编辑器：6 图标栏 + 面包屑 + 10 项溢出菜单 + 查找条 + 大纲（`build/u2/u3/u4/u5.png`）；预览跳转 `PreviewActivity`（`u6.png`）；× 与长按菜单并存（`u11.png`）；release 包复测 `u8/u9/u10.png`                                                                           | 已对齐参考图                                          |
| R20 主页 / 设置页 / 清除记录（真机 0.7.2/14） | —             | 主页去掉备份并排、主题改 Sun/Moon 图标、表头 `clear`、行尾 × 只清记录（`build/r20_home.png`）；`clear` 后 6→5 + toast `build/r20_clear_one.png`；「全部文档」显示「・已清除记录」+「恢复」（`r20_all_docs2.png`）、恢复后回列表（`r20_restore.png`）；`clear` 全部后 `0 个文件` 且「查看全部文档（6）」保留（`r20_clear_all.png`）；全屏设置页 APPEARANCE/DATA 分组（`r20_dev_settings.png`） | 达标                                              |
| R20 A→关→B 内容不串（真机）               | —             | big-sample（`editor mount id=8964e953… 548245 chars`）→ × 关闭（`editor closed … chars=548245`）→ 郑居敬（`editor mount id=3d976200… 1268 chars`），界面与字数均为 B（`build/r20_ab.png`）                                                                                                                             | 达标                                              |
| R20 深色系统栏 + 图标                   | —             | 模拟器深色：状态栏 / 导航栏随主题转黑、图标转白（`build/r20_emu_home_dark.png`、`r20_emu_ed.png`）；真机复测同（`r20_dev_home.png`）；启动页 / 桌面图标为「白纸 + 蓝脊 + 铅笔」母题（首帧 `r20_emu_home.png`）                                                                                                                                            | 达标                                              |
| R21 缺陷①打开文件直开（真机 0.7.4）          | 点开即进编辑器       | SAF 选 Download/`chatgpt-qichen.md`（52.77 KB）→ `open 25405 chars db=23ms`、`editor ready in 140ms`、797 行直接进编辑器（`build/r21_open_result.png`）                                                                                                                                                         | 达标                                              |
| R21 缺陷②最近排序（真机）                  | 按最近打开排序       | 打开后 `chatgpt-qichen.md` 在「全部」视图置顶，其余按 3 分钟 / 1 小时前排（`build/r21_sorted.png`、`r21_sorted_all.png`）；表头「最近 / 全部」双态高亮                                                                                                                                                                                  | 达标                                              |
| R21 缺陷③预览不回顶（真机）                 | 静置位置不变        | 25,405 字预览下滚至「2. 武士神庙」→ 静置 20 s 位置完全一致、logcat 零重渲染（`build/r21_preview_scrolled.png` vs `r21_preview_after20s.png`）                                                                                                                                                                                | 达标                                              |
| R21 图标复刻（真机桌面）                   | 按图标设计.png     | 深藏青底 + 米白圆角卡 + 三行手写波浪（中行橙光晕）+ 右下橙光标条；真机桌面核验渲染                                                                                                                                                                                                                                                     | 已复刻（矢量近似）                                       |
| H2 编辑器进出内存回归（真机）                 | PSS 抖动 ≤30 MB | 10 轮 开→采→关→采：关闭态 162,320–163,919 KB、打开态 165,486–166,260 KB，抖动～2 MB、无累积增长（`android/tmp/h2_memlog.txt`）                                                                                                                                                                                             | 达标                                              |
| SAF 字节保真（真机 0.7.11）              | 往返字节一致        | GB18030 + CRLF 原始字节经 `gateway.open → save` 往返 SHA-256 `37785b57…` 一致；mode=ATOMIC\_RENAME                                                                                                                                                                                                          | 达标                                              |
| SAF 千文件枚举（真机）                    | 可枚举、截断策略与桌面一致 | 1000 文件目录（Download/saf1000，adb 预置）：`listTree total=400 ms=8229`（400 上限截断）                                                                                                                                                                                                                         | 达标                                              |
| SAF 断电无半截（真机）                    | 强杀后目标文件完整     | 7 轮不同延迟强杀（含打进写入序列样本）：`safPowerVerify` 全部 V1\_INTACT/V2\_INTACT、`tmpLeftover=0`、零 CORRUPT；换名为 FS 级原子 rename；OPPO provider `deleteDocument` 不可用 → 同目标第二次起保存退化 IN\_PLACE（已知限制，tmp 读回校验 + RecoveryManager 缓解）                                                                                         | 达标（含已知限制记录）                                     |
| H5 冷开基线（真机 0.7.11）               | 建立可对比基线       | `am start -W` COLD 三采样 TotalTime 480 / 492 / 467 ms，中位 480 ms                                                                                                                                                                                                                                     | 基线已建                                            |
| 单文件枚举授权崩溃修复（0.7.6）               | 非崩溃           | `documentTreeRoots()` 只返回 tree 型授权（此前混入单文件授权 → `fromTreeUri` 抛 `IllegalArgumentException`，导入备份路径可复现）                                                                                                                                                                                              | 已修复                                             |
| 冷启动首屏                            | 无门槛           | R15：启动即文档列表（`build/home6.png` / `final2.png`），此前被 panel 整屏遮盖不可见                                                                                                                                                                                                                                   | 已修正                                             |
| 列表项 → 编辑器（1 MB）                  | ≤1.5 s        | R15：`build/m2.png`，465,438 字 / 12,503 行，`editor total open=116ms`（WebView 预热态）；点项到可编辑含 `repository.get` 58 ms + `setDocument` 49 ms                                                                                                                                                               | 达标                                              |

## 5. P2 期间必须解决的事项

按「P1 挂账 / 阻塞 / 高优先 / 建议」四档分级。P1 挂账项不关闭不影响 P2 推进，但**必须在 P4 发布门禁前关闭**。

### 5.1 P1 挂账（设备条件不足，非代码缺陷）



| #  | 事项                    | 验收判据                          | 当前证据                                                                                            | 处置方向                                                                              |
| -- | --------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| B2 | 滚动 ≥55 fps            | 连续 fling 12 次，采样帧率中位数 ≥55 fps | **R18 真机实测（OPPO A56 5G）**：连续 fling 57 / 56 / 57 / 43（中位 56.5），高频短滑 48 / 36 / 49 / 39，idle 56–60 | **已通过（用户裁定 2026-11-19）**：以稳态中位 ≥55 为口径判定达标，**不再列为门槛**；极限连续拖动段（36–48）记录为已知特性，不单列处置 |
| B3 | 中文输入 5 分钟无丢字（IME 组合态） | 拼音候选窗切换、长拼音回改下 5 分钟零丢字        | 中文链路 50,076 字符零丢字（R12）；IME 组合态自动化无法驱动（ADBKeyboard 在 API 36 无效，已卸载）                              | **跳过（用户裁定 2026-11-19）**：不再作为门槛；若后续出现中文丢字投诉，按真机人工录屏 + 落库字数比对复测                     |

### 5.2 阻塞项（P2 内的功能缺口，逐条给出补法）



| #    | 事项                                             | 人日 | 判据                                | 现状                                                                                                                                                                                                                                                                                        |
| ---- | ---------------------------------------------- | -- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P2-1 | 命令面板（`Ctrl+Shift+I` 唤起，动作搜索）                   | 4  | 可检索全部编辑器动作并执行；`S4` 快捷键面同步实测       | **已关闭（R14）**：`EditorActions` 16 条动作单源下发，页内面板列出全部条目（`build/p2j.png`），点「文档大纲」执行成功（`build/p2k.png`）；检索为空格分词 AND（label/keywords/category 三字段），`EditorActionsTest` 8 条覆盖                                                                                                                       |
| P2-2 | 预览大纲面板 + 双向滚动同步                                | 5  | 大纲按标题层级生成，点击跳转；编辑↔预览滚动位置双向对齐      | **已关闭（R14 大纲 + R18 同步）**：`HeadingIndex` 解析 `#`–`######`（跳过围栏，≤500 条）；`ScrollSync` 以编辑器顶端行 ↔ 预览标题下标互推，两侧 900 ms 抑制窗防回弹；`PreviewActivity` 600 ms 轮询驱动，分屏与预览页共用。真机 548,166 字符预览 `ready 98/480 ms`，平板分屏首帧即对齐编辑器顶端标题。**反向链路由同一轮询覆盖，未逐条构造反向用例**                                                 |
| P2-3 | 设置页（字号 / 字体 / 行高 / 折行 / 主题跟随系统）                | 4  | 改动即时生效并持久化，重启后保持                  | **已关闭（R14）**：字号 15→23 / 行高 / 折行即时热应用（`build/p2o.png`），落盘 `shared_prefs/editor-prefs.xml`（`fontSize=23`），强杀重启后仍为 23（`build/p2q.png`）。字体族与「跟随系统主题」两项并入 P4 主题细化                                                                                                                              |
| P2-4 | 单文件「另存为」+ 分享入口                                 | 3  | SAF 另存不覆盖原文件；分享走 `ACTION_SEND` 文本 | **基本关闭（R14）**：另存弹 SAF（`build/p2t.png`，Downloads + 未命名.md + SAVE）、分享弹 chooser 且正文预览正确（`build/p2u.png`）；「同名重复另存不覆盖原文件」未逐次验证                                                                                                                                                                 |
| P2-5 | 保存 / 恢复验收实测（`SaveQueue`+`RecoveryManager`+ 镜像） | 5  | 断电式中断后重开无半截内容；末批输入不丢；镜像与库一致       | **已关闭（R19）**：新增 `DraftJournal`，输入即刻写 `recovery/<docId>.json`（单线程合并队列，110 ms / 548 KB），`RecoveryManager.recover()` 在 `journalRev > dbRev` 时回填并重写镜像与 note、再删日志，否则丢弃。实测 10 字符输入后 150 ms 强杀 → `recover restored journalRev=970 dbRev=966 chars=465448`、`mount 465448 chars`；5 条单测覆盖           |
| P2-6 | 查找替换「整批一步撤销」「仅选区」逐项验收                          | 2  | 20 处替换后一次撤销全部回退；仅选区模式不触碰选区外       | **已关闭（R18）**：页内 `selfCheckFind()` 断言 `replaced=3 / afterReplaceClean=true / undoRestored=true / selectionReplaced=1 / selectionOnly=true`。首轮 `undoRestored=false` 已定根为探针缺陷（同 tick 内两笔事务被历史合并），改 650 ms 分步后通过                                                                              |
| P2-7 | 跨端金标准语料对照                                      | 3  | 桌面版同一批语料在 Android 侧渲染结果一致（口径见下）   | **已关闭（R19）**：12 条语料（标题 / 行内 / 有序无序 / 表格 / 围栏 / 引用 / 链接图片分隔线 / 转义 / CJK / 软换行 /setext），桌面 Python-Markdown 3.10.2 与 Android markdown-it 各出「折叠纯文本 + 白名单标签计数」指纹，模拟器 `golden done ok=12/12`、`--compare` **12/12 一致**。口径说明：不比 HTML 字节（两侧引擎不同、codehilite 会多包 div/span），白名单刻意排除 span/div/br/class |

P2-1…P2-7 原合计 26 人日。R14 关闭 9，R18 关闭 P2-2（2）与 P2-6（2），R19 关闭 P2-5（3）与 P2-7（2），**剩余 0 人日**（P2-4 的「同名重复另存不覆盖」仍属未验项，不占人日）。Q1–Q5 属方案 §14 待决项，R18 已按拍板方向全部落地（不计入 M1 人日）。

### 5.3 高优先（P2 内并行）



| #  | 事项                                | 验收判据                                                     | 说明                                                                                                                                                                                          |
| -- | --------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1 | 路线 C 死代码清理                        | 构建 / 单测通过，无双内核残留                                         | **已关闭（R15 完成收尾）**：R13 删 `feature/editor/EditorController.kt`；R15 拆掉主页的路线 C 编辑器壳（工具栏 / 查找替换栏 / 标签胶囊 / 状态行 / 「编辑当前文档」按钮）与 `findOpenFlow`、`applyReplaceAll`，界面只剩「Compose 文档列表 + WebView 编辑器」两屏 |
| H2 | 编辑器进出与内存回归                        | 反复进出编辑器 10 次 PSS 抖动 ≤30 MB，`release()` 后同进程重建 WebView 正常 | **已关闭（R21）**：10 轮进出 PSS 关闭态 162–164 MB / 打开态 165.5–166.3 MB，抖动～2 MB 无累积增长；WebView 同进程重建由每轮开关编辑器链路覆盖（`android/tmp/h2_memlog.txt`）                                                            |
| H3 | `armeabi-v7a` 纳入 splits           | 明确纳入或排除并写入工程化文档                                          | **已决（R21，用户拍板「排除」）**：`splits.abi.include("arm64-v8a", "x86_64")`，结论已写入 `ANDROID_ENGINEERING.md`                                                                                             |
| H4 | CI 实际运行一次                         | 两 job 全绿且有产物                                             | **永久跳过（R21，用户拍板「不做 git 推送」）**：不再列为发布门槛                                                                                                                                                      |
| H5 | Baseline Profile / Macrobenchmark | 冷开耗时进 benchmark 基线                                       | **基线已建（R22）**：`am start -W` COLD 三采样 480 / 492 / 467 ms（中位 480 ms）为 0.7.11 基线；Macrobenchmark 工具链未建，随 H4 挂起                                                                                  |

### 5.4 建议项



| #  | 事项                                     | 说明                                                                                                |
| -- | -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| S1 | Q1–Q5 拍板（平板双栏、物理键盘一等、图片策略、HTML 脚本、云备份） | **已关闭（R18 落地）**：Q1 平板双栏、Q2 物理键盘快捷键、Q3 插图、Q4 净化口径、Q5 云备份均已实现，细节见 `ANDROID_OPEN_QUESTIONS.md`       |
| S2 | SAF S2 三项实测（千文件枚举、字节保真、断电无半截）          | 需人工授权目录树，归 P3                                                                                     |
| S3 | 预览页首渲染 800 ms 与内存回落                    | **首渲染已达标（R18）**：真机 548 千字符 `preview ready 98 / 480 ms`；内存回落仍待 H2 一并测                              |
| S4 | 更多快捷键映射实测（Ctrl+Tab、Ctrl+Shift+P）       | 归 P2-1 同批                                                                                         |
| S5 | 文档版本号一致性脚本化                            | 已关闭（R24）：设置页版本号改 PackageManager 动态读取，消除硬编码漂移；构建脚本版本号提为唯一来源 `appVersionName/appVersionCode`                                                                                           |
| S6 | `PreviewActivity` 工具栏与编辑器归一（R17 遗留不一致） | **已关闭（R18）**：改为「BACK / 标题 / 日夜间 / PDF / 关闭」图标栏（`PanelIconView` Canvas 自绘），`build/r18_preview.png` |
| S7 | 页内代码块「Copy」按钮、`My folders` 页、编辑器/预览切换文档按钮 | **R33 三项全部落地**：T1 切换文档按钮（R33 起改为弹出式列表，v0.7.23）、T2 代码块 Copy（v0.7.21）、T3 My folders 页（v0.7.22）均已交付（见 R31/R32/R33）。R35（v0.7.24）将长按菜单与 WebDAV 对话框视觉统一为 App 深色卡片风格（无功能增删）。Q6–Q9 已按建议拍板（见 OPEN_QUESTIONS） |

### 5.5 进入 P3 前必须关闭的清单（按阻塞强度排序）



| 序  | 事项                                           | 归属       | 关闭判据                                                                                                                                   |
| -- | -------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | P2-2 预览↔编辑器双向滚动同步                            | P2 余项    | **已关闭（R18）**：`HeadingIndex` + `ScrollSync` 600 ms 轮询双向对齐，分屏首帧对齐                                                                        |
| 2  | P2-5 保存 / 恢复中断实测                             | P2 余项    | **已关闭（R19）**：`DraftJournal` + `RecoveryManager` 回填，末批输入零丢失（journalRev 970 /dbRev 966 / 465,448 字符）                                     |
| 3  | P2-6 查找替换两项验收                                | P2 余项    | **已关闭（R18）**：自检 5 项断言全 true                                                                                                            |
| 4  | P2-7 跨端金标准语料对照                               | P2 余项    | **已关闭（R19）**：12 条语料指纹比对 12/12 一致，口径差异（HTML 字节 vs 文本 + 标签计数）已写明                                                                         |
| 5  | B2 滚动帧率真机判定                                  | P1 挂账    | **已通过（用户裁定）**：稳态中位 56.5 ≥55，不再列为门槛                                                                                                     |
| 6  | B3 中文 IME 5 分钟真机                             | P1 挂账    | **跳过（用户裁定）**：自动化无法驱动组合态，不再列为门槛                                                                                                         |
| 7  | Q1–Q5 拍板                                     | 用户决策     | **已关闭（R18 落地 / R19 Q5 实测通过）**：Q5 云备份端到端 201/279,569 B/16 notes 全通过；Q2 物理键盘按用户决定跳过                                                      |
| 8  | H3 `armeabi-v7a` splits 决策                   | 工程       | **已关闭（R21）**：用户拍板「排除」，`splits.abi.include("arm64-v8a","x86_64")`，已写入 `ANDROID_ENGINEERING.md`                                           |
| 9  | H4 CI 实跑                                     | 工程       | **永久跳过（R21，用户拍板「不做 git 推送」）**：不再列为门槛                                                                                                   |
| 10 | S3 预览首渲染 800 ms 与内存回落                        | P2/P4 交界 | **已关闭**：首渲染 98/480 ms（R18）；内存回落 H2 回归 10 轮无累积（R21）                                                                                    |
| 11 | H2 编辑器进出内存回归                                 | P2 高优先   | **已关闭（R21）**：10 轮 PSS 抖动 ~2 MB，无累积增长                                                                                                   |
| 12 | H5 Baseline Profile / Macrobenchmark         | P3/P4 工程 | **基线已建（R22）**：`am start -W` COLD 中位 480 ms；Macrobenchmark 工具链随 H4 挂起                                                                    |
| 13 | R20 设置页只做「现有能力 + 参考图分组样式」                    | R20 遗留   | **已关闭（R21）**：用户拍板「补齐」——AMOLED、字体三段、编辑/阅读字号、Full-screen reading、PDF 深色导出、FEEDBACK 两行已落地（Language 未做：单语言应用无切换语义，已按「不做」口径记录）；结论见 `ANDROID_OPEN_QUESTIONS.md` |
| 14 | R20 `documents.recent_hidden` 与桌面版 schema 差异 | R20 遗留   | **已关闭（R21）**：Android 自持 `recent_hidden` + `opened_at`（schema v5），导出 zip 不含该两列 → 桌面忽略；已在 `ANDROID_IMPLEMENTATION.md` 记录                  |
| 15 | R20 图标「逐像素一致」口径                              | R20 遗留   | **已关闭（R21）**：用户拍板「按 `图标设计.png` 复刻」——已按参考图重绘（矢量近似，波浪笔迹以 stroke 路径近似），真机桌面核验；1:1 像素级一致未要求                                        |
| 16 | R20「清除记录」的可达性复核                              | R20 遗留   | **已关闭（R21）**：表头改为常驻「最近 / 全部」双态切换（拍板「按建议」），找回入口常驻可达；真机实测切换正常                                                              |

### 5.6 进入 P4（发布门禁）前需要解决的事项（R22 收敛后的余量清单）

| 序 | 事项 | 来源 | 关闭判据 / 现状 |
| -- | --- | --- | --- |
| 1 | P2-4「同名重复另存不覆盖原文件」逐次验证 | P2 未验项 | 另存到同名 SAF 目标至少一次实测「原文件不覆盖、生成副本名」；本轮原子换名改动后需连带回归「另存为 → 再次另存 → 打开验证」 |
| 2 | SAF `deleteDocument` 不可用的产品化决策 | R22 已知限制 | OPPO externalstorage provider 删除被拒：同目标第二次保存退化 IN_PLACE + `.old` 残留。决策项：接受并写入用户文档（现状），或对「另存为已有文件」先 rename 原目标为时间戳备份再走原子换名 |
| 3 | 仪器测试（androidTest）补齐 | P4 门禁 | **已关闭（R26）**：新增 `PersistenceSmokeTest`（启动 + 打开 + 落盘）+ 重写 `EditorUiSmokeTest` 三条，模拟器 4/4 全通过；运行 `:app:connectedDebugAndroidTest` |
| 4 | H4 CI（用户拍板永久跳过） | 工程 | 不做 git 推送，CI 不建；发布门禁以本地 `testDebugUnitTest + lintRelease + assembleRelease + verifyReleaseBudget` 全绿为准 |
| 5 | Macrobenchmark 工具链 | H5 余量 | 本地 `am start -W` 基线已建（中位 480 ms）；是否引入 benchmark 模块由发布前决定，不阻塞 |
| 6 | `editor page ready` 冷启 65 s 现象 | 观察项 | 首次安装后首个冷启 WebView bundle 加载 65 s（仅一次），后续冷启 0.4–1.6 s；结论为「解压/校验一次性开销」，下一轮若复现再优化（资产预解压或 zip 对齐） |

## 6. 更新规则



1. 每轮任务结束：追加 §3 一行（轮次、交付、阶段、进度 %），同步 §2 子项状态与 §5 阻塞项是否关闭。

2. 进度百分比口径：P1 用 40+40+20 三分段（工程与内核 40 / 硬门槛 40 / 测试与文档 20，仅达标计分）；P2 起改用**人日加权**—— 按方案 §9.2 的 11 条 M1 任务线人日权重，任务线按 100% / 95% / 85% / 80% / 70% / 60% / 0% 取值，公式为 Σ(人日 × 取值) / Σ 人日。**分母取十一条任务线权重之和 86**（方案 §9 正文写作 84，与表内 3+6+9+12+8+9+10+10+7+4+8=86 有 2 人日口径差，本文一律以表内权重求和为准）。当前 99% = Σ(3×1 + 6×1 + 9×1 + 12×1 + 8×1 + 9×1 + 10×0.95 + 10×1 + 7×0.95 + 4×1 + 8×1) = 85.15 / 86。

3. 阶段切换必须同时改 §1 的出口判定依据与本文标题下的「最近更新」。

4. **每轮必须出包（R16 起）**：任何代码改动的轮次，交付时必须同时给出 `gradle :app:assembleRelease` 产出的两个 ABI 包路径与体积；只跑 `assembleDebug` 视为未交付。理由：真机安装的是 release 包，debug 包只用于模拟器回归；此前 release 包停在 0.6.0，导致 "改了代码但真机界面没变"。

5. 数字只写实测值，未测写「未测」，不以估算替代。

---

## 7. 移植方案存档（原 ANDROID_PORT_PLAN.md v1.0，R23 合并清洗并入）

> 原独立方案文档已并入本节并删除；被其他文档覆盖的内容不再重复（风险 → `ANDROID_RISK_REGISTER.md`、不可移植映射 → `ANDROID_FEATURE_MATRIX.md`、待决项 → `ANDROID_OPEN_QUESTIONS.md`、Spike 实测 → `ANDROID_SPIKE_REPORT.md`、工程化与发布 → `ANDROID_ENGINEERING.md`）。实现细节与接口签名见 `ANDROID_IMPLEMENTATION.md`。

| 项目 | 内容 |
| --- | --- |
| 编制日期 | 2026-11-18 |
| 源项目基线 | Gscratchpad 1.14.3（`src/scratchpad/`，23 模块 9,549 行） |
| 目标平台 | Android 8.0（API 26）及以上，手机 / 平板 / 折叠屏 |
| 方案结论 | 原定路线 C（Kotlin + Compose 原生）为主线、路线 D 为编辑器备选；**S1 不达标后已切路线 D（CodeMirror 6 in WebView），自 0.5.0 起生效** |

### 7.1 目标与范围

- 目标：与桌面版数据兼容、行为一致的本地即时记事本——零操作持久化（300 ms 防抖 + 单写线程 + journal）、多标签会话恢复、源码编辑 + Markdown 预览（KaTeX/Mermaid 全离线）、笔记库管理与文件互通、纯本地零联网。
- v1 核心：笔记库（SQLite 同构）、多标签、编辑（高亮/行号/撤销/折叠）、自动保存、预览、查找替换、主题、单文件读写。v2 全功能：侧栏视图、目录搜索、批量替换、片段、列编辑、简繁、PDF、capture、桌面导入、维护。
- 不做：`$HOME` 真实磁盘树语义、D-Bus、CLI 子命令、WeasyPrint、`black`/`ruff`/`shfmt`、Nautilus 集成、全局 Ctrl 快捷键作为主交互路径（完整映射见 `ANDROID_FEATURE_MATRIX.md`）。
- 非目标：不追求与桌面版像素级一致界面；不在 Android 上运行 GTK/PyGObject；不为 iOS 预留抽象层。

### 7.2 可行性基线（S0 时点）

| 维度 | 事实 |
| --- | --- |
| 代码规模 | 9,549 行 / 23 模块；UI 耦合约 6,700 行（70%）绑 GTK4/Adw/GtkSourceView/WebKitGTK，必须重写 |
| 纯逻辑 | 2,734 行（store 992、fssearch 388、markdown_render 390、snippets 329、formatter 189、outline 128、columnedit 122、escapecodec 64、assets 66、paths 66），可 1:1 语义转写 |
| 测试 / 资产 | 桌面测试 33 文件 5,167 行转金标准语料；`vendor/` 5.4 MB（Mermaid 10.9.1、KaTeX 0.16.11、markdown-it 14）在 WebView 内直接复用 |
| 原栈直搬否决 | GTK Android 后端无 GL 渲染器；PyGObject/GtkSourceView 无 Android 产物；WebKitGTK 无解（Android 仅系统 WebView）；D-Bus/XDG/`$HOME`/单实例设施不存在 |

### 7.3 路线决策

| 路线 | 形态 | 工作量 | 决策 |
| --- | --- | --- | --- |
| A 原栈直搬 | GTK Android 后端 + PyGObject | 不可行 | 否决 |
| B Termux + proot + X11 | 容器内跑现有 DEB | 0.3–0.5 人月 | 仅技术演示，产品化不成立 |
| C Kotlin + Compose 原生 | UI 重写，逻辑转写 | 核心 4.6 / 全功能 12.3 人月 | 原定主线；S1 后编辑器层被 D 取代 |
| **D Kotlin 壳 + WebView/CodeMirror 6** | 编辑器与渲染在 WebView 内 | 核心 3.5 / 全功能 9 人月 | **采纳（现行）** |
| E Flutter / CMP | 跨端重写 | 核心 5 / 全功能 11 人月 | 无跨端需求，不采纳 |
| F Chaquopy 保留 Python 逻辑 | 原生 UI + Python 数据层 | 核心 6 / 全功能 13 人月 | 不采纳：运行时收益被集成成本抵消；`os.walk` 在 SAF 下不成立；写线程需重编排 |

### 7.4 架构决策记录（ADR）

| ADR | 决策 | 理由 / 现状 |
| --- | --- | --- |
| ADR-01 | 数据层用原始 SQLite + `SQLiteOpenHelper`，不用 Room | 桌面 schema 需 1:1 保留（现为 Android 自持 v5） |
| ADR-02 | 预览用系统 WebView + `WebViewAssetLoader` | 复用 KaTeX/Mermaid 资产 |
| ADR-03 | PDF 用 `WebView.createPrintDocumentAdapter` | 真分页矢量输出，替代 WeasyPrint |
| ADR-04 | ~~编辑器首选 Sora Editor~~ | **已被路线 D 取代：CodeMirror 6 in WebView** |
| ADR-05 | 折叠保留「全文落盘」不变量，实现用区间装饰 | 落地于 CodeMirror 6 折叠扩展 |
| ADR-06 | 相对图片引用改为应用私有 `assets/<docId>/` + SHA-256 去重 | SAF 无稳定路径语义 |
| ADR-07 | 简繁转换引入 OpenCC JNI | 未接入（M2 余量，见 FEATURE_MATRIX 第 4 项） |

### 7.5 架构与模块映射

分层：`ui/feature（Compose）→ domain（纯 Kotlin 可单测）→ data（SQLite/journal/notes/assets）`，`platform`（SAF FileGateway、PreviewHost、PdfExporter、CaptureReceiver）横切。包结构以 `ANDROID_IMPLEMENTATION.md` 现状为准。

| 源模块 | 行数 | Android 落点 | 处理 |
| --- | --- | --- | --- |
| `application.py` | 262 | `GscratchpadApp` + `MainActivity` + capture | 重写 |
| `window.py` | 2,149 | `MainScreen` + 标签/保存/命令注册（拆 4 模块） | 重写并拆分 |
| `editor.py` | 796 | 编辑器（路线 D：CodeMirror 6 宿主） | 重写 |
| `folding.py` | 348 | `FoldModel` + 折叠扩展 | 重写，保留全文落盘不变量 |
| `sidebar.py` / `fssearch_ui.py` / `snippets_ui.py` | 1,166 / 687 / 316 | 设置页 / 查找替换 / 片段（按 Android 交互收敛） | 重写 |
| `command_menu.py` | 230 | 命令面板 | 重写 |
| `preview.py` / `pdfexport.py` | 211 / 281 | `PreviewHost` + `PdfExporter` | 重写 |
| `capture.py` | 311 | `CaptureContract` + 校验 | 部分转写 |
| `store.py` | 992 | `DbHelper` + DAO + `SaveQueue` + `RecoveryManager` | 转写 |
| `fssearch.py` | 388 | Scanner/Plan/Applier/Encoding | 转写（`os.walk` → SAF） |
| `markdown_render.py` | 390 | `render/render.js` | 转写为 JS |
| `snippets.py` / `outline.py` / `columnedit.py` / `escapecodec.py` / `assets.py` | 329 / 128 / 122 / 64 / 66 | domain 纯逻辑 | 1:1 转写 |
| `paths.py` / `keymap.py` | 66 / 56 | 应用私有目录 / 快捷键映射（§7.9） | 重写 |

### 7.6 契约与不变量

**Capture 契约**：Action `io.github.gscratchpad.CAPTURE`；入口显式 Intent 或 `ACTION_SEND`（text/plain）；extras `text/title/book/page/key/mode`（create/append，缺省 append）；校验与桌面 `capture.py` 逐条一致（UTF-8、禁 NUL、≤1 MB、key ≤256 无空白、title ≤200）；校验失败 `RESULT_FIRST_USER`；同 key 幂等、append 永不覆盖；后台落盘不建界面。追加块格式保持「`---` + `> 《书名》 · 章节 · 页 · 时间`」不变。

**语义不变量（测试契约）**：

| 编号 | 不变量 | 验收方式 |
| --- | --- | --- |
| I1 | 落盘内容恒为全文，折叠不改内容 | 折叠后保存导出，与折叠前逐字节一致 |
| I2 | `revision` 单调递增，旧快照被丢弃 | 乱序提交 100 次库内 revision 单调 |
| I3 | 先写 journal 再提交，启动回填 | 强杀进程后内容为最新一次输入 |
| I4 | `notes/` 镜像原子替换 | 写入中断后镜像要么旧要么新 |
| I5 | 单写线程串行，UI 只读 | 并发 8 次保存无锁错误、顺序正确 |
| I6 | 关闭标签不删除文档 | 关闭后仍在「全部」可见 |
| I7 | capture 同 key 幂等、append 不覆盖 | 同 key 两次 create 得同一 doc_id |
| I8 | 批量替换保留编码/BOM/换行，先备份 | 替换前后字节级差异只在目标文本 |

### 7.7 数据迁移（桌面 → Android）

导入包 = `manifest.json` + `gscratchpad.db`（导出前 checkpoint TRUNCATE 只读快照）+ 可选 `notes/`、`assets/`。流程：解压校验（`manifest.schema` + `integrity_check` + 行数）→ `ATTACH` 事务写入（跳过窗口几何与 `fs_root`）→ `source_path` 路径转 URI（匹配已授权树按文件名映射，其余置空记报告）→ 图片统一复制进 `assets/<docId>/`（SHA-256 去重）并重写正文 → 迁移报告（成功/跳过/断链/失效）。冲突策略：同 id 取 `updated_at` 新者、另一份写 `conflict/<id>.md`；revision 冲突取大者；同名不同 id 全保留。

### 7.8 里程碑与工作量

M0 技术验证 14 人日 → M1 核心版 86 人日（11 条任务线，权重即 §4 进度计分分母）→ M2 全功能 91 人日 → M3 打磨与上架 55 人日，合计 244 人日 + 10% 缓冲 ≈ 268 人日 ≈ 12.3 人月。S1–S4 量化门槛与实测结论见 `ANDROID_SPIKE_REPORT.md`。

### 7.9 快捷键映射（物理键盘）

| 桌面 | Android | 触屏入口 |
| --- | --- | --- |
| Ctrl+N / Ctrl+W / Ctrl+Tab | 同左 | 标签栏「＋」/ 长按菜单 / 滑动 |
| Ctrl+F / Ctrl+H / Ctrl+Shift+F / Ctrl+Shift+H | 同左 | 顶栏放大镜 / 选区菜单 / 目录工具 |
| Ctrl+K / Ctrl+Shift+P / Ctrl+Shift+I | 同左 | 命令按钮 / 预览切换 / 工具菜单 |
| F2 重命名 / F9 侧栏 / Ctrl+Shift+E 片段 | 同左 | 长按菜单 / 侧栏按钮 / 设置 |

### 7.10 依赖替换对照

| 桌面依赖 | Android 替代 | 备注 |
| --- | --- | --- |
| GTK4 + libadwaita | Compose + Material 3 | 视觉按 Adwaita 配色重绘 |
| GtkSourceView 5 | ~~Sora Editor~~ → CodeMirror 6 | 路线 D |
| WebKitGTK 6.0 | 系统 WebView + AssetLoader | 本地资源虚拟主机 |
| PyGObject | 不适用 | 无 Python 运行时 |
| Pygments / python-markdown | highlight.js / markdown-it | 净化与占位规则照搬 |
| weasyprint / opencc 子进程 | PrintDocumentAdapter / OpenCC JNI | 后者未接入 |
| sqlite3 (Python) | `SQLiteOpenHelper` | 同 DDL、同 WAL |
| Mermaid 10.9.1 / KaTeX 0.16.11 | 同版本资产直接复用 | `assets/vendor/` |

