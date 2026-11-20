package io.github.gscratchpad

import io.github.gscratchpad.platform.PreviewHtml
import org.junit.Assert.assertTrue
import org.junit.Test

/** R33：预览页「切换文档」浮层的 shell 产物断言（纯 JVM，不启 WebView）。 */
class PreviewHtmlDocsTest {

    private val shell = PreviewHtml.buildShell(dark = false, needsMath = false, needsMermaid = false)

    @Test
    fun `切换文档浮层DOM与样式存在`() {
        assertTrue(shell.contains("id=\"gs-docs\""))
        assertTrue(shell.contains("id=\"gs-docs-list\""))
        assertTrue(shell.contains("#gs-docs[hidden]"))
    }

    @Test
    fun `文档列表注入与浮层打开函数存在`() {
        assertTrue(shell.contains("window.gsSetDocs"))
        assertTrue(shell.contains("window.gsOpenDocs"))
        assertTrue(shell.contains("window.gsCloseDocs"))
    }

    @Test
    fun `点选文档回传id到桥`() {
        assertTrue(shell.contains("window.gscratchpad.switchDoc"))
    }

    @Test
    fun `浮层点空白关闭监听覆盖两个浮层`() {
        assertTrue(shell.contains("if (ol && !ol.hidden)"))
        assertTrue(shell.contains("if (dl && !dl.hidden)"))
    }
}
