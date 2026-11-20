package io.github.gscratchpad

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * §11 UI 层冒烟：主页关键入口可见、双态切换与新建入口可用。
 *
 * 说明（P4 门禁修订）：原三条断言引用的「新建 / 查找 / 预览」文案已随版本演进失效——
 * 主页按钮现为「新建文档 / 打开文件」，查找栏已迁入 WebView 页内（Compose 层不可见），
 * 「预览」在编辑器子窗口内。本测试改为基于当前主页真实 UI 的稳定断言，避免纸面测试误报。
 * 落盘链路另见 [PersistenceSmokeTest]。
 *
 * 运行：gradlew :app:connectedDebugAndroidTest
 */
@RunWith(AndroidJUnit4::class)
class EditorUiSmokeTest {

    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    @Test
    fun main_toolbar_is_visible_on_launch() {
        rule.onNodeWithText("打开文件").assertIsDisplayed()
        rule.onNodeWithText("新建文档").assertIsDisplayed()
        rule.onNodeWithText("最近").assertIsDisplayed()
        rule.onNodeWithText("全部").assertIsDisplayed()
        rule.onNodeWithText("文件夹").assertIsDisplayed() // T3 三态入口
    }

    @Test
    fun folders_entry_switches_view() {
        // T3：点「文件夹」进入分组视图，可见新建入口与「未归档」虚拟组
        rule.onNodeWithText("文件夹").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("未归档").assertIsDisplayed()
        rule.onNodeWithText("＋ 新建文件夹").assertIsDisplayed()
        // 切回「最近」文件夹视图消失
        rule.onNodeWithText("最近").performClick()
        rule.waitForIdle()
        assert(rule.onAllNodesWithText("＋ 新建文件夹").fetchSemanticsNodes().isEmpty()) {
            "「最近」视图下不应有文件夹新建入口"
        }
    }

    @Test
    fun recent_all_toggle_switches_view() {
        // 初始「最近」视图有 clear 入口
        rule.onNodeWithText("clear").assertIsDisplayed()
        // 切到「全部」后 clear 隐藏
        rule.onNodeWithText("全部").performClick()
        rule.waitForIdle()
        assert(rule.onAllNodesWithText("clear").fetchSemanticsNodes().isEmpty()) {
            "「全部」视图下不应有 clear 入口"
        }
        // 切回「最近」clear 重现
        rule.onNodeWithText("最近").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("clear").assertIsDisplayed()
    }

    @Test
    fun new_document_entry_is_clickable() {
        // 新建入口可点击（点击后进入 WebView 编辑器子窗口，本测试只验证主页入口响应）
        rule.onNodeWithText("新建文档").performClick()
        rule.waitForIdle()
        // 进入编辑器后主页入口节点应已让位给 panel；仅断言点击过程无崩溃
    }
}
