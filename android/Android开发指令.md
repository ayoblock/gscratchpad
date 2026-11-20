# Android 开发项目指令（从本机部署实录提炼）

> 用途：作为 AI 编程助手的项目指令 / 自定义指令，适用于本机（Ubuntu 26.04 + Wayland）上的 Android 项目开发。
> 来源：2026-11-19 本机 Android 开发环境全链路部署实录（Studio / SDK / AVD / KVM / 无头启动验证）。
> 位置约定： Android 项目工作区建立后，本文件迁入该项目根；迁移前存放于 `~/WorkBuddy/coord/`。
> 配套：跨项目对接、知识沉淀、工程卫生规则见 `~/WorkBuddy/coord/项目指令统一包.md`，本文件不重复；新条目按其规定写入 `~/WorkBuddy/knowledge/`。

---

## 一、核心工作原则

1. **环境实测先行**：动手前先核实环境事实（`~/Downloads/android/env.sh` 已定义的路径、SDK 组件版本、KVM 可用性），关键 API 行为（AGP / Gradle 版本兼容矩阵、Jetpack API 签名）从官方文档或源码核实，不以训练记忆为准。
2. **不猜测性修复**：用户报「没修复」即根因假设错误，停止同层面修补，下探一层找结构性根因（参考：模拟器下载失败，直接补丁重试无效，根因是 sdkmanager 单线程链路不稳，换 aria2c 多线程方案才解决）。
3. **最小复现探针**：疑难问题先写最小可运行模块（或 `adb shell` 命令序列）逐层转储测量数据（logcat、dumpsys、布局层级），证伪假设后再改主代码。探针用完即删。
4. **A/B 实验区分「环境问题 vs 应用 bug」**：同一现象先在真机与模拟器、或最小 demo 上复现对照；模拟器独有即环境问题，真机也现才是应用 bug。
5. **先确认「实际在跑什么」**：诊断前查安装的 debug/release 变体（`adb shell pm list packages`）、运行进程（`adb shell ps -A | grep <pkg>`）、`build.gradle` 实际配置；装的是旧 APK 是常见假 bug 来源。

## 二、本机环境事实（2026-11-19 实测，避坑清单）

### 部署布局（勿改动路径约定）
- 全部落在 sda2 分区 `~/Downloads/android/`（根分区仅 42G 余量，**禁止移回 $HOME 根目录**）：
  - Studio：`~/Downloads/android/android-studio`（Rabbit 2 Patch 1，2026.2.2.9，JBR = OpenJDK 25）
  - SDK：`~/Downloads/android/sdk`（platform-tools 37.0.1、platforms;android-36、build-tools 36.1.0、emulator 37.4.1、system-images;android-36;google_apis;x86_64 r07）
  - AVD：`~/Downloads/android/avd`（Pixel_API_36：Pixel profile、2 GB RAM、1080×2280@440dpi）
  - Gradle 用户目录：`~/Downloads/android/gradle-home`（内含阿里云镜像 init.gradle，项目级**无需**再配镜像）
- 环境变量统一在 `~/Downloads/android/env.sh`，已由 `~/.zshrc` 自动 source（ANDROID_HOME / ANDROID_AVD_HOME / GRADLE_USER_HOME / JAVA_HOME / PATH）。脚本内调用 Android 工具时**显式 source 该文件**，不假设 PATH 已就绪。
- 桌面入口：`~/.local/share/applications/android-studio.desktop`。

### 系统与权限
- Ubuntu 26.04.1，Wayland（Unity 会话）。Studio 渲染异常（黑屏/输入卡顿）先切 Xorg 会话验证，不急于重装。
- **sudo 需交互密码，Agent 无法自动安装**：生成明确命令交用户执行，不假装已安装。
- **沙箱禁 rm / rmdir**：删除用 `python3 -c "os.remove(...)" / os.rmdir(...) / shutil.rmtree(...)`（`rmdir` 被 shim 拦截）。
- KVM 已就绪：`cng` 在 `kvm` 组（新登录会话生效；脚本内旧会话用 `sg kvm -c '<命令>'` 临时提权）。
- adb + udev：`/etc/udev/rules.d/51-android.rules` 已配置，真机插拔即用；无需再装 platform-tools。

### 资源边界（4C8T Haswell / 15 GB 内存 / GTX 1060 3GB）
- 内存低于官方 16G 门槛：Studio `-Xmx2g`、Gradle `org.gradle.workers.max=2`、**单 AVD 2 GB，禁止并行多 AVD**；构建时关掉浏览器大页签再跑。
- 模拟器 GPU：3 GB 显存低于官方 4G 门槛，AVD 分辨率已压至 1080p 内；有窗口调试用默认 `hw.gpu.mode=auto`（host），无头测试用 `-gpu swiftshader_indirect`。
- 实测基线：Pixel_API_36 无头冷启动至 `sys.boot_completed=1` ≈ 160 s（swiftshader_indirect）。

## 三、工具链规范与已知陷阱

### SDK 安装与元数据（实测踩过）
- **sdkmanager 直连 dl.google.com 单线程不可靠**：连接重置导致事务整体回滚；新版（2026）cmdline-tools **忽略 `--proxy` / `--no_https` 代理参数**，本地仓库方案不可行。
- 可靠安装法：`aria2c -x8 -s8 -k4M -c` 直下官方 zip → 解压对齐 SDK 标准布局 → 用远端仓库 XML 的 `remotePackage` 块合成 `package.xml`（localPackage 格式；命名空间映射：主仓库 repository2-3.xml，系统镜像在主仓库内以 `sys-img/google_apis/x86_64-36_r07.zip` 形式引用）→ `sdkmanager --list_installed` 验证识别。
- **Google zip 自带顶层目录**：unzip 后必须检查并上提一层，否则二进制落在 `sdk/<pkg>/<pkg>/`。
- **`test -x` 对目录也返回真**：验证二进制存在用 `test -f`。
- sdkmanager 把仓库 XML 缓存在 `~/.android/cache/sdkbin-*`，查包 URL 优先翻缓存，不必逐个探测 XML 文件名。

### AVD / 模拟器（实测踩过）
- `avdmanager create avd` **不接受 `--hw.*` 参数**：先创建，再改 `config.ini`（hw.ramSize / hw.lcd.* / hw.gpu.*）。
- 机器无皮肤包：`config.ini` 必须设 `showDeviceFrame=no`，否则启动异常。
- 机器自建 AVD 后检查 `avd.name` / `avd.id` 是否残留 `<build>` 占位符，是则替换为实际名称；`~/.android/avd` 与自定义 `ANDROID_AVD_HOME` 的入口 `.ini` 中 `path` 必须为绝对路径。
- 无头冒烟测试固定命令：
  `emulator -avd Pixel_API_36 -no-window -no-snapshot -no-boot-anim -gpu swiftshader_indirect -no-audio`，
  用 `adb shell getprop sys.boot_completed` 轮询（10s 间隔），完成后 `adb emu kill` 释放资源。
- 测试模拟器必须显式关闭：15 GB 内存的机器上残留 qemu 进程会拖垮后续构建。

### 构建规范（常规纪律）
- 一律用项目自带 `./gradlew`，不用全局 gradle；AGP / Gradle / JDK 版本矩阵先查官方兼容表再定（本机 JAVA_HOME = JBR 25，若 AGP 要求更低 JDK 用 Studio 内置 JDK 列表切换）。
- 新依赖需说明必要性；依赖版本冲突以 `./gradlew dependencies` / `dependencyInsight` 输出为准，不猜。
- 国内网络环境：Maven 依赖已由 init.gradle 阿里云镜像覆盖；但**组件/镜像 zip 类资源**（如 AGP 下载的 NDK、CMake）仍走 dl.google.com，遇超时按上文 aria2c 方法处理。

### adb / 设备调试
- 模拟器对外暴露：`adb -a -P 5555 nodaemon server`；与笔记本经 ZeroTier 互通（笔记本已装 ZeroTier）：`adb connect <ZeroTier-IP>:5555`。
- 截图取证用 `adb exec-out screencap -p > <项目>/.tmp/shot.png`，不入版本控制。
- 无障碍/权限类测试先 `adb shell pm grant` 预授权，减少手动确认环节。

## 四、诊断流程（固定套路）

1. 复现 → 最小探针逐层测量（logcat 过滤 tag / `dumpsys` / Layout Inspector / `uiautomator dump`）。
2. 对照官方源码或 AOSP 文档确认机制。
3. A/B 最小 demo 或真机对照，排除模拟器环境因素。
4. 修复 → 同探针复测 → 全量回归。
5. 疑难杂症先排除：旧 APK 未卸载（签名冲突装不上新包）、Gradle daemon 带旧配置（`./gradlew --stop`）、模拟器快照陈旧（`-no-snapshot` 冷启动复测）、跑错变体（debug vs release 行为差异）。

## 五、回归与交付纪律

1. 每轮改动后固定动作：`./gradlew lint` → `./gradlew assembleDebug`（零警告）→ 单元测试 → 涉 UI 的 `connectedDebugAndroidTest` 或真机/模拟器实测 + 截图。
2. 回归必须覆盖**新缺陷的精确触发条件**，并把触发条件写进测试断言注释。
3. 交付：版本号唯一来源（`build.gradle(.kts)` 的 `versionName`/`versionCode`），交付时列出 APK/AAB 绝对路径与安装命令（`adb install -r`，覆盖安装失败时先卸载并说明原因）；不宣称未执行的验证。
4. 临时探针、调试 logcat 导出、`.tmp` 夹具用完即清；构建产物目录（`build/`）里程碑前 `./gradlew clean` 防磁盘膨胀（sda2 余量有限）。
5. 工作日志与 README 同步更新（含根因与实证数据，不只是「修了」）。

## 六、知识沉淀

- 本文未覆盖且已实证的 Android 栈结论（AGP 兼容矩阵、模拟器行为、Gradle 配置坑），按 `~/WorkBuddy/knowledge/README.md` 的条目格式（现象/根因/处置/来源/日期）沉淀到 `knowledge/`（建议新建 `android-common.md`）；写入前查重，与库版本绑定的条目标注适用版本。
- 与已有项目（scratchpad / Lectula 等）的对接需求走 `~/WorkBuddy/contracts/` 与 `~/WorkBuddy/issues/` 流程，不在本文扩展。
