# Android 开发环境安装记录（Windows）

本机：<Windows 开发机>，Windows 10 Pro 10.0.19045 x64，AMD Ryzen 5 3550H，RAM 14.9 GB。
安装时间：2026-11-19。
安装形态：全部组件为便携式目录部署，仅 Android Studio 走官方安装器落盘到默认目录；环境变量写在 Machine 级。

## 1. 组件清单

| 组件 | 版本 | 安装路径 | 验证方式与结果 |
|---|---|---|---|
| JDK（Temurin/Adoptium） | 21.0.13+9 LTS | `<JDK-21 路径>` | `java -version` → openjdk 21.0.13；`javac -version` → javac 21.0.13 |
| Gradle | 9.9.1 | `<Gradle 路径>-9.9.1` | `gradle -v` → Gradle 9.9.1，Kotlin 2.4.21，JVM 为 JDK 21 |
| Android SDK 根目录 | 23.0.0（cmdline-tools） | `<Android SDK>` | 目录存在，`sdkmanager --list_installed` 正常输出 |
| cmdline-tools | latest 23.0.0 | `<Android SDK>\cmdline-tools\latest` | `sdkmanager.bat`、`avdmanager.bat`、`android.exe` 可用 |
| Platform-Tools | 37.0.1 | `<Android SDK>\platform-tools` | `adb version` → 1.0.41 / 37.0.1-15733141 |
| Emulator | 37.2.13 | `<Android SDK>\emulator` | `emulator -version` → 37.2.13.0（build 16740729） |
| SDK Platform | android-35 (r02)、android-36 (r02) | `<Android SDK>\platforms` | 目录 `android-35`、`android-36` 均生成 |
| Build-Tools | 36.0.0、36.1.0 | `<Android SDK>\build-tools` | 目录 `36.0.0`、`36.1.0` 均生成 |
| System Image | android-36 / default / x86_64（1.9 GB 解包后） | `<Android SDK>\system-images\android-36\default\x86_64` | `sdkmanager` 安装 exit=0，目录生成 |
| AVD | Pixel_API36（Pixel 6 硬件配置，Android 16 / API 36） | `<用户目录>\.android\avd\Pixel_API36.avd` | `avdmanager list avd` 可列出；冷启动后 `sys.boot_completed=1` |
| Android Studio | 2026.2.2.9（build AI-262.10968.63.2622.16840690） | `C:\Program Files\Android\Android Studio` | `bin\studio64.exe` 存在；内置 JBR 25.0.4 可运行；开始菜单快捷方式已创建 |

## 2. 环境变量（Machine 级）

| 变量 | 值 |
|---|---|
| `JAVA_HOME` | `<JDK-21 路径>` |
| `ANDROID_HOME` | `<Android SDK>` |
| `ANDROID_SDK_ROOT` | `<Android SDK>` |
| `GRADLE_HOME` | `<Gradle 路径>-9.9.1` |

PATH（Machine）前置顺序：

```
C:\Program Files\Android\Android Studio\bin
<JDK-21 路径>\bin
<Android SDK>\platform-tools
<Android SDK>\cmdline-tools\latest\bin
<Android SDK>\emulator
<Gradle 路径>-9.9.1\bin
```
其余原有条目（WindowsApps、system32、WSL、ZeroTier、VS Code 等）保留在其后。

已从 Machine PATH 移除 `<下载目录>-tools`（旧 adb 残留目录，其 adb 版本低于 SDK 37.0.1，且会因 Machine PATH 优先于 User PATH 而抢占 `adb` 命令）。该目录本身未删除。

PATH 解析验证：在合并后的 PATH 中逐一查找，`java.exe → <JDK-21 路径>\bin`、`javac.exe → <JDK-21 路径>\bin`、`gradle.bat → <Gradle 路径>-9.9.1\bin`、`adb.exe → <Android SDK>\platform-tools`、`sdkmanager.bat → <Android SDK>\cmdline-tools\latest\bin`、`emulator.exe → <Android SDK>\emulator`，全部命中预期路径。

## 3. 安装过程中遇到的三个真实问题

1. winget 通道曾被 UAC 阻断：`Google.AndroidStudio` 包下载完成但安装阶段无子进程、`C:\Program Files\Android` 为空，判定为等待提权。改为直接运行官方安装器（当前会话本身已是 High Mandatory Level），以 `/S /D=<Android Studio>` 静默安装。安装器忽略了 `/D` 参数，产物落在默认目录 `C:\Program Files\Android\Android Studio`（3342 个文件、3400 MB、`studio64.exe` 与 `uninstall.exe` 齐全）；退出码返回 1223，属该安装器在静默模式下的返回码异常，安装本身成功。PATH 因此指向 `C:\Program Files\Android\Android Studio\bin`，而非 `<Android Studio>\bin`。
2. 首次从 winget 缓存复制的安装器比官方直链短 1,738,088 字节（1,529,872,384 vs 1,531,610,472），Authenticode 为 `NotSigned`、无 NSIS 尾结构、7-Zip 报 `Cannot open the file as archive`。重新完整下载后签名为 `Valid`、签名者 `CN=Google LLC`，安装成功。结论：该文件在下载中断后处于截断状态。
3. cmdline-tools 23.0.0 中 `sdkmanager` 已标记 deprecated，且**包名分隔符由 `;` 变为 `/`**。使用 `platforms;android-36`、`build-tools;36.1.0` 这类旧写法时退出码为 0 但一个包都不落盘；改用 `platforms/android-36`、`build-tools/36.1.0` 后正常安装。

## 4. 端到端验证证据

| 验证项 | 方法 | 结果 |
|---|---|---|
| 完整构建 | 在 `<临时目录>-setup\probe-app` 建最小 Java 应用（AGP 9.5.1、compileSdk 36、build-tools 36.1.0、minSdk 24），执行 `gradle assembleDebug` | `BUILD SUCCESSFUL in 2m 37s`，33 个任务全部执行，产出 `app-debug.apk`（853 KB） |
| 构建后清理 | 删除探针工程 | 已删除，`<临时目录>-setup\probe-app` 不存在 |
| 模拟器加速 | `emulator -accel-check` | `WHPX(10.0.19045) is installed and usable` |
| 模拟器冷启动 | `emulator -avd Pixel_API36 -no-window -no-audio -no-snapshot -no-boot-anim -gpu swiftshader_indirect` | 60 秒内 `sys.boot_completed=1`；`adb devices` 显示 `emulator-5554 device` |
| 设备属性 | `adb shell getprop` | `ro.build.version.sdk=36`，`ro.product.cpu.abi=x86_64` |
| 构建告警 | Gradle 输出 | `Deprecated Gradle features were used in this build, making it incompatible with Gradle 10` —— 来自 AGP 9.5.1 的 Gradle 内部 API 使用，Gradle 9.9.1 下不影响构建 |

## 5. 现状与待办

| 项目 | 状态 |
|---|---|
| 模拟器加速（WHPX） | `emulator -accel-check` 报 WHPX 可用，模拟器实际启动成功。`HypervisorPlatform` 可选功能显示为 Disabled，但本机已由其他机制提供 WHPX，无需再启用 |
| AVD | 已创建 `Pixel_API36`，可直接启动 |
| NDK / CMake | 未安装。纯 Kotlin/Java 工程不需要；涉及原生代码时按实际需求补 `ndk/<版本>` |
| Git | 未安装。仅在使用 Studio 的 Git 集成或命令行版本控制时需要 |
| 环境变量生效范围 | Machine 级已写入并广播 `WM_SETTINGCHANGE`；已处于运行状态的终端、cmd、IDE 需重启进程才能读到新 PATH |

## 6. 常用命令

```powershell
java -version
gradle -v
adb devices
sdkmanager --list_installed
sdkmanager "platforms/android-36" "build-tools/36.1.0"
avdmanager list avd
```

## 7. 相关文件

| 文件 | 说明 |
|---|---|
| `<临时目录>-setup\studio-setup.exe` | 官方安装器（1,531,610,472 字节，签名有效） |
| `<临时目录>-setup\jdk2.zip` | JDK 21 压缩包（195.9 MB） |
| `<临时目录>-setup\gradle.zip` | Gradle 9.9.1 压缩包（134,921,139 字节） |
| `<临时目录>-setup\cmdline2.zip` | cmdline-tools 压缩包（147.8 MB） |
| `<临时目录>-setup\sdk-setup.log` | 首轮 SDK 安装日志 |
| `<临时目录>-setup\sdk-install2.log` | platform / build-tools 安装日志 |
| `<临时目录>-setup\sysimg.log` | 系统镜像安装日志 |
| `<临时目录>-setup\env-setup.log` | 环境变量写入与 PATH 重建记录 |
