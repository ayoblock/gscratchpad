package io.github.gscratchpad.domain

import org.json.JSONArray
import org.json.JSONObject

/**
 * 「切换文档」浮层的列表数据序列化（R33）。
 *
 * 把当前文档列表 + 激活 id 编成页内 WebView 可直接消费的 JSON 数组：
 * `[{"id":"...","title":"...","active":true}, ...]`。
 * 保持传入顺序（主页「最近/全部」口径，通常按 opened_at 倒序），
 * 激活项用 active 标记供页内高亮。纯函数便于 JVM 单测。
 */
object DocListJson {
    data class Item(val id: String, val title: String, val active: Boolean)

    /** 序列化文档列表。ids/titles 一一对应，activeId 命中者标记 active。 */
    fun serialize(ids: List<String>, titles: List<String>, activeId: String?): String {
        val arr = JSONArray()
        for (i in ids.indices) {
            val title = titles.getOrNull(i).orEmpty().ifBlank { "未命名" }
            arr.put(
                JSONObject()
                    .put("id", ids[i])
                    .put("title", title)
                    .put("active", ids[i] == activeId),
            )
        }
        return arr.toString()
    }
}
