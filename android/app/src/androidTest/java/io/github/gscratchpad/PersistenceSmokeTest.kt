package io.github.gscratchpad

import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.gscratchpad.domain.model.Format
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * §5.6 / P4 发布门禁：connectedSmoke（启动 + 打开 + 落盘）。
 *
 * 与 [EditorUiSmokeTest] 的纯 UI 冒烟互补：本测试走真实 Application 容器，
 * 验证「Activity 能启动 → 文档能打开打点 → 内容保存后 DB 与镜像文件均落盘」。
 * 不依赖 WebView 面板焦点，避免真机上面板抢占焦点导致 uiautomator 抓不到节点的问题。
 *
 * 运行：gradlew :app:connectedDebugAndroidTest
 */
@RunWith(AndroidJUnit4::class)
class PersistenceSmokeTest {

    @Test
    fun launch_open_and_persist_document() {
        val app = ApplicationProvider.getApplicationContext<GscratchpadApp>()
        val container = app.container

        // 启动：真实拉起 MainActivity（Compose 主界面）
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        var docId: String? = null
        try {
            runBlocking { container.bootstrap() }

            // 打开：创建文档并打打开时间点
            val doc = runBlocking {
                container.repository.create(
                    format = Format.MD,
                    title = "connectedSmoke-${System.currentTimeMillis()}",
                )
            }
            docId = doc.id
            runBlocking { container.repository.touchOpened(doc.id) }
            assertNotNull(
                "打开后应能从仓库读回文档",
                runBlocking { container.repository.get(doc.id) },
            )

            // 落盘：写入内容并强制 flush
            val content = "# 冒烟\n\nconnectedSmoke 落盘验证\n"
            val ticket = runBlocking {
                container.repository.saveNow(doc.id, content, doc.revision + 1)
            }
            assertTrue("saveNow 应被接受", ticket.accepted)
            assertTrue("flush 应成功", runBlocking { container.repository.flush() })

            // 校验：DB 与镜像文件一致
            val reloaded = runBlocking { container.repository.get(doc.id) }
            assertNotNull("落盘后文档应仍在 DB", reloaded)
            assertEquals("DB 内容应与写入一致", content, reloaded!!.content)
            val mirror = container.paths.noteFile(doc.id, doc.format)
            assertTrue("镜像文件应存在：${mirror.absolutePath}", mirror.exists())
            assertEquals("镜像内容应与写入一致", content, mirror.readText())
        } finally {
            scenario.close()
            // 清理测试数据：删除文档同时移除镜像与 meta 指针
            docId?.let { id -> runBlocking { container.repository.delete(id) } }
        }
    }
}
