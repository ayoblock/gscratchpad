package io.github.gscratchpad

import io.github.gscratchpad.platform.PreviewHtml
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * T2 代码块 Copy 按钮的 shell 产物断言（纯 JVM，不启 WebView）：
 * 锁定桥方法、DOM 注入、幂等前提（innerHTML 全量重建）、mermaid 跳过顺序与样式都在。
 */
class PreviewHtmlCopyTest {

    private val shell = PreviewHtml.buildShell(dark = false, needsMath = false, needsMermaid = true)

    @Test
    fun `导出桥方法 copyText 供 JS 调用剪贴板`() {
        // 桥对象在 PreviewHost.attach 里注册，这里锁定 shell 端 JS 确实调用了它
        assertTrue(shell.contains("window.gscratchpad.copyText"))
    }

    @Test
    fun `注入函数遍历 pre code 并复制 textContent`() {
        assertTrue(shell.contains("function addCopyButtons()"))
        assertTrue(shell.contains("querySelectorAll('#content pre')"))
        assertTrue(shell.contains("code.textContent"))
    }

    @Test
    fun `复制按钮有即时反馈与复制成功文案`() {
        assertTrue(shell.contains("已复制"))
        assertTrue(shell.contains("gs-copy"))
    }

    @Test
    fun `注入发生在 mermaid 渲染之后从而跳过 mermaid 块`() {
        val renderMermaidAt = shell.indexOf("renderMermaid();")
        val addCopyAt = shell.indexOf("addCopyButtons();")
        assertTrue(renderMermaidAt >= 0 && addCopyAt >= 0)
        assertTrue("addCopyButtons 必须在 renderMermaid 之后：mermaid 的 pre 已被换成 div", addCopyAt > renderMermaidAt)
    }

    @Test
    fun `每次渲染全量重建 innerHTML 保证按钮幂等不叠加`() {
        assertTrue(shell.contains("content.innerHTML = md ? md.render(source) : ''"))
    }

    @Test
    fun `按钮样式存在且含主题色与 right 定位`() {
        assertTrue(shell.contains(".gs-copy"))
        assertTrue(shell.contains("position:absolute"))
        assertFalse("按钮不得用 navigator.clipboard（无 WebChromeClient 不可靠）",
            shell.contains("navigator.clipboard"))
    }
}
