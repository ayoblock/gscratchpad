#!/bin/bash
# 构建 DEB 安装包。用法：./packaging/build_deb.sh [输出目录]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$PROJECT_ROOT/dist}"
APP_ID="io.github.gscratchpad.Gscratchpad"
VERSION="1.17.0"
PKG="gscratchpad"
STAGING="$OUT_DIR/${PKG}_${VERSION}-1"

echo "==> 清理旧构建"
/bin/rm -rf "$STAGING" || true
# 更版自动清理：移除 dist 内除当前版本以外的全部旧产物（staging 树与 deb）。
# 仅按包名前缀匹配，不碰输出目录中的其它文件；rm 只落在 dist，风险面有限。
find "$OUT_DIR" -maxdepth 1 -name "${PKG}_*" ! -name "${PKG}_${VERSION}-1" \
    -exec /bin/rm -rf {} + 2>/dev/null || true

mkdir -p \
    "$STAGING/DEBIAN" \
    "$STAGING/usr/lib/gscratchpad/scratchpad" \
    "$STAGING/usr/bin" \
    "$STAGING/usr/share/gscratchpad/vendor" \
    "$STAGING/usr/share/applications" \
    "$STAGING/usr/share/dbus-1/services" \
    "$STAGING/usr/share/icons/hicolor/scalable/apps" \
    "$STAGING/usr/share/doc/$PKG"

echo "==> 复制源码"
cp "$PROJECT_ROOT/src/scratchpad/"*.py "$STAGING/usr/lib/gscratchpad/scratchpad/"

echo "==> 复制离线资源（mermaid / KaTeX / python-markdown）"
cp -r "$PROJECT_ROOT/vendor/js" "$STAGING/usr/share/gscratchpad/vendor/"
cp -r "$PROJECT_ROOT/vendor/markdown" "$STAGING/usr/share/gscratchpad/vendor/"
cp -r "$PROJECT_ROOT/vendor"/markdown-*.dist-info "$STAGING/usr/share/gscratchpad/vendor/"

echo "==> 复制桌面文件与图标"
cp "$PROJECT_ROOT/data/$APP_ID.desktop" "$STAGING/usr/share/applications/"
cp "$PROJECT_ROOT/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
   "$STAGING/usr/share/icons/hicolor/scalable/apps/"

# D-Bus service 文件：外部应用（如 Lectula）以 app.capture 调用时支持总线激活
# （实例未运行则由 dbus-daemon 以 --gapplication-service 拉起，常驻不弹窗）。
cat > "$STAGING/usr/share/dbus-1/services/$APP_ID.service" <<SERVICE
[D-BUS Service]
Name=$APP_ID
Exec=/usr/bin/gscratchpad --gapplication-service
SERVICE

echo "==> 生成启动器 /usr/bin/gscratchpad"
cat > "$STAGING/usr/bin/gscratchpad" <<'LAUNCHER'
#!/usr/bin/python3
import sys

sys.path.insert(0, "/usr/share/gscratchpad/vendor")
sys.path.insert(0, "/usr/lib/gscratchpad")

from scratchpad.application import main

sys.exit(main())
LAUNCHER
chmod 755 "$STAGING/usr/bin/gscratchpad"

cat > "$STAGING/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
# 刷新桌面数据库：让 Nautilus / GNOME Shell 立刻认得新的 desktop 文件
# 与 MimeType 声明，不必等它自己重扫或注销重登。
set -e

if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
fi
exit 0
POSTINST
chmod 755 "$STAGING/DEBIAN/postinst"

cat > "$STAGING/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
# 卸载后同步移除关联记录，避免「打开方式」里留下点不动的死条目。
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
fi
exit 0
POSTRM
chmod 755 "$STAGING/DEBIAN/postrm"

echo "==> 生成控制文件"
cat > "$STAGING/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION-1
Section: gnome
Priority: optional
Architecture: all
Installed-Size: $(du -sk "$STAGING" | cut -f1)
Depends: python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1,
 gir1.2-gtksource-5, gir1.2-webkit-6.0, gir1.2-javascriptcoregtk-6.0,
 python3-pygments, weasyprint
Recommends: fonts-noto-cjk, opencc, shfmt, black
Maintainer: Gscratchpad contributors <gscratchpad@localhost>
Description: 即时记事本：多标签、免保存、Markdown 预览、PDF 导出
 Gscratchpad 是一款原生 GTK4 桌面即时记事本。
 .
 - 打开即输入，无需手动保存（300ms 防抖自动落盘）
 - 关闭标签与退出均不弹保存提示，重启自动恢复全部标签
 - TXT / Markdown / HTML 多格式，支持语法高亮、源码/分屏/实时预览
 - 行号显示与源码折叠（Markdown 标题 / 缩进块 / 括号块）
 - Markdown 预览支持数学公式（KaTeX）与 Mermaid 流程图，全部本地离线渲染
 - 悬浮式侧边栏：笔记列表 / 文件夹 / 本机磁盘树 / Markdown 大纲
 - 支持拖放导入图片、导出 A4 PDF
 - 格式化排版（JSON/XML/HTML/Python/Bash）与中文简繁转换（opencc）
 - 数据保存在 ~/.local/share/gscratchpad（SQLite + 文件镜像 + 恢复日志）
CONTROL

cat > "$STAGING/usr/share/doc/$PKG/copyright" <<'COPYRIGHT'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: gscratchpad
Source: local build

Files: *
Copyright: 2026 Gscratchpad contributors
License: MIT
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
.
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Files: usr/share/gscratchpad/vendor/js/mermaid.min.js
Copyright: Copyright (c) mermaid.js contributors
License: MIT

Files: usr/share/gscratchpad/vendor/js/katex/*
Copyright: Copyright (c) Khan Academy
License: MIT

Files: usr/share/gscratchpad/vendor/markdown/*
Copyright: 2007-2026 Python Markdown contributors
License: BSD-3-Clause
COPYRIGHT

echo "==> 构建 DEB"
mkdir -p "$OUT_DIR"
dpkg-deb --root-owner-group --build "$STAGING" "$OUT_DIR/${PKG}_${VERSION}-1_all.deb"

# 构建成功的 staging 树不留盘（约 7 MB/版），失败时保留供排查
/bin/rm -rf "$STAGING"

echo "==> 完成：$OUT_DIR/${PKG}_${VERSION}-1_all.deb"
