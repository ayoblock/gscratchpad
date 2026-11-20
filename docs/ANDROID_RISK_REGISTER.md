# Android 移植风险登记（方案 §10 落地）

登记口径：风险条目、触发信号、影响、应对取自移植方案 §10（方案已并入 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §7 存档）；「当前状态」列只写已实测或已在测试中闭合的证据，未验证的写「未触发/未验证」，不写推测。

| ID | 风险 | 触发信号 | 影响 | 应对 | 当前状态（实测证据） |
|---|---|---|---|---|---|
| R1 | 编辑器折叠与大文档性能不达标 | S1 折叠 >200 ms 或滚动掉帧 >20% | M1 返工，工期 +4–6 周 | 先 Spike 验证；不达标切 CodeMirror 6；折叠降级为区间装饰 | **已触发**。`ANDROID_SPIKE_REPORT.md` §1：`spike-big.png` 979,960 字打开时 Compose 单 `BasicTextField` 布局阻塞 26,737 ms 并 ANR；滚动 197 帧中 101 帧卡顿（51.27%），50th 48 ms。DB 读取侧 29–30 ms 正常。折叠区间计算本体无性能问题（`FoldModel` 纯字符串扫描，1 MB 文本毫秒级）。出路为 Sora Editor 或 CodeMirror 6 |
| R2 | SAF 目录枚举与遍历过慢 | 1,000 文件 >8 s | 目录搜索/批量替换不可用 | 后台索引缓存 + 深度与数量上限 + 流式返回 | **未触发**。S2 三项（千文件枚举、字节保真、断电无半截）需人工授权 SAF 目录树，尚未执行。SAF 写回路径 `SafFileGateway` 原子替换逻辑已被单测覆盖 |
| R3 | 中文输入法合成与撤销栈冲突 | 连续输入出现丢字、重复字 | 核心体验受损 | 按 `InputConnection` 规范实现；真机矩阵必测；保留原生 EditText 兜底 | **未验证**。S1「折叠与中文输入」未测；`EditorUiSmokeTest` 只覆盖 ASCII 输入。迁移进入 View 体系编辑器后需重测 |
| R4 | WebView 内存回收不可控 | 多标签切换后 RSS 持续上涨 | 中低端机 OOM | 单活跃预览 + 立即 `destroy()` + HTML 缓存；预览默认关闭 | **已触发**。S3 实测 PSS 74,935 KB → 138,341 KB → 152,018 KB，返回后不回落。当前已用独立 `PreviewActivity` + `onDestroy` 里 `host?.release()` 收口，但「回收是否生效」尚无以 PSS 为口径的复测 |
| R5 | 相对图片引用语义丢失 | 导入后图片显示空白 | 迁移用户数据受损 | 导入时重写为私有 assets URL；迁移报告列出断链项 | **已在测试中闭合**。`DesktopBackupContractTest` 断言：图片引用重写进私有 `assets/` 且引用可解析；`source_path` 置空、`deadPaths=1` 进报告 |
| R6 | 导入中断导致库损坏 | 导入进程被杀 | 笔记丢失 | 先写临时库 + 事务 + `integrity_check`，成功后原子替换 | **已在测试中闭合（逻辑层）**。`DesktopBackupContractTest`：schema 不匹配时不动目标库；zip-slip 路径被拒绝；`verified` 报告与 0 errors。进程被杀的中断点未做断电实测 |
| R7 | 桌面版继续演进造成双端漂移 | 桌面新增 schema 变更 | 导入失败、行为分叉 | schema 版本 + 金标准语料为契约；schema 变更双端同步评审 | **已在测试中闭合（当前 v3）**。契约测试按 §6.1 格式现场构造备份包（`manifest.json` + `gscratchpad.db` + `assets/pic.png`），5 篇文档覆盖 markdown/txt/html/带图/空文档、两个文件夹、closed 状态、窗口几何 meta；断言 5/5 导入、标题/revision/文件夹/正文 SHA-256 一致、`sort_index` 顺序保留、`window_w` 未导入、`view_mode` 保留 |
| R8 | 编辑器第三方库停止维护 | Sora Editor 12 个月无提交 | 后续维护困难 | 锁定版本；折叠/查找等核心能力不依赖该库私有 API | **监控中**。核心能力（折叠 `FoldModel`、查找替换 `TextSearch`）已在 domain 层独立实现，不依赖编辑器库私有 API；`FoldModel`/`TextSearch` 覆盖分别 94.4%/96.9% |
| R9 | 格式化能力回归 | 用户依赖 Python/Bash 排版 | 功能缺失投诉 | v1 范围外声明；后续接格式化服务或内置简化实现 | **已知缺口**。Android 端无格式化入口；v1 范围外 |
| R10 | 商店政策与 targetSdk 要求变化 | Play 提高 targetSdk 门槛 | 上架延期 | M3 预留 4 人日升级窗口；CI 每季度检查政策 | **已触发（低等级）**。当前 `targetSdk=36`，`lint` 报 `OldTargetApi`（最新为 37）；compileSdk 37 与 compose-bom 2026.x 本机不可得，已在 `app/lint.xml` 显式忽略并记录原因 |

---

## 风险与测试层的对应

| 层级（§11） | 覆盖的风险 | 当前实测结果 |
|---|---|---|
| 单元（JUnit，JVM） | R5、R6、R7、R8、R9 的逻辑面 | 53 条全绿；domain 行覆盖 243/271 = 89.7%（fold 94.4%、search 96.9%、model 71.4%） |
| 契约（备份包 → 导入 → 断言） | R5、R6、R7 | 5 条全绿，0 静默丢失 |
| UI（Compose UI Test） | R1、R3、R4 的界面面 | `EditorUiSmokeTest` 3/3 通过（29.189 s（首轮 15.869 s））：新建标签不崩溃、工具栏可见、查找栏展开并显示替换动作 |
| 性能（Macrobenchmark/Perfetto） | R1、R4 | 未执行；现数据来自 Spike 阶段手工测量（见 `ANDROID_SPIKE_REPORT.md`） |
| 输入法矩阵 | R3 | 未执行 |
| 兼容矩阵（API 26/29/31/34/36、四厂商） | R1、R4、R10 | 仅 API 36 模拟器（Pixel_API36，x86_64）验证 |

---

## 结论

| 风险 | 判定 |
|---|---|
| R1 | **已闭合（S3，路线 D）**：CodeMirror 6 内核落地，打开 1 MB / 滚动 / IME / 折叠真机与单测全过（详见 `ANDROID_STAGE_STATUS.md` §3） |
| R4 | 已触发，PSS 不回落。独立 Activity 只解决覆盖问题，不解决回收；H2 内存回归（R22）实测 10 轮抖动 ~2 MB 无累积，观察项 |
| R5 / R6 / R7 | 当前 schema 与备份格式下已由契约测试闭合，0 静默丢失 |
| R2 / R3 | **已闭合（R21–R22）**：SAF 目录树授权与千文件枚举真机实测通过；中文 IME 合成态为真机矩阵项（用户裁定跳过，见 `ANDROID_OPEN_QUESTIONS.md`） |
| R8 / R9 / R10 | 已记录为可接受或范围外，带处置条件 |
