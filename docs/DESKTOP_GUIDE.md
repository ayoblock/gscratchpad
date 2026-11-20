# Gscratchpad 桌面版使用手册

> 本文是桌面 GTK 版（Ubuntu，Python + GTK4/libadwaita）的详细手册；概览与安装见根目录 [README](../README.md)。测试结果见 [TEST_REPORT.md](TEST_REPORT.md)。

## 功能总表

- **零操作持久化**：输入停止 300ms 后自动保存（防抖），SQLite WAL + 事务 + 恢复日志保证崩溃/断电安全
- **多标签页**：新建 / 重命名 / 关闭（不删除文档）/ 拖动排序，记住活动标签，重启完整恢复
- **TXT / Markdown / HTML 多格式**：可随时切换；Markdown/HTML 提供语法高亮（GtkSourceView 5），HTML 文档预览原文载入（相对资源按文件目录解析）
- **行号与源码折叠**：行号常显；折叠箭头支持 Markdown 标题/代码围栏、缩进块（Python 等）、括号块（JSON 等）；落盘内容永远为全文
- **格式化排版**：Ctrl+Shift+I 对 JSON / XML / HTML / Python / Bash 排版（Python/Bash 优先调用系统 black/ruff/shfmt，缺失时提示安装）
- **简繁转换**：菜单「工具」或编辑区右键，简⇄繁转换（子进程调用系统 opencc，缺失时提示安装）；有选区时只转换选中文字（其余正文不动），无选区整篇
- **Markdown 预览**：源码 / 分屏 / 实时预览三种模式，支持标题、列表、引用、表格、代码高亮（Pygments）
- **数学公式**：KaTeX，LaTeX 语法（`$...$` 行内 / `$$...$$` 块级）
- **Mermaid 流程图**：本地离线渲染（```` ```mermaid ```` 代码块）
- **图片管理**：拖放或菜单「插入图片…」——文档已关联本机文件时写**相对路径引用**（不复制图片，便于与 Markdown 一起移动/版本管理）；尚未关联文件时复制到应用资源目录并按内容去重
- **文件关联**：`gscratchpad a.md` 或 Nautilus「用 Gscratchpad 打开」，多文件各开一标签、重复文件只切标签；应用已开着时在同一窗口打开
- **PDF 导出**：WeasyPrint 真分页（行不被切半、文字矢量可选中可搜索、A4 排版），weasyprint 缺失时自动回退位图导出并提示
- **查找替换**：Ctrl+F / Ctrl+H，支持正则、区分大小写与**转义**开关；`\n` `\t` `\r` `\\` `\xHH` `\uHHHH` 按控制字符解释（查找与替换都生效）；「全部替换」带**仅选区**开关，整批合并为一次撤销
- **撤销 / 重做**：标题栏按钮 + Ctrl+Z / Ctrl+Shift+Z（或 Ctrl+Y）；整段操作合并为一次撤销；折叠/展开不计入撤销栈
- **列编辑**：菜单「工具」或编辑区右键——每行加前缀 / 后缀、行排序、去除重复行；作用于选区覆盖的整行，执行前自动展开折叠
- **目录搜索**：Ctrl+Shift+F——对真实目录递归搜索，结果按文件分组；双击打开并定位到关键词
- **目录批量替换**：Ctrl+Shift+H——先预览、按文件勾选后执行；保留原编码/BOM/换行符，执行前自动备份
- **主题切换**：标题栏月亮/太阳按钮，日间/夜间即时切换并持久化
- **文本片段**：自定义模板（`{{cursor}}` 光标落点、`{{date}} {{time}} {{title}}` 变量），可录制快捷键；触发词 Tab 展开
- **编辑进度记忆**：光标行号随手记入 meta，重新打开回到上次的位置
- **清理与维护**：清除已关闭的笔记（破坏性确认、单事务删除）；清理孤儿文件并压缩数据库（只处理本应用数据目录，绝不触碰关联的本机原文件）
- **侧边文件管理器**：F9 开关，悬浮卡片式；四个视图——笔记（三视图 + 四种排序 + 筛选）、文件夹（应用内归类）、磁盘（`$HOME` 真实文件树、懒加载、四种排序）、大纲（Markdown 标题目录）；选中后自动收起可开关，Esc 关闭
- **Markdown 大纲**：按 CommonMark 规则识别 ATX/Setext 标题，源码模式跳行、预览模式滚动定位
- **内存自控**：预览面板不可见超 90 秒销毁 WebView；KaTeX/Mermaid 仅当文档真的含公式/图表时才注入
- **打开/保存本机文件**：Ctrl+O 多选打开文本文件；Ctrl+S 已关联文件原子写回，未关联时另存为
- **命令菜单**：Ctrl+K——5 个语义分组 + 动态「已关闭的文档」+ 顶部搜索框，每条命令右侧显示真实生效的快捷键
- **捕获接口（capture v1）**：供其它程序把笔记写入本应用（详见下文）

## 与文件管理器关联

DEB 里带 `MimeType=text/plain;text/markdown;` 与 `Exec=gscratchpad %U`，装完即可：

```bash
# 命令行直接打开（多个文件会各开一个标签；已打开则切到该标签）
gscratchpad ~/notes/todo.md
gscratchpad a.md b.txt

# 设为 .md 的默认程序
gio mime text/markdown io.github.gscratchpad.Gscratchpad.desktop
# 恢复 gedit
gio mime text/markdown org.gnome.gedit.desktop
```

- 安装**不会**自动抢默认关联，只在「打开方式」里出现（Nautilus 右键 → 打开方式）
- 应用已开着时双击文件，会在**同一个窗口**新开标签，不会起第二个进程
- `text/plain` 也在声明里，所以 `.txt`/`.log` 的「打开方式」同样能看到它
- 应用被回收/最小化时同样生效：文件路径会先挂起，窗口建好后立刻打开

**装完不生效的两个常见原因**：① 旧进程还在跑（旧代码没有文件处理），必须完全退出再启动；② Nautilus 缓存了应用列表，`nautilus -q` 或重新登录一次即可。

## 数据布局

```
~/.local/share/gscratchpad/
├── gscratchpad.db       # SQLite（WAL）：文档内容、标题、格式、顺序、状态
├── gscratchpad.db-wal   # WAL 日志（崩溃恢复）
├── notes/               # 每个文档的内容镜像文件（原子写入）
├── assets/<doc-id>/     # 未关联本机文件的文档导入图片时的资源目录
├── replace-backups/     # 目录批量替换的自动备份（按时间戳分目录）
└── recovery/            # 写前恢复日志（提交成功后自动清除）
```

## 供其它程序调用（capture v1）

外部应用（PDF/EPUB 阅读器等）可把笔记写入本应用。纯写方向，无读取/更新/删除接口。

**D-Bus（主通道，Python/GTK 应用）**：

```
目标:  io.github.gscratchpad.Gscratchpad
路径:  /io/github/gscratchpad/Gscratchpad
接口:  org.gtk.Actions，方法 Activate("capture", [<参数元组>])
参数:  GVariant (ssssss)——text, title, book, page, key, mode
```

注意：动作名是裸名 `capture`，**不带** `app.` 前缀（`app.capture` 是进程内 `activate_action()` 的写法）。`Activate` 完整签名为 `(sava{sv})`，platform_data 是必填项（传空字典 `{}`）。

- `mode` 为 `create` 或 `append`（缺省 append，action 通道必须显式传）
- `key` 全局唯一，调用方必须自带命名空间前缀（如 `lectula:<书 id>`）；同 key 的 `create` 幂等返回既有文档
- `append` 永不覆盖既有内容，追加块为行首独立一行 `---` 分隔 + 引用块（书名 · 页码 · 时间）
- **book/page 传裸内容**：book 不带 `《》`（引用行的书名号由本程序添加）；page 放「第N章 · 1/2 页」这类描述
- 调用为 fire-and-forget，无返回值；成功判据 = `Activate` 无 `GLib.Error`
- 可用性探测：`org.gtk.Actions.DescribeAll` 中含 `capture` 即可用

**命令行（降级通道，任意语言）**：

```
gscratchpad --capture-title <s> --capture-book <s> --capture-page <s> \
            --capture-key <s> --capture-mode <create|append> (- | --capture-text <s>)
```

- 正文二选一：末尾单独 `-`（stdin 读入 utf-8）或 `--capture-text <s>`
- 退出码：`0` 成功 / `1` 参数错误 / `2` 服务不可达 / `3` 校验失败 / `4` 落盘异常；stdout 保持为空
- 实例运行中 → 经 `org.gtk.Application.CommandLine` 转发并带回真实退出码；未运行 → 本地直落数据目录，不建窗不常驻
- 校验在转发前本地完成，失败时绝不触碰运行中的实例

**约束**：正文 utf-8、禁 NUL、单次 ≤ 1MB（批量导出请逐条调用）；key ≤ 256 字符且不含空白；title ≤ 200 字符。调用方不得直接读写本应用数据目录或 SQLite。

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| Ctrl+Z / Ctrl+Shift+Z | 撤销 / 重做（Ctrl+Y 同重做） |
| Ctrl+N | 新建标签 |
| Ctrl+W | 关闭当前标签（保留文档） |
| Ctrl+Tab / Ctrl+Shift+Tab | 下一个 / 上一个标签 |
| Ctrl+1…9 | 切换到指定标签 |
| Ctrl+F / Ctrl+H | 当前文档内查找 / 替换 |
| Ctrl+Shift+F | 在目录中搜索（跨文件） |
| Ctrl+Shift+H | 目录批量替换（先预览、自动备份） |
| Ctrl+O | 打开本机文件（可多选，拖入文件同样有效） |
| Ctrl+S | 保存到本机文件（未关联时另存为；自动保存不依赖它） |
| Ctrl+Shift+P | 源码 ⇄ 预览切换 |
| Ctrl+Shift+I | 格式化排版（JSON/XML/HTML/Python/Bash） |
| F2 | 重命名标签 |
| F9 | 显示 / 隐藏侧边栏 |
| Ctrl+K | 打开命令菜单 |
| Ctrl+Shift+E | 片段与自动补全设置 |
| （自定义） | 片段快捷键在设置里录制 |

## 片段与触发词

- 片段 = 名称 + 模板 + 可选快捷键，存在文档库 meta 里（随库备份）。
- 模板语法：`{{cursor}}` 光标落点；`{{date}}` `{{time}}` `{{datetime}}` `{{title}}` 变量；`\n` `\t` `\r` `\\` 转义；未知写法原样保留——bash 的 `$VAR`、`printf "%s\n"` 不会被吃掉。
- 录制快捷键时按 Esc 取消；只按修饰键不算；无修饰键只接受 F1–F12。
- 与核心快捷键冲突时弹出「仍然改绑」，「恢复默认快捷键」可一键还原。
- Tab 展开只在光标前恰好是触发词且前面是词边界时生效；`life` 里的 `ife` 不会展开。

## 侧边栏

侧栏是**悬浮卡片**：圆角 + 阴影浮在正文上方，显示/隐藏不会引起编辑区宽度跳动。

- **笔记**：三种视图——「最近更新」（含已关闭的文档）、「未关闭」、「按格式」分组；排序下拉（最近更新 / 最早更新 / 标题 A→Z / Z→A，中文跟随系统 locale）；搜索框按标题即时筛选；右键可重命名、移动到文件夹、永久删除。
- **文件夹**：应用内的笔记归类，不动磁盘上的任何文件。右上角＋新建；笔记行可拖到文件夹上或右键移动；删除文件夹只是把其中笔记移回「未归档」。
- **磁盘**：从主目录出发的真实文件树，只显示文件夹与文本类文件，隐藏目录、`.git`/`node_modules` 与二进制自动跳过；目录懒加载，单目录超过 400 项截断提示；排序按钮可切换名称/最近修改/按类型；单击即打开，右键可打开/显示/复制路径。
- **大纲**：Markdown 文档的标题目录；围栏代码块、缩进代码、HTML 注释里的 `#` 不会误判。点击条目：源码模式光标跳行，预览模式滚动定位并短暂高亮。

## 目录搜索与替换

数据源始终是**你自己选择的真实目录**，不会碰应用内部的笔记库：

1. **目录搜索**（Ctrl+Shift+F）：选目录后输入关键词，结果按文件分组；单击只是选中，双击才打开该文件并跳到对应行；右键有「替换此内容…」。
2. **目录批量替换**（Ctrl+Shift+H）：先「预览替换」，确认后执行；执行前二次确认并自动备份。改动查找/替换内容会作废旧预览。

行为细节：递归子目录、字面量替换（可切正则）、UTF-8/GB18030 自动识别、BOM 与 CRLF 原样保留、二进制与大文件跳过；预览之后若文件被其他程序改动，该文件会被跳过。

**转义**：非正则模式下 `\n` `\t` `\r` `\\` 被解释成实际字符；正则模式下直接用 re 语法（`\1` 反向引用由 re 处理）。

## 内存占用

1. **预览空闲回收**：预览面板不可见超过 90 秒后销毁 WebView；阈值可用 `GSCRATCHPAD_PREVIEW_IDLE=<秒>` 覆盖。
2. **KaTeX / Mermaid 按需加载**：渲染时先判断正文是否真的含公式/图表，没有就完全不注入。

实测（Ubuntu 26.04 / WebKitGTK 2.52）：启动基线主进程 RSS 214 MB；纯文字预览 271 MB（WebKit 进程 178 MB）；含公式 + Mermaid 273 MB；切回源码 2 秒后回收至 0 个 WebKit 进程。`ps` 显示的是 RSS 之和，实际物理占用（PSS）约为其 40%~60%。

## 测试

```bash
# 单元测试
/usr/bin/python3 -m unittest discover -s tests -p "test_*.py"

# GUI 自动化测试（每项独立数据目录）
SCRATCHPAD_DATA_DIR=/tmp/sp-a /usr/bin/python3 tests/gui_test.py write        # 写入三标签
SCRATCHPAD_DATA_DIR=/tmp/sp-a /usr/bin/python3 tests/gui_test.py write --kill # SIGKILL 崩溃模拟
SCRATCHPAD_DATA_DIR=/tmp/sp-a /usr/bin/python3 tests/gui_test.py verify       # 重启恢复验证
SCRATCHPAD_DATA_DIR=/tmp/sp-b /usr/bin/python3 tests/gui_test.py autosave
SCRATCHPAD_DATA_DIR=/tmp/sp-c /usr/bin/python3 tests/gui_test.py closetab
SCRATCHPAD_DATA_DIR=/tmp/sp-d /usr/bin/python3 tests/gui_test.py preview
SCRATCHPAD_DATA_DIR=/tmp/sp-e /usr/bin/python3 tests/gui_test.py image
SCRATCHPAD_DATA_DIR=/tmp/sp-f /usr/bin/python3 tests/gui_test.py pdf
SCRATCHPAD_DATA_DIR=/tmp/sp-g /usr/bin/python3 tests/gui_test.py find
SCRATCHPAD_DATA_DIR=/tmp/sp-h /usr/bin/python3 tests/gui_test.py dark
```

更多端到端脚本（侧边栏、片段、目录搜索、维护、内存等）见 `tests/` 目录；详细结果见 [TEST_REPORT.md](TEST_REPORT.md)。

## 架构

```
src/scratchpad/
├── application.py    # 应用入口、快捷键、样式
├── command_menu.py   # 命令菜单：分组命令 + 搜索框（Ctrl+K），单一数据源
├── window.py         # 主窗口：标签管理、自动保存调度、菜单、状态栏
├── editor.py         # 编辑器标签页：GtkSourceView、查找替换、拖放
├── folding.py        # 源码折叠引擎（物理移除 + 影子恢复，落盘恒为全文）
├── formatter.py      # JSON/XML/HTML/Python/Bash 格式化排版（纯函数）
├── fssearch.py       # 目录搜索与批量替换（编码/BOM/换行保真、备份、并发校验）
├── fssearch_ui.py    # 目录搜索 / 批量替换 对话框
├── snippets.py       # 文本片段：模板渲染、加速键规范化、触发词表（纯逻辑）
├── snippets_ui.py    # 片段与自动补全设置
├── keymap.py         # 核心快捷键表
├── sidebar.py        # 侧边栏：笔记列表、文件夹、磁盘树、大纲
├── outline.py        # Markdown 大纲解析（纯逻辑）
├── preview.py        # WebKitGTK 6.0 预览面板（空闲回收、滚动位置保持）
├── markdown_render.py# Markdown → HTML（公式/Mermaid 占位保护、按需加载、净化）
├── pdfexport.py      # 双管线：WeasyPrint 真分页 / 位图回退 → A4 PDF
├── store.py          # SQLite 持久化层（WAL、事务、journal 恢复）
├── assets.py         # 图片导入（SHA-256 去重）
└── paths.py          # XDG 路径解析
```

## 已知限制

1. **PDF 导出依赖 weasyprint**：缺失或运行失败时自动回退位图快照管线并 Toast 提示；位图管线文字不可选中。
2. Mermaid 仅保证 mermaid 10.9.1 核心图形；渲染失败时预览中显示原始文本与错误说明，不影响文档内容。
3. 行内公式语法为 `$...$`，未匹配成对的 `$` 按原文显示。

## 故障排查

- **确认当前运行的是哪份代码**：`gscratchpad --version` 会打印版本与代码目录。本应用是单实例应用：升级后若旧窗口还开着，需先完全退出（Ctrl+Q）再启动。
- **快捷键完全不响应**：用 `GSCRATCHPAD_KEYDEBUG=1 gscratchpad` 启动，主窗口收到的每个按键都会打印到 stderr。若按键无输出，说明在到达应用前就被环境消耗掉（输入法/系统级快捷键），与应用内绑定无关。
