#!/bin/bash
# 卸载脚本：移除 DEB 包（用户数据 ~/.local/share/gscratchpad 不受影响）。
# 用法：sudo ./scripts/uninstall.sh [--purge-data]
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

echo "==> 卸载 gscratchpad"
$SUDO apt-get remove -y gscratchpad || $SUDO dpkg -r gscratchpad || true
$SUDO update-desktop-database >/dev/null 2>&1 || true

if [ "${1:-}" = "--purge-data" ]; then
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gscratchpad"
    echo "警告：将永久删除用户数据目录 $DATA_DIR（包含所有笔记）。"
    read -r -p "确认删除？输入 yes 继续：" answer
    if [ "$answer" = "yes" ]; then
        rm -rf "$DATA_DIR"
        echo "==> 用户数据已删除"
    else
        echo "==> 已保留用户数据：$DATA_DIR"
    fi
else
    echo "==> 用户数据保留在 ~/.local/share/gscratchpad"
    echo "    如需彻底删除，执行：sudo ./scripts/uninstall.sh --purge-data"
fi

echo "==> 卸载完成"
