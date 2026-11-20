package io.github.gscratchpad.platform

import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction

enum class NewlineStyle(val sequence: String) { LF("\n"), CRLF("\r\n") }

data class TextStyle(val charset: Charset, val hasBom: Boolean, val newline: NewlineStyle)

data class DecodedText(
    val text: String,
    val style: TextStyle,
)

/**
 * 文本编解码（方案 §5.3）：UTF-8 / GB18030 自动识别，保留 BOM 与换行风格。
 * 纯逻辑，可在 JVM 上逐条回归。
 */
object TextCodec {

    private val UTF8_BOM = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())

    fun decode(bytes: ByteArray): DecodedText {
        val hasBom = bytes.size >= 3 && bytes.copyOfRange(0, 3).contentEquals(UTF8_BOM)
        val body = if (hasBom) bytes.copyOfRange(3, bytes.size) else bytes

        var charset: Charset
        var text: String
        try {
            text = strictDecode(body, Charsets.UTF_8)
            charset = Charsets.UTF_8
        } catch (_: CharacterCodingException) {
            val gb = Charset.forName("GB18030")
            text = strictDecode(body, gb)
            charset = gb
        }
        // 编辑期统一用 LF；写回时按 style.newline 还原
        val normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return DecodedText(normalized, TextStyle(charset, hasBom, detectNewline(text)))
    }

    fun encode(text: String, style: TextStyle): ByteArray {
        val normalized = normalizeNewlines(text, style.newline)
        val body = normalized.toByteArray(style.charset)
        return if (style.hasBom && style.charset == Charsets.UTF_8) UTF8_BOM + body else body
    }

    /** 二进制判定：含 NUL 字节，或长度超过 2 MB 且解码后替换字符占比过高。 */
    fun looksBinary(bytes: ByteArray): Boolean {
        if (bytes.any { it == 0.toByte() }) return true
        if (bytes.size <= 2 * 1024 * 1024) return false
        val probe = bytes.copyOfRange(0, minOf(bytes.size, 4096))
        val decoded = String(probe, Charsets.ISO_8859_1)
        val control = decoded.count { it.code < 0x09 }
        return control > probe.size / 20
    }

    private fun strictDecode(bytes: ByteArray, charset: Charset): String {
        val decoder = charset.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        return decoder.decode(ByteBuffer.wrap(bytes)).toString()
    }

    private fun detectNewline(text: String): NewlineStyle {
        val crlf = Regex("\r\n").findAll(text).count()
        val loneLf = text.count { it == '\n' } - crlf
        return if (crlf > 0 && crlf >= loneLf) NewlineStyle.CRLF else NewlineStyle.LF
    }

    private fun normalizeNewlines(text: String, style: NewlineStyle): String {
        val lf = text.replace("\r\n", "\n").replace("\r", "\n")
        return if (style == NewlineStyle.CRLF) lf.replace("\n", "\r\n") else lf
    }
}
