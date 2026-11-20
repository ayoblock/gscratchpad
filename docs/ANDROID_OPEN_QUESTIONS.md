# Android 待决项（§14 Q1–Q5）

版本：0.8.2（versionCode 45）。日期：2026-11-20。R24–R44 各轮改动均不改变 Q1–Q10 的拍板结论。**逐轮变更史以 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §5.4 为唯一权威记录**，本文不重复维护流水账。
来源表：移植方案 §14 待决项（方案已并入 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §7 存档）。

**结论：Q1–Q5 均已拍板并在 0.7.0 按所选方向落地**（用户指令「Q1–Q5 全部实现」）。下表保留原始「现状依据 / 建议 / 影响」，并在「落地状态」列写明实现口径与实测证据。

## Q1 是否在 v1 提供平板双栏

| 维度 | 内容 |
|---|---|
| 现状依据（v1 前） | 标签栏、编辑区、预览均为单栏；空 Activity 只有一个 WebView 承载全部内容 |
| 建议（v1 前） | v1 单栏 + 侧栏浮层；M3 再加双栏 |
| 影响（v1 前） | 双栏需新增 side-by-side 容器与两套 WebView 生命周期；估算 +12 人日 |
| 拍板 | 与平板双栏同屏（编辑器 + 预览）|
| 落地状态 | **已实现（0.7.0）**：`MainActivity` 增 `panelContainer` 横向容器 + `setSplit(on, auto)`，`smallestScreenWidthDp ≥ 600` 自动开启；600 ms 协程轮询驱动预览滚动跟随，800 ms 节流重渲染。模拟器 1600×2560 / 320 dpi 实测 `split on auto=true`、面包屑「大文档1MB ›」、465,438 字两侧同时渲染（`build/r18_tablet.png`）。真机 360 dp 手工开启可用但面包屑被挤空（窄屏列宽限制，平板不受影响） |

## Q2 物理键盘是否作为一等交互

| 维度 | 内容 |
|---|---|
| 现状依据（v1 前） | `dispatchKeyEvent` + `Shortcuts` 已保留 Ctrl+N/W/F/H/K、F2、F9；页内另有 `onJsShortcut` |
| 建议（v1 前） | 保留映射，不作为主路径 |
| 影响（v1 前） | 作为一等交互需键位冲突矩阵、焦点抢占与 IME 组合态处理 |
| 拍板 | 作为一等交互 |
| 落地状态 | **代码已实现（0.7.0）**：`Shortcuts` 扩到 15 个 `KeyAction`（新增 SAVE / SAVE_AS / OPEN / TOGGLE_SPLIT / HELP / IMAGE / RENAME），新增 `resolvePlain()`（F1 / F2 / F9）；页内 keymap 同步 `Mod-s / Mod-Shift-s / Mod-o / Mod-d / Mod-i / Mod-Shift-/` 与 `F1 / F2 / F9`；新增 `#help` 快捷键面板（14 条）。**按用户裁定跳过（R19）**：无外接键盘可用，键码路径不再作为验收门槛；代码保留，接上键盘即生效 |

## Q3 图片是否允许留在 SAF 原目录

| 维度 | 内容 |
|---|---|
| 现状依据（v1 前） | 私有 `files/assets/<docId>/` 与 SHA-256 去重已实现；编辑器无图片插入入口 |
| 建议（v1 前） | 统一复制进私有 `assets/`，正文改写为相对路径 |
| 影响（v1 前） | 原目录引用会引入 R5 风险（授权撤销即失效、跨设备不可移植） |
| 拍板 | 一律复制进私有目录，不引用外部 URI |
| 落地状态 | **已实现（0.7.0）**：`importImage()` → `AssetStore.importBytes` 落 `files/assets/<docId>/<sha12>.<ext>` → 正文插入 `![](assets/<docId>/<file>)`。真机实测 `image imported assets/8964e953…/70e94f462164.png (197947 B)`，文档 548,180 → 548,243 字符，分屏预览渲染正确 |

## Q4 是否保留 HTML 完整格式（含用户脚本）

| 维度 | 内容 |
|---|---|
| 现状依据（v1 前） | 预览链路 markdown-it + 净化规则照搬桌面版；JS 桥仅暴露 `onReady` / `onChange` / `onMetric` / `onShortcut` / `onAction` |
| 建议（v1 前） | 预览按现规则净化，导出不执行脚本 |
| 影响（v1 前） | 放开用户脚本与 JS 桥共存会扩大攻击面 |
| 拍板 | 预览与 PDF 均不执行用户脚本 |
| 落地状态 | **已实现（0.7.0）**：`securityLevel:'strict'` + `html:false` 保持；新增的图片资产走 `WebViewAssetLoader` 专用路径（相对 `assets/…` 改写为 `/assets/…`），并由渲染层剔除 `javascript:` / `data:` 等非法协议 `src` |

## Q5 是否接入应用内备份到云盘

| 维度 | 内容 |
|---|---|
| 现状依据（v1 前） | `BackupExporter` 只做「私有目录打包 + SAF 手动导出」；无网络权限、无账号体系 |
| 建议（v1 前） | v2 后按需，v1 走 SAF 手动导出 |
| 影响（v1 前） | 接云盘需网络权限、账号、增量同步与冲突合并，估算 +15 人日 |
| 拍板 | 接入（WebDAV 通用协议，不绑定具体厂商） |
| 落地状态 | **端到端实测通过（R19）**：`CloudBackup`（PUT / HEAD / GET + Basic auth，12 s / 30 s 超时）、`showCloudDialog()`（URL / 账号 / 密码 + 保存配置 / 上传 / 从云端恢复）、`buildBackupZip()` 复用 `BackupExporter`；清单新增 `INTERNET` 权限与 `usesCleartextTraffic="true"`。实测服务器 `http://<LAN-IP>:5244/dav/backups`（Alist，`admin/123456`）：上传 `HTTP 201 Created`、HEAD `279,569 B`、GET 回读 `279,569 B`、zip 条目 `manifest.json` + `gscratchpad.db` + 16 个 `notes/*.md`，`hasDb / hasManifest / sizeMatch / ok` 全 true。前提两条：① Android 9+ 默认拦明文 http，需 `usesCleartextTraffic`；② Alist 的 `/dav` 是聚合虚拟根，PUT 返回 404，URL 必须指向真实子目录 |

## 汇总

| ID | 待决 | 拍板 | 落地状态 |
|---|---|---|---|
| Q1 | v1 平板双栏 | 双栏同屏 | 已实现并实测（平板模拟器） |
| Q2 | 物理键盘一等交互 | 作为一等交互 | 代码完成（0.7.0），按用户裁定跳过实测（无外接键盘） |
| Q3 | 图片是否留在 SAF 原目录 | 一律复制进私有目录 | 已实现并实测（真机 197,947 B 插图） |
| Q4 | HTML 是否保留用户脚本 | 不执行用户脚本 | 已实现（strict + html:false + 非法协议剔除） |
| Q5 | 是否接云盘备份 | 接（WebDAV） | **端到端实测通过（R19）**：201 上传 / 279,569 B 回读 / 16 notes / sizeMatch=true |

## 由此产生的取舍记录

1. `INTERNET` 权限与 0.3.0 起「纯本地、不联网」的口径冲突：仅用于用户显式触发的 WebDAV 备份，其余路径不发起网络请求；已在 `AndroidManifest.xml` 注释写明。
2. 平板双栏复用同一个 `PreviewHost` 实现（新开预览 WebView 亦走 `renderMarkdown` 幂等短路），因此双栏不会引入第二套渲染管线。
3. 物理键盘动作（`SAVE_AS` / `OPEN`）在页内与宿主各有一份入口，动作 id 以 Kotlin `EditorActions` 为唯一真源，避免 R17 的 `snippet`/`snippets` 类不匹配再次出现。
4. R20「清除记录」：本工程文档 = DB 行 + `notes/<id>.md` 镜像，删行即真丢内容，所以「×」与 `clear` 只写可见性标记 `documents.recent_hidden`（schema 3→4），删除仍只在长按菜单；导出 zip 不含该列，桌面版导入时按 0 处理（即全部视为「最近可见」），跨端不引入新字段语义。
5. R20 设置页：参考图 `Screenshot_20261119_175253_com.pilcrowmd.jpg` 中的 AMOLED、Language、PDF colors、字体三段、Full-screen reading、FEEDBACK 两行**未实现**，本轮只复刻分组卡片 + 分段按钮 + Slider + Switch 的版式；是否补齐留作进入 P3 前的决策项（见 `ANDROID_STAGE_STATUS.md` §5.5 第 13 条）。
6. R20 应用图标：按桌面版 SVG 的视觉母题重绘 vector（白纸 + 蓝脊 + 横线 + 38° 铅笔），**不承诺与 SVG 逐像素一致**；`icon` 与 `roundIcon` 指向同一 `@mipmap/ic_launcher`，未新增密度 PNG。

## R21/R22 补充拍板与结论（2026-11-19）

| # | 事项 | 拍板 | 结论 |
|---|---|---|---|
| 1 | R20 遗留九项 | 1 测 SAF 三项 / 2 设置页补齐 / 3 否（已闭环）/ 4 图标按 `图标设计.png` 复刻 / 5 表头双态按建议 / 6 测 H2 / 7 排除 armeabi-v7a / 8 不做 git 推送 / 9 测 H5 | 全部执行完毕：SAF 三项真机实测通过、设置页补齐落地（AMOLED/字体三段/阅读字号/全屏阅读/PDF 深色/FEEDBACK）、图标复刻并真机核验、H2 抖动 ~2 MB 通过、`armeabi-v7a` 已从 splits 排除、CI 永久跳过、H5 基线中位 480 ms |
| 2 | Language 行 | 单语言应用 | **不做**：应用无多语言切换语义，设置页不复刻该行 |
| 3 | 「打开文件」语义 | 导入副本进库并直开 | 已实现并实测：外部 SAF 文件以副本进库（保留 `sourcePath`）+ 直接进编辑器；「引用外部路径不复制」未采用 |
| 4 | SAF provider `deleteDocument` 不可用 | 接受 + 记录 | OPPO externalstorage provider 拒绝第三方删除（`Delete not supported`）：原子换名后 `.old` 清理失败仅留冗余备份；同目标第二次起保存退化 IN_PLACE，撕裂风险由 tmp 读回校验 + `RecoveryManager` 缓解；产品化备选（时间戳备份换名）留待发布前决策 |
| 5 | `editor page ready in 65685ms` | 观察项 | 仅首次安装后首个冷启出现（WebView bundle 一次性解压/校验），后续冷启 0.4–1.6 s；不复现则不优化 |
| 6 | H4 CI / git 推送 | 永久跳过 | 不再列为发布门槛；发布门禁以本地 `testDebugUnitTest + lintRelease + assembleRelease + verifyReleaseBudget` 全绿为准 |


## R29 立项决策项（2026-11-20，详见 `archive/ANDROID_TASK_CHARTER.md`（已归档，立项三项 T1/T2/T3 全部交付））

> 三项功能立项：T1 编辑器/预览内切换文档按钮、T2 代码块 Copy 按钮、T3 My folders 页。
> **2026-11-20 R31：用户拍板「Q6–Q9 按建议」，四项全部按建议执行**（同批指令开工 T1+T2）。

| # | 事项 | 建议 | 拍板 | 影响 |
|---|---|---|---|---|
| Q6 | T3 `renameFolder` 撞名策略 | 拒绝并提示（不静默合并），与桌面版语义对齐 | **按建议：拒绝并提示** | T3 需在 `FolderPolicy` 加冲突分支，Repository 返回失败而非合并 |
| Q7 | T3 文件夹视图是否显示「已清除记录」(recentHidden) 文档 | 不显示（与「最近」口径一致），或加开关 | **按建议：不显示** | 文件夹视图数据过滤 `!recentHidden`，与主页「最近」口径一致 |
| Q8 | T3 文档移入文件夹交互 | 长按菜单选目标文件夹（DnD 退化为菜单，真机已证 Panel 焦点干扰触摸） | **按建议：长按菜单** | T3 UI 用长按文档弹文件夹选择，不做拖拽 |
| Q9 | 出包批次 | T1+T2 合并一版、T3 独立一版 | **按建议：T1+T2 一版、T3 一版** | T1+T2 已合并出 v0.7.21；T3 已独立出 v0.7.22（Q6–Q8 均按建议落地） |

## R30 SAF 打开过滤器处置拍板（2026-11-20）

| # | 事项 | 方案 | 拍板 | 结论 |
|---|---|---|---|---|
| Q10 | 另存文件被 ROM 登记为 BIN 导致「打开文件」无法选中 | 甲：打开过滤器加入 application/octet-stream；乙：过滤器改全类型 + 扩展名白名单 | **用户选乙** | 已落地 `OpenPolicy`：全类型通配符 + md/markdown/html/htm/txt 白名单兜底；华为真机需用户实机确认 |
