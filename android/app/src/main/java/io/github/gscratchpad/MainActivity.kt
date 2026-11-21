package io.github.gscratchpad

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import kotlin.coroutines.resume
import android.text.Html
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.Box as ComposeBox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.edit
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.lifecycleScope
import io.github.gscratchpad.capture.CaptureContract
import io.github.gscratchpad.capture.CaptureException
import io.github.gscratchpad.capture.CaptureRequest
import io.github.gscratchpad.capture.CaptureResult
import io.github.gscratchpad.data.MetaKeys
import io.github.gscratchpad.domain.search.SearchOptions
import io.github.gscratchpad.domain.search.TextSearch
import io.github.gscratchpad.domain.model.DocState
import io.github.gscratchpad.platform.MaintenancePolicy
import io.github.gscratchpad.domain.model.Document
import io.github.gscratchpad.domain.model.Folder
import io.github.gscratchpad.domain.model.Format
import io.github.gscratchpad.domain.model.SaveState
import io.github.gscratchpad.domain.keys.KeyAction
import io.github.gscratchpad.domain.keys.Shortcuts
import io.github.gscratchpad.importlib.BackupExporter
import io.github.gscratchpad.importlib.DesktopImporter
import io.github.gscratchpad.platform.FolderPolicy
import io.github.gscratchpad.platform.FoldersScreen
import io.github.gscratchpad.platform.OpenPolicy
import io.github.gscratchpad.platform.SafFileGateway
import io.github.gscratchpad.platform.SaveAsPolicy
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.io.File

/**
 * 单 Activity + Compose（方案 §4.1）。
 * 处理 VIEW / SEND / CAPTURE；编辑即 300 ms 防抖落盘；`onStop` 强制 flush。
 */
class MainActivity : ComponentActivity() {

    private val container: AppContainer by lazy { (application as GscratchpadApp).container }
    private lateinit var gateway: SafFileGateway
    /** R38：File 直读网关，仅在已获所有文件访问权时经 FileDirectWriter 启用。 */
    private val fileGateway = io.github.gscratchpad.platform.FileGateway()
    private var editorHost: io.github.gscratchpad.platform.EditorHost? = null

    private val docs = MutableStateFlow<List<Document>>(emptyList())
    private val activeId = MutableStateFlow<String?>(null)
    private val text = MutableStateFlow("")
    private val status = MutableStateFlow("")
    private val dark = MutableStateFlow(false)
    // R35：WebDAV 对话框改 Compose，命令式触发用 ticket 计数（编辑器桥接 / 设置页均可唤起）
    private val cloudDialogTicket = MutableStateFlow(0)
    private var revision: Long = 0
    private var saveJob: kotlinx.coroutines.Job? = null

    private val openFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { openExternal(it) }
    }
    private val saveAs = registerForActivityResult(io.github.gscratchpad.platform.WorkDirCreateDocument()) { uri ->
        uri?.let { saveAsExternal(it) }
    }

    /** R33：触发另存，若有工作目录则把选择器初始定位过去。 */
    private fun launchSaveAs(title: String) {
        saveAs.launch(
            io.github.gscratchpad.platform.WorkDirCreateDocument.Request(
                fileName = SaveAsPolicy.fileName(title),
                initialUri = workDirUri(),
            ),
        )
    }
    private val importBackup = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { importBackupFrom(it) }
    }
    private val exportBackup = registerForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        uri?.let { exportBackupTo(it) }
    }
    /** Q3：插入图片走系统图片选择器，字节复制进私有 assets 后写入相对引用。 */
    private val pickImage = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { importImage(it) }
    }
    /** Q5：云盘目录通道，选一个由云盘 DocumentsProvider 提供的目录。 */
    private val pickCloudDir = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        uri?.let { persistUriPermission(it); cloudDirUri = it; toast("云盘目录已绑定") }
    }
    /** P3 SAF 三项自检的目录授权通道：授权后自动执行 safSelfCheck。 */
    private val pickSafCheckDir = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            persistUriPermission(uri)
            if (pendingSafCheckAfterPick) {
                pendingSafCheckAfterPick = false
                lifecycleScope.launch { safSelfCheck(uri) }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // R38：注入 File 直读写回能力。仅当「API 支持 + 已授予所有文件访问 + documentId
        // 可映射为共享存储真实路径」时生效，否则 SafFileGateway.save 原样回退 SAF。
        gateway = SafFileGateway(
            this,
            fileDirectWriter = io.github.gscratchpad.platform.FileDirectWriter { documentId, text_, style ->
                if (!allFilesAccessGranted()) return@FileDirectWriter false
                val path = io.github.gscratchpad.platform.FileDirectPolicy.resolvePath(documentId)
                if (!io.github.gscratchpad.platform.FileDirectPolicy.shouldUseFileDirect(true, true, path)) {
                    return@FileDirectWriter false
                }
                fileGateway.saveAtomic(path!!, text_, style)
            },
        )
        androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, true)
        // 主题持久化：启动即按上次选择设置状态栏/导航栏明暗，避免"内容深色、通知栏白条"
        dark.value = getSharedPreferences("editor-prefs", MODE_PRIVATE).getBoolean("dark", false)
        workDirBinding.value = io.github.gscratchpad.platform.WorkDirPolicy.read(
            getSharedPreferences("editor-prefs", MODE_PRIVATE),
        )
        window.decorView.post { applySystemBars(dark.value) }
        if (intent?.action == CaptureContract.ACTION) {
            handleCaptureIntent(intent)
            return
        }
        lifecycleScope.launch {
            container.bootstrap()
            reload()
            if (intent?.action == Intent.ACTION_SEND) {
                val shared = intent.getStringExtra(Intent.EXTRA_TEXT)
                if (!shared.isNullOrBlank()) {
                    val doc = container.repository.create(Format.MD, "分享内容")
                    container.repository.saveNow(doc.id, shared, 2)
                    reload(doc.id)
                }
            }
            launch {
                container.saveQueue.states.collect { state ->
                    status.value = when (state.status) {
                        SaveState.Status.SAVED -> "已保存"
                        SaveState.Status.SAVING -> "保存中…"
                        SaveState.Status.ERROR -> "保存失败：${state.message}"
                    }
                }
            }
        }
        setContent { AppScreen() }
        setupEditorOverlay()
        intent?.getStringExtra("openDoc")?.let { pendingOpenDocId = it }
        intent?.getIntExtra("soakSeconds", 0)?.takeIf { it > 0 }?.let { pendingSoakSeconds = it }
        intent?.getStringExtra("openPanel")?.let { pendingPanel = it }
        intent?.getStringExtra("runAction")?.let { pendingRunAction = it }
        if (intent?.getStringExtra("split") == "true") pendingSplit = true
        // 自动化验证：am start --es openDirPicker true 直接弹出 File 目录浏览器
        if (intent?.getStringExtra("openDirPicker") == "true") dirPickerOpen.value = true
        // 自动化验证：am start --es openFilePicker true 直接弹出 File 本地文件浏览器（R42）
        if (intent?.getStringExtra("openFilePicker") == "true") openFilePickerOpen.value = true
        // R41 自动化验证：绑定指定工作目录后把「切换文档」列表 JSON 打到 logcat（VerifySwitch tag）
        intent?.getStringExtra("verifyWorkDir")?.let { path ->
            lifecycleScope.launch {
                bindWorkDirPath(path)
                reload()
                android.util.Log.d("VerifySwitch", currentDocsJson())
            }
        }
        registerBackHandler()
    }

    override fun onResume() {
        super.onResume()
        // Activity 窗口此时已 attach，decorView.windowToken 有效，可以挂 panel 子窗口
        attachEditorPanelIfNeeded()
        // 从系统授权页返回后刷新「所有文件访问」状态（File 直读工作目录依赖此权限）
        allFilesGranted.value = allFilesAccessGranted()
    }

    // ---- 共享存储访问辅助方法（R42：API 30+ 走 MANAGE_EXTERNAL_STORAGE，API 29- 走传统 READ）

    /** 是否真正获得 File 直读能力（统一判定，兼容华为 Android 10 等低版本机）。 */
    private fun allFilesAccessGranted(): Boolean {
        val api = Build.VERSION.SDK_INT
        // lint 的 NewApi 只识别同表达式内的 SDK_INT 守卫，故在此处内联而非用局部 api 变量
        val manage = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            false
        }
        val legacy = android.content.pm.PackageManager.PERMISSION_GRANTED ==
            androidx.core.content.ContextCompat.checkSelfPermission(
                this,
                android.Manifest.permission.READ_EXTERNAL_STORAGE,
            )
        return io.github.gscratchpad.platform.StorageAccess.canBrowse(api, manage, legacy)
    }

    /** 请求 File 直读所需的存储权限（分版本：API 30+ 跳设置页，API 29- 弹运行时权限）。 */
    private fun requestAllFilesAccess() {
        val api = Build.VERSION.SDK_INT
        if (io.github.gscratchpad.platform.StorageAccess.supportsManageAll(api)) {
            runCatching {
                startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:$packageName"),
                    ),
                )
            }.onFailure { toast("无法打开授权页：${it.message}") }
        } else {
            requestLegacyStorage.launch(android.Manifest.permission.READ_EXTERNAL_STORAGE)
        }
    }

    /** API 29- 传统存储权限申请（Activity Result API）；返回后刷新 File 直读能力状态。 */
    private val requestLegacyStorage = registerForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
    ) { granted ->
        allFilesGranted.value = allFilesAccessGranted()
        if (granted) toast("存储权限已授予，可浏览真实目录")
        else toast("未获得存储权限，无法列出目录")
    }

    /**
     * R40：打开工作目录浏览器。无「所有文件访问」权限时仍允许进入（对话框内给出授权入口），
     * 因为 Android 11+ 的 ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION 需在设置页跳转。
     */
    private fun openWorkDirPicker() {
        dirPickerOpen.value = true
    }

    /** R40：确认绑定 File 直读目录——写偏好、更新 StateFlow、关闭对话框。 */
    private fun bindWorkDirPath(path: String) {
        val prefs = getSharedPreferences("editor-prefs", MODE_PRIVATE)
        io.github.gscratchpad.platform.WorkDirPolicy.savePath(prefs, path)
        workDirBinding.value = io.github.gscratchpad.platform.WorkDirPolicy.read(prefs)
        dirPickerOpen.value = false
        toast("已绑定工作目录：${io.github.gscratchpad.platform.FileDirPolicy.label(path)}")
    }

    // ---------------------------------------------------------------- R39 维护（复刻桌面版）

    /** 先扫描已关闭笔记数与正文体积供确认，不改数据。 */
    private fun preparePurgeClosed(onReady: (String) -> Unit) {
        lifecycleScope.launch {
            val closed = docs.value.filter { it.state == DocState.CLOSED }
            if (closed.isEmpty()) {
                toast("没有已关闭的笔记")
                return@launch
            }
            val bytes = closed.sumOf { it.content.toByteArray(Charsets.UTF_8).size.toLong() }
            onReady(
                "将从应用中移除 ${closed.size} 篇已关闭笔记的记录与图片缓存" +
                    "（正文约 ${MaintenancePolicy.humanSize(bytes)}）。\n\n" +
                    "本机上的原文件不会被删除，仍可重新打开；清除后这些笔记的正文将从应用中消失，无法在应用内恢复。",
            )
        }
    }

    private fun executePurgeClosed(onDone: (String) -> Unit) {
        lifecycleScope.launch {
            val report = container.repository.purgeClosed()
            // 修复：purge 删除了 DB 记录后必须刷新主页列表，否则已清除的笔记仍留在界面上。
            docs.value = container.dao.allDocuments()
            if (activeId.value != null && docs.value.none { it.id == activeId.value }) {
                docs.value.firstOrNull()?.id?.let { activate(it) }
            }
            val suffix = if (report.errors.isEmpty()) "" else "（${report.errors.size} 项缓存未清除）"
            onDone("已从应用移除 ${report.purgedDocs} 篇已关闭笔记$suffix")
        }
    }

    /** 先扫描孤儿计数与可回收空间，无可清理项直接提示、不弹确认框。 */
    private fun prepareMaintenance(onReady: (String) -> Unit) {
        lifecycleScope.launch {
            val scan = container.repository.scanOrphans()
            val items = mutableListOf<String>()
            if (scan.orphanNotes > 0) items += "镜像文件 ${scan.orphanNotes} 个（${MaintenancePolicy.humanSize(scan.orphanNotesBytes)}）"
            if (scan.orphanAssets > 0) items += "图片资源 ${scan.orphanAssets} 个（${MaintenancePolicy.humanSize(scan.orphanAssetsBytes)}）"
            if (scan.orphanJournals > 0) items += "恢复日志 ${scan.orphanJournals} 个"
            if (scan.staleMeta > 0) items += "失效映射 ${scan.staleMeta} 条"
            val reclaimable = scan.dbFreeBytes >= 256 * 1024
            if (items.isEmpty() && !reclaimable) {
                toast("数据目录已无需要清理的内容")
                return@launch
            }
            val sb = StringBuilder()
            if (items.isNotEmpty()) {
                sb.append("将删除本应用数据目录内无对应笔记的文件：\n")
                items.forEach { sb.append("· ").append(it).append('\n') }
            }
            if (reclaimable) sb.append("\n数据库可回收约 ${MaintenancePolicy.humanSize(scan.dbFreeBytes)} 空闲页。")
            sb.append("\n只处理应用私有目录，不触碰你关联的本机原文件。")
            onReady(sb.toString())
        }
    }

    private fun executeMaintenance(onDone: (String) -> Unit) {
        lifecycleScope.launch {
            val report = container.repository.maintain(vacuum = true)
            val count = report.orphanNotes + report.orphanAssets + report.orphanJournals
            val vacuum = if (report.vacuumed) "，数据库已压缩" else ""
            val suffix = if (report.errors.isEmpty()) "" else "（${report.errors.size} 项失败）"
            onDone("已清理 $count 项孤儿文件$vacuum$suffix")
        }
    }

    // ---------------------------------------------------------------- 编辑器（路线 D，常驻 WebView）

    private var editorView: android.webkit.WebView? = null
    private var previewContainer: android.view.ViewGroup? = null
    private var windowManager: android.view.WindowManager? = null
    private var panelParams: android.view.WindowManager.LayoutParams? = null
    private var panelAdded: Boolean = false
    private var pendingPanelAttach: Boolean = false
    private var pageLoadStarted: Boolean = false
    /** 自动化用：am start --es openDoc <id> 直达指定文档（等页面就绪后打开）。 */
    private var pendingOpenDocId: String? = null
    /** 自动化用：am start --ei soakSeconds <n> 在页面就绪后跑中文注入 soak。 */
    private var pendingSoakSeconds: Int? = null
    /** 自动化用：am start --es openPanel palette|outline|settings 页面就绪后直接打开对应面板。 */
    private var pendingPanel: String? = null
    /** 自动化用：am start --es runAction share|saveAs|foldAll|... 页面就绪后直接执行动作。 */
    private var pendingRunAction: String? = null

    /** SAF 自检：尚无目录授权时先弹目录选择器，授权后自动继续。 */
    private var pendingSafCheckAfterPick = false
    private var editingDocId: String = ""
    private var editorRevision: Long = 0
    private var editorLatest: String = ""
    /** 当前文档标题：页面重载后由 onReady 重推，避免面包屑空白。 */
    private var editorTitle: String = ""
    private var editorSaveJob: kotlinx.coroutines.Job? = null
    private var editorOpen: Boolean = false
    private var editorAttachedAt: Long = 0
    /**
     * 编辑器世代号：每次打开/关闭 +1。
     * 用于屏蔽「打开 A → 关闭 → 打开 B」时旧协程（关闭时的落盘、reload 的 activate）
     * 在切换完成后又把 A 的内容推回编辑器/写进 B（R20 定根）。
     */
    private var editorEpoch: Long = 0

    // ---- Q1 双栏 / Q3 图片 / Q5 云备份
    private var panelContainer: android.widget.LinearLayout? = null
    private var splitPreviewView: android.webkit.WebView? = null
    private var splitPreviewHost: io.github.gscratchpad.platform.PreviewHost? = null
    private var splitOn = false
    private var splitRenderAt = 0L
    private var splitSyncJob: kotlinx.coroutines.Job? = null

    // ---- 同页预览（编辑器 ↔ 预览在 panel 子窗口内互斥切换，无 Activity 跳转）
    private var previewScreen: io.github.gscratchpad.platform.PreviewScreen? = null
    private var previewOpen: Boolean = false
    private var cloudDirUri: android.net.Uri? = null
    /** 当前绑定的工作目录（R40 File 直读路径 / 旧 SAF 树），null 表示未绑定。 */
    private val workDirBinding = MutableStateFlow<io.github.gscratchpad.platform.WorkDirPolicy.Binding?>(null)
    /** R40：File 目录浏览器对话框是否打开。 */
    private val dirPickerOpen = mutableStateOf(false)
    /** R42：File 本地文件打开浏览器对话框是否打开。 */
    private val openFilePickerOpen = mutableStateOf(false)

    // ---- 共享存储访问能力（R42：API 30+ MANAGE_EXTERNAL_STORAGE / API 29- 传统 READ）
    /** 是否已获得 File 直读能力。授权返回后（onResume / onRequestPermissionsResult）刷新。 */
    private val allFilesGranted = mutableStateOf(false)
    /** 自动化用：am start --es split true 页面就绪后直接开双栏（窄屏也能验证）。 */
    private var pendingSplit: Boolean = false

    /**
     * 编辑器以常驻 WebView 覆盖在 Compose 之上：页面在应用启动时就开始加载，
     * 打开文档只剩 setDoc 的成本。WebView 与 Activity 同生命周期，不再整页重载。
     */
    private fun setupEditorOverlay() {
        val view = android.webkit.WebView(this)
        view.setBackgroundColor(0xFFFFFFFF.toInt())
        // panel 是独立子窗口，BACK 不经过 Activity.dispatchKeyEvent，必须在这里转发给 dispatcher
        view.setOnKeyListener { _, keyCode, event ->
            if (keyCode == android.view.KeyEvent.KEYCODE_BACK && event.action == android.view.KeyEvent.ACTION_UP) {
                onBackPressedDispatcher.onBackPressed()
                true
            } else {
                false
            }
        }
        editorView = view
        // Q1：panel 的根是横向容器，宽屏时可并排塞入编辑 WebView 与预览 WebView
        panelContainer = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.HORIZONTAL
            addView(view, android.widget.LinearLayout.LayoutParams(0, android.view.ViewGroup.LayoutParams.MATCH_PARENT, 1f))
        }
        val host = io.github.gscratchpad.platform.EditorHost(view)
        editorHost = host
        io.github.gscratchpad.platform.ScrollSync.editor = host
        editorAttachedAt = android.os.SystemClock.elapsedRealtime()
        host.onReady = {
            android.util.Log.d(
                "Gscratchpad",
                "editor page ready in ${android.os.SystemClock.elapsedRealtime() - editorAttachedAt}ms",
            )
            // 动作表由 Kotlin 下发，页内命令面板据此渲染
            host.pushActions()
            // R33：文档列表下发，页内「切换文档」浮层据此渲染
            pushDocsToEditor()
            applyEditorPrefs()
            // 页面重载后标题会丢，重推一次（面包屑不显示空标题）
            if (editorTitle.isNotEmpty()) host.setTitle(editorTitle)
            pendingOpenDocId?.let { id -> pendingOpenDocId = null; openEditor(id) }
            pendingSoakSeconds?.let { s ->
                pendingSoakSeconds = null
                // 诊断钩子：中文注入 soak（走 CM 事务，替代无法自动化的 IME 组合态）
                editorHost?.soakChinese(s)
            }
            pendingPanel?.let { which ->
                pendingPanel = null
                // 诊断钩子：页面就绪后直接开面板，绕开工具栏坐标点击
                view.postDelayed({
                    when (which) {
                        "palette" -> host.openPalette()
                        "outline" -> host.openOutline()
                        "settings" -> host.openSettings()
                    }
                }, 1200)
            }
            pendingRunAction?.let { act ->
                pendingRunAction = null
                view.postDelayed({ onEditorAction(act) }, 1500)
            }
            if (pendingSplit) {
                pendingSplit = false
                view.postDelayed({ setSplit(true) }, 1500)
            }
        }
        host.onMetrics = { m ->
            android.util.Log.d(
                "Gscratchpad",
                "editor total ${android.os.SystemClock.elapsedRealtime() - editorAttachedAt}ms" +
                    " open=${m.openMs}ms fold=${m.foldMs}ms",
            )
        }
        host.onDocChanged = { text ->
            editorLatest = text
            editorRevision += 1
            // 输入即刻写热日志（P2-5）：不等 300 ms 防抖，强杀后最后一批字符仍可从 journal 恢复
            container.draftJournal.offer(editingDocId, editorRevision, text)
            scheduleEditorSave()
            scheduleSplitRender()
        }
        host.onPrefsChanged = { json ->
            runCatching { saveEditorPrefs(json) }
        }
        host.onAction = ::onEditorAction
        // R41：目录里未入库的文件用 file: 虚拟 id，点选时按需导入再打开；已入库的走原切换。
        host.onSwitchDocById = { id ->
            if (io.github.gscratchpad.domain.WorkDirSwitchList.isVirtual(id)) {
                openWorkDirFile(io.github.gscratchpad.domain.WorkDirSwitchList.pathOf(id))
            } else {
                switchToDoc(id)
            }
        }
        host.onJsShortcut = { name ->
            io.github.gscratchpad.domain.keys.Shortcuts.resolve(true, false, name)?.let { act ->
                when (act) {
                    io.github.gscratchpad.domain.keys.KeyAction.PREVIEW -> onEditorAction("preview")
                    io.github.gscratchpad.domain.keys.KeyAction.CLOSE -> onEditorAction("close")
                    io.github.gscratchpad.domain.keys.KeyAction.NEW -> onEditorAction("new")
                    io.github.gscratchpad.domain.keys.KeyAction.FIND,
                    io.github.gscratchpad.domain.keys.KeyAction.REPLACE,
                    -> onEditorAction("find")
                    io.github.gscratchpad.domain.keys.KeyAction.RENAME -> renameCurrentDialog()
                    else -> Unit
                }
            }
        }
        // 加载延后到 panel 挂载完成，避免 WebView 换窗口触发渲染进程重建 + 整页重载
        pendingPanelAttach = true
        val decor = window.decorView
        if (decor.isAttachedToWindow) attachEditorPanelIfNeeded()
        else decor.addOnAttachStateChangeListener(object :
            android.view.View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(v: android.view.View) {
                attachEditorPanelIfNeeded()
                // panel 是 Activity 的子窗口，沿用 Activity 的 decorView 判断 attach 时机
                v.removeOnAttachStateChangeListener(this) // Compose 首帧可能早于 decor attach，兜底再试一次
            }

            override fun onViewDetachedFromWindow(v: android.view.View) = Unit
        })
    }

    /** 在 Activity 窗口 attach 完成后把 WebView 挂成 panel 子窗口：Z 序在 Compose 之上，保留硬件合成。 */
    private fun attachEditorPanelIfNeeded() {
        if (!pendingPanelAttach) return
        val view = panelContainer ?: return
        val lp = android.view.WindowManager.LayoutParams(
            android.view.WindowManager.LayoutParams.MATCH_PARENT,
            android.view.WindowManager.LayoutParams.MATCH_PARENT,
            android.view.WindowManager.LayoutParams.TYPE_APPLICATION_PANEL,
            android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            android.graphics.PixelFormat.OPAQUE,
        )
        lp.token = window.decorView.windowToken ?: return
        lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
        // 必须给窗口本身初始透明：addView 之后只改本地 lp 不影响已合成的窗口，panel 会从挂载起就盖住整屏
        lp.alpha = 0f
        // R42：初始就必须置 NOT_FOCUSABLE——否则主页态（透明 panel）仍持有窗口焦点，
        // BACK 事件被送进这个子窗口、既不到 WebView 的 OnKeyListener 也不到 Activity 主窗口，
        // 导致连按返回无法退出（真机/模拟器均复现）。showPanel 会清除该标志并 requestFocus。
        lp.flags = lp.flags or android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        panelParams = lp
        val wm = getSystemService(android.content.Context.WINDOW_SERVICE) as android.view.WindowManager
        windowManager = wm
        runCatching { wm.addView(view, lp) }
            .onSuccess {
                pendingPanelAttach = false
                panelAdded = true
                android.util.Log.d(
                    "Gscratchpad",
                    "editor panel attached at ${android.os.SystemClock.elapsedRealtime() - editorAttachedAt}ms",
                )
                if (!pageLoadStarted) {
                    // 必须先有窗口再加载：把 WebView 从无窗口搬进窗口会重建渲染进程、整页重载（实测多 1.4 s）
                    pageLoadStarted = true
                    editorHost?.attach()
                    // Q1：宽屏默认并排预览（>600dp 短边，与 Material 双栏断点一致）
                    if (resources.configuration.smallestScreenWidthDp >= 600) setSplit(true, auto = true)
                }
            }
            .onFailure { android.util.Log.d("Gscratchpad", "editor panel add failed: ${it.message}") }
    }

    private fun openEditor(docId: String) {
        val host = editorHost ?: return
        val view = editorView ?: return
        editorEpoch += 1
        val myEpoch = editorEpoch
        lifecycleScope.launch {
            val doc = container.repository.get(docId) ?: return@launch
            // 期间被关闭或切到别的文档：丢弃本次打开，避免旧内容写进新会话
            if (myEpoch != editorEpoch) return@launch
            editingDocId = docId
            editorRevision = doc.revision
            editorLatest = doc.content
            activeId.value = docId
            showPanel()
            view.requestFocus()
            editorOpen = true
            host.setTheme(dark.value)
            host.setTitle(doc.title)
            editorTitle = doc.title
            // 页面刚就绪时 setDocTitle 可能落在还不可执行的时机，补一次重推
            view.postDelayed({ if (editingDocId == docId) editorHost?.setTitle(editorTitle) }, 400)
            val t0 = java.lang.System.nanoTime()
            host.setDocument(doc.content)
            android.util.Log.d(
                "Gscratchpad",
                "editor mount id=$docId ${doc.content.length} chars load=" +
                    "${(java.lang.System.nanoTime() - t0) / 1_000_000}ms",
            )
            container.repository.setMeta(io.github.gscratchpad.data.MetaKeys.ACTIVE_DOC, docId)
            container.repository.setState(docId, open = true)
            // 最近打开打点：首页「最近文档」按 opened_at 倒序（R20 修复排序）
            container.repository.touchOpened(docId)
            if (splitOn) {
                splitPreviewHost?.let {
                    io.github.gscratchpad.platform.ScrollSync.attach(it, doc.content)
                    it.renderMarkdown(doc.content, dark.value)
                }
            }
        }
    }

    private fun showPanel() {
        attachEditorPanelIfNeeded()
        val wm = windowManager ?: return
        val lp = panelParams ?: return
        val view = panelContainer ?: return
        if (!panelAdded) return
        lp.alpha = 1f
        lp.flags = lp.flags and android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
        lp.flags = lp.flags and android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
        runCatching { wm.updateViewLayout(view, lp) }
        // 窗口从全透明切回不透明时 SurfaceFlinger 不会主动重绘旧内容，强制一次无效化
        view.invalidate()
        view.postInvalidateOnAnimation()
        view.requestFocus()
    }

    private fun hidePanel() {
        val wm = windowManager ?: return
        val lp = panelParams ?: return
        val view = panelContainer ?: return
        if (!panelAdded) return
        lp.alpha = 0f
        // 隐藏时同时置 NOT_TOUCHABLE + NOT_FOCUSABLE：否则这个全屏 panel 仍是窗口焦点持有者，
        // 而 Activity 主窗口变成「无焦点窗口」，输入事件被丢弃并最终触发 ANR
        // （Input dispatching timed out / Application does not have a focused window）。
        lp.flags = lp.flags or android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        lp.flags = lp.flags or android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        runCatching { wm.updateViewLayout(view, lp) }
        view.clearFocus()
        window.decorView.requestFocus()
    }

    private fun closeEditor() {
        // 关闭编辑器时预览一并退出，避免预览视图残留在空窗口
        if (previewOpen) exitPreview()
        // 先同步取快照再异步落盘：此前 flushEditor() 在协程里读实时字段，
        // 用户「关闭 A 立刻打开 B」时会把 A 的正文写进 B（R20 定根）
        val id = editingDocId
        val snapshot = editorLatest
        val snapshotRev = editorRevision
        editorEpoch += 1
        val myEpoch = editorEpoch
        editorSaveJob?.cancel()
        hidePanel()
        editorView?.clearFocus()
        editingDocId = ""
        editorOpen = false
        android.util.Log.d("Gscratchpad", "editor closed id=$id chars=${snapshot.length}")
        lifecycleScope.launch {
            if (id.isNotEmpty()) {
                container.repository.saveNow(id, snapshot, snapshotRev)
                saveExternalIfBound(id, snapshot)
                container.repository.setState(id, open = false)
                container.draftJournal.drop(id)
            }
            if (myEpoch == editorEpoch) reload()
        }
    }

    private fun scheduleEditorSave() {
        val id = editingDocId
        if (id.isEmpty()) return
        editorSaveJob?.cancel()
        editorSaveJob = lifecycleScope.launch {
            kotlinx.coroutines.delay(300)
            container.repository.saveNow(id, editorLatest, editorRevision)
        }
    }

    private suspend fun flushEditor() {
        editorSaveJob?.cancel()
        val id = editingDocId
        if (id.isNotEmpty() && editorLatest.isNotEmpty()) {
            container.repository.saveNow(id, editorLatest, editorRevision)
            saveExternalIfBound(id, editorLatest)
        }
    }

    /**
     * R33：若当前文档绑定了外部文件（另存/工作目录新建/外部打开都会写 sourcePath meta），
     * 强制 flush 时把正文同步写回该文件。失败仅提示，不影响内部库已落盘。
     */
    private suspend fun saveExternalIfBound(id: String, content: String) {
        val sp = container.repository.getMeta(MetaKeys.sourcePath(id), null)
        if (sp.isNullOrBlank()) return
        val style = io.github.gscratchpad.platform.TextStyle(
            Charsets.UTF_8, false, io.github.gscratchpad.platform.NewlineStyle.LF,
        )
        when {
            // R40：File 直读路径绑定——真实路径写回，不产生 .old。
            // R45：失败原因细化上报（共享存储校验/父目录/临时写入/读回/替换五环节），便于真机定位。
            sp.startsWith("/") -> {
                val err = fileGateway.saveAtomicDetailed(sp, content, style)
                if (err != null) {
                    android.util.Log.w("Gscratchpad", "saveExternal failed path=$sp err=$err")
                    toast("外部文件同步失败：$err")
                }
            }
            // 旧 SAF 绑定：sourcePath 是 content:// URI
            sp.startsWith("content://") -> {
                runCatching {
                    gateway.save(android.net.Uri.parse(sp), content, style)
                }.onFailure { toast("外部文件同步失败：${it.message}") }
            }
        }
    }

    private fun onEditorAction(action: String) {
        when (action) {
            "new" -> lifecycleScope.launch {
                flushEditor()
                val doc = createDocWithWorkDir()
                openEditor(doc.id)
            }
            "close", "back" -> {
                editorHost?.closeOverlays()
                closeEditor()
            }
            "preview" -> enterPreview()
            "prevDoc" -> switchDocument(-1)
            "nextDoc" -> switchDocument(1)
            "docs" -> {
                pushDocsToEditor()
                editorHost?.openDocs()
            }
            "fold" -> editorHost?.foldAtCursor()
            "foldAll" -> editorHost?.foldAll()
            "unfoldAll" -> editorHost?.unfoldAll()
            "palette" -> editorHost?.openPalette()
            "outline" -> editorHost?.openOutline()
            "settings" -> editorHost?.openSettings()
            "saveAs" -> {
                val title = docs.value.firstOrNull { it.id == editingDocId }?.title ?: "未命名"
                launchSaveAs(title)
            }
            "share" -> shareCurrent()
            "openFile" -> openFile.launch(OpenPolicy.MIME_TYPES)
            "snippet", "snippets" -> showEditorSnippets()
            "theme" -> {
                setDark(!dark.value)
                editorHost?.setTheme(dark.value)
                editorView?.setBackgroundColor(if (dark.value) 0xFF1C1C1E.toInt() else 0xFFFFFFFF.toInt())
                splitPreviewView?.setBackgroundColor(if (dark.value) 0xFF1F2328.toInt() else 0xFFFFFFFF.toInt())
                if (splitOn) splitPreviewHost?.renderMarkdown(editorLatest, dark.value)
                if (previewOpen) previewScreen?.setDark(dark.value)
            }
            "save" -> lifecycleScope.launch {
                flushEditor()
                toast("已保存")
            }
            "split" -> setSplit(!splitOn)
            "image" -> pickImage.launch("image/*")
            "help" -> editorHost?.openHelp()
            "cloudBackup" -> showCloudDialog()
            "selfCheckFind" -> editorView?.evaluateJavascript("window.NativeEditor.selfCheckFind()") { r ->
                android.util.Log.d("Gscratchpad", "selfCheckFind result=$r")
            }
            "selfCheckGolden" -> runGoldenCorpus()
            "cloudSelfCheck" -> lifecycleScope.launch { cloudSelfCheck() }
            "safSelfCheck" -> {
                val granted = gateway.documentTreeRoots().firstOrNull()
                if (granted != null) lifecycleScope.launch { safSelfCheck(granted) }
                else { pendingSafCheckAfterPick = true; pickSafCheckDir.launch(null) }
            }
            "safPowerWrite" -> gateway.documentTreeRoots().firstOrNull()?.let { tree ->
                lifecycleScope.launch { safPowerWrite(tree) }
            }
            "safPowerVerify" -> gateway.documentTreeRoots().firstOrNull()?.let { tree ->
                lifecycleScope.launch { safPowerVerify(tree) }
            }
            "find" -> Unit
        }
    }

    // ---------------------------------------------------------------- Q1 双栏预览

    /**
     * 双栏：panel 容器内并排「编辑器 WebView + 预览 WebView」，两栏各占一半宽度。
     * 宽屏（shortestScreenWidthDp ≥ 600）在首次挂载时自动开启；窄屏可通过动作 `split` 手动开关。
     */
    private fun setSplit(on: Boolean, auto: Boolean = false) {
        val panel = panelContainer ?: return
        // 同页预览期间不允许分屏抢占：两栏 WebView 会盖住预览视图
        if (previewOpen && on) return
        if (on == splitOn && !auto) return
        splitOn = on
        if (on) {
            val view = splitPreviewView ?: run {
                val wv = android.webkit.WebView(this)
                wv.setBackgroundColor(if (dark.value) 0xFF1F2328.toInt() else 0xFFFFFFFF.toInt())
                panel.addView(
                    wv,
                    android.widget.LinearLayout.LayoutParams(0, android.view.ViewGroup.LayoutParams.MATCH_PARENT, 1f),
                )
                splitPreviewView = wv
                val host = io.github.gscratchpad.platform.PreviewHost(this, wv, container.paths.assets)
                splitPreviewHost = host
                host.attach()
                host.onReady = {
                    host.renderMarkdown(editorLatest.ifEmpty { text.value }, dark.value)
                    io.github.gscratchpad.platform.ScrollSync.attach(host, editorLatest)
                }
                wv
            }
            view.visibility = android.view.View.VISIBLE
            // 新增子 View 后父窗口需强制重排/重绘，否则新 WebView 区域会显示上一次分屏的残留像素
            panel.invalidate()
            panel.postInvalidateOnAnimation()
            panelParams?.let { lp -> runCatching { windowManager?.updateViewLayout(panel, lp) } }
            view.post {
                view.invalidate()
                view.requestLayout()
            }
            splitPreviewHost?.let {
                io.github.gscratchpad.platform.ScrollSync.attach(it, editorLatest.ifEmpty { text.value })
                it.renderMarkdown(editorLatest.ifEmpty { text.value }, dark.value)
            }
            startSplitSync()
            android.util.Log.d("Gscratchpad", "split on auto=$auto")
            toast("已开启分屏预览")
        } else {
            stopSplitSync()
            splitPreviewHost?.let {
                io.github.gscratchpad.platform.ScrollSync.detach(it)
                it.release()
            }
            splitPreviewView?.let { panel.removeView(it) }
            splitPreviewHost = null
            splitPreviewView = null
            android.util.Log.d("Gscratchpad", "split off")
            toast("已关闭分屏预览")
        }
    }

    private fun startSplitSync() {
        splitSyncJob?.cancel()
        splitSyncJob = lifecycleScope.launch {
            var lastY = -1f
            while (true) {
                kotlinx.coroutines.delay(600)
                val p = splitPreviewHost ?: break
                p.currentScrollY { y ->
                    if (lastY >= 0f && kotlin.math.abs(y - lastY) > 6f) {
                        io.github.gscratchpad.platform.ScrollSync.onPreviewScrolled(y)
                    }
                    lastY = y
                }
                io.github.gscratchpad.platform.ScrollSync.pullFromEditor()
            }
        }
    }

    private fun stopSplitSync() {
        splitSyncJob?.cancel()
        splitSyncJob = null
    }

    // ---------------------------------------------------------------- 同页预览（编辑器 ↔ 预览互斥切换）

    /**
     * 在当前 panel 子窗口内以「编辑器 WebView 隐藏、预览视图显示」的方式进入预览。
     * 相比原独立 Activity：省去任务栈跳转与 WebView 重建，进/出无黑屏空档；返回键先退预览。
     */
    private fun enterPreview() {
        if (previewOpen) return
        lifecycleScope.launch {
            flushEditor()
            val id = editingDocId
            if (id.isEmpty()) return@launch
            val doc = container.repository.get(id) ?: return@launch
            val panel = panelContainer ?: return@launch

            val screen = previewScreen ?: run {
                val s = io.github.gscratchpad.platform.PreviewScreen(
                    this@MainActivity,
                    container.paths.assets,
                    onClose = { exitPreview() },
                    onToggleTheme = {
                        setDark(!dark.value)
                        previewScreen?.setDark(dark.value)
                    },
                    onOpenDocs = {
                        pushDocsToPreview()
                        previewScreen?.openDocs()
                    },
                    onSelectDoc = { id ->
                        if (io.github.gscratchpad.domain.WorkDirSwitchList.isVirtual(id)) {
                            openWorkDirFile(io.github.gscratchpad.domain.WorkDirSwitchList.pathOf(id))
                        } else {
                            switchToDoc(id)
                        }
                    },
                )
                panel.addView(
                    s,
                    android.widget.LinearLayout.LayoutParams(
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    ),
                )
                previewScreen = s
                s
            }
            // 编辑器与分屏预览让位：横排容器里只有预览视图占位
            editorView?.visibility = android.view.View.GONE
            splitPreviewView?.visibility = android.view.View.GONE
            // 分屏同步会在隐藏的 WebView 上继续 pullFromEditor，进入预览时停掉
            if (splitOn) stopSplitSync()
            screen.visibility = android.view.View.VISIBLE
            screen.show(editorLatest, doc.title, dark.value)
            // R33：进预览时下发文档列表，浮层点开前 onOpenDocs 还会再刷新一次
            pushDocsToPreview()
            previewOpen = true
            // 强制重排/重绘：panel 从只显示 WebView 切到含原生顶栏的视图树
            panel.invalidate()
            panel.postInvalidateOnAnimation()
            screen.alpha = 0f
            screen.animate().alpha(1f).setDuration(140).start()
            android.util.Log.d("Gscratchpad", "preview entered in-place id=$id")
        }
    }

    private fun exitPreview() {
        if (!previewOpen) return
        previewOpen = false
        previewScreen?.pauseSync()
        previewScreen?.visibility = android.view.View.GONE
        editorView?.visibility = android.view.View.VISIBLE
        if (splitOn) {
            splitPreviewView?.visibility = android.view.View.VISIBLE
            splitPreviewHost?.let {
                io.github.gscratchpad.platform.ScrollSync.attach(it, editorLatest)
                it.renderMarkdown(editorLatest, dark.value)
            }
            startSplitSync()
        }
        editorView?.requestFocus()
    }

    /** 双栏时编辑器改动 → 预览重渲染（800 ms 节流，避免每次按键重排整篇）。 */
    private fun scheduleSplitRender() {
        if (!splitOn) return
        val now = android.os.SystemClock.elapsedRealtime()
        if (now - splitRenderAt < 800) return
        splitRenderAt = now
        splitPreviewHost?.renderMarkdown(editorLatest, dark.value)
    }

    // ---------------------------------------------------------------- Q3 图片插入

    /** 图片字节复制进 `files/assets/<docId>/<sha12>.<ext>`，正文写相对引用 `assets/<docId>/<file>`。 */
    private fun importImage(uri: Uri) {
        val id = editingDocId
        if (id.isEmpty()) {
            toast("请先打开一个文档")
            return
        }
        lifecycleScope.launch {
            val bytes = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                runCatching { contentResolver.openInputStream(uri)?.use { it.readBytes() } }.getOrNull()
            }
            if (bytes == null || bytes.isEmpty()) {
                toast("读取图片失败")
                return@launch
            }
            val rawType = contentResolver.getType(uri)?.substringAfterLast('/').orEmpty()
            val ext = "." + when (rawType) {
                "jpeg" -> "jpg"
                "svg+xml" -> "svg"
                "x-icon" -> "png"
                "" -> "png"
                else -> rawType
            }
            val rel = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                runCatching { container.assets.importBytes(id, bytes, ext) }.getOrNull()
            }
            if (rel == null) {
                toast("不支持的图片格式：$ext")
                return@launch
            }
            editorHost?.insert("\n![]($rel)\n")
            android.util.Log.d("Gscratchpad", "image imported $rel (${bytes.size} B)")
            toast("已插入图片 ${rel.substringAfterLast('/')}")
        }
    }

    // ---------------------------------------------------------------- Q5 云备份

    private fun cloudPrefs() = getSharedPreferences("cloud-backup", MODE_PRIVATE)

    private fun cloudConfig(): io.github.gscratchpad.platform.CloudBackup.Config = cloudPrefs().let { p ->
        io.github.gscratchpad.platform.CloudBackup.Config(
            baseUrl = p.getString("url", "").orEmpty(),
            user = p.getString("user", "").orEmpty(),
            password = p.getString("pass", "").orEmpty(),
        )
    }

    private fun saveCloudConfig(url: String, user: String, pass: String) {
        cloudPrefs().edit {
            putString("url", url)
            putString("user", user)
            putString("pass", pass)
        }
    }

    /** R35：改用 Compose 对话框，命令式调用只负责 +1 ticket，配置读取交给 Composable。 */
    private fun showCloudDialog() {
        cloudDialogTicket.value += 1
    }

    private fun buildBackupZip(): File? {
        val cache = File(cacheDir, "cloud-${System.currentTimeMillis()}.zip")
        val report = BackupExporter.export(
            target = cache,
            appVersion = "0.7.0",
            exportedAt = System.currentTimeMillis() / 1000.0,
            snapshotDb = { file ->
                container.db.checkpointTruncate()
                container.paths.dbFile.copyTo(file, overwrite = true)
            },
            notesDir = container.paths.notes,
            assetsDir = container.paths.assets,
        )
        if (report.errors.isNotEmpty()) {
            android.util.Log.d("Gscratchpad", "cloud export failed: ${report.errors.first()}")
            cache.delete()
            return null
        }
        android.util.Log.d("Gscratchpad", "cloud export ok bytes=${cache.length()} notes=${report.notes}")
        return cache
    }

    private fun cloudUpload() {
        lifecycleScope.launch {
            flushEditor()
            val zip = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { buildBackupZip() }
            if (zip == null) {
                toast("打包失败")
                return@launch
            }
            val cfg = cloudConfig()
            val res = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                io.github.gscratchpad.platform.CloudBackup.upload(cfg, zip)
            }
            android.util.Log.d("Gscratchpad", "cloud upload ${res.ok} ${res.detail} bytes=${zip.length()}")
            toast(if (res.ok) "已上传 ${zip.length() / 1024} KB（${res.detail}）" else "上传失败：${res.detail}")
            zip.delete()
        }
    }

    private fun cloudDownload() {
        lifecycleScope.launch {
            val target = File(cacheDir, "cloud-download-${System.currentTimeMillis()}.zip")
            val cfg = cloudConfig()
            val res = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                io.github.gscratchpad.platform.CloudBackup.download(cfg, target)
            }
            android.util.Log.d("Gscratchpad", "cloud download ${res.ok} ${res.detail}")
            if (!res.ok) {
                toast("下载失败：${res.detail}")
                return@launch
            }
            importBackupZip(target, File(cacheDir, "cloud-restore-${System.currentTimeMillis()}"))
            target.delete()
        }
    }

    /**
     * 云备份端到端自检（Q5）：`--es runAction cloudSelfCheck --es cloudUrl ... --es cloudUser ... --es cloudPass ...`
     * 依次：保存配置 → flush → 打包 → PUT → HEAD → GET → 校验 zip 结构与字节数。
     * 结果写 logcat `cloudSelfCheck result=...`，便于在无界面环境下判定传输链路。
     */
    private suspend fun cloudSelfCheck() {
        val url = intent.getStringExtra("cloudUrl").orEmpty()
        val user = intent.getStringExtra("cloudUser").orEmpty()
        val pass = intent.getStringExtra("cloudPass").orEmpty()
        if (url.isEmpty()) {
            android.util.Log.d("Gscratchpad", "cloudSelfCheck result={\"ok\":false,\"reason\":\"缺少 cloudUrl\"}")
            return
        }
        saveCloudConfig(url, user, pass)
        flushEditor()
        val out = org.json.JSONObject()
        out.put("url", url)
        val zip = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { buildBackupZip() }
        if (zip == null) {
            out.put("ok", false).put("reason", "打包失败")
            android.util.Log.d("Gscratchpad", "cloudSelfCheck result=$out")
            return
        }
        out.put("localBytes", zip.length())
        val cfg = cloudConfig()
        val up = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            io.github.gscratchpad.platform.CloudBackup.upload(cfg, zip)
        }
        out.put("uploadOk", up.ok).put("uploadDetail", up.detail)
        val remote = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            io.github.gscratchpad.platform.CloudBackup.remoteSize(cfg)
        }
        out.put("remoteBytes", remote)
        val target = File(cacheDir, "cloud-selfcheck-${System.currentTimeMillis()}.zip")
        val down = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            io.github.gscratchpad.platform.CloudBackup.download(cfg, target)
        }
        out.put("downloadOk", down.ok).put("downloadDetail", down.detail)
        if (down.ok) {
            val entries = runCatching {
                java.util.zip.ZipFile(target).use { zf -> zf.entries().toList().map { it.name } }
            }.getOrDefault(emptyList())
            out.put("zipBytes", target.length())
            out.put("zipEntries", org.json.JSONArray(entries.filter { it.isNotBlank() }))
            out.put("hasDb", entries.any { it.endsWith("gscratchpad.db") })
            out.put("hasManifest", entries.any { it.endsWith("manifest.json") })
            out.put("sizeMatch", target.length() == remote || remote < 0)
            target.delete()
        }
        out.put("ok", up.ok && down.ok)
        android.util.Log.d("Gscratchpad", "cloudSelfCheck result=$out")
        toast(if (out.optBoolean("ok")) "云端往返校验通过" else "云端往返校验失败")
        zip.delete()
    }

    // ---------------------------------------------------------------- P3 SAF 三项自检

    /** 断电测试语料：确定性 2 MB 文本，marker 区分 V1/V2。 */
    private fun safPowerContent(marker: String): String {
        val sb = StringBuilder(2_100_000)
        val line = "断电测试 $marker 0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
        while (sb.length < 2_000_000) sb.append(line)
        return sb.toString()
    }

    private fun safSha(bytes: ByteArray): String =
        java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    private fun safReadRaw(uri: android.net.Uri): ByteArray? =
        contentResolver.openInputStream(uri)?.use { it.readBytes() }

    private fun safTreeRoot(treeUri: android.net.Uri) =
        androidx.documentfile.provider.DocumentFile.fromTreeUri(this, treeUri)

    /**
     * SAF 三项自检（P3-5）：
     * A 字节保真——GB18030 + CRLF 原始字节经 gateway.open→save 往返后 SHA-256 一致；
     * B 千文件枚举——对含 1000 文件子目录 saf1000 的授权树执行 listTree，记录条数与耗时；
     * C 断电无半截——由 safPowerWrite（配合外部 force-stop）与 safPowerVerify 两段完成。
     * 结果写 logcat `safCheck ...`。
     */
    private suspend fun safSelfCheck(treeUri: android.net.Uri) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            // —— A 字节保真 ——
            val root = safTreeRoot(treeUri)
            root?.findFile("fidelity.md")?.delete()
            val fidelity = gateway.createInTree(treeUri, "fidelity.md", "text/markdown")
            val gb = java.nio.charset.Charset.forName("GB18030")
            val raw = "中文测试：字节保真\r\nSecond line 中文内容\r\n3rd mixed English 中文\r\n"
                .toByteArray(gb)
            contentResolver.openOutputStream(fidelity, "wt")?.use { it.write(raw) }
            val before = safReadRaw(fidelity)
            val opened = gateway.open(fidelity)
            val mode = gateway.save(fidelity, opened.text, opened.style)
            val after = safReadRaw(fidelity)
            val fidelityOk = before != null && after != null && safSha(before) == safSha(after)
            android.util.Log.d(
                "Gscratchpad",
                "safCheck fidelity ok=$fidelityOk mode=$mode charset=${opened.style.charset.name()} " +
                    "newline=${opened.style.newline} beforeSha=${before?.let(::safSha)?.take(12)} " +
                    "afterSha=${after?.let(::safSha)?.take(12)}",
            )

            // 删除能力探针：定位 deleteDocument 对「新建文档 URI」与「rename 返回 URI」的支持情况
            runCatching {
                val p1 = gateway.createInTree(treeUri, "delprobe.md", "text/markdown")
                val d1 = runCatching { contentResolver.delete(p1, null, null) }
                android.util.Log.d("SafGW", "delProbe created rows=${d1.getOrDefault(-1)} err=${d1.exceptionOrNull()?.message}")
                val p2 = gateway.createInTree(treeUri, "delprobe2.md", "text/markdown")
                val r2 = runCatching { android.provider.DocumentsContract.renameDocument(contentResolver, p2, "delprobe3.md") }
                val d2 = r2.getOrNull()?.let { runCatching { contentResolver.delete(it, null, null) } }
                android.util.Log.d("SafGW", "delProbe renamed rows=${d2?.getOrDefault(-1)} err=${d2?.exceptionOrNull()?.message}")
                runCatching { contentResolver.delete(p2, null, null) }
            }

            // —— B 千文件枚举（授权树即 adb 预置的 saf1000，单目录 1000 项，listTree 按 400 截断） ——
            val t0 = System.currentTimeMillis()
            val entries = gateway.listTree(treeUri)
            val ms = System.currentTimeMillis() - t0
            android.util.Log.d(
                "Gscratchpad",
                "safCheck listTree total=${entries.size} ms=$ms " +
                    "firstF=${entries.firstOrNull()?.name} mdCount=${entries.count { it.name.endsWith(".md") }}",
            )

            // —— C 断电基座：写入 V1 基线 ——
            root?.findFile("power.md")?.delete()
            val power = gateway.createInTree(treeUri, "power.md", "text/markdown")
            val utf8Lf = io.github.gscratchpad.platform.TextStyle(Charsets.UTF_8, false, io.github.gscratchpad.platform.NewlineStyle.LF)
            val t1 = System.currentTimeMillis()
            val modeC = gateway.save(power, safPowerContent("V1"), utf8Lf)
            android.util.Log.d(
                "Gscratchpad",
                "safCheck power baseline mode=$modeC ms=${System.currentTimeMillis() - t1} " +
                    "bytes=${safReadRaw(power)?.size}",
            )
            toast("SAF 自检 A/B 完成，结果见 logcat")
        }
    }

    /** C 段写入端：单次 findFile 后连续覆写 12 轮，外部在任意轮次中途 force-stop 以验证无半截。 */
    private suspend fun safPowerWrite(treeUri: android.net.Uri) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val power = safTreeRoot(treeUri)?.findFile("power.md") ?: run {
                android.util.Log.d("Gscratchpad", "safPowerWrite: 找不到 power.md")
                return@withContext
            }
            val style = io.github.gscratchpad.platform.TextStyle(Charsets.UTF_8, false, io.github.gscratchpad.platform.NewlineStyle.LF)
            val content = safPowerContent("V2")
            repeat(12) { round ->
                val t0 = System.currentTimeMillis()
                val mode = gateway.save(power.uri, content, style)
                android.util.Log.d(
                    "Gscratchpad",
                    "safPowerWrite round=$round done mode=$mode ms=${System.currentTimeMillis() - t0}",
                )
            }
        }
    }

    /** C 段验证端：power.md 必须是完整 V1 或完整 V2，绝不允许半截；并报告 .tmp 残留。 */
    private suspend fun safPowerVerify(treeUri: android.net.Uri) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val root = safTreeRoot(treeUri)
            val power = root?.findFile("power.md")
            val bytes = power?.let { safReadRaw(it.uri) }
            val state = when {
                bytes == null -> "missing"
                safSha(bytes) == safSha(safPowerContent("V1").toByteArray(Charsets.UTF_8)) -> "V1_INTACT"
                safSha(bytes) == safSha(safPowerContent("V2").toByteArray(Charsets.UTF_8)) -> "V2_INTACT"
                else -> "CORRUPT"
            }
            val tmpLeft = root?.listFiles()?.count { it.name?.endsWith(".tmp") == true } ?: -1
            android.util.Log.d("Gscratchpad", "safCheck power state=$state bytes=${bytes?.size} tmpLeftover=$tmpLeft")
        }
    }

    /**
     * P2-7 跨端金标准语料：用与预览完全相同的 markdown-it 外壳渲染 `assets/golden/corpus.json`，
     * 逐条取指纹并写 `golden|<name>|<json>`；桌面侧由 scripts/golden_fingerprint.py --compare 对照。
     */
    private fun runGoldenCorpus() {
        val raw = runCatching {
            assets.open("golden/corpus.json").use { it.readBytes().toString(Charsets.UTF_8) }
        }.getOrNull()
        if (raw.isNullOrEmpty()) {
            toast("缺少 golden/corpus.json（先跑 scripts/golden_fingerprint.py）")
            return
        }
        val cases = runCatching { org.json.JSONArray(raw) }.getOrNull() ?: return
        val web = android.webkit.WebView(this)
        web.settings.javaScriptEnabled = true
        val frame = android.widget.FrameLayout(this).apply { alpha = 0f }
        frame.addView(web, 2, 2)
        (findViewById<android.view.ViewGroup>(android.R.id.content)).addView(
            frame,
            android.widget.FrameLayout.LayoutParams(2, 2),
        )
        val host = io.github.gscratchpad.platform.PreviewHost(this, web, container.paths.assets)
        host.attach()
        lifecycleScope.launch {
            kotlinx.coroutines.delay(500)
            var ok = 0
            for (i in 0 until cases.length()) {
                val name = cases.getJSONObject(i).optString("name")
                val md = cases.getJSONObject(i).optString("md")
                host.renderMarkdown(md, false)
                var fp = ""
                var tries = 0
                while (tries < 25 && fp.length < 8) {
                    kotlinx.coroutines.delay(60)
                    fp = evalString(host, "window.gsFingerprint ? window.gsFingerprint() : ''")
                    tries++
                }
                if (fp.length >= 8) ok++
                android.util.Log.d("Gscratchpad", "golden|$name|$fp")
                kotlinx.coroutines.delay(40)
            }
            android.util.Log.d("Gscratchpad", "golden done ok=$ok/${cases.length()}")
            runCatching { host.release() }
            runCatching {
                frame.removeAllViews()
                (frame.parent as? android.view.ViewGroup)?.removeView(frame)
            }
        }
    }

    private suspend fun evalString(host: io.github.gscratchpad.platform.PreviewHost, script: String): String {
        return kotlinx.coroutines.suspendCancellableCoroutine { cont ->
            host.evaluate(script) { v ->
                val unwrapped = runCatching {
                    (org.json.JSONTokener(v ?: "").nextValue() as? String).orEmpty()
                }.getOrDefault("")
                if (cont.isActive) cont.resume(unwrapped) {}
            }
        }
    }

    /** 分享出口（P2-4）：把当前正文以纯文本 ACTION_SEND 发出。 */
    private fun shareCurrent() {
        val body = editorLatest.ifEmpty { text.value }
        if (body.isBlank()) {
            toast("没有可分享的内容")
            return
        }
        val title = docs.value.firstOrNull { it.id == editingDocId }?.title.orEmpty().ifBlank { "未命名" }
        val send = Intent(Intent.ACTION_SEND)
            .setType("text/plain")
            .putExtra(Intent.EXTRA_SUBJECT, title)
            .putExtra(Intent.EXTRA_TEXT, body)
        startActivity(Intent.createChooser(send, "分享文档"))
    }

    private fun showEditorSnippets() {
        val labels = io.github.gscratchpad.domain.snippet.Snippet.entries.map { it.label }.toTypedArray()
        android.app.AlertDialog.Builder(this)
            .setTitle("插入片段")
            .setItems(labels) { _, index ->
                val snippet = io.github.gscratchpad.domain.snippet.Snippet.entries[index]
                editorHost?.insert(snippet.body)
                editorHost?.focus()
            }
            .show()
    }

    override fun onDestroy() {
        // R42：Activity 销毁前先移除 WebView Panel 子窗口，否则 WindowLeaked
        // （返回键退出时实测到：finish 后 LinearLayout panel 仍挂在 WindowManager 上）。
        panelContainer?.let { panel ->
            runCatching { windowManager?.removeViewImmediate(panel) }
        }
        panelAdded = false
        stopSplitSync()
        previewScreen?.release()
        previewScreen = null
        previewOpen = false
        io.github.gscratchpad.platform.ScrollSync.editor = null
        splitPreviewHost?.let {
            io.github.gscratchpad.platform.ScrollSync.detach(it)
            it.release()
        }
        splitPreviewHost = null
        splitPreviewView = null
        editorHost?.release()
        super.onDestroy()
    }

    // 返回键改走 OnBackPressedDispatcher（onBackPressed 覆盖对预测性返回手势无效，lint 会拦）
    private fun registerBackHandler() {
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // 同页预览打开时，返回键先退出预览回到编辑器
                if (previewOpen) {
                    exitPreview()
                    return
                }
                if (editorOpen) {
                    closeEditor()
                    return
                }
                // 主页态（无预览、无编辑器）：直接结束 Activity 退出应用。
                // 不再用「isEnabled=false + 二次 onBackPressed」那套——预测性返回手势下该技巧
                // 不可靠（实测焦点已回到 MainActivity、连按返回仍不退出）。finish() 最确定。
                finish()
            }
        })
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // singleTask：其他应用再次投递 CAPTURE / SEND 时不会重建 Activity
        if (intent.action == CaptureContract.ACTION) {
            handleCaptureIntent(intent)
        } else if (intent.action == Intent.ACTION_SEND) {
            val shared = intent.getStringExtra(Intent.EXTRA_TEXT)
            if (!shared.isNullOrBlank()) {
                lifecycleScope.launch {
                    val doc = container.repository.create(Format.MD, "分享内容")
                    container.repository.saveNow(doc.id, shared, 2)
                    reload(doc.id)
                }
            }
        }
    }

    override fun onStop() {
        super.onStop()
        val id = activeId.value ?: return
        // 用容器级协程，避免界面销毁时把最后一次落盘取消掉
        container.saveAndFlush(id, text.value, revision)
    }

    // ------------------------------------------------------------------ capture

    private fun handleCaptureIntent(intent: Intent) {
        lifecycleScope.launch {
            try {
                container.bootstrap()
                val request = CaptureRequest(
                    text = intent.getStringExtra(CaptureContract.EXTRA_TEXT).orEmpty(),
                    title = intent.getStringExtra(CaptureContract.EXTRA_TITLE).orEmpty(),
                    book = intent.getStringExtra(CaptureContract.EXTRA_BOOK).orEmpty(),
                    page = intent.getStringExtra(CaptureContract.EXTRA_PAGE).orEmpty(),
                    key = intent.getStringExtra(CaptureContract.EXTRA_KEY).orEmpty(),
                    mode = intent.getStringExtra(CaptureContract.EXTRA_MODE) ?: CaptureContract.MODE_APPEND,
                )
                val result: CaptureResult = container.captureService.capture(request)
                setResult(RESULT_OK)
                Toast.makeText(this@MainActivity, "已写入 ${result.title}", Toast.LENGTH_SHORT).show()
            } catch (e: CaptureException) {
                setResult(
                    if (e.code == CaptureContract.EXIT_STORE) CaptureContract.RESULT_STORE
                    else CaptureContract.RESULT_INVALID,
                    Intent().putExtra(CaptureContract.EXTRA_REASON, e.message),
                )
            } catch (e: Exception) {
                setResult(
                    CaptureContract.RESULT_STORE,
                    Intent().putExtra(CaptureContract.EXTRA_REASON, e.message),
                )
            } finally {
                finish()
            }
        }
    }

    // ------------------------------------------------------------------ 文档

    private suspend fun reload(selectId: String? = null) {
        // 列表展示全部文档（含已关闭），关闭的显示为 closed，点开即重新置为 open
        val all = container.dao.allDocuments()
        docs.value = all
        val target = selectId ?: activeId.value?.takeIf { id -> all.any { it.id == id } }
            ?: all.firstOrNull()?.id
        if (target != null) activate(target)
    }

    /** T3：文件夹视图数据（列表 + 计数），与 reload() 分开，仅在进入/操作文件夹时调用。 */
    private suspend fun reloadFolders(
        onResult: (List<Folder>, Map<String, Int>) -> Unit,
    ) {
        val list = container.repository.folders()
        val counts = container.repository.folderCounts()
        onResult(list, counts)
    }

    /**
     * T3：新建（old=null）或重命名文件夹。返回错误提示文本（null 表示成功）。
     * 校验在 FolderPolicy（纯）+ Repository（撞名拒绝），此处统一 runCatching 转文案。
     */
    private suspend fun folderWrite(old: String?, name: String): String? = runCatching {
        if (old == null) container.repository.createFolder(name)
        else container.repository.renameFolder(old, name)
        Unit
    }.exceptionOrNull()?.message

    private suspend fun activate(id: String) {
        val t0 = System.nanoTime()
        val doc = container.repository.get(id) ?: return
        val dbMs = (System.nanoTime() - t0) / 1_000_000
        activeId.value = id
        text.value = doc.content
        // 编辑器关闭时绝不回推内容：否则「关闭→reload」会把上一篇（或列表首篇）
        // 重新塞进隐藏的 WebView，紧接着打开 B 就会看到 A 的正文（R20 定根）
        if (editorOpen) editorHost?.setDocument(doc.content)
        revision = doc.revision
        val applyMs = (System.nanoTime() - t0) / 1_000_000 - dbMs
        container.repository.setMeta(MetaKeys.ACTIVE_DOC, id)
        android.util.Log.d(
            "Gscratchpad",
            "open ${doc.content.length} chars db=${dbMs}ms apply=${applyMs}ms rev=${doc.revision}",
        )
    }

    /**
     * T1：统一文档切换内核（页内按钮 / 命令面板 / 物理快捷键三入口共用）。
     * delta = -1 上一篇 / +1 下一篇；循环边界由 [DocumentSwitch] 纯逻辑计算。
     *
     * 竞态防护（R20 同类）：入口处先递增 editorEpoch 使之前任何打开/切换协程失效，
     * 协程内先 flush 当前未落盘正文再 activate，两次 await 后再校验 epoch，
     * 快速连点只有最后一次生效，不丢草稿、不串内容。
     */
    private fun switchDocument(delta: Int) {
        val list = docs.value
        if (list.size <= 1) return
        val idx = io.github.gscratchpad.domain.DocumentSwitch.targetIndexById(
            list.map { it.id }, activeId.value, delta,
        )
        if (idx < 0) return
        switchToDoc(list[idx].id)
    }

    /**
     * R33：按 id 切换到指定文档（编辑器/预览「切换文档」浮层点选入口）。
     * 与 [switchDocument] 共用同一竞态防护与预览态同步逻辑。
     */
    private fun switchToDoc(target: String) {
        if (target == activeId.value) return
        if (docs.value.none { it.id == target }) return
        editorEpoch += 1
        val myEpoch = editorEpoch
        lifecycleScope.launch {
            flushEditor()
            if (myEpoch != editorEpoch) return@launch
            activate(target)
            if (myEpoch != editorEpoch) return@launch
            if (previewOpen) {
                val doc = container.repository.get(target) ?: return@launch
                previewScreen?.show(editorLatest, doc.title, dark.value)
            }
        }
    }

    /**
     * R41：从「切换文档」浮层点选一个尚未入库的工作目录文件——按需导入并打开。
     * 先按 sourcePath 反查是否已存在对应文档（防重复导入），未命中才读文件建文档。
     */
    private fun openWorkDirFile(path: String) {
        lifecycleScope.launch {
            // 路径安全：必须在共享存储下，且在「当前文档同目录 / 绑定工作目录」（R45 口径）内
            val activeSp = activeId.value?.let {
                container.dao.getMeta(io.github.gscratchpad.data.MetaKeys.sourcePath(it), null)
            }
            val dir = io.github.gscratchpad.domain.WorkDirSwitchList.dirForList(
                activeSp, workDirBinding.value?.path,
            )
            if (dir.isNullOrBlank() ||
                !io.github.gscratchpad.platform.FileDirectPolicy.isSharedStoragePath(path) ||
                io.github.gscratchpad.domain.WorkDirSwitchList.parentOf(path) != dir.trimEnd('/')
            ) {
                toast("文件不在可切换的目录内")
                return@launch
            }
            // 反查已入库文档：sourcePath 精确匹配则直接切换，避免重复建文档
            val existing = docs.value.firstOrNull { doc ->
                container.dao.getMeta(io.github.gscratchpad.data.MetaKeys.sourcePath(doc.id), null) == path
            }
            if (existing != null) {
                switchToDoc(existing.id)
                return@launch
            }
            val content = fileGateway.readDocText(path)
            if (content == null) {
                toast("无法读取该文件（可能不是文本或已损坏）")
                return@launch
            }
            val name = path.substringAfterLast('/')
            val format = when (io.github.gscratchpad.platform.OpenPolicy.extensionOf(name)) {
                "md", "markdown" -> Format.MD
                "html", "htm", "xhtml" -> Format.HTML
                else -> Format.TXT
            }
            val title = name.substringBeforeLast('.', name)
            flushEditor()
            val doc = container.repository.create(format, title)
            container.repository.saveNow(doc.id, content, 2)
            container.repository.setMeta(io.github.gscratchpad.data.MetaKeys.sourcePath(doc.id), path)
            docs.value = container.dao.allDocuments()
            openEditor(doc.id)
            toast("已导入并打开 $name")
        }
    }

    /**
     * R41：当前文档列表序列化（编辑器/预览「切换文档」浮层共用）。
     * 绑定了 File 直读工作目录时，把该目录里的文档文件也并进来（无论是否打开过）；
     * 未入库的文件用 file: 虚拟 id，点击时由 [openWorkDirFile] 按需导入。
     */
    private fun currentDocsJson(): String {
        val all = docs.value
        val binding = workDirBinding.value
        // R45：列目录口径改为「当前文档同目录优先，绑定工作目录回退」——
        // 未绑定工作目录、或从绑定目录之外打开的文档，其同目录文件也要出现在切换列表。
        val activeSp = activeId.value?.let {
            container.dao.getMeta(io.github.gscratchpad.data.MetaKeys.sourcePath(it), null)
        }
        val dirPath = io.github.gscratchpad.domain.WorkDirSwitchList.dirForList(activeSp, binding?.path)
        val entries = all.map { doc ->
            val sp = container.dao.getMeta(io.github.gscratchpad.data.MetaKeys.sourcePath(doc.id), null)
            io.github.gscratchpad.domain.WorkDirSwitchList.DocEntry(doc.id, doc.title, sp)
        }
        val dirFiles = if (dirPath.isNullOrBlank()) emptyList() else fileGateway.listDocFiles(dirPath)
        val items = io.github.gscratchpad.domain.WorkDirSwitchList.build(dirPath, entries, dirFiles)
        return io.github.gscratchpad.domain.DocListJson.serialize(
            items.map { it.id },
            items.map { it.title },
            activeId.value,
        )
    }

    /** R33：把当前文档列表下发到编辑器页内「切换文档」浮层。 */
    private fun pushDocsToEditor() {
        editorHost?.setDocs(currentDocsJson())
    }

    /** R33：把当前文档列表下发到预览页「切换文档」浮层。 */
    private fun pushDocsToPreview() {
        previewScreen?.setDocs(currentDocsJson())
    }

    private fun onTextChanged(newText: String) {
        text.value = newText
        revision += 1
        val id = activeId.value ?: return
        saveJob?.cancel()
        saveJob = lifecycleScope.launch {
            delay(300)
            container.repository.saveNow(id, newText, revision)
        }
    }

    /** 非编辑器来源的整篇改写（批量替换/导入回灌），需要把新正文推回 CodeMirror。 */
    private fun applyExternalText(newText: String) {
        onTextChanged(newText)
        editorHost?.setDocument(newText)
    }

    /** 新建文档；若绑定了工作目录，同时在该目录建同名 .md 并关联 sourcePath。
     *  R40：path 绑定走 File 直读（绕开 SAF 视图过滤），旧 SAF tree 绑定保留原逻辑。 */
    private suspend fun createDocWithWorkDir(): io.github.gscratchpad.domain.model.Document {
        val doc = container.repository.create(Format.MD)
        val binding = workDirBinding.value
        when {
            binding?.path != null -> {
                val created = fileGateway.createEmptyFile(binding.path!!, SaveAsPolicy.fileName(doc.title))
                if (created != null) {
                    container.repository.setMeta(MetaKeys.sourcePath(doc.id), created)
                } else {
                    toast("工作目录建文件失败，已建本地文档")
                }
            }
            else -> {
                val tree = workDirUri()
                if (tree != null) {
                    runCatching {
                        val c = gateway.createInTree(tree, SaveAsPolicy.fileName(doc.title), "text/markdown")
                        container.repository.setMeta(MetaKeys.sourcePath(doc.id), c.toString())
                    }.onFailure { toast("工作目录建文件失败，已建本地文档：${it.message}") }
                }
            }
        }
        return doc
    }

    private fun newDocument() {
        lifecycleScope.launch {
            val doc = createDocWithWorkDir()
            reload(doc.id)
            // 新建即进入编辑器：主页只是文档列表，写正文必须走 CodeMirror
            openEditor(doc.id)
        }
    }

    private fun closeTab() {
        val id = activeId.value ?: return
        lifecycleScope.launch {
            container.repository.saveNow(id, text.value, revision)
            container.repository.setState(id, open = false)
            activeId.value = null
            reload()
        }
    }

    private fun persistUriPermission(uri: Uri) {
        runCatching { gateway.takePersistablePermission(uri) }
    }

    /** R33：解绑工作目录（仅清除本应用记住的绑定，不删除目录里的任何文件）。 */
    private fun unbindWorkDir() {
        val prefs = getSharedPreferences("editor-prefs", MODE_PRIVATE)
        io.github.gscratchpad.platform.WorkDirPolicy.clear(prefs)
        workDirBinding.value = null
        toast("已解绑工作目录，本地文件未删除")
    }

    /** R33：把绑定的工作目录字符串还原成 Uri。 */
    private fun workDirUri(): android.net.Uri? =
        workDirBinding.value?.uri?.let { runCatching { android.net.Uri.parse(it) }.getOrNull() }

    /**
     * R42：从 File 直读浏览器打开本地文件——根治 SAF「下载」入口目录过滤导致的缺项。
     * 读真实路径正文 → 建库文档 → 绑定 sourcePath（flush 时由 FileGateway 原子写回原文件）→ 进编辑器。
     * 复用 [openWorkDirFile] 的导入内核，只是在选文件层换成文件浏览器。
     */
    private fun openLocalFilePath(path: String) {
        lifecycleScope.launch {
            val name = path.substringAfterLast('/')
            if (!io.github.gscratchpad.platform.OpenPolicy.isSupported(name)) {
                toast(io.github.gscratchpad.platform.OpenPolicy.REJECT_MESSAGE)
                return@launch
            }
            val text = fileGateway.readDocText(path)
            if (text == null) {
                toast("读取失败或文件非文本：$name")
                return@launch
            }
            // 已入库的同路径文档直接打开，避免重复导入
            val existing = docs.value.firstOrNull { doc ->
                container.dao.getMeta(MetaKeys.sourcePath(doc.id), null) == path
            }
            openFilePickerOpen.value = false
            if (existing != null) {
                switchToDoc(existing.id)
                return@launch
            }
            val format = when (io.github.gscratchpad.platform.OpenPolicy.extensionOf(name)) {
                "md", "markdown" -> Format.MD
                "html", "htm", "xhtml" -> Format.HTML
                else -> Format.TXT
            }
            val title = name.substringBeforeLast('.', name)
            flushEditor()
            val doc = container.repository.create(format, title)
            container.repository.saveNow(doc.id, text, 2)
            container.repository.setMeta(MetaKeys.sourcePath(doc.id), path)
            docs.value = container.dao.allDocuments()
            openEditor(doc.id)
            toast("已打开 $name")
        }
    }

    private fun openExternal(uri: Uri) {
        lifecycleScope.launch {
            try {
                // 打开过滤器已放开到 */*（兼容 ROM 把 octet-stream 另存的 .md 登记成 BIN），
                // 这里按扩展名白名单兜底，拒绝图片/压缩包等非文档，不让它们混进编辑器。
                val name = gateway.displayName(uri)
                if (!OpenPolicy.isSupported(name)) {
                    toast(OpenPolicy.REJECT_MESSAGE)
                    return@launch
                }
                gateway.takePersistablePermission(uri)
                val opened = gateway.open(uri)
                val format = when (OpenPolicy.extensionOf(opened.displayName)) {
                    "md", "markdown" -> Format.MD
                    "html", "htm" -> Format.HTML
                    else -> Format.TXT
                }
                val doc = container.repository.create(format, opened.displayName)
                container.repository.saveNow(doc.id, opened.text, 2)
                container.repository.setMeta(MetaKeys.sourcePath(doc.id), uri.toString())
                reload(doc.id)
                // 外部打开即进入编辑器：只加进最近列表、停在主页是 R20 报的缺陷
                openEditor(doc.id)
            } catch (e: Exception) {
                toast("打开失败：${e.message}")
            }
        }
    }

    private fun saveAsExternal(uri: Uri) {
        val id = activeId.value ?: return
        lifecycleScope.launch {
            try {
                val doc = container.repository.get(id) ?: return@launch
                // 另存必须写编辑器实时正文：新建文档时 text.value 仍是空串，只有 editorLatest 有内容。
                val body = SaveAsPolicy.content(editorLatest, text.value)
                gateway.save(uri, body, io.github.gscratchpad.platform.TextStyle(Charsets.UTF_8, false, io.github.gscratchpad.platform.NewlineStyle.LF))
                // 先把正文落内部库，避免「另存文件有内容、内部库仍是空串」的分叉。
                container.repository.saveNow(id, body, editorRevision)
                container.repository.setMeta(MetaKeys.sourcePath(id), uri.toString())
                // 对齐桌面版：另存后标题同步为文件名 stem，并打点进「最近」列表。
                val savedName = gateway.displayName(uri)
                val newTitle = SaveAsPolicy.savedTitle(savedName)
                if (newTitle.isNotBlank() && newTitle != doc.title) {
                    container.repository.rename(id, newTitle)
                }
                container.repository.touchOpened(id)
                // 只刷新列表数据，不 reload(id)——reload 会 activate → setDocument 重置编辑器、丢光标。
                // touchOpened 已把 opened_at 置新，allDocuments 按 opened_at DESC 会把该文档排到「最近」最前。
                docs.value = container.dao.allDocuments()
                toast("已保存到 $savedName")
            } catch (e: Exception) {
                toast("保存失败：${e.message}")
            }
        }
    }

    private fun importBackupFrom(uri: Uri) {
        lifecycleScope.launch {
            try {
                val cache = File(cacheDir, "import-${System.currentTimeMillis()}")
                cache.mkdirs()
                val zip = File(cache, "backup.zip")
                contentResolver.openInputStream(uri)?.use { input ->
                    zip.outputStream().use { output -> input.copyTo(output) }
                }
                importBackupZip(zip, cache)
            } catch (e: Exception) {
                toast("导入失败：${e.message}")
            }
        }
    }

    /** 备份包导入（SAF 与云备份共用）：解包 → [DesktopImporter] → 刷新列表。 */
    private suspend fun importBackupZip(zip: File, cache: File) {
        val unpacked = File(cache, "unpacked")
        DesktopImporter.extract(zip, unpacked)
        val importer = DesktopImporter(
            targetDb = container.db,
            dao = container.dao,
            assets = container.assets,
            paths = container.paths,
            openSourceDb = { file ->
                io.github.gscratchpad.data.openReadOnlySqlDb(file.absolutePath)
            },
            resolveSourceUri = { path ->
                val name = path.substringAfterLast('/')
                gateway.documentTreeRoots().firstOrNull { tree ->
                    runCatching {
                        androidx.documentfile.provider.DocumentFile.fromTreeUri(this@MainActivity, tree)
                            ?.findFile(name) != null
                    }.getOrDefault(false)
                }?.let { tree ->
                    runCatching {
                        androidx.documentfile.provider.DocumentFile.fromTreeUri(this@MainActivity, tree)
                            ?.findFile(name)?.uri?.toString()
                    }.getOrNull()
                }
            },
        )
        val report = importer.import(unpacked)
        reload()
        toast(
            "导入完成：${report.docsImported} 篇，冲突 ${report.conflicts}，" +
                "断链图片 ${report.brokenImages}，失效路径 ${report.deadPaths}" +
                if (report.errors.isEmpty()) "" else "，错误 ${report.errors.size}",
        )
    }

    /** §6.1 / §13：导出备份包（manifest + db 快照 + notes + assets），经 SAF 落盘。 */
    private fun exportBackupTo(uri: Uri) {
        lifecycleScope.launch {
            try {
                val id = activeId.value
                if (id != null) container.repository.saveNow(id, text.value, revision)
                container.repository.flush()
                val cache = File(cacheDir, "export-${System.currentTimeMillis()}.zip")
                val report = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    BackupExporter.export(
                        target = cache,
                        appVersion = "0.5.1",
                        exportedAt = System.currentTimeMillis() / 1000.0,
                        snapshotDb = { file ->
                            container.db.checkpointTruncate()
                            container.paths.dbFile.copyTo(file, overwrite = true)
                        },
                        notesDir = container.paths.notes,
                        assetsDir = container.paths.assets,
                    )
                }
                if (report.errors.isNotEmpty()) {
                    toast("导出失败：${report.errors.first()}")
                    return@launch
                }
                contentResolver.openOutputStream(uri)?.use { output ->
                    cache.inputStream().use { it.copyTo(output) }
                }
                cache.delete()
                toast("已导出：${report.notes} 篇镜像、${report.assets} 个资源、${report.bytes / 1024} KB")
            } catch (e: Exception) {
                toast("导出失败：${e.message}")
            }
        }
    }

    /** 物理键盘（方案附录 B）：返回 true 表示已消费。 */
    /** 物理键盘（方案附录 B）：在 Activity 层拦截，Compose 焦点树拿不到的组合键也能生效。 */
    @android.annotation.SuppressLint("RestrictedApi") // 覆写 ComponentActivity.dispatchKeyEvent 属平台常规做法
    override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
        if (event.action == android.view.KeyEvent.ACTION_DOWN) {
            val plain = when (event.keyCode) {
                android.view.KeyEvent.KEYCODE_F1 -> "F1"
                android.view.KeyEvent.KEYCODE_F2 -> "F2"
                android.view.KeyEvent.KEYCODE_F9 -> "F9"
                else -> null
            }
            plain?.let { name ->
                Shortcuts.resolvePlain(name)?.let { if (runShortcut(it)) return true }
            }
            if (event.isCtrlPressed) {
                val name = when (event.keyCode) {
                    android.view.KeyEvent.KEYCODE_N -> "N"
                    android.view.KeyEvent.KEYCODE_W -> "W"
                    android.view.KeyEvent.KEYCODE_F -> "F"
                    android.view.KeyEvent.KEYCODE_H -> "H"
                    android.view.KeyEvent.KEYCODE_P -> "P"
                    android.view.KeyEvent.KEYCODE_I -> "I"
                    android.view.KeyEvent.KEYCODE_O -> "O"
                    android.view.KeyEvent.KEYCODE_S -> "S"
                    android.view.KeyEvent.KEYCODE_D -> "D"
                    android.view.KeyEvent.KEYCODE_SLASH -> "SLASH"
                    android.view.KeyEvent.KEYCODE_TAB -> "TAB"
                    else -> null
                }
                val action = name?.let { Shortcuts.resolve(true, event.isShiftPressed, it) }
                if (action != null && runShortcut(action)) return true
            }
        }
        return super.dispatchKeyEvent(event)
    }

    /** 返回 true 表示已消费。 */
    private fun runShortcut(action: KeyAction): Boolean {
        android.util.Log.d("Gscratchpad", "shortcut $action")
        when (action) {
            KeyAction.NEW -> newDocument()
            KeyAction.CLOSE -> closeTab()
            // 查找/替换统一走页内查找条（路线 C 的 Compose 查找栏已删除）
            KeyAction.FIND, KeyAction.REPLACE -> editorHost?.openFind()
            KeyAction.PREVIEW -> {
                if (previewOpen) exitPreview() else enterPreview()
            }
            KeyAction.NEXT_TAB -> switchDocument(1)
            KeyAction.PREV_TAB -> switchDocument(-1)
            KeyAction.PALETTE -> editorHost?.openPalette()
            KeyAction.OUTLINE -> editorHost?.openOutline()
            KeyAction.SAVE -> lifecycleScope.launch { flushEditor(); toast("已保存") }
            KeyAction.SAVE_AS -> {
                val title = docs.value.firstOrNull { it.id == editingDocId }?.title ?: "未命名"
                launchSaveAs(title)
            }
            KeyAction.OPEN -> openFile.launch(OpenPolicy.MIME_TYPES)
            KeyAction.TOGGLE_SPLIT -> setSplit(!splitOn)
            KeyAction.HELP -> editorHost?.openHelp()
            KeyAction.IMAGE -> pickImage.launch("image/*")
            KeyAction.RENAME -> renameCurrentDialog()
        }
        return true
    }

    /** Q2：F2 重命名当前文档（物理键盘一等交互的常规动作）。 */
    private fun renameCurrentDialog() {
        val id = editingDocId
        if (id.isEmpty()) {
            toast("没有打开的文档")
            return
        }
        val current = docs.value.firstOrNull { it.id == id }?.title.orEmpty()
        val input = android.widget.EditText(this).apply {
            setText(current)
            setSelection(current.length)
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("重命名")
            .setView(input)
            .setPositiveButton("确定") { _, _ ->
                val title = input.text.toString().trim()
                if (title.isEmpty()) return@setPositiveButton
                lifecycleScope.launch {
                    container.repository.rename(id, title)
                    editorHost?.setTitle(title)
                    editorTitle = title
                    reload(id)
                    toast("已重命名")
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 阅读偏好持久化（字号 / 行高 / 折行），下次进入编辑器时回灌。 */
    private fun applyEditorPrefs() {
        val prefs = getSharedPreferences("editor-prefs", MODE_PRIVATE)
        editorHost?.setPrefs(
            prefs.getInt("fontSize", 15),
            prefs.getFloat("lineHeight", 1.2f),
            prefs.getBoolean("wrap", true),
            prefs.getString("fontFamily", "sans") ?: "sans",
        )
    }

    private fun saveEditorPrefs(json: String) {
        val obj = org.json.JSONObject(json)
        getSharedPreferences("editor-prefs", MODE_PRIVATE).edit {
            putInt("fontSize", obj.optInt("fontSize", 15))
            putFloat("lineHeight", obj.optDouble("lineHeight", 1.2).toFloat())
            putBoolean("wrap", obj.optBoolean("wrap", true))
        }
        android.util.Log.d(
            "Gscratchpad",
            "editor prefs saved ${obj.optInt("fontSize", 15)}/${obj.optDouble("lineHeight", 1.2)}/${obj.optBoolean("wrap", true)}",
        )
    }

    /** 无图标库依赖的「设置」滑块图标（三条滑轨 + 三枚旋钮）。 */
    @Composable
    private fun SlidersIcon(tint: Color) {
        Canvas(Modifier.size(20.dp)) {
            val rows = listOf(0.20f to 0.34f, 0.50f to 0.68f, 0.80f to 0.46f)
            rows.forEach { (yRatio, knobRatio) ->
                val y = size.height * yRatio
                drawLine(
                    color = tint.copy(alpha = 0.75f),
                    start = androidx.compose.ui.geometry.Offset(0f, y),
                    end = androidx.compose.ui.geometry.Offset(size.width, y),
                    strokeWidth = 1.4.dp.toPx(),
                )
                drawCircle(
                    color = tint,
                    radius = 3.dp.toPx(),
                    center = androidx.compose.ui.geometry.Offset(size.width * knobRatio, y),
                )
            }
        }
    }

    /** 月亮：切到日间的按钮图标（当前深色）。用背景色圆咬出月牙，避免引入 Path 贝塞尔。 */
    @Composable
    private fun MoonIcon(tint: Color, bg: Color) {
        Canvas(Modifier.size(20.dp)) {
            val r = size.minDimension / 2f
            drawCircle(color = tint.copy(alpha = 0.85f), radius = r * 0.9f)
            drawCircle(
                color = bg,
                radius = r * 0.62f,
                center = androidx.compose.ui.geometry.Offset(size.width * 1.06f, size.height * 0.32f),
            )
        }
    }

    /** 太阳：切到夜间的按钮图标（当前浅色）。 */
    @Composable
    private fun SunIcon(tint: Color) {
        Canvas(Modifier.size(20.dp)) {
            val c = androidx.compose.ui.geometry.Offset(size.width / 2f, size.height / 2f)
            drawCircle(color = tint, radius = size.minDimension * 0.24f, center = c)
            repeat(8) { i ->
                val a = Math.toRadians(i * 45.0)
                val inner = size.minDimension * 0.34f
                val outer = size.minDimension * 0.48f
                drawLine(
                    color = tint.copy(alpha = 0.8f),
                    start = androidx.compose.ui.geometry.Offset(
                        c.x + (inner * Math.cos(a)).toFloat(),
                        c.y + (inner * Math.sin(a)).toFloat(),
                    ),
                    end = androidx.compose.ui.geometry.Offset(
                        c.x + (outer * Math.cos(a)).toFloat(),
                        c.y + (outer * Math.sin(a)).toFloat(),
                    ),
                    strokeWidth = 1.4.dp.toPx(),
                )
            }
        }
    }

    /** 列表里的相对时间：updatedAt 为 epoch 秒（与 repository 的 now() 同口径）。 */
    private fun relativeTime(updatedAt: Double): String {
        if (updatedAt <= 0.0) return "未知时间"
        val delta = (System.currentTimeMillis() / 1000.0 - updatedAt).coerceAtLeast(0.0).toLong()
        return when {
            delta < 60 -> "刚刚"
            delta < 3600 -> "${delta / 60} 分钟前"
            delta < 86400 -> "${delta / 3600} 小时前"
            delta < 86400L * 30 -> "${delta / 86400} 天前"
            else -> {
                val cal = java.util.Calendar.getInstance().apply { timeInMillis = (updatedAt * 1000).toLong() }
                String.format(
                    java.util.Locale.US,
                    "%d-%02d-%02d",
                    cal.get(java.util.Calendar.YEAR),
                    cal.get(java.util.Calendar.MONTH) + 1,
                    cal.get(java.util.Calendar.DAY_OF_MONTH),
                )
            }
        }
    }

    private fun toast(message: String) {
        runOnUiThread { Toast.makeText(this, message, Toast.LENGTH_SHORT).show() }
    }

    /** 夜间模式一并延展到系统栏：状态栏/导航栏底色随主题，图标黑/白跟随（R20）。 */
    private fun setDark(on: Boolean) {
        dark.value = on
        getSharedPreferences("editor-prefs", MODE_PRIVATE).edit { putBoolean("dark", on) }
        editorHost?.setTheme(on)
        applySystemBars(on)
    }

    private fun applySystemBars(isDark: Boolean) {
        val bars = androidx.core.view.WindowCompat.getInsetsController(getWindow(), getWindow().decorView)
        bars.isAppearanceLightStatusBars = !isDark
        bars.isAppearanceLightNavigationBars = !isDark
        @Suppress("DEPRECATION")
        window.statusBarColor = if (isDark) 0xFF1F2328.toInt() else 0xFFFFFFFF.toInt()
        @Suppress("DEPRECATION")
        window.navigationBarColor = if (isDark) 0xFF1F2328.toInt() else 0xFFFFFFFF.toInt()
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            window.isNavigationBarContrastEnforced = false
        }
    }

    // ------------------------------------------------------------------ UI

    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun AppScreen() {
        val docList by docs.collectAsState()
        val isDark by dark.collectAsState()
        val workDir by workDirBinding.collectAsState()
        val prefs = remember { getSharedPreferences("editor-prefs", MODE_PRIVATE) }
        var settingsOpen by remember { mutableStateOf(false) }
        var showAll by remember { mutableStateOf(false) }
        // ---- R39 维护确认对话框状态
        var purgeConfirm by remember { mutableStateOf(false) }
        var purgeConfirmText by remember { mutableStateOf("") }
        var maintenanceConfirm by remember { mutableStateOf(false) }
        var maintenanceConfirmText by remember { mutableStateOf("") }
        // ---- T3 文件夹视图状态
        var showFolders by remember { mutableStateOf(false) }
        var folderList by remember { mutableStateOf<List<Folder>>(emptyList()) }
        var folderCounts by remember { mutableStateOf<Map<String, Int>>(emptyMap()) }
        var folderExpanded by remember { mutableStateOf<Set<String>>(setOf(FolderPolicy.UNFILED)) }
        var folderMoveDocId by remember { mutableStateOf<String?>(null) }
        var folderCreateOpen by remember { mutableStateOf(false) }
        var folderRenameTarget by remember { mutableStateOf<String?>(null) }
        var folderDeleteTarget by remember { mutableStateOf<String?>(null) }
        var folderDialogText by remember { mutableStateOf("") }
        var folderDialogError by remember { mutableStateOf<String?>(null) }
        var fontSize by remember { mutableStateOf(prefs.getInt("fontSize", 15)) }
        var lineHeight by remember { mutableStateOf(prefs.getFloat("lineHeight", 1.2f)) }
        var wrap by remember { mutableStateOf(prefs.getBoolean("wrap", true)) }
        var amoled by remember { mutableStateOf(prefs.getBoolean("amoled", false)) }
        var fontFamily by remember { mutableStateOf(prefs.getString("fontFamily", "sans") ?: "sans") }
        var readingSize by remember { mutableStateOf(prefs.getInt("readingSize", 16)) }
        var fullRead by remember { mutableStateOf(prefs.getBoolean("fullRead", false)) }
        var pdfDark by remember { mutableStateOf(prefs.getBoolean("pdfDark", false)) }
        var menuDocId by remember { mutableStateOf<String?>(null) }
        var renameTarget by remember { mutableStateOf<Document?>(null) }
        var renameText by remember { mutableStateOf("") }
        var deleteTarget by remember { mutableStateOf<Document?>(null) }
        // ---- R35 WebDAV Compose 对话框状态
        var cloudDialogOpen by remember { mutableStateOf(false) }
        var cloudUrlText by remember { mutableStateOf("") }
        var cloudUserText by remember { mutableStateOf("") }
        var cloudPassText by remember { mutableStateOf("") }
        val cloudTicket by cloudDialogTicket.collectAsState()
        LaunchedEffect(cloudTicket) {
            if (cloudTicket > 0) {
                val cfg = cloudConfig()
                cloudUrlText = cfg.baseUrl
                cloudUserText = cfg.user
                cloudPassText = cfg.password
                cloudDialogOpen = true
            }
        }

        fun persistPrefs(size: Int, line: Float, wrapped: Boolean) {
            prefs.edit {
                putInt("fontSize", size)
                putFloat("lineHeight", line)
                putBoolean("wrap", wrapped)
            }
            editorHost?.setPrefs(size, line, wrapped, fontFamily)
            android.util.Log.d("Gscratchpad", "prefs from home $size/$line/$wrapped")
        }

        fun openLink(url: String) {
            runCatching {
                startActivity(
                    Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }.onFailure { toast("没有可打开该链接的应用") }
        }

        val background = when {
            isDark && amoled -> Color(0xFF000000)
            isDark -> Color(0xFF1F2328)
            else -> Color(0xFFFFFFFF)
        }
        val foreground = if (isDark) Color(0xFFE6EDF3) else Color(0xFF1F2328)
        val cardBg = when {
            isDark && amoled -> Color(0xFF0D0D0D)
            isDark -> Color(0xFF262B31)
            else -> Color(0xFFF2F3F5)
        }
        val muted = foreground.copy(alpha = 0.58f)

        MaterialTheme {
            Surface(Modifier.fillMaxSize(), color = background) {
                Column(Modifier.fillMaxSize().systemBarsPadding()) {
                    Row(
                        Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text("Gscratchpad", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = foreground)
                            Text(
                                "Markdown 编辑 · 本地存储",
                                Modifier.padding(top = 2.dp),
                                fontSize = 12.sp,
                                color = muted,
                            )
                        }
                        Box(
                            Modifier.size(44.dp).clickable { settingsOpen = true },
                            contentAlignment = Alignment.Center,
                        ) { SlidersIcon(foreground) }
                        Spacer(Modifier.width(2.dp))
                        Box(
                            Modifier.size(44.dp).clickable { setDark(!isDark) },
                            contentAlignment = Alignment.Center,
                        ) {
                            if (isDark) MoonIcon(foreground, background) else SunIcon(foreground)
                        }
                    }

                    Column(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Button(
                            onClick = { openFilePickerOpen.value = true },
                            Modifier.fillMaxWidth().height(54.dp),
                            shape = RoundedCornerShape(14.dp),
                            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                                containerColor = if (isDark) Color(0xFFE6EDF3) else Color(0xFF1F2328),
                                contentColor = if (isDark) Color(0xFF1F2328) else Color(0xFFFFFFFF),
                            ),
                        ) {
                            Text("打开文件", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        }
                        // R44：SAF 备用入口移到「设置工作目录」下方（用户拍板：合并后的位置在此）；
                        // 云盘 / 其它 DocumentsProvider 仍需系统选择器（File API 看不到云盘）。
                        OutlinedButton(
                            onClick = ::newDocument,
                            Modifier.fillMaxWidth().height(50.dp),
                            shape = RoundedCornerShape(14.dp),
                            border = BorderStroke(1.dp, foreground.copy(alpha = 0.26f)),
                        ) {
                            Text("新建文档", fontSize = 15.sp, color = foreground)
                        }
                        // R40：打开本地文件夹 → File 直读浏览器逐级选择（绕开 SAF 视图过滤）；R44 改名
                        OutlinedButton(
                            onClick = ::openWorkDirPicker,
                            Modifier.fillMaxWidth().height(50.dp),
                            shape = RoundedCornerShape(14.dp),
                            border = BorderStroke(1.dp, foreground.copy(alpha = 0.26f)),
                        ) {
                            Text("设置工作目录", fontSize = 14.sp, color = foreground)
                        }
                        TextButton(
                            onClick = { openFile.launch(OpenPolicy.MIME_TYPES) },
                            Modifier.fillMaxWidth(),
                        ) {
                            Text("从云盘或其它位置打开", fontSize = 12.sp, color = muted)
                        }
                        if (workDir != null) {
                            Row(
                                Modifier.fillMaxWidth().padding(horizontal = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    io.github.gscratchpad.platform.WorkDirPolicy.label(workDir!!),
                                    fontSize = 12.sp,
                                    color = muted,
                                    modifier = Modifier.weight(1f),
                                )
                                TextButton(onClick = { unbindWorkDir() }) {
                                    Text("解绑", fontSize = 12.sp, color = muted)
                                }
                            }
                        }
                    }

                    val visibleDocs = if (showAll) docList else docList.filter { !it.recentHidden }

                    Row(
                        Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 12.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // 常驻三态切换：最近 / 全部 / 文件夹（T3）
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "最近",
                                color = if (!showAll && !showFolders) foreground else muted,
                                fontSize = 12.sp,
                                letterSpacing = 1.sp,
                                fontWeight = if (!showAll && !showFolders) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.clickable { showFolders = false; showAll = false }.padding(horizontal = 4.dp, vertical = 6.dp),
                            )
                            Text("/", color = muted, fontSize = 12.sp)
                            Text(
                                "全部",
                                color = if (showAll && !showFolders) foreground else muted,
                                fontSize = 12.sp,
                                letterSpacing = 1.sp,
                                fontWeight = if (showAll && !showFolders) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.clickable { showFolders = false; showAll = true }.padding(horizontal = 4.dp, vertical = 6.dp),
                            )
                            Text("/", color = muted, fontSize = 12.sp)
                            Text(
                                "文件夹",
                                color = if (showFolders) foreground else muted,
                                fontSize = 12.sp,
                                letterSpacing = 1.sp,
                                fontWeight = if (showFolders) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.clickable {
                                    showFolders = true
                                    lifecycleScope.launch { reloadFolders { f, c -> folderList = f; folderCounts = c } }
                                }.padding(horizontal = 4.dp, vertical = 6.dp),
                            )
                        }
                        if (!showAll && !showFolders) {
                            TextButton(
                                onClick = {
                                    lifecycleScope.launch {
                                        container.repository.clearAllRecent()
                                        reload()
                                        toast("已清除最近记录，文档与正文未删除")
                                    }
                                },
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                                modifier = Modifier.height(28.dp),
                            ) {
                                Text("clear", color = muted, fontSize = 12.sp, letterSpacing = 1.sp)
                            }
                        }
                        Spacer(Modifier.weight(1f))
                        Text(
                            if (showFolders) "${folderList.size} 个文件夹" else "${visibleDocs.size} 个文件",
                            color = muted, fontSize = 12.sp,
                        )
                    }
                    if (showFolders) {
                        FoldersScreen(
                            folders = folderList,
                            docs = docList,
                            counts = folderCounts,
                            expanded = folderExpanded,
                            onToggleGroup = { key ->
                                folderExpanded = if (folderExpanded.contains(key)) folderExpanded - key
                                else folderExpanded + key
                            },
                            onOpenDoc = { id -> openEditor(id) },
                            onLongClickDoc = { id -> folderMoveDocId = id },
                            onMoveDocClick = { id -> folderMoveDocId = id },
                            onCreateFolder = { folderCreateOpen = true; folderDialogText = ""; folderDialogError = null },
                            onRenameFolder = { name ->
                                folderRenameTarget = name; folderDialogText = name; folderDialogError = null
                            },
                            onDeleteFolder = { name -> folderDeleteTarget = name },
                            isDark = isDark,
                            foreground = foreground,
                            cardBg = cardBg,
                            muted = muted,
                        )
                    } else Column(
                        Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (visibleDocs.isEmpty()) {
                            Text(
                                if (showAll) "还没有文档，点上方「新建文档」开始"
                                else "最近记录已清空，文档仍在库中，可点下方「查看全部文档」找回",
                                Modifier.padding(vertical = 24.dp),
                                color = muted,
                                fontSize = 14.sp,
                            )
                        }
                        visibleDocs.forEach { doc ->
                            ComposeBox {
                                Row(
                                    Modifier.fillMaxWidth()
                                        .clip(RoundedCornerShape(12.dp))
                                        .background(cardBg)
                                        .combinedClickable(
                                            onClick = { openEditor(doc.id) },
                                            onLongClick = { menuDocId = doc.id },
                                        )
                                        .padding(start = 14.dp, end = 4.dp, top = 10.dp, bottom = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                        Text(
                                            doc.title,
                                            fontSize = 16.sp,
                                            color = foreground,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        Text(
                                            doc.format.name.lowercase() + " · " + relativeTime(doc.updatedAt) +
                                                if (doc.recentHidden) " · 已清除记录" else "",
                                            fontSize = 12.sp,
                                            color = foreground.copy(alpha = 0.5f),
                                        )
                                    }
                                    if (doc.recentHidden) {
                                        TextButton(
                                            onClick = {
                                                lifecycleScope.launch {
                                                    container.repository.restoreRecent(doc.id)
                                                    reload()
                                                    toast("已恢复到最近列表")
                                                }
                                            },
                                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                                        ) { Text("恢复", fontSize = 12.sp, color = foreground.copy(alpha = 0.7f)) }
                                    } else {
                                        // × 只清除最近记录，不删除文档与正文（删除走长按菜单）
                                        Box(
                                            Modifier.size(44.dp).clickable {
                                                lifecycleScope.launch {
                                                    container.repository.clearRecent(doc.id)
                                                    reload()
                                                    toast("已清除记录（文档未删除）")
                                                }
                                            },
                                            contentAlignment = Alignment.Center,
                                        ) {
                                            Text("×", fontSize = 20.sp, color = foreground.copy(alpha = 0.45f))
                                        }
                                    }
                                }
                                DropdownMenu(
                                    expanded = menuDocId == doc.id,
                                    onDismissRequest = { menuDocId = null },
                                    containerColor = cardBg,
                                    shape = RoundedCornerShape(12.dp),
                                    tonalElevation = 0.dp,
                                    shadowElevation = 8.dp,
                                ) {
                                    DropdownMenuItem(
                                        text = { Text("重命名", fontSize = 15.sp) },
                                        leadingIcon = {
                                            io.github.gscratchpad.platform.RenameIcon(foreground)
                                        },
                                        colors = io.github.gscratchpad.platform.appMenuColors(foreground, muted),
                                        onClick = {
                                            menuDocId = null
                                            renameTarget = doc
                                            renameText = doc.title
                                        },
                                    )
                                    DropdownMenuItem(
                                        text = { Text("删除", fontSize = 15.sp) },
                                        leadingIcon = {
                                            io.github.gscratchpad.platform.DeleteIcon(foreground)
                                        },
                                        colors = io.github.gscratchpad.platform.appMenuColors(foreground, muted),
                                        onClick = {
                                            menuDocId = null
                                            deleteTarget = doc
                                        },
                                    )
                                }
                            }
                        }
                        if (!showAll) {
                            TextButton(
                                onClick = { showAll = true },
                                modifier = Modifier.align(Alignment.CenterHorizontally),
                            ) {
                                Text("查看全部文档（${docList.size}）", fontSize = 12.sp, color = muted)
                            }
                        }
                        Spacer(Modifier.height(12.dp))
                    }

                    if (settingsOpen) {
                        Dialog(
                            onDismissRequest = { settingsOpen = false },
                            properties = DialogProperties(
                                usePlatformDefaultWidth = false,
                                decorFitsSystemWindows = false,
                            ),
                        ) {
                            SettingsScreen(
                                isDark = isDark,
                                background = background,
                                foreground = foreground,
                                cardBg = cardBg,
                                muted = muted,
                                fontSize = fontSize,
                                lineHeight = lineHeight,
                                wrap = wrap,
                                amoled = amoled,
                                fontFamily = fontFamily,
                                readingSize = readingSize,
                                fullRead = fullRead,
                                pdfDark = pdfDark,
                                onToggleTheme = { setDark(!isDark) },
                                onAmoled = {
                                    amoled = it
                                    prefs.edit { putBoolean("amoled", it) }
                                },
                                onFontSize = { fontSize = it; persistPrefs(it, lineHeight, wrap) },
                                onLineHeight = { lineHeight = it; persistPrefs(fontSize, it, wrap) },
                                onWrap = { wrap = it; persistPrefs(fontSize, lineHeight, it) },
                                onFontFamily = {
                                    fontFamily = it
                                    prefs.edit { putString("fontFamily", it) }
                                    editorHost?.setPrefs(fontSize, lineHeight, wrap, it)
                                },
                                onReadingSize = {
                                    readingSize = it
                                    prefs.edit { putInt("readingSize", it) }
                                },
                                onFullRead = {
                                    fullRead = it
                                    prefs.edit { putBoolean("fullRead", it) }
                                },
                                onPdfDark = {
                                    pdfDark = it
                                    prefs.edit { putBoolean("pdfDark", it) }
                                },
                                onFeedbackGithub = {
                                    openLink("https://github.com/gscratchpad/gscratchpad")
                                },
                                onFeedbackMail = {
                                    openLink("mailto:feedback@gscratchpad.local?subject=Gscratchpad%20feedback")
                                },
                                onImportBackup = {
                                    settingsOpen = false
                                    importBackup.launch(arrayOf("application/zip", "application/octet-stream"))
                                },
                                onExportBackup = {
                                    val title = docs.value.firstOrNull()?.title ?: "gscratchpad"
                                    settingsOpen = false
                                    exportBackup.launch("$title-backup.zip")
                                },
                                onCloud = {
                                    settingsOpen = false
                                    showCloudDialog()
                                },
                                onPurgeClosed = {
                                    preparePurgeClosed { text ->
                                        purgeConfirmText = text
                                        purgeConfirm = true
                                    }
                                },
                                onMaintenance = {
                                    prepareMaintenance { text ->
                                        maintenanceConfirmText = text
                                        maintenanceConfirm = true
                                    }
                                },
                                storageGranted = allFilesGranted.value,
                                onRequestStorage = ::requestAllFilesAccess,
                                onClose = { settingsOpen = false },
                            )
                        }
                    }

                    // ---- R40：File 直读工作目录浏览器
                    if (dirPickerOpen.value) {
                        io.github.gscratchpad.platform.FileDirPicker(
                            startPath = io.github.gscratchpad.platform.FileDirPolicy.ROOT,
                            granted = allFilesGranted.value,
                            foreground = foreground,
                            muted = muted,
                            background = background,
                            cardBg = cardBg,
                            onPick = ::bindWorkDirPath,
                            onRequestPermission = ::requestAllFilesAccess,
                            onDismiss = { dirPickerOpen.value = false },
                            permissionHint = io.github.gscratchpad.platform.StorageAccess.hint(Build.VERSION.SDK_INT),
                            permissionAction = io.github.gscratchpad.platform.StorageAccess.actionLabel(Build.VERSION.SDK_INT),
                        )
                    }

                    // ---- R42：File 本地文件打开浏览器（绕开 SAF 视图过滤）；R43：以工作目录为根
                    if (openFilePickerOpen.value) {
                        io.github.gscratchpad.platform.FileOpenPicker(
                            startPath = workDir?.path?.let { io.github.gscratchpad.platform.FileDirPolicy.normalize(it) }
                                ?: io.github.gscratchpad.platform.FileDirPolicy.ROOT,
                            granted = allFilesGranted.value,
                            foreground = foreground,
                            muted = muted,
                            background = background,
                            cardBg = cardBg,
                            onPickFile = ::openLocalFilePath,
                            onRequestPermission = ::requestAllFilesAccess,
                            onDismiss = { openFilePickerOpen.value = false },
                            permissionHint = io.github.gscratchpad.platform.StorageAccess.hint(Build.VERSION.SDK_INT),
                            permissionAction = io.github.gscratchpad.platform.StorageAccess.actionLabel(Build.VERSION.SDK_INT),
                        )
                    }

                    // ---- R39：维护确认对话框（先计数后确认，风格与 R35 一致）
                    if (purgeConfirm) {
                        AlertDialog(
                            onDismissRequest = { purgeConfirm = false },
                            containerColor = background,
                            title = { Text("清除已关闭的笔记？", color = foreground) },
                            text = { Text(purgeConfirmText, fontSize = 13.sp, color = foreground) },
                            confirmButton = {
                                TextButton(onClick = {
                                    executePurgeClosed { msg ->
                                        purgeConfirm = false
                                        toast(msg)
                                    }
                                }) { Text("移除记录", color = foreground) }
                            },
                            dismissButton = {
                                TextButton(onClick = { purgeConfirm = false }) { Text("取消", color = muted) }
                            },
                        )
                    }
                    if (maintenanceConfirm) {
                        AlertDialog(
                            onDismissRequest = { maintenanceConfirm = false },
                            containerColor = background,
                            title = { Text("清理孤儿文件并压缩数据库？", color = foreground) },
                            text = { Text(maintenanceConfirmText, fontSize = 13.sp, color = foreground) },
                            confirmButton = {
                                TextButton(onClick = {
                                    executeMaintenance { msg ->
                                        maintenanceConfirm = false
                                        toast(msg)
                                    }
                                }) { Text("开始清理", color = foreground) }
                            },
                            dismissButton = {
                                TextButton(onClick = { maintenanceConfirm = false }) { Text("取消", color = muted) }
                            },
                        )
                    }

                    // ---- R35：WebDAV 云备份对话框（Compose，风格与重命名/删除一致）
                    if (cloudDialogOpen) {
                        AlertDialog(
                            onDismissRequest = { cloudDialogOpen = false },
                            containerColor = background,
                            title = {
                                Text(
                                    "云备份（WebDAV）",
                                    color = foreground,
                                    fontSize = 19.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            },
                            text = {
                                val fieldColors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                    focusedTextColor = foreground,
                                    unfocusedTextColor = foreground,
                                    cursorColor = foreground,
                                    focusedLabelColor = muted,
                                    unfocusedLabelColor = muted,
                                    focusedPlaceholderColor = muted.copy(alpha = 0.7f),
                                    unfocusedPlaceholderColor = muted.copy(alpha = 0.7f),
                                    focusedBorderColor = foreground.copy(alpha = 0.6f),
                                    unfocusedBorderColor = foreground.copy(alpha = 0.28f),
                                )
                                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                    OutlinedTextField(
                                        value = cloudUrlText,
                                        onValueChange = { cloudUrlText = it },
                                        singleLine = true,
                                        label = { Text("WebDAV 目录 URL") },
                                        placeholder = { Text("https://…/dav/") },
                                        colors = fieldColors,
                                    )
                                    OutlinedTextField(
                                        value = cloudUserText,
                                        onValueChange = { cloudUserText = it },
                                        singleLine = true,
                                        label = { Text("账号（可空）") },
                                        colors = fieldColors,
                                    )
                                    OutlinedTextField(
                                        value = cloudPassText,
                                        onValueChange = { cloudPassText = it },
                                        singleLine = true,
                                        label = { Text("密码 / 应用密码") },
                                        visualTransformation = PasswordVisualTransformation(),
                                        colors = fieldColors,
                                    )
                                }
                            },
                            confirmButton = {
                                Button(
                                    onClick = {
                                        saveCloudConfig(
                                            cloudUrlText.trim(), cloudUserText.trim(), cloudPassText,
                                        )
                                        cloudDialogOpen = false
                                        toast("云备份配置已保存")
                                    },
                                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                                        containerColor = if (isDark) Color(0xFFE6EDF3) else Color(0xFF1F2328),
                                        contentColor = if (isDark) Color(0xFF1F2328) else Color(0xFFFFFFFF),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                ) { Text("保存配置") }
                            },
                            dismissButton = {
                                Row {
                                    TextButton(onClick = {
                                        saveCloudConfig(
                                            cloudUrlText.trim(), cloudUserText.trim(), cloudPassText,
                                        )
                                        cloudDialogOpen = false
                                        cloudUpload()
                                    }) { Text("上传", color = foreground) }
                                    TextButton(onClick = {
                                        saveCloudConfig(
                                            cloudUrlText.trim(), cloudUserText.trim(), cloudPassText,
                                        )
                                        cloudDialogOpen = false
                                        cloudDownload()
                                    }) { Text("从云端恢复", color = foreground) }
                                }
                            },
                        )
                    }

                    renameTarget?.let { doc ->
                        AlertDialog(
                            onDismissRequest = { renameTarget = null },
                            title = { Text("重命名") },
                            containerColor = background,
                            text = {
                                OutlinedTextField(
                                    value = renameText,
                                    onValueChange = { renameText = it },
                                    singleLine = true,
                                    label = { Text("标题") },
                                )
                            },
                            confirmButton = {
                                Button(onClick = {
                                    val title = renameText.trim()
                                    if (title.isEmpty()) {
                                        toast("标题不能为空")
                                    } else {
                                        lifecycleScope.launch {
                                            container.repository.rename(doc.id, title)
                                            renameTarget = null
                                            reload(doc.id)
                                            toast("已重命名为「$title」")
                                        }
                                    }
                                }) { Text("确定") }
                            },
                            dismissButton = {
                                Button(onClick = { renameTarget = null }) { Text("取消") }
                            },
                        )
                    }

                    deleteTarget?.let { doc ->
                        AlertDialog(
                            onDismissRequest = { deleteTarget = null },
                            title = { Text("从应用移除文档") },
                            containerColor = background,
                            text = { Text("将从应用中移除「${doc.title}」的记录与正文缓存；本机上的原文件不会被删除，仍可重新打开。") },
                            confirmButton = {
                                Button(onClick = {
                                    lifecycleScope.launch {
                                        container.repository.delete(doc.id)
                                        if (activeId.value == doc.id) activeId.value = null
                                        deleteTarget = null
                                        reload()
                                        toast("已从应用移除「${doc.title}」")
                                    }
                                }) { Text("移除") }
                            },
                            dismissButton = {
                                Button(onClick = { deleteTarget = null }) { Text("取消") }
                            },
                        )
                    }

                    // ---- T3 文件夹：新建 / 重命名对话框（共用，folderRenameTarget=null 表示新建）
                    if (folderCreateOpen || folderRenameTarget != null) {
                        val isRename = folderRenameTarget != null
                        AlertDialog(
                            onDismissRequest = { folderCreateOpen = false; folderRenameTarget = null },
                            title = { Text(if (isRename) "重命名文件夹" else "新建文件夹") },
                            containerColor = background,
                            text = {
                                Column {
                                    OutlinedTextField(
                                        value = folderDialogText,
                                        onValueChange = { folderDialogText = it; folderDialogError = null },
                                        singleLine = true,
                                        label = { Text("文件夹名") },
                                        isError = folderDialogError != null,
                                    )
                                    if (folderDialogError != null) {
                                        Text(
                                            folderDialogError!!,
                                            color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                                            fontSize = 12.sp,
                                            modifier = Modifier.padding(top = 6.dp),
                                        )
                                    }
                                }
                            },
                            confirmButton = {
                                Button(onClick = {
                                    lifecycleScope.launch {
                                        val err = folderWrite(folderRenameTarget, folderDialogText)
                                        if (err == null) {
                                            folderCreateOpen = false; folderRenameTarget = null
                                            reload()
                                            reloadFolders { f, c -> folderList = f; folderCounts = c }
                                            toast(if (isRename) "已重命名文件夹" else "已新建文件夹")
                                        } else {
                                            folderDialogError = err
                                        }
                                    }
                                }) { Text("确定") }
                            },
                            dismissButton = {
                                Button(onClick = { folderCreateOpen = false; folderRenameTarget = null }) { Text("取消") }
                            },
                        )
                    }

                    // ---- T3 文件夹：删除确认（强调文档回到未归档、不删除正文）
                    folderDeleteTarget?.let { name ->
                        AlertDialog(
                            onDismissRequest = { folderDeleteTarget = null },
                            title = { Text("删除文件夹") },
                            containerColor = background,
                            text = { Text("删除「$name」后，其中的笔记会回到「未归档」，正文不会被删除。") },
                            confirmButton = {
                                Button(onClick = {
                                    lifecycleScope.launch {
                                        container.repository.deleteFolder(name)
                                        folderDeleteTarget = null
                                        reload()
                                        reloadFolders { f, c -> folderList = f; folderCounts = c }
                                        toast("已删除文件夹「$name」，笔记已回到未归档")
                                    }
                                }) { Text("删除") }
                            },
                            dismissButton = {
                                Button(onClick = { folderDeleteTarget = null }) { Text("取消") }
                            },
                        )
                    }

                    // ---- T3 文件夹：长按文档 → 选目标文件夹移动（Q8）
                    folderMoveDocId?.let { docId ->
                        val targets = listOf("") + folderList.map { it.name }
                        DropdownMenu(
                            expanded = true,
                            onDismissRequest = { folderMoveDocId = null },
                            containerColor = cardBg,
                            shape = RoundedCornerShape(12.dp),
                            tonalElevation = 0.dp,
                            shadowElevation = 8.dp,
                        ) {
                            Text(
                                "移动到文件夹",
                                Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                fontSize = 12.sp, color = muted,
                            )
                            targets.forEach { target ->
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            if (target.isEmpty()) FolderPolicy.UNFILED else target,
                                            fontSize = 15.sp,
                                        )
                                    },
                                    leadingIcon = {
                                        io.github.gscratchpad.platform.FolderOutlineIcon(foreground)
                                    },
                                    colors = io.github.gscratchpad.platform.appMenuColors(foreground, muted),
                                    onClick = {
                                        folderMoveDocId = null
                                        lifecycleScope.launch {
                                            container.repository.moveToFolder(docId, target)
                                            reload()
                                            reloadFolders { f, c -> folderList = f; folderCounts = c }
                                            toast("已移动到「${FolderPolicy.display(target)}」")
                                        }
                                    },
                                )
                            }
                        }
                    }

                    LaunchedEffect(isDark) {
                        editorHost?.setTheme(isDark)
                        applySystemBars(isDark)
                    }
                }
            }
        }
    }

    // ---------------------------------------------------------------- 设置页

    /** 全屏设置页：参照 `android/tmp/Screenshot_20261119_175253_com.pilcrowmd.jpg` 的分组卡片布局。 */
    @Composable
    private fun SettingsScreen(
        isDark: Boolean,
        background: Color,
        foreground: Color,
        cardBg: Color,
        muted: Color,
        fontSize: Int,
        lineHeight: Float,
        wrap: Boolean,
        amoled: Boolean,
        fontFamily: String,
        readingSize: Int,
        fullRead: Boolean,
        pdfDark: Boolean,
        onToggleTheme: () -> Unit,
        onAmoled: (Boolean) -> Unit,
        onFontSize: (Int) -> Unit,
        onLineHeight: (Float) -> Unit,
        onWrap: (Boolean) -> Unit,
        onFontFamily: (String) -> Unit,
        onReadingSize: (Int) -> Unit,
        onFullRead: (Boolean) -> Unit,
        onPdfDark: (Boolean) -> Unit,
        onFeedbackGithub: () -> Unit,
        onFeedbackMail: () -> Unit,
        onImportBackup: () -> Unit,
        onExportBackup: () -> Unit,
        onCloud: () -> Unit,
        onPurgeClosed: () -> Unit,
        onMaintenance: () -> Unit,
        storageGranted: Boolean,
        onRequestStorage: () -> Unit,
        onClose: () -> Unit,
    ) {
        Surface(Modifier.fillMaxSize(), color = background) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                    .systemBarsPadding().padding(horizontal = 14.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(9.dp),
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Settings", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = foreground)
                        Text(
                            "Customize your editing experience",
                            Modifier.padding(top = 1.dp),
                            fontSize = 12.sp,
                            color = muted,
                        )
                    }
                    Box(
                        Modifier.size(36.dp).clip(RoundedCornerShape(18.dp))
                            .background(cardBg).clickable { onClose() },
                        contentAlignment = Alignment.Center,
                    ) { Text("✕", fontSize = 15.sp, color = muted) }
                }

                SettingLabel("APPEARANCE", muted)

                SettingCard(cardBg) {
                    Text("Theme", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        // 夜间 / AMOLED（纯黑）/ 日间 三段
                        SegmentPill("夜间", isDark && !amoled, foreground, muted, Modifier.weight(1f)) {
                            onAmoled(false)
                            if (!isDark) onToggleTheme()
                        }
                        SegmentPill("AMOLED", isDark && amoled, foreground, muted, Modifier.weight(1f)) {
                            onAmoled(true)
                            if (!isDark) onToggleTheme()
                        }
                        SegmentPill("日间", !isDark, foreground, muted, Modifier.weight(1f)) {
                            onAmoled(false)
                            if (isDark) onToggleTheme()
                        }
                    }
                }

                SettingCard(cardBg) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("字体", Modifier.weight(1f), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                        Text(
                            when (fontFamily) {
                                "mono" -> "等宽"
                                "serif" -> "衬线"
                                else -> "无衬线"
                            },
                            fontSize = 13.sp,
                            color = muted,
                        )
                    }
                    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        SegmentPill("无衬线", fontFamily == "sans", foreground, muted, Modifier.weight(1f)) {
                            onFontFamily("sans")
                        }
                        SegmentPill("等宽", fontFamily == "mono", foreground, muted, Modifier.weight(1f)) {
                            onFontFamily("mono")
                        }
                        SegmentPill("衬线", fontFamily == "serif", foreground, muted, Modifier.weight(1f)) {
                            onFontFamily("serif")
                        }
                    }
                }

                SettingCard(cardBg) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("编辑字号", Modifier.weight(1f), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                        Text("$fontSize sp", fontSize = 13.sp, color = muted)
                    }
                    Row(Modifier.padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("A", fontSize = 12.sp, color = muted)
                        Slider(
                            value = fontSize.toFloat(),
                            onValueChange = { onFontSize(it.toInt().coerceIn(11, 32)) },
                            valueRange = 11f..32f,
                            steps = 20,
                            colors = sliderColors(foreground),
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        Text("A", fontSize = 20.sp, color = muted)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("阅读字号", Modifier.weight(1f), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                        Text("$readingSize px", fontSize = 13.sp, color = muted)
                    }
                    Row(Modifier.padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("A", fontSize = 12.sp, color = muted)
                        Slider(
                            value = readingSize.toFloat(),
                            onValueChange = { onReadingSize(it.toInt().coerceIn(12, 28)) },
                            valueRange = 12f..28f,
                            steps = 15,
                            colors = sliderColors(foreground),
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        Text("A", fontSize = 20.sp, color = muted)
                    }
                    Text(
                        "正文示例 · Markdown 编辑",
                        fontSize = fontSize.sp,
                        color = foreground.copy(alpha = 0.85f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }

                SettingCard(cardBg) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("行高", Modifier.weight(1f), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                        Text(String.format(java.util.Locale.US, "%.2f", lineHeight), fontSize = 13.sp, color = muted)
                    }
                    Slider(
                        value = lineHeight,
                        onValueChange = { onLineHeight((it * 20f).toInt() / 20f) },
                        valueRange = 0.5f..2.5f,
                        steps = 39,
                        colors = sliderColors(foreground),
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }

                SettingCard(cardBg) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("自动折行", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                            Text("长行在编辑区内换行显示，不横向滚动", fontSize = 11.sp, color = muted)
                        }
                        Switch(
                            checked = wrap,
                            onCheckedChange = onWrap,
                            colors = SwitchDefaults.colors(checkedTrackColor = foreground.copy(alpha = 0.75f)),
                        )
                    }
                    SettingDivider(foreground)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("全屏阅读", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                            Text("预览页隐藏顶栏，正文占满屏幕", fontSize = 11.sp, color = muted)
                        }
                        Switch(
                            checked = fullRead,
                            onCheckedChange = onFullRead,
                            colors = SwitchDefaults.colors(checkedTrackColor = foreground.copy(alpha = 0.75f)),
                        )
                    }
                    SettingDivider(foreground)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("PDF 深色导出", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = foreground)
                            Text("导出 PDF 时使用深色底（默认白底）", fontSize = 11.sp, color = muted)
                        }
                        Switch(
                            checked = pdfDark,
                            onCheckedChange = onPdfDark,
                            colors = SwitchDefaults.colors(checkedTrackColor = foreground.copy(alpha = 0.75f)),
                        )
                    }
                }

                SettingLabel("DATA", muted)
                SettingCard(cardBg) {
                    SettingRow("导入备份", "从桌面版备份 zip 恢复", foreground, muted, onImportBackup)
                    SettingDivider(foreground)
                    SettingRow("导出备份", "打包数据库、正文与图片", foreground, muted, onExportBackup)
                    SettingDivider(foreground)
                    SettingRow("云端备份（WebDAV）", "上传 / 从云端恢复", foreground, muted, onCloud)
                }

                // R39：复刻桌面版的两个维护动作（先扫描计数、确认后才动数据目录）
                SettingLabel("MAINTENANCE", muted)
                SettingCard(cardBg) {
                    SettingRow("清除已关闭的笔记", "从应用移除已关闭笔记的记录与图片缓存，原文件保留", foreground, muted, onPurgeClosed)
                    SettingDivider(foreground)
                    SettingRow("清理孤儿文件并压缩数据库", "扫描无对应笔记的残留文件与失效映射", foreground, muted, onMaintenance)
                }

                // R40：工作目录走 File 直读，必须授予「所有文件访问」权限才能浏览真实目录。
                SettingLabel("STORAGE", muted)
                SettingCard(cardBg) {
                    SettingRow(
                        "存储权限（本地文件夹必需）",
                        if (storageGranted) "已授予 · 可浏览真实目录"
                        else "未授予 · 点此开启「${io.github.gscratchpad.platform.StorageAccess.actionLabel(Build.VERSION.SDK_INT)}」",
                        foreground, muted,
                        if (!storageGranted) onRequestStorage else null,
                    )
                }

                SettingLabel("FEEDBACK", muted)
                SettingCard(cardBg) {
                    SettingRow("GitHub 仓库", "查看源码与更新记录", foreground, muted, onFeedbackGithub)
                    SettingDivider(foreground)
                    SettingRow("邮件反馈", "描述问题或建议", foreground, muted, onFeedbackMail)
                }

                SettingLabel("ABOUT", muted)
                SettingCard(cardBg) {
                    // 版本从 PackageManager 读取，避免与 build.gradle.kts 硬编码漂移
                    val ctx = androidx.compose.ui.platform.LocalContext.current
                    val pkgInfo = runCatching {
                        @Suppress("DEPRECATION")
                        ctx.packageManager.getPackageInfo(ctx.packageName, 0)
                    }.getOrNull()
                    val verLabel = if (pkgInfo != null) {
                        @Suppress("DEPRECATION")
                        "${pkgInfo.versionName} · versionCode ${pkgInfo.versionCode}"
                    } else "未知版本"
                    SettingRow("版本", verLabel, foreground, muted, null)
                    SettingDivider(foreground)
                    SettingRow("数据目录", "应用私有 files/（不联网，除显式云备份）", foreground, muted, null)
                }
                Spacer(Modifier.height(12.dp))
            }
        }
    }

    /** Slider 用主题前景色，避免 Material 默认紫色与黑白灰界面冲突。 */
    @Composable
    private fun sliderColors(foreground: Color) = androidx.compose.material3.SliderDefaults.colors(
        thumbColor = foreground,
        activeTrackColor = foreground.copy(alpha = 0.55f),
        inactiveTrackColor = foreground.copy(alpha = 0.14f),
        activeTickColor = Color.Transparent,
        inactiveTickColor = Color.Transparent,
    )

    @Composable
    private fun SettingLabel(text: String, muted: Color) {
        Text(text, fontSize = 11.sp, letterSpacing = 1.2.sp, color = muted, modifier = Modifier.padding(start = 2.dp, top = 1.dp))
    }

    @Composable
    private fun SettingCard(cardBg: Color, content: @Composable () -> Unit) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardBg)
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) { content() }
    }

    @Composable
    private fun SegmentPill(
        label: String,
        selected: Boolean,
        foreground: Color,
        muted: Color,
        modifier: Modifier = Modifier,
        onClick: () -> Unit,
    ) {
        Box(
            modifier.height(34.dp).clip(RoundedCornerShape(9.dp))
                .background(if (selected) foreground.copy(alpha = 0.10f) else Color.Transparent)
                .clickable { onClick() },
            contentAlignment = Alignment.Center,
        ) {
            Text(label, fontSize = 13.sp, color = if (selected) foreground else muted)
        }
    }

    @Composable
    private fun SettingRow(
        title: String,
        subtitle: String,
        foreground: Color,
        muted: Color,
        onClick: (() -> Unit)?,
    ) {
        Row(
            Modifier.fillMaxWidth().clickable(enabled = onClick != null) { onClick?.invoke() }
                .padding(vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(title, fontSize = 14.sp, color = foreground)
                Text(subtitle, Modifier.padding(top = 1.dp), fontSize = 11.sp, color = muted)
            }
            if (onClick != null) Text("›", fontSize = 18.sp, color = muted)
        }
    }

    @Composable
    private fun SettingDivider(foreground: Color) {
        Box(
            Modifier.fillMaxWidth().height(1.dp)
                .background(foreground.copy(alpha = 0.08f)),
        )
    }
}













