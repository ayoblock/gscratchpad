package io.github.gscratchpad.platform

import io.github.gscratchpad.data.AppPaths
import io.github.gscratchpad.data.AtomicFiles
import io.github.gscratchpad.data.DocumentDao
import io.github.gscratchpad.data.MirrorStore
import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.domain.model.Format
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * 云同步引擎（sync v1，语义规约 docs/SYNC_PROTOCOL.md，与桌面
 * `src/scratchpad/syncengine.py` 逐语义对应）。
 *
 * - [SyncPlanner.planSync] 为纯函数：与桌面端共用同一组夹具场景
 *   （SM-01…SM-11，见 JVM `SyncEngineTest`），保证双端合并判定一致。
 * - [SyncEngine.run] 为 IO 编排：WebDAV 拉推、资源补缺、dao 落库、
 *   冲突/删除败者保全到 `recovery/sync-<ts>/`、本地状态文件读写。
 *
 * 核心语义：
 * - 墓碑 = `deleted: {docId: 删除时间戳}` 随 manifest 传播；updated_at 新者胜。
 * - 双变冲突：updated_at 新者胜，败者正文保全；平局本地胜。
 * - assets 内容寻址（sha256 前 12 位），存在即跳过。
 */
object SyncProtocol {
    const val PROTOCOL = 1

    fun contentHash(text: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }

    fun foldersHash(folders: List<Pair<String, Double>>): String {
        val joined = folders.sortedBy { it.first }.joinToString("\n") { "${it.first}:${it.second}" }
        return contentHash(joined)
    }
}

/** 本地同步状态（设备本地文件 `sync-state.json`，永不出现在 docs 语义中）。 */
data class SyncState(
    var deviceId: String = "",
    var deviceName: String = "",
    /** docId -> 删除时间戳（墓碑）。 */
    val deleted: MutableMap<String, Double> = mutableMapOf(),
    /** docId -> 上次推送的 content_hash。 */
    var ownPushed: MutableMap<String, String> = mutableMapOf(),
    var ownFoldersHash: String = "",
    var ownPushedDeleted: MutableMap<String, Double> = mutableMapOf(),
    val ownAssetsPushed: MutableSet<String> = mutableSetOf(),
    /** docId -> 上次推送的 state（open/closed）。关闭/打开不改内容哈希，
     *  必须独立跟踪，否则关闭状态永不同步、对端「清理已关闭文档」清不到（R51）。 */
    val ownStates: MutableMap<String, String> = mutableMapOf(),
    /** peerId -> docId -> 上次应用的 content_hash（基线）。 */
    val peers: MutableMap<String, MutableMap<String, String>> = mutableMapOf(),
    var lastResult: String = "",
) {
    companion object {
        /** 墓碑保留期：90 天（用户拍板）。过期墓碑在收敛阶段清理，防止状态文件无限膨胀。 */
        const val TOMBSTONE_TTL_SECONDS: Long = 90L * 24 * 60 * 60

        fun load(file: File): SyncState {
            val state = SyncState()
            runCatching {
                val data = JSONObject(file.readText(Charsets.UTF_8))
                if (data.optInt("protocol", 0) != SyncProtocol.PROTOCOL) return state
                state.deviceId = data.optString("device_id")
                state.deviceName = data.optString("device_name")
                val deleted = data.optJSONObject("deleted")
                if (deleted != null) {
                    deleted.keys().forEach { state.deleted[it] = deleted.optDouble(it, 0.0) }
                }
                val pushed = data.optJSONObject("own_pushed")
                if (pushed != null) pushed.keys().forEach { state.ownPushed[it] = pushed.optString(it) }
                state.ownFoldersHash = data.optString("own_folders_hash")
                val pd = data.optJSONObject("own_pushed_deleted")
                if (pd != null) pd.keys().forEach { state.ownPushedDeleted[it] = pd.optDouble(it, 0.0) }
                val assets = data.optJSONArray("own_assets_pushed")
                if (assets != null) for (i in 0 until assets.length()) state.ownAssetsPushed.add(assets.optString(i))
                val ownStates = data.optJSONObject("own_states")
                if (ownStates != null) {
                    ownStates.keys().forEach { state.ownStates[it] = ownStates.optString(it) }
                }
                val peers = data.optJSONObject("peers")
                if (peers != null) {
                    peers.keys().forEach { peerId ->
                        val m = mutableMapOf<String, String>()
                        val docs = peers.optJSONObject(peerId)
                        docs?.keys()?.forEach { m[it] = docs.optString(it) }
                        state.peers[peerId] = m
                    }
                }
                state.lastResult = data.optString("last_result")
            }
            if (state.deviceId.isEmpty()) {
                state.deviceId = java.util.UUID.randomUUID().toString().replace("-", "")
            }
            if (state.deviceName.isEmpty()) {
                state.deviceName = android.os.Build.MODEL ?: "android"
            }
            return state
        }

        fun save(file: File, state: SyncState) {
            val deleted = JSONObject()
            state.deleted.forEach { (k, v) -> deleted.put(k, v) }
            val pushed = JSONObject()
            state.ownPushed.forEach { (k, v) -> pushed.put(k, v) }
            val pd = JSONObject()
            state.ownPushedDeleted.forEach { (k, v) -> pd.put(k, v) }
            val assetsArr = org.json.JSONArray()
            state.ownAssetsPushed.sorted().forEach { assetsArr.put(it) }
            val ownStates = JSONObject()
            state.ownStates.forEach { (k, v) -> ownStates.put(k, v) }
            val peers = JSONObject()
            state.peers.forEach { (peerId, docs) ->
                val m = JSONObject()
                docs.forEach { (k, v) -> m.put(k, v) }
                peers.put(peerId, m)
            }
            val payload = JSONObject()
                .put("protocol", SyncProtocol.PROTOCOL)
                .put("device_id", state.deviceId)
                .put("device_name", state.deviceName)
                .put("deleted", deleted)
                .put("own_pushed", pushed)
                .put("own_folders_hash", state.ownFoldersHash)
                .put("own_pushed_deleted", pd)
                .put("own_assets_pushed", assetsArr)
                .put("own_states", ownStates)
                .put("peers", peers)
                .put("last_result", state.lastResult)
            file.parentFile?.mkdirs()
            AtomicFiles.write(file, payload.toString().toByteArray(Charsets.UTF_8))
        }
    }

    /**
     * 墓碑 90 天过期清理（P2）：只删本设备登记的过期墓碑，不触碰 learned-from-peer 之外的数据。
     * 返回清理条数。清理后若对端仍持有该墓碑，下一轮 planSync 会重新学习——这是 tombstone
     * 的最终一致性代价，规约 §4 已注明。
     */
    fun expireTombstones(now: Double, ttlSeconds: Long = TOMBSTONE_TTL_SECONDS): Int {
        val cutoff = now - ttlSeconds
        var n = 0
        val it = deleted.iterator()
        while (it.hasNext()) {
            val entry = it.next()
            if (entry.value < cutoff) {
                // 同步移除 ownPushed：否则收敛阶段「ownPushed 有但本地无且无墓碑」会立即重建墓碑，
                // 使 TTL 形同虚设（expired 日志由调用方上报）。
                ownPushed.remove(entry.key)
                it.remove()
                n++
            }
        }
        val itp = ownPushedDeleted.iterator()
        while (itp.hasNext()) {
            if (itp.next().value < cutoff) { itp.remove() }
        }
        return n
    }

    fun addDeleted(docId: String, ts: Double? = null) {
        val stamp = ts ?: (System.currentTimeMillis() / 1000.0)
        val current = deleted[docId]
        if (current == null || stamp > current) deleted[docId] = stamp
        ownPushed.remove(docId)
    }

    fun removeDeleted(docId: String) {
        deleted.remove(docId)
        ownPushedDeleted.remove(docId)
    }
}

/** 对端 manifest 条目（manifest.json 的 docs[] 元素，键与桌面一致 snake_case）。 */
typealias PeerEntry = Map<String, Any?>

data class PeerManifest(
    val deviceId: String,
    val deviceName: String,
    /** docId -> manifest 条目（snake_case 键）。 */
    val docs: Map<String, PeerEntry>,
    /** docId -> 删除时间戳。 */
    val deleted: Map<String, Double>,
    val folders: List<Pair<String, Double>>,
    val exportedAt: Double,
)

data class LocalDocInfo(
    val hash: String,
    val revision: Long,
    val updatedAt: Double,
    /** R51：参与合并的本地 state；哈希相等但 state 有差异时仍需应用对端条目。 */
    val state: String = "open",
)

/**
 * 纯函数合并规划器（与桌面 plan_sync 逐语义对应；夹具 SM-01…SM-11 双端共用）。
 */
object SyncPlanner {
    /**
     * 平局哨兵：JVM 夹具 SM-01…SM-11 与桌面端共用（桌面端平局本地胜），默认传此值保持
     * 既有夹具断言不变；生产调用必须传入真实 [SyncState.deviceId] 才启用 P2 元组裁决。
     */
    const val TIE_LOCAL_WINS = "\uFFFF"

    data class Plan(
        val applies: List<Pair<String, PeerEntry>> = emptyList(),
        val preserveLocalBeforeApply: List<String> = emptyList(),
        val preservePeer: List<Pair<String, String>> = emptyList(),
        val deletes: List<String> = emptyList(),
        val folderMerge: List<Pair<String, Double>> = emptyList(),
        val undelete: List<String> = emptyList(),
        val tombstonesLearned: Map<String, Double> = emptyMap(),
        val newPeers: Map<String, Map<String, String>> = emptyMap(),
        val conflicts: Int = 0,
        val deleteVsEdit: Int = 0,
    )

    fun planSync(
        local: Map<String, LocalDocInfo>,
        ownPushed: Map<String, String>,
        ownDeleted: Map<String, Double>,
        peers: List<PeerManifest>,
        peerStates: Map<String, Map<String, String>>,
        now: Double,
        localDeviceId: String = TIE_LOCAL_WINS,
    ): Plan {
        val applies = mutableListOf<Pair<String, PeerEntry>>()
        val preserveLocal = mutableListOf<String>()
        val preservePeer = mutableListOf<Pair<String, String>>()
        val deletes = mutableListOf<String>()
        val undelete = mutableListOf<String>()
        val tombstones = mutableMapOf<String, Double>()
        val folderMerge = mutableListOf<Pair<String, Double>>()
        var conflicts = 0
        var deleteVsEdit = 0

        val workingDeleted = ownDeleted.toMutableMap()
        val workingLocal = local.toMutableMap()

        // ---- T：墓碑收集与删除传播
        for (peer in peers) {
            for ((docId, delTs) in peer.deleted) {
                val known = workingDeleted[docId]
                if (known != null) {
                    if (delTs > known) {
                        workingDeleted[docId] = delTs
                        tombstones[docId] = delTs
                    }
                    continue
                }
                val info = workingLocal[docId]
                if (info != null) {
                    if (info.updatedAt > delTs) {
                        // 本地文档比删除更新：文档胜（编辑/重建压过删除）
                        deleteVsEdit++
                        continue
                    }
                    deletes.add(docId)
                    workingLocal.remove(docId)
                }
                workingDeleted[docId] = delTs
                tombstones[docId] = delTs
            }
        }

        // ---- D：对端文档条目
        val newPeers = mutableMapOf<String, Map<String, String>>()
        for (peer in peers) {
            val baseline = peerStates[peer.deviceId] ?: emptyMap()
            val newBaseline = mutableMapOf<String, String>()
            for ((docId, entry) in peer.docs) {
                val peerHash = entry["content_hash"] as? String ?: continue
                val tDel = workingDeleted[docId]
                if (tDel != null) {
                    val updatedAt = (entry["updated_at"] as? Number)?.toDouble() ?: 0.0
                    if (updatedAt > tDel) {
                        // 对端文档比墓碑新：对端重建/编辑胜 → 恢复（规约 §4.3）
                        undelete.add(docId)
                        applies.add(peer.deviceId to entry)
                        workingLocal[docId] = LocalDocInfo(peerHash, (entry["revision"] as? Number)?.toLong() ?: 0L, updatedAt, entry["state"] as? String ?: "open")
                        workingDeleted.remove(docId)
                        newBaseline[docId] = peerHash
                    }
                    // 否则墓碑胜（陈旧条目）：跳过
                    continue
                }
                val localInfo = workingLocal[docId]
                if (localInfo == null) {
                    applies.add(peer.deviceId to entry)
                        workingLocal[docId] = LocalDocInfo(
                            peerHash,
                            (entry["revision"] as? Number)?.toLong() ?: 0L,
                            (entry["updated_at"] as? Number)?.toDouble() ?: 0.0,
                            entry["state"] as? String ?: "open",
                        )
                    newBaseline[docId] = peerHash
                    continue
                }
                val localHash = localInfo.hash
                if (peerHash == localHash) {
                    // R51：内容同源但 state 有差异（关闭/打开不改变内容哈希）→
                    // 以 updated_at LWW 裁决：仅当对端时间戳更新才应用其 state，
                    // 防止对端陈旧 manifest 把本机刚做的关闭/打开改回去。
                    val peerState = entry["state"] as? String ?: "open"
                    val peerUpdatedAt = (entry["updated_at"] as? Number)?.toDouble() ?: 0.0
                    if (peerState != localInfo.state && peerUpdatedAt > localInfo.updatedAt) {
                        applies.add(peer.deviceId to entry)
                        workingLocal[docId] = LocalDocInfo(peerHash, localInfo.revision, peerUpdatedAt, peerState)
                    }
                    newBaseline[docId] = peerHash
                    continue
                }
                val peerChanged = peerHash != baseline[docId]
                val localChanged = localHash != ownPushed[docId]
                if (peerChanged && localChanged) {
                    // 冲突（P2）：(updated_at, device_id) 字典序元组裁决，消灭平局歧义。
                    // 桌面夹具默认 localDeviceId=TIE_LOCAL_WINS（"\uFFFF" > 任何 hex deviceId），
                    // 平局仍本地胜；生产传真实 deviceId，平局由 deviceId 大者胜。
                    val peerUpdatedAt = (entry["updated_at"] as? Number)?.toDouble() ?: 0.0
                    val peerWins = peerUpdatedAt > localInfo.updatedAt ||
                        (peerUpdatedAt == localInfo.updatedAt && peer.deviceId > localDeviceId)
                    if (peerWins) {
                        preserveLocal.add(docId)
                        applies.add(peer.deviceId to entry)
                        workingLocal[docId] = LocalDocInfo(peerHash, (entry["revision"] as? Number)?.toLong() ?: 0L, peerUpdatedAt, entry["state"] as? String ?: "open")
                        newBaseline[docId] = peerHash
                    } else {
                        preservePeer.add(peer.deviceId to docId)
                    }
                    conflicts++
                } else if (peerChanged && !localChanged) {
                    applies.add(peer.deviceId to entry)
                        workingLocal[docId] = LocalDocInfo(
                            peerHash,
                            (entry["revision"] as? Number)?.toLong() ?: 0L,
                            (entry["updated_at"] as? Number)?.toDouble() ?: 0.0,
                            entry["state"] as? String ?: "open",
                        )
                    newBaseline[docId] = peerHash
                } else {
                    // 仅本地变（push 处理）或内容同源：仅刷新基线
                    newBaseline[docId] = baseline[docId] ?: localHash
                }
            }
            newPeers[peer.deviceId] = newBaseline
        }

        // ---- 文件夹合并
        val seen = mutableSetOf<String>()
        for (peer in peers) {
            for (folder in peer.folders) {
                if (seen.add(folder.first)) folderMerge.add(folder)
            }
        }

        return Plan(
            applies = applies,
            preserveLocalBeforeApply = preserveLocal,
            preservePeer = preservePeer,
            deletes = deletes,
            folderMerge = folderMerge,
            undelete = undelete,
            tombstonesLearned = tombstones,
            newPeers = newPeers,
            conflicts = conflicts,
            deleteVsEdit = deleteVsEdit,
        )
    }
}

/**
 * 传输抽象：引擎只依赖这五个操作。生产实现 [SyncDav]（HttpURLConnection，
 * Android 运行时支持 MKCOL/PROPFIND 自定义方法）；JVM 测试可注入内存实现
 * （桌面 JDK 的 HttpURLConnection 拒绝自定义方法，无法直连 stub WebDAV）。
 */
interface DavOps {
    fun put(path: String, data: ByteArray, contentType: String = "application/octet-stream")
    fun getOptional(path: String): ByteArray?
    fun get(path: String): ByteArray
    fun mkcolDeep(path: String)
    fun propfindChildren(path: String): List<String>
}

/**
 * 同步引擎 IO 编排。全部为阻塞调用，调用方必须在 IO 线程（仅应用打开时触发，
 * 无后台调度——用户拍板）。
 */
class SyncEngine(
    private val dao: DocumentDao,
    private val paths: AppPaths,
    private val dav: DavOps,
    private val log: (String) -> Unit = {},
) {
    data class Result(
        var ok: Boolean,
        var message: String,
        var applied: Int = 0,
        var deleted: Int = 0,
        var conflicts: Int = 0,
        /** 本轮生成的冲突文档篇数（P1：冲突败者从 recovery 文本改为可编辑文档）。 */
        var conflictDocs: Int = 0,
        var pushedDocs: Int = 0,
    )

    private val stateFile: File = File(paths.root, "sync-state.json")

    fun run(): Result {
        val result = Result(ok = false, message = "")
        try {
            runInner(result)
        } catch (e: SyncDavException) {
            result.message = "同步失败：${e.message}"
        } catch (e: Exception) {
            result.message = "同步失败：${e.message}"
        }
        return result
    }

    private fun runInner(result: Result) {
        val state = SyncState.load(stateFile)
        val all = dao.allDocuments(includeClosed = true)
        val local = all.associate {
            it.id to LocalDocInfo(SyncProtocol.contentHash(it.content), it.revision, it.updatedAt, it.state.id)
        }.toMutableMap()
        val folders = dao.folderRows().map { it.name to it.createdAt }

        // ---- 墓碑一致性收敛（必须在 pull 之前，语义同桌面）
        val nowTs = System.currentTimeMillis() / 1000.0
        for (docId in state.ownPushed.keys.toList()) {
            if (docId !in local && docId !in state.deleted) state.addDeleted(docId, nowTs)
        }
        for (docId in state.deleted.keys.toList()) {
            val info = local[docId] ?: continue
            if (info.updatedAt > state.deleted[docId]!!) {
                state.removeDeleted(docId)
            } else {
                val doc = dao.get(docId)
                if (doc != null) preserve(preserveDir(), "${docId}-deleted.${doc.format.ext}", doc.content)
                dao.delete(docId)
                paths.noteFile(docId, doc?.format ?: Format.TXT).delete()
                paths.assetDir(docId).deleteRecursively()
                local.remove(docId)
                result.deleted++
            }
        }

        // ---- 墓碑 90 天过期清理（P2）：清理后对端仍持有则下轮重新学习，最终一致。
        state.expireTombstones(nowTs)

        // ---- Pull
        dav.mkcolDeep("sync/${state.deviceId}")
        val peers = fetchPeerManifests(state)
        val plan = SyncPlanner.planSync(
            local, state.ownPushed, state.deleted, peers, state.peers, nowTs, state.deviceId,
        )

        val preserveDir = preserveDir()
        result.conflicts = plan.conflicts
        for (docId in plan.deletes) {
            val doc = dao.get(docId)
            if (doc != null) preserve(preserveDir, "${docId}-deleted.${doc.format.ext}", doc.content)
            dao.delete(docId)
            paths.assetDir(docId).deleteRecursively()
            result.deleted++
        }

        val docsCache = mutableMapOf<String, Map<String, String>?>()
        for ((peerId, entry) in plan.applies) {
            val content = peerDocContent(peerId, entry, docsCache) ?: continue
            val docId = entry["id"] as String
            if (docId in plan.preserveLocalBeforeApply) {
                dao.get(docId)?.let { existing ->
                    createConflictDoc(existing, "local", peerId, nowTs, result)
                }
            }
            dao.applyRemote(
                id = docId,
                title = entry["title"] as? String ?: "",
                format = Format.fromId(entry["format"] as? String),
                content = content,
                sortIndex = (entry["sort_index"] as? Number)?.toInt() ?: 0,
                state = DocState.fromId(entry["state"] as? String),
                revision = (entry["revision"] as? Number)?.toLong() ?: 0L,
                createdAt = (entry["created_at"] as? Number)?.toDouble() ?: 0.0,
                updatedAt = (entry["updated_at"] as? Number)?.toDouble() ?: 0.0,
                folder = entry["folder"] as? String ?: "",
            )
            paths.noteFile(docId, Format.fromId(entry["format"] as? String)).parentFile?.mkdirs()
            fetchPeerAssets(peerId, entry)
            result.applied++
        }

        for ((peerId, docId) in plan.preservePeer) {
            val entry = peers.firstOrNull { it.deviceId == peerId }?.docs?.get(docId) ?: continue
            val content = peerDocContent(peerId, entry, docsCache) ?: continue
            val loser = io.github.gscratchpad.domain.model.Document(
                id = docId,
                title = entry["title"] as? String ?: docId,
                format = Format.fromId(entry["format"] as? String),
                content = content,
                updatedAt = (entry["updated_at"] as? Number)?.toDouble() ?: nowTs,
            )
            createConflictDoc(loser, "peer", peerId, nowTs, result)
        }

        for ((name, createdAt) in plan.folderMerge) {
            dao.createFolder(name, createdAt)
        }

        for ((docId, ts) in plan.tombstonesLearned) state.addDeleted(docId, ts)
        for (docId in plan.undelete) state.removeDeleted(docId)
        state.peers.clear()
        state.peers.putAll(plan.newPeers.mapValues { it.value.toMutableMap() })
        for (peer in peers) state.peers.getOrPut(peer.deviceId) { mutableMapOf() }

        // ---- Push
        result.pushedDocs = push(state, folders, result)

        result.ok = true
        val conflictNote = if (result.conflictDocs > 0) "，冲突文档 ${result.conflictDocs}" else ""
        result.message = "同步完成：应用 ${result.applied}，删除 ${result.deleted}，冲突 ${result.conflicts}$conflictNote，推送 ${result.pushedDocs} 篇"
        state.lastResult = result.message
        SyncState.save(stateFile, state)
    }

    private fun preserveDir(): File =
        File(paths.recovery, "sync-${java.text.SimpleDateFormat("yyyyMMdd-HHmmss").format(java.util.Date())}")

    private fun preserve(dir: File, filename: String, content: String) {
        runCatching {
            dir.mkdirs()
            AtomicFiles.write(File(dir, filename), content.toByteArray(Charsets.UTF_8))
        }
    }

    /**
     * 冲突败者落地为可编辑冲突文档（P1，替代旧的 recovery 纯文本保全）。
     *
     * - 新文档用独立 UUID，标题带「(冲突 yyyyMMdd-HHmmss)」后缀，与胜者并存于文档列表，可被编辑/另存/删除。
     * - 正文首行加溯源注释（md/html 用 HTML 注释，txt 用 `#` 行），标明来源设备与原始文档 id。
     * - 同步属性按新文档参与下轮 push（自己的目录），因此其它设备也能看到该冲突副本。
     * - `format` 沿用败者；`folder` 清空（避免误归入胜者文件夹）；revision 从 0 起。
     */
    private fun createConflictDoc(
        loser: io.github.gscratchpad.domain.model.Document,
        side: String,
        peerId: String,
        nowTs: Double,
        result: Result,
    ) {
        runCatching {
            val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss").format(java.util.Date())
            val newId = java.util.UUID.randomUUID().toString().replace("-", "")
            val header = when (loser.format) {
                Format.TXT -> "# gs-sync-conflict: doc=${loser.id} loser=$side peer=$peerId at=$stamp\n\n"
                else -> "<!-- gs-sync-conflict: doc=${loser.id} loser=$side peer=$peerId at=$stamp -->\n\n"
            }
            val conflictDoc = io.github.gscratchpad.domain.model.Document(
                id = newId,
                title = "${loser.title} (冲突 $stamp)",
                format = loser.format,
                content = header + loser.content,
                sortIndex = 0,
                state = DocState.OPEN,
                revision = 0L,
                createdAt = nowTs,
                updatedAt = nowTs,
                folder = "",
            )
            dao.insert(conflictDoc)
            MirrorStore(paths).write(newId, conflictDoc.content, conflictDoc.format)
            result.conflictDocs++
        }
    }

    private fun fetchPeerManifests(state: SyncState): List<PeerManifest> {
        val peers = mutableListOf<PeerManifest>()
        for (name in dav.propfindChildren("sync")) {
            if (name == state.deviceId) continue
            val raw = dav.getOptional("sync/$name/manifest.json") ?: continue
            val data = runCatching { JSONObject(String(raw, Charsets.UTF_8)) }.getOrNull() ?: continue
            if (data.optInt("protocol", 0) != SyncProtocol.PROTOCOL) continue
            val docs = mutableMapOf<String, PeerEntry>()
            val docsArr = data.optJSONArray("docs")
            if (docsArr != null) {
                for (i in 0 until docsArr.length()) {
                    val entry = docsArr.optJSONObject(i) ?: continue
                    val map = mutableMapOf<String, Any?>()
                    entry.keys().forEach { k ->
                        // assets 在 JSON 里是数组：转成 List<String>，
                        // 否则 fetchPeerAssets 的 `as? List<String>` 必失败（资产永不同步）
                        map[k] = if (k == "assets") {
                            val arr = entry.optJSONArray(k)
                            (0 until (arr?.length() ?: 0)).mapNotNull { arr?.optString(it) }
                        } else {
                            entry.opt(k)
                        }
                    }
                    docs[entry.optString("id")] = map
                }
            }
            val deleted = mutableMapOf<String, Double>()
            val deletedObj = data.optJSONObject("deleted")
            if (deletedObj != null) {
                deletedObj.keys().forEach { deleted[it] = deletedObj.optDouble(it, 0.0) }
            } else {
                val arr = data.optJSONArray("deleted")
                if (arr != null) for (i in 0 until arr.length()) deleted[arr.optString(i)] = 0.0
            }
            val folders = mutableListOf<Pair<String, Double>>()
            val foldersArr = data.optJSONArray("folders")
            if (foldersArr != null) {
                for (i in 0 until foldersArr.length()) {
                    val f = foldersArr.optJSONObject(i) ?: continue
                    folders.add(f.optString("name") to f.optDouble("created_at", 0.0))
                }
            }
            peers.add(
                PeerManifest(
                    deviceId = data.optString("device_id", name),
                    deviceName = data.optString("device_name", name),
                    docs = docs,
                    deleted = deleted,
                    folders = folders,
                    exportedAt = data.optDouble("exported_at", 0.0),
                )
            )
        }
        return peers
    }

    private fun peerDocContent(
        peerId: String,
        entry: PeerEntry,
        cache: MutableMap<String, Map<String, String>?>,
    ): String? {
        if (peerId !in cache) {
            val raw = dav.getOptional("sync/$peerId/docs.zip")
            cache[peerId] = if (raw == null) null else {
                val contents = mutableMapOf<String, String>()
                java.util.zip.ZipInputStream(raw.inputStream()).use { zis ->
                    var e = zis.nextEntry
                    while (e != null) {
                        if (e.name.startsWith("docs/") && !e.isDirectory) {
                            contents[e.name.removePrefix("docs/")] = String(zis.readBytes(), Charsets.UTF_8)
                        }
                        e = zis.nextEntry
                    }
                }
                contents
            }
        }
        return cache[peerId]?.get(entry["id"] as String)
    }

    private fun fetchPeerAssets(peerId: String, entry: PeerEntry) {
        val docId = entry["id"] as String
        @Suppress("UNCHECKED_CAST")
        val assets = entry["assets"] as? List<String> ?: return
        for (name in assets) {
            val dest = File(paths.assetDir(docId), name)
            if (dest.isFile) continue
            val raw = runCatching { dav.get("sync/$peerId/assets/$docId/$name") }.getOrNull() ?: continue
            dest.parentFile?.mkdirs()
            AtomicFiles.write(dest, raw)
        }
    }

    private fun localAssetNames(docId: String): List<String> {
        val dir = paths.assetDir(docId)
        if (!dir.isDirectory) return emptyList()
        return dir.listFiles { f -> f.isFile && !f.name.startsWith(".") }
            ?.map { it.name }?.sorted() ?: emptyList()
    }

    private fun buildManifest(state: SyncState, docs: List<io.github.gscratchpad.domain.model.Document>, folders: List<Pair<String, Double>>): Pair<JSONObject, ByteArray> {
        val entries = org.json.JSONArray()
        val payloads = mutableMapOf<String, String>()
        for (doc in docs) {
            entries.put(
                JSONObject()
                    .put("id", doc.id)
                    .put("title", doc.title)
                    .put("format", doc.format.id)
                    .put("revision", doc.revision)
                    .put("updated_at", doc.updatedAt)
                    .put("created_at", doc.createdAt)
                    .put("sort_index", doc.sortIndex)
                    .put("state", doc.state.id)
                    .put("folder", doc.folder)
                    .put("content_hash", SyncProtocol.contentHash(doc.content))
                    .put("assets", org.json.JSONArray(localAssetNames(doc.id)))
            )
            payloads[doc.id] = doc.content
        }
        val deletedObj = JSONObject()
        state.deleted.forEach { (k, v) -> if (k !in payloads) deletedObj.put(k, v) }
        val foldersArr = org.json.JSONArray()
        folders.forEach { (n, ts) -> foldersArr.put(JSONObject().put("name", n).put("created_at", ts)) }
        val manifest = JSONObject()
            .put("protocol", SyncProtocol.PROTOCOL)
            .put("device_id", state.deviceId)
            .put("device_name", state.deviceName)
            .put("exported_at", System.currentTimeMillis() / 1000.0)
            .put("docs", entries)
            .put("deleted", deletedObj)
            .put("folders", foldersArr)
        val buf = java.io.ByteArrayOutputStream()
        java.util.zip.ZipOutputStream(buf).use { zos ->
            zos.putNextEntry(java.util.zip.ZipEntry("manifest.json"))
            zos.write(manifest.toString().toByteArray(Charsets.UTF_8))
            zos.closeEntry()
            for ((docId, text) in payloads) {
                zos.putNextEntry(java.util.zip.ZipEntry("docs/$docId"))
                zos.write(text.toByteArray(Charsets.UTF_8))
                zos.closeEntry()
            }
        }
        return manifest to buf.toByteArray()
    }

    private fun push(state: SyncState, folders: List<Pair<String, Double>>, result: Result): Int {
        val docs = dao.allDocuments(includeClosed = true)
        val currentHashes = docs.associate { it.id to SyncProtocol.contentHash(it.content) }
        for (docId in state.ownPushed.keys) {
            if (docId !in currentHashes && docId !in state.deleted) state.addDeleted(docId)
        }
        val currentFoldersHash = SyncProtocol.foldersHash(folders)
        val currentAssetKeys = docs.flatMap { doc ->
            localAssetNames(doc.id).map { "${doc.id}/$it" }
        }.toSet()
        val docsChanged = currentHashes != state.ownPushed
        val foldersChanged = currentFoldersHash != state.ownFoldersHash
        val deletedChanged = state.deleted != state.ownPushedDeleted
        val assetsChanged = currentAssetKeys != state.ownAssetsPushed
        // R51：关闭/打开只改 state 与 updated_at，content hash 不变——state 必须独立纳入
        // 变更检测，否则对端 manifest 永久 state=open，其「清理已关闭文档」清不到。
        val currentStates = docs.associate { it.id to it.state.id }
        val statesChanged = currentStates != state.ownStates
        if (!docsChanged && !foldersChanged && !deletedChanged && !assetsChanged && !statesChanged) return 0

        dav.mkcolDeep("sync/${state.deviceId}")
        val (manifest, docsZip) = buildManifest(state, docs, folders)

        val pushed = state.ownAssetsPushed.toMutableSet()
        for (doc in docs) {
            for (file in paths.assetDir(doc.id).listFiles { f -> f.isFile && !f.name.startsWith(".") } ?: emptyArray()) {
                val key = "${doc.id}/${file.name}"
                if (key in pushed) continue
                dav.put("sync/${state.deviceId}/assets/${doc.id}/${file.name}", file.readBytes())
                pushed.add(key)
            }
        }

        dav.put("sync/${state.deviceId}/docs.zip", docsZip, "application/zip")
        dav.put(
            "sync/${state.deviceId}/manifest.json",
            manifest.toString().toByteArray(Charsets.UTF_8),
            "application/json",
        )
        state.ownPushed = currentHashes.toMutableMap()
        state.ownFoldersHash = currentFoldersHash
        state.ownPushedDeleted = state.deleted.toMutableMap()
        state.ownStates.clear()
        state.ownStates.putAll(currentStates)
        state.ownAssetsPushed.clear()
        state.ownAssetsPushed.addAll(pushed)
        return currentHashes.size
    }
}
