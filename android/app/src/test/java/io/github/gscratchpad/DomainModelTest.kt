package io.github.gscratchpad

import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Folder
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.domain.model.SaveState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** domain/model 覆盖：格式/状态映射、字数统计（中英混排）、展示模型。 */
class DomainModelTest {

    @Test
    fun `format maps id and falls back to txt`() {
        assertEquals(Format.MD, Format.fromId("md"))
        assertEquals(Format.HTML, Format.fromId("html"))
        assertEquals(Format.TXT, Format.fromId("txt"))
        assertEquals(Format.TXT, Format.fromId("docx"))
        assertEquals(Format.TXT, Format.fromId(null))
        assertEquals("md", Format.MD.ext)
    }

    @Test
    fun `state maps id and falls back to open`() {
        assertEquals(DocState.OPEN, DocState.fromId("open"))
        assertEquals(DocState.CLOSED, DocState.fromId("closed"))
        assertEquals(DocState.OPEN, DocState.fromId("archived"))
        assertEquals(DocState.OPEN, DocState.fromId(null))
        assertEquals("closed", DocState.CLOSED.id)
    }

    @Test
    fun `char count equals content length`() {
        val doc = Document(id = "a", title = "t", format = Format.MD, content = "abc中文")
        assertEquals(5, doc.charCount)
    }

    @Test
    fun `word count counts cjk per char and latin per word`() {
        val doc = Document(
            id = "a",
            title = "t",
            format = Format.MD,
            content = "你好 world 再见 Android",
        )
        // CJK 4 字 + 拉丁 2 词
        assertEquals(6, doc.wordCount)
    }

    @Test
    fun `word count handles kana and blank content`() {
        val kana = Document(id = "b", title = "t", format = Format.TXT, content = "カタカナ")
        assertEquals(4, kana.wordCount)
        val empty = Document(id = "c", title = "t", format = Format.TXT)
        assertEquals(0, empty.wordCount)
        val spaces = Document(id = "d", title = "t", format = Format.TXT, content = "   \n\t  ")
        assertEquals(0, spaces.wordCount)
    }

    @Test
    fun `display models keep defaults`() {
        val folder = Folder("工作")
        assertEquals(0.0, folder.createdAt, 0.0)
        val state = SaveState("a", SaveState.Status.SAVING)
        assertEquals("saving", state.status.id)
        assertEquals("", state.message)
        assertTrue(Document(id = "x", title = "", format = Format.MD).folder.isEmpty())
    }
}
