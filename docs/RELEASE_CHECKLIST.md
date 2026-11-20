# GitHub 发布检查单

> 每次公开推送/发 Release 前过一遍。本清单首次执行于 2026-11-20（MIT 首发前清洗）。

## 1. 敏感信息扫描（发布前必跑）

```bash
# 真机序列号 / 机器名 / 局域网 IP / 本机绝对路径
grep -rnE "VG6TQ|ERLDU|PFVM10|DESKTOP-[A-Z0-9]{5}|10\.[0-9]+\.[0-9]+\.[0-9]+|/home/[a-z0-9_]+|\\\\Users\\\\" \
  --include="*.md" --include="*.kt" --include="*.py" --include="*.yml" .
# 凭据形态（应只命中 example/占位符）
grep -rniE "password|passwd|token|secret|api[_-]?key" --include="*.md" --include="*.kt" --include="*.py" .
```

- 命中即改：真机序列号 → 「真机 A/B/C（品牌）」；局域网 IP → `<LAN-IP>`；机器名 → `<开发机>`；绝对路径 → `<仓库根>`/`<Android SDK>` 占位符。
- **签名材料绝不入库**：`android/keystore.properties`、`*.jks`、`*.keystore` 已被 `.gitignore` 排除，推送前再确认 `git status` 不含它们。

## 2. 截图脱敏（2026-11-20 已核验）

`docs/screenshots/` 全部 7 张核验通过：均以 `SCRATCHPAD_DATA_DIR=/tmp/shot-*` 一次性数据目录拍摄，内容为演示语料（「大纲示例」、虚构笔记），无用户名、无真实文件路径、无设备信息。后续新增截图沿用同一纪律：**演示数据目录 + 虚构内容，禁用真实笔记与真实路径**。

## 3. 仓库卫生

- 根 `.gitignore`：`__pycache__/`、`dist/`、`tmp/`、`.workbuddy/`、Android 构建产物与签名材料。
- `docs/archive/` 只放历史文档，不放密钥、不含敏感数据（ENV_SETUP 中的机器名/路径已通用化）。
- 发布产物（deb / APK）走 GitHub Releases，不入库。

## 4. 文档口径

- 逐轮变更史唯一权威记录 = `docs/ANDROID_STAGE_STATUS.md` §5.4；其余文档头部只留版本戳 + 指针，不重复流水账。
- README 保持「概览 + 安装 + 构建 + 文档索引」，长篇手册在 `docs/DESKTOP_GUIDE.md`。
- 文档中的设备/环境表述用通用写法（「真机 A」「模拟器 Pixel_API36」），不写序列号。

## 5. 发布动作

1. `git init && git add -A` 后检查 `git status` 无构建产物/密钥/`__pycache__`。
2. 打 tag（如 `v1.16.0-desktop` / `v0.7.23-android` 或统一 tag）。
3. GitHub Releases 上传 `dist/*.deb` 与 `android/dist/*.apk`，附安装命令（deb：`sudo apt install ./…deb`；APK：`adb install -r …`）。
