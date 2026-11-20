package io.github.gscratchpad.domain.model

/** 文档格式。id 与桌面 schema 的 CHECK 约束取值一致。 */
enum class Format(val id: String, val ext: String) {
    TXT("txt", "txt"),
    MD("md", "md"),
    HTML("html", "html");

    companion object {
        fun fromId(id: String?): Format = entries.firstOrNull { it.id == id } ?: TXT
    }
}

enum class DocState(val id: String) {
    OPEN("open"),
    CLOSED("closed");

    companion object {
        fun fromId(id: String?): DocState = entries.firstOrNull { it.id == id } ?: OPEN
    }
}

/**
 * 与桌面 `store.Document` 字段一一对应。
 * 时间戳沿用桌面语义：REAL 秒（epoch）。
 */
data class Document(
    val id: String,
    val title: String,
    val format: Format,
    val content: String = "",
    val sortIndex: Int = 0,
    val state: DocState = DocState.OPEN,
    val revision: Long = 0L,
    val createdAt: Double = 0.0,
    val updatedAt: Double = 0.0,
    val folder: String = "",
    /** 「清除记录」标记：文档、正文、镜像全部保留，仅从最近列表隐藏（v4）。 */
    val recentHidden: Boolean = false,
    /** 最近一次打开时间（epoch 秒，v5）：首页「最近文档」按此倒序。 */
    val openedAt: Double = 0.0,
) {
    val charCount: Int get() = content.length

    /** 中英混排字数：CJK/假名按字计，其余按空白分隔的词计（与 `Document.word_count` 一致）。 */
    val wordCount: Int
        get() {
            var cjk = 0
            val latin = StringBuilder(content.length)
            for (ch in content) {
                val code = ch.code
                val isCjk = (code in 0x3040..0x30FF) ||
                    (code in 0x3400..0x9FFF) ||
                    (code in 0xF900..0xFAFF)
                if (isCjk) {
                    cjk++
                    latin.append(' ')
                } else {
                    latin.append(ch)
                }
            }
            return cjk + latin.toString().trim().split(Regex("\\s+")).count { it.isNotEmpty() }
        }
}

/** 供 UI 展示的保存状态（对应 `store.SaveState`）。 */
data class SaveState(
    val docId: String,
    val status: Status,
    val message: String = "",
    val timestamp: Double = 0.0,
) {
    enum class Status(val id: String) {
        SAVED("saved"),
        SAVING("saving"),
        ERROR("error"),
    }
}

data class Folder(val name: String, val createdAt: Double = 0.0)

data class PurgeReport(
    var purgedDocs: Int = 0,
    var purgedBytes: Long = 0L,
    var errors: MutableList<String> = mutableListOf(),
)

data class MaintenanceReport(
    var orphanNotes: Int = 0,
    var orphanNotesBytes: Long = 0L,
    var orphanAssets: Int = 0,
    var orphanAssetsBytes: Long = 0L,
    var orphanJournals: Int = 0,
    var staleMeta: Int = 0,
    var dbBytesBefore: Long = 0L,
    var dbBytesAfter: Long = 0L,
    var dbFreeBytes: Long = 0L,
    var vacuumed: Boolean = false,
    val errors: MutableList<String> = mutableListOf(),
)
