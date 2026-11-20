package io.github.gscratchpad

import io.github.gscratchpad.platform.NewlineStyle
import io.github.gscratchpad.platform.TextCodec
import io.github.gscratchpad.platform.TextStyle
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.charset.Charset

/** §5.3 规则 1 的字节级回归：编码 / BOM / 换行三种属性写回后必须原样还原。 */
class TextCodecTest {

    @Test
    fun `utf8 roundtrip is byte identical`() {
        val original = "第一行\n第二行\n".toByteArray(Charsets.UTF_8)
        val decoded = TextCodec.decode(original)
        assertEquals(Charsets.UTF_8, decoded.style.charset)
        assertFalse(decoded.style.hasBom)
        assertEquals(NewlineStyle.LF, decoded.style.newline)
        assertArrayEquals(original, TextCodec.encode(decoded.text, decoded.style))
    }

    @Test
    fun `utf8 bom is preserved`() {
        val body = "带 BOM 的文本".toByteArray(Charsets.UTF_8)
        val bom = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())
        val original = bom + body

        val decoded = TextCodec.decode(original)
        assertTrue(decoded.style.hasBom)
        assertEquals("带 BOM 的文本", decoded.text)
        assertArrayEquals(original, TextCodec.encode(decoded.text, decoded.style))
    }

    @Test
    fun `crlf is preserved on write back`() {
        val original = "a\r\nb\r\nc\r\n".toByteArray(Charsets.UTF_8)
        val decoded = TextCodec.decode(original)
        assertEquals(NewlineStyle.CRLF, decoded.style.newline)
        assertEquals("a\nb\nc\n", decoded.text)
        assertArrayEquals(original, TextCodec.encode(decoded.text, decoded.style))
    }

    @Test
    fun `gb18030 is detected and preserved`() {
        val gb = Charset.forName("GB18030")
        val original = "简体中文与标点，测试。".toByteArray(gb)
        val decoded = TextCodec.decode(original)
        assertEquals(gb, decoded.style.charset)
        assertEquals("简体中文与标点，测试。", decoded.text)
        assertArrayEquals(original, TextCodec.encode(decoded.text, decoded.style))
    }

    @Test
    fun `bom plus crlf roundtrips`() {
        val bom = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())
        val original = bom + "x\r\ny".toByteArray(Charsets.UTF_8)
        val decoded = TextCodec.decode(original)
        val style = TextStyle(Charsets.UTF_8, true, NewlineStyle.CRLF)
        assertArrayEquals(original, TextCodec.encode(decoded.text, style))
    }

    @Test
    fun `nul byte is treated as binary`() {
        assertTrue(TextCodec.looksBinary(byteArrayOf(0x61, 0x00, 0x62)))
        assertFalse(TextCodec.looksBinary("普通文本".toByteArray(Charsets.UTF_8)))
    }
}
