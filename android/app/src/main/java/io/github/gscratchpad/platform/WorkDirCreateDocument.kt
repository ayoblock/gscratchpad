package io.github.gscratchpad.platform

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.activity.result.contract.ActivityResultContract

/**
 * 另存文件选择器（R33）：在 AndroidX [androidx.activity.result.contract.ActivityResultContracts.CreateDocument]
 * 基础上增加 `EXTRA_INITIAL_URI`，用于把选择器初始定位到绑定的「工作目录」。
 *
 * 无工作目录时 [Request.initialUri] 传 null，行为与原 CreateDocument 完全一致。
 * EXTRA_INITIAL_URI 只是"建议性"起点，部分 ROM/DocumentsProvider 会忽略，属可接受降级。
 */
class WorkDirCreateDocument : ActivityResultContract<WorkDirCreateDocument.Request, Uri?>() {

    data class Request(val fileName: String, val initialUri: Uri? = null)

    override fun createIntent(context: Context, input: Request): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = SaveAsPolicy.MIME
            putExtra(Intent.EXTRA_TITLE, input.fileName)
            input.initialUri?.let { putExtra(DocumentsContract.EXTRA_INITIAL_URI, it) }
        }

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == RESULT_OK) intent?.data else null
}
