package io.github.gscratchpad.platform

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * R54：锁住 esbuild 产物里的编辑栏（Obsidian 同款）、选区操作条与桥方法。
 * 编辑器 UI 全部在 WebView 页内，Compose 仪器测试看不到这些控件，只能对产物做断言。
 */
class EditorAssetTest {

    private fun assetHtml(): String {
        val candidates = listOf(
            File("src/main/assets/editor/index.html"),
            File("app/src/main/assets/editor/index.html"),
        )
        val file = candidates.firstOrNull { it.exists() }
            ?: throw AssertionError("未找到 assets/editor/index.html（cwd=${System.getProperty("user.dir")}）")
        return file.readText()
    }

    @Test
    fun 编辑栏十六个按钮齐全() {
        val html = assetHtml()
        assertTrue("缺少编辑栏容器", html.contains("id=\"toolbar\""))
        listOf(
            "undo", "redo", "h1", "h2", "h3", "bold", "italic", "strike", "hl",
            "icode", "quote", "ul", "ol", "task", "link", "cblock",
        ).forEach {
            assertTrue("缺少编辑栏按钮 $it", html.contains("data-tb=\"$it\""))
        }
    }

    @Test
    fun 选区操作条四按钮且不含撤销重做() {
        val html = assetHtml()
        assertTrue("缺少选区操作条容器", html.contains("id=\"selbar\""))
        listOf("copy", "cut", "paste", "selectAll").forEach {
            assertTrue("缺少选区操作条按钮 $it", html.contains("data-sel=\"$it\""))
        }
        assertFalse("撤销不应在选区操作条（已移入编辑栏）", html.contains("data-sel=\"undo\""))
        assertFalse("重做不应在选区操作条（已移入编辑栏）", html.contains("data-sel=\"redo\""))
    }

    @Test
    fun 长按手柄与系统选择禁用已入包() {
        val html = assetHtml()
        assertTrue("缺少自绘手柄", html.contains("id=\"handle-a\"") && html.contains("id=\"handle-b\""))
        assertTrue("未禁用系统文本选择", html.contains("user-select:none") || html.contains("user-select: none"))
        // minify 会混淆内部函数名，只能断言保留标识：触摸监听与 window 桥属性
        assertTrue("缺少长按触摸监听", html.contains("touchstart"))
        assertTrue("缺少编辑栏动作桥", html.contains("toolbarAct"))
    }

    @Test
    fun 选区与撤销桥方法已入包() {
        val html = assetHtml()
        listOf(
            "NativeEditor.selection",
            "NativeEditor.setSelection",
            "NativeEditor.undo",
            "NativeEditor.redo",
            "NativeEditor.toolbarAct",
            "NativeEditor.copySelection",
            "NativeEditor.cutSelection",
            "NativeEditor.pasteSelection",
            "NativeEditor.selfCheckEdit",
        ).forEach { assertTrue("缺少桥方法 $it", html.contains(it)) }
    }

    @Test
    fun 文档装载不进入撤销历史() {
        assertTrue("setDoc 必须标注 addToHistory=false", assetHtml().contains("addToHistory"))
    }
}
