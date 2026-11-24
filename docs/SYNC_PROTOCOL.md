# GScratchpad 云同步协议（sync v1）

状态：active（2026-11-25） · 适用：桌面 ≥1.17.0 / Android ≥0.9.0 · 传输：WebDAV

本规约是桌面端（`src/scratchpad/syncengine.py`）与 Android 端
（`android/.../platform/SyncEngine.kt`）两个实现的唯一事实来源。合并语义的任何
变更必须先改本文件并同步两侧实现与测试夹具（`tests/test_sync_merge.py` 与
Android JVM 单测共用同一组夹具数据）。

## 1. 远端布局

用户配置一个 WebDAV 基目录（含可选内嵌用户名，如
`http://admin@10.42.239.55:5244/dav/hdd/test`）。布局：

```
<base>/gscratchpad-desktop.zip          # 桌面自动备份（整包快照，仅桌面写）
<base>/gscratchpad-cloud.zip            # Android 云备份（R35 现有功能，仅 Android 写）
<base>/sync/<device-id>/manifest.json   # 该设备全量文档索引（仅该设备写）
<base>/sync/<device-id>/docs.zip        # 该设备全量正文快照（仅该设备写）
<base>/sync/<device-id>/assets/<docId>/<name>   # 不可变 blob（仅该设备写）
```

核心不变量：**每台设备只写自己的目录，只读别人的**——结构上消灭并发写冲突
（方案 B 哲学的延伸）。`gscratchpad-*.zip` 备份通道与 sync 通道互不干扰；
恢复时可导入任一 zip。

## 2. manifest.json

```json
{
  "protocol": 1,
  "device_id": "uuid4hex",
  "device_name": "hostname",
  "exported_at": 1764000000.0,
  "docs": [
    {"id": "...", "title": "...", "format": "md", "revision": 12,
     "updated_at": 1764000000.0, "created_at": 0.0,
     "sort_index": 0, "state": "open", "folder": "",
     "content_hash": "sha256hex", "assets": ["4d9cae2d5fcc.jpg"]}
  ],
  "deleted": {"doc_id": 1764000000.0},
  "folders": [{"name": "...", "created_at": 0.0}]
}
```

- `content_hash` = SHA-256(content UTF-8) hex。
- `deleted` 为墓碑表：`{doc_id: 删除时间戳}`（见 §4）。文档与墓碑统一按
  `updated_at` 新者胜裁决——文档比墓碑新则文档胜（编辑/重建压过删除），
  墓碑不旧于文档则删除胜（删除传播）。
- `folders` 同步；**meta 一律不同步**（两端 meta 全部为设备本地状态：窗口几何、
  游标、source_path、ext:、fs_root、视图模式等）。

## 3. docs.zip

zip 结构（与 Android `BackupExporter` 工具链无依赖，独立生成）：

```
manifest.json   # 同 §2，自描述
docs/<doc_id>   # 正文原文（UTF-8）
```

assets 不进 docs.zip：逐文件 PUT 到 `assets/<docId>/<name>`，文件名两端同构
（SHA-256 前 12 位 + 小写扩展名，内容寻址不可变），同步即补缺、天然免冲突。

## 4. 墓碑与删除传播

各设备在本地 `sync-state.json` 维护 `deleted: {doc_id: 删除时间戳}`（设备
本地，不入 db、不入版本控制）。统一裁决：**`updated_at` 新者胜**。

1. 本地删除文档（`delete` / `purge_closed`）→ `{id: 删除时刻}` 加入墓碑表
   （删除回调 + push 阶段隐式发现双重保障）。
2. 应用对端墓碑：本地文档 `updated_at` ≤ 墓碑时间 → 删除生效，正文先保全到
   `recovery/sync-<ts>/<doc_id>-deleted.<ext>`（安全网）；本地文档更新 →
   文档胜，本地保留并在下轮 push 压过该墓碑。
3. 本地墓碑 + 对端 manifest docs 条目：条目 `updated_at` > 墓碑时间 → 对端
   重建/编辑胜，恢复文档并撤销本地墓碑；否则陈旧条目跳过（防复活）。
4. 本地重建同 id 文档（恢复备份等）→ 墓碑撤销（引擎收敛阶段处理）。

不修改两端 db schema（无 deleted_at 列）：删除即真实删除 + 带时间戳墓碑
传播，避免 v4/v6 迁移与 CHECK 约束变更。已知边界：从备份恢复的旧文档
（updated_at 早于墓碑）会被较新的删除收敛，内容保全在 recovery/ 可找回。

## 5. 同步算法

本地状态文件 `<data_root>/sync-state.json`：

```json
{"protocol": 1, "device_id": "...", "device_name": "...",
 "deleted_ids": [...],
 "own_pushed": {"doc_id": "content_hash", ...},
 "own_folders_hash": "sha256hex",
 "peers": {"peer_id": {"doc_id": "content_hash", ...}},
 "last_result": "..."}
```

单次同步（后台线程，全程不碰 UI 线程；db 经 store 工作线程队列）：

1. **Pull**：PROPFIND `<base>/sync/`（Depth:1）枚举 peer 目录 → 逐 peer
   GET `manifest.json` → 对每个 doc 三态判定（基线 = `peers[peer][id]`，
   本地现状 = 当前 content_hash）：
   - 仅远端变 → 应用（§6）。
   - 双变（远端 ≠ 基线 且 本地 ≠ own_pushed 且 本地 ≠ 远端）→ 冲突（§7）。
   - 内容 hash 相等 → 仅刷新基线。
   - 本地 `deleted_ids` ∩ 对端 `docs` → 恢复（§4.3）。
   - 对端 `deleted` ∩ 本地现存 → 删除传播（§4.2）。
   - 对端 folders 变化 → 合并 folders 表（INSERT OR IGNORE）。
2. **Push**：对比当前本地全部 docs/folders 与 `own_pushed`/`own_folders_hash`；
   有差异 → 上传新 assets → 重写 docs.zip → 重写 manifest.json → 更新
   `own_pushed`。无差异且远端 manifest 本地已记录 → 跳过上传。
3. 写回 `sync-state.json`（原子写），记录 last_result 供状态行展示。

## 6. 应用远端文档

经 store 工作线程 `apply_sync` 任务：

- INSERT（本地不存在且非墓碑冲突）或 UPSERT：`revision = max(local, peer) + 1`，
  `updated_at`/`created_at`/`title`/`format`/`sort_index`/`state`/`folder`
  以对端为准；写 notes/ 镜像。
- assets：对端 manifest 条目 `assets` 列表中本地缺失的文件逐个 GET 落盘到
  `assets/<docId>/<name>`（存在且大小一致则跳过）。
- folders：`INSERT OR IGNORE INTO folders`。

## 7. 冲突

- 判定：双变且 `local_hash != peer_hash`。
- 胜者：`updated_at` 较新者；相等（同一编辑回传等场景）时以本地为胜者。
- 败者保全：败者正文写入 `recovery/sync-<时间戳>/<doc_id>-<local|peer>.<ext>`，
  文件头两行注释标注 `<!-- sync-conflict: doc=<id> winner=<src> at=<ts> -->`
  （txt/html 无 HTML 注释语法时仅文件名承担溯源）。
- 胜者按 §6 应用或留在本地等待 push。

## 8. 传输要求

- 方法：PUT / GET / HEAD / PROPFIND（Depth:1）/ MKCOL；Basic 认证。
- URL 允许内嵌用户名 `http://user@host/path`，解析后拆为独立 user 字段；
  密码单独存储（桌面 libsecret 优先、meta 明文回退；Android SharedPreferences，
  与 R35 现状一致）。
- 超时：连接 12s / 读取 30s（与 R35 CloudBackup 一致）；网络错误/5xx 重试 1 次。
- MKCOL 逐级创建缺失目录；405/已存在视为成功。
- HEAD 不可用（部分服务器）时降级为 GET 处理。

## 9. 触发

- 桌面：启动后延迟 15s、内容变更防抖 10s、定时（默认 5 分钟）、窗口关闭前 flush。
- Android：仅应用打开时（onResume，flush 后触发）；无后台调度（用户拍板）。
- 自动备份（`gscratchpad-desktop.zip`）：桌面定时默认 30 分钟 + 关闭时，
  仅 db fingerprint（文档数 + max(revision,updated_at)）变化时上传。

## 10. 一致性夹具

合并语义以纯函数实现（输入：本地 docs、own_pushed、peer manifest、基线；
输出：apply/conflict/delete 决策列表），两侧共用同一组夹具
（`tests/test_sync_merge.py` 的 JSON 夹具 = Android
`SyncEngineTest` 资源），保证双端判定逐字段一致。

## 11. 实现与验证状态（2026-11-25）

- 桌面：`src/scratchpad/syncengine.py` + `webdav.py`（v1.17.0 落地）。
- Android：`platform/SyncDav.kt` + `platform/SyncEngine.kt`（0.9.0 落地，
  引擎经 `DavOps` 接口解耦以便 JVM 测试注入内存传输）。
- 夹具：桌面 `tests/test_sync_merge.py`（SM-01…SM-11）= Android
  `SyncEngineTest` 同名场景，逐字段对应。
- 已验证：桌面 239 例、Android 223 例全绿；真实 AList 服务器
  （`http://10.42.239.55:5244/dav/hdd/test`）双设备 E2E 全过：
  推→拉→互改→冲突 updated_at 新者胜+败者保全→删除传播→删除正文保全。
  已知实现细节：败者保全发生在「持有败者内容的一侧」（若败者此前已推送，
  由对端拉取时保全 `-peer`，本地不再重复保全）。
