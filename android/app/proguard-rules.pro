# Gscratchpad Android R8 规则（方案 §12）
# 1) WebView JS 接口：PreviewHost 内匿名对象通过 @JavascriptInterface 暴露给页面，
#    R8 会重命名匿名类方法导致页面回调失效，必须保留。
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class io.github.gscratchpad.platform.PreviewHost$attach$2$1 { *; }

# 2) WebView 相关反射
-keep class android.webkit.** { *; }

# 3) 不保留调试信息到可读符号，但保留行号用于本地崩溃日志定位
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# 4) 资源 id 供 WebViewAssetLoader 按路径拼装，无需 keep；assets 不参与 shrink
