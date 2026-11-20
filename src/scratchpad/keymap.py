"""全局快捷键表（核心动作）。

单独成模块是为了让 `window.py` 能在不反向导入 `application.py`（会循环）的前提下
判断“这个加速键已经被谁占用”。键为动作名，值为 GTK 加速键列表。
"""

from __future__ import annotations

ACCELS: dict[str, list[str]] = {
    "win.new-tab": ["<Control>N"],
    "win.close-tab": ["<Control>W"],
    "win.next-tab": ["<Control>Tab"],
    "win.prev-tab": ["<Control><Shift>Tab"],
    "win.find": ["<Control>F"],
    "win.replace": ["<Control>H"],
    "win.undo": ["<Control>Z"],
    "win.redo": ["<Control><Shift>Z", "<Control>Y"],
    "win.open-file": ["<Control>O"],
    "win.save-file": ["<Control>S"],
    "win.toggle-mode": ["<Control><Shift>P"],
    "win.cycle-writing-mode": ["<Control><Shift>M"],
    "win.toggle-typewriter": ["<Control><Shift>T"],
    "win.format-doc": ["<Control><Shift>I"],
    "win.rename-tab": ["F2"],
    "win.toggle-sidebar": ["F9"],
    "win.command-menu": ["<Control>K"],
    "win.manage-snippets": ["<Control><Shift>E"],
    "win.column-take": ["<Control><Shift>K"],
    "app.quit": ["<Control>Q"],
}
for _i in range(1, 10):
    ACCELS[f"win.goto-{_i}"] = [f"<Control>{_i}"]

# 冲突提示里的人话说明
LABELS: dict[str, str] = {
    "win.new-tab": "新建标签",
    "win.close-tab": "关闭标签",
    "win.next-tab": "下一个标签",
    "win.prev-tab": "上一个标签",
    "win.find": "查找",
    "win.replace": "查找与替换",
    "win.undo": "撤销",
    "win.redo": "重做",
    "win.open-file": "打开本机文件",
    "win.save-file": "保存到本机文件",
    "win.toggle-mode": "切换源码 / 预览",
    "win.cycle-writing-mode": "循环切换写作模式宽度",
    "win.toggle-typewriter": "打字机模式（光标行固定于视口百分比处）",
    "win.format-doc": "格式化排版",
    "win.rename-tab": "重命名标签",
    "win.toggle-sidebar": "显示 / 隐藏侧边栏",
    "win.command-menu": "命令菜单",
    "win.manage-snippets": "管理片段",
    "win.column-take": "按列提取",
    "app.quit": "退出",
}


def label_for(action: str) -> str:
    if action in LABELS:
        return LABELS[action]
    if action.startswith("win.goto-"):
        return f"切换到标签 {action.rsplit('-', 1)[-1]}"
    return action
