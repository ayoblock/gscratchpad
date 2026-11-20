package io.github.gscratchpad

import io.github.gscratchpad.platform.MarkdownFeatures
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** S3：只有含公式/图表的文档才注入 KaTeX / Mermaid。 */
class MarkdownFeaturesTest {

    @Test
    fun `math detected for inline and block`() {
        assertTrue(MarkdownFeatures.hasMath("公式 \$E=mc^2\$"))
        assertTrue(MarkdownFeatures.hasMath("\$\$\nx=1\n\$\$"))
    }

    @Test
    fun `plain text has no math`() {
        assertFalse(MarkdownFeatures.hasMath("价格 10 元，折扣 20%"))
    }

    @Test
    fun `mermaid fence detected`() {
        assertTrue(MarkdownFeatures.hasMermaid("```mermaid\ngraph TD\n A-->B\n```"))
        assertFalse(MarkdownFeatures.hasMermaid("```kotlin\nval a=1\n```"))
    }
}
