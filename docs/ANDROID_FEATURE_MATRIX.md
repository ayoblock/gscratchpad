# Android 功能矩阵（§13 十项不可移植映射的落地状态）

版本：0.8.3（versionCode 46）。日期：2026-11-21。R24–R45 的界面打磨、SAF 链路修复、功能增量、视觉统一、所有文件访问验证、File 直读通道铺开与维护功能复刻均不改变 §13 十项映射的落地状态。**逐轮变更史以 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §5.4 为唯一权威记录**，本文不重复维护流水账。
来源表：移植方案 §13（已并入 [ANDROID_STAGE_STATUS.md](ANDROID_STAGE_STATUS.md) §7 存档）。证据列只写设备实测或单测可复核的事实。

| # | 桌面功能 | 处置 | 替代方案 | Android 现状 | 实测证据 | 缺口归属 |
|---|---|---|---|---|---|---|
| 1 | `$HOME` 真实磁盘树 | 放弃 | SAF 授权目录树（用户显式选择） | 已实现 `SafFileGateway`：目录树枚举、按 URI 读写、持久授权 | 单测 `DesktopBackupContractTest` 5 条通过；R22 真机 SAF 三项实测通过：千文件枚举（1000 项目录按 400 截断、8.2–8.9 s）、字节保真（GB18030+CRLF 往返 SHA 一致）、断电无半截（两步 `renameDocument` 原子换名、7 轮强杀零 CORRUPT） | S2 / M2 已闭合 |
| 2 | D-Bus `capture` + CLI 双通道 | 替换 | `io.github.gscratchpad.CAPTURE` Intent + `ACTION_SEND` | 已实现两种入口，`CaptureContract.ACTION` 与 `ACTION_SEND`(text/plain) 均落到新建文档 | 显式 SEND 实测送达：新建文档「分享内容」8 字；隐式 SEND 弹系统 Resolver（含 Gscratchpad / Bluetooth / Messaging） | 与桌面 CLI 的载荷等价性未覆盖，归 M2 |
| 3 | WeasyPrint 真分页 | 替换 | `PrintDocumentAdapter` | 已实现 `PdfExporter`，走系统打印对话框输出 PDF | 10,425 字符样本：`ISO A4`、`1/13`、导出 241,347 B；`pypdf` 抽取首页 850 字符；代码块与表格均不拆页 | 公式与图片在 PDF 中的表现未复测，归 M1 |
| 4 | `opencc` 子进程 | 替换 | OpenCC JNI | 未接入：简⇄繁转换入口与默认映射缺失 | 无运行时证据；`TextCodecTest` 6 条只覆盖编码探测与 BOM/CRLF | M2 |
| 5 | `black` / `ruff` / `shfmt` | 删除 | JSON/XML/HTML 内置排版保留；Python/Bash 排版不在范围 | 已按方案裁剪：Python/Bash 排版不出入口，JSON/XML/HTML 格式化保留 | 单测覆盖 JSON/XML/HTML 缩进与非法输入不抛异常 | 无（范围外，方案已声明） |
| 6 | Nautilus「用…打开」 | 替换 | `ACTION_VIEW` + `text/plain` / `text/markdown` 过滤器 | Manifest 已注册 VIEW 过滤器，外部文件管理器「用…打开」可用 | 过滤器声明在 `AndroidManifest.xml`；跨应用实测未执行 | 跨应用入口复测归 M2 |
| 7 | 单实例窗口唤醒 | 替换 | `launchMode="singleTask"` + `onNewIntent` | `MainActivity` 与 `PreviewActivity` 均为 `singleTask`；已编辑实例内切文档不走重建。R24 起编辑器内点「预览」改为同一 panel 内视图互斥切换（`PreviewScreen`），不再跳 Activity；`PreviewActivity` 仅保留为外部 intent 薄壳入口 | `onNewIntent` 路径切文档后无二次 `editor page ready`，只有一次 `editor mount id=<docId>`；同页切换 140 ms 淡入无黑屏 | 无 |
| 8 | 全局 Ctrl 快捷键 | 降级 | 工具栏 + 选区菜单为主；物理键盘保留映射 | 编辑器页面内工具栏 9 个按钮（新建/关闭/查找/预览/折叠/片段/夜间/保存/返回）；`MainActivity.dispatchKeyEvent` + `Shortcuts.resolve` 保留映射 | 工具栏实测：查找条展开、折叠 17 ms、主题切换；键盘实测 `Ctrl+N` 日志 `shortcut NEW`，文档数 1→2 | `Ctrl+Tab`、`Ctrl+Shift+P` 未逐条实测，归 M1 |
| 9 | Tab 触发词展开 | 降级 | 工具栏「插入片段」+ 物理键盘 Tab 双通道 | `SnippetLibrary` 4 个片段可从工具栏插入正文 | 实测插入后正文尾部为 `SEND通道验证\|``` kotlin \|\|``` \|`，单测 `SnippetAndShortcutTest` 4 条通过 | 物理键盘 Tab 触发未实测，归 M1 |
| 10 | 备份到 `~/.local/share/...` | 替换 | 应用私有 `backups/` + 可选导出到 SAF | 已实现 `BackupExporter`：私有目录打包 + SAF 导出 `分享内容-backup.zip` | 导出文件 2,063 B = manifest 65 B + db 45,056 B + 3 篇 notes；`BackupRoundTripTest` 2 条通过 | 云盘/自动备份不在 v1，归 Q5 |

## 汇总

| 状态 | 项 |
|---|---|
| 已落地并有设备实测证据 | 1（SAF 三项，R22）、2、3（能力）、7、8、9、10（云备份 Q5 端到端，R19） |
| 已落地、实测只覆盖部分判据 | 3（公式与图片在 PDF 中的表现）、6（跨应用入口）、8（`Ctrl+Tab` / `Ctrl+Shift+P`）、9（物理键盘 Tab 触发；无外接键盘，用户裁定跳过） |
| 未接入 | 4（OpenCC JNI） |
| 方案内明确删除 | 5 |
| 用户拍板不做 | 10 云盘自动化（本地 WebDAV 端到端已实测；CI/H4 不做 git 推送，永久跳过） |

