package io.github.gscratchpad.domain.keys

/**
 * 物理键盘快捷键映射（方案附录 B 的 Android 侧解析层）。
 *
 * 与界面解耦：这里只把「Ctrl / Shift + 键名」解析为动作，Compose 侧负责取键名与执行。
 * 触屏主路径是工具栏按钮，物理键盘是第二通道。
 */
enum class KeyAction {
    NEW, CLOSE, FIND, REPLACE, PREVIEW, NEXT_TAB, PREV_TAB, PALETTE, OUTLINE,
    SAVE, SAVE_AS, OPEN, TOGGLE_SPLIT, HELP, IMAGE, RENAME,
}

object Shortcuts {

    /** keyName 取 [androidx.compose.ui.input.key.Key] 的英文名（`Key.N` → "N"）。 */
    fun resolve(ctrl: Boolean, shift: Boolean, keyName: String): KeyAction? {
        if (!ctrl) return null
        val k = keyName.uppercase()
        return when {
            shift && k == "P" -> KeyAction.PREVIEW
            shift && k == "H" -> KeyAction.REPLACE
            shift && k == "I" -> KeyAction.PALETTE
            shift && k == "O" -> KeyAction.OUTLINE
            shift && k == "F" -> null
            shift && k == "S" -> KeyAction.SAVE_AS
            shift && (k == "SLASH" || k == "/") -> KeyAction.HELP
            // Ctrl+Shift+TAB 上一文档；TAB 单独为下一文档（与帮助文案一致）
            shift && k == "TAB" -> KeyAction.PREV_TAB
            k == "TAB" -> KeyAction.NEXT_TAB
            k == "N" -> KeyAction.NEW
            k == "W" -> KeyAction.CLOSE
            k == "F" -> KeyAction.FIND
            k == "H" -> KeyAction.REPLACE
            k == "S" -> KeyAction.SAVE
            k == "O" -> KeyAction.OPEN
            k == "D" -> KeyAction.TOGGLE_SPLIT
            k == "I" -> KeyAction.IMAGE
            else -> null
        }
    }

    /** 不依赖 Ctrl 的单键（F1/F2/F9），物理键盘为一等交互时直接生效。 */
    fun resolvePlain(keyName: String): KeyAction? = when (keyName.uppercase()) {
        "F1" -> KeyAction.HELP
        "F2" -> KeyAction.RENAME
        "F9" -> KeyAction.TOGGLE_SPLIT
        else -> null
    }
}
