#!/bin/bash
# 安装脚本：检查并安装 APT 依赖，然后安装 DEB 包。
# 用法：sudo ./scripts/install.sh [deb 文件路径]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 不传参时自动取 dist/ 里版本最高的包（此前硬编码了 1.0.0，版本一升就找不到）
if [ $# -ge 1 ]; then
    DEB="$1"
else
    DEB="$(ls -1 "$PROJECT_ROOT"/dist/gscratchpad_*_all.deb 2>/dev/null | sort -V | tail -1 || true)"
fi

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

DEPS=(
    python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
    gir1.2-gtksource-5 gir1.2-webkit-6.0 gir1.2-javascriptcoregtk-6.0
    python3-pygments fonts-noto-cjk
)

echo "==> 检查依赖（Ubuntu 26.04 LTS）"
MISSING=()
for dep in "${DEPS[@]}"; do
    if ! dpkg -s "$dep" >/dev/null 2>&1; then
        MISSING+=("$dep")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "==> 缺少依赖：${MISSING[*]}"
    $SUDO apt-get update
    $SUDO apt-get install -y "${MISSING[@]}"
else
    echo "==> 依赖已全部就绪"
fi

if [ -z "${DEB:-}" ] || [ ! -f "$DEB" ]; then
    echo "==> dist/ 里没有安装包，开始构建"
    "$PROJECT_ROOT/packaging/build_deb.sh"
    DEB="$(ls -1 "$PROJECT_ROOT"/dist/gscratchpad_*_all.deb | sort -V | tail -1)"
fi

echo "==> 安装 $DEB"
$SUDO apt-get install -y "$DEB"

echo "==> 更新桌面数据库"
$SUDO update-desktop-database >/dev/null 2>&1 || true
$SUDO gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true

echo "==> 安装完成。可从应用菜单启动 Gscratchpad，或执行：gscratchpad"
