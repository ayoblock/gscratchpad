package io.github.gscratchpad

import io.github.gscratchpad.platform.SaveAsPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * 「另存为」回归锁定：
 *  - #4 后缀被追加 .txt：MIME 必须是不触发扩展名推断的 application/octet-stream，文件名恰好一个 .md；
 *  - #5 另存写出空内容：新建文档时 text 为空但 editorLatest 有正文，必须取 editorLatest。
 */
class SaveAsPolicyTest {
    @Test
    fun `MIME 必须是不触发扩展名推断的中性类型`() {
        // text/plain 会把文件名改成 .txt（未命名.md.txt），text/markdown 会把用户手输的 .txt 改回 .md。
        // octet-stream 不推断扩展名，后缀完全由文件名决定。
        assertEquals("application/octet-stream", SaveAsPolicy.MIME)
        assertNotEquals("text/plain", SaveAsPolicy.MIME)
        assertNotEquals("text/markdown", SaveAsPolicy.MIME)
    }

    @Test
    fun `新建文档另存取编辑器实时正文而非空的 text`() {
        // 新建文档场景：editorLatest 有正文，text.value 仍是空串
        assertEquals("新建的正文", SaveAsPolicy.content("新建的正文", ""))
    }

    @Test
    fun `编辑器正文为空时才回退到 text`() {
        assertEquals("兜底正文", SaveAsPolicy.content("", "兜底正文"))
    }

    @Test
    fun `两者都空时返回空串`() {
        assertEquals("", SaveAsPolicy.content("", ""))
    }

    @Test
    fun `编辑器正文优先于 text 即使两者都非空`() {
        assertEquals("最新正文", SaveAsPolicy.content("最新正文", "过期正文"))
    }

    @Test
    fun `文件名补 md 后缀`() {
        assertEquals("未命名.md", SaveAsPolicy.fileName("未命名"))
    }

    @Test
    fun `文件名已有 md 后缀不重复追加`() {
        assertEquals("我的笔记.md", SaveAsPolicy.fileName("我的笔记.md"))
        // 大小写不敏感识别后缀，但不改写用户输入的大小写
        assertEquals("README.MD", SaveAsPolicy.fileName("README.MD"))
    }

    @Test
    fun `另存标题取文件名 stem 不含扩展名`() {
        assertEquals("未命名", SaveAsPolicy.savedTitle("未命名.md"))
        assertEquals("foo", SaveAsPolicy.savedTitle("foo.txt"))
        assertEquals("README", SaveAsPolicy.savedTitle("README.MD"))
    }

    @Test
    fun `无扩展名沿用整名 空 stem 回退整名`() {
        assertEquals("笔记", SaveAsPolicy.savedTitle("笔记"))
        assertEquals(".bashrc", SaveAsPolicy.savedTitle(".bashrc"))
    }
}
