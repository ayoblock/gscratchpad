import java.util.Properties

plugins {
    id("com.android.application") version "9.5.1"
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10"
    id("jacoco")
}

jacoco {
    toolVersion = "0.8.12"
}

tasks.withType<Test>().configureEach {
    extensions.configure<JacocoTaskExtension> {
        isIncludeNoLocationClasses = true
        excludes = listOf("jdk.internal.*")
    }
}

/** 发版版本号唯一来源：defaultConfig 与 release 产物命名共用，避免两处漂移。 */
val appVersionName = "0.9.8"
val appVersionCode = 55

/** CI / 发版机注入 upload key：android/keystore.properties（不入库）。 */
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "io.github.gscratchpad"
    compileSdk = 36

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    defaultConfig {
        applicationId = "io.github.gscratchpad"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables { useSupportLibrary = true }
    }

    /** §12：arm64-v8a 必选，armeabi-v7a 按覆盖决定，模拟器 x86_64；不产 universal。 */
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "x86_64")
            isUniversalApk = false
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // 有 keystore.properties 用 upload key；本地度量体积时退回 debug 签名
            signingConfig = if (keystoreProps.isNotEmpty()) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf("META-INF/LICENSE*", "META-INF/NOTICE*")
        // vendor/js 为已压缩产物，二次压缩无收益
        jniLibs.useLegacyPackaging = false
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

/**
 * 发版规范：release APK 命名为 scratchpad-<abi>-release-<versionName>.apk。
 * 用新版 Variant API（AGP 9.x 已移除 applicationVariants）按 ABI 输出逐个重命名；
 * selector 限定仅 release，debug 产物名保持默认、不受影响。
 */
androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.outputs.forEach { output ->
            val abi = output.filters
                .firstOrNull { it.filterType == com.android.build.api.variant.FilterConfiguration.FilterType.ABI }
                ?.identifier
            if (!abi.isNullOrEmpty()) {
                output.outputFileName.set("scratchpad-$abi-release-$appVersionName.apk")
            }
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("org.xerial:sqlite-jdbc:3.46.1.0")

    androidTestImplementation(platform("androidx.compose:compose-bom:2025.10.01"))
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

/**
 * §11 单元覆盖：只用 JVM 单测的 exec + debug 类目录，输出 HTML/XML。
 * 运行：gradle :app:jacocoDebugUnitTest
 */
tasks.register<JacocoReport>("jacocoDebugUnitTest") {
    dependsOn("testDebugUnitTest")
    reports {
        xml.required = true
        html.required = true
    }
    val debugTree = fileTree(
        layout.buildDirectory.dir("intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes"),
    ) {
        exclude("**/R.class", "**/R\$*.class", "**/BuildConfig.*", "**/Manifest*.*")
    }
    classDirectories.setFrom(debugTree)
    sourceDirectories.setFrom(files("src/main/java"))
    executionData.setFrom(fileTree(layout.buildDirectory) { include("jacoco/testDebugUnitTest.exec") })
}

/**
 * §11 覆盖门禁：domain 层行覆盖 ≥ 80%。低于门槛直接失败，CI 用同一任务。
 * 依赖 jacocoDebugUnitTest 生成的 XML。
 */
tasks.register("coverageGate") {
    dependsOn("jacocoDebugUnitTest")
    val report = layout.buildDirectory.file("reports/jacoco/jacocoDebugUnitTest/jacocoDebugUnitTest.xml")
    inputs.file(report)
    doLast {
        val factory = javax.xml.parsers.DocumentBuilderFactory.newInstance().apply {
            setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)
        }
        val xml = factory.newDocumentBuilder().parse(report.get().asFile)
        val packages = xml.getElementsByTagName("package")
        var covered = 0
        var missed = 0
        for (i in 0 until packages.length) {
            val pkg = packages.item(i) as org.w3c.dom.Element
            val name = pkg.getAttribute("name")
            if (!name.startsWith("io/github/gscratchpad/domain")) continue
            val children = pkg.childNodes
            for (j in 0 until children.length) {
                val c = children.item(j) as? org.w3c.dom.Element ?: continue
                if (c.tagName != "counter" || c.getAttribute("type") != "LINE") continue
                covered += c.getAttribute("covered").toInt()
                missed += c.getAttribute("missed").toInt()
            }
        }
        val total = covered + missed
        val pct = if (total == 0) 0.0 else covered * 100.0 / total
        logger.lifecycle(
            "domain 行覆盖 $covered/$total = " + "%.1f".format(pct) + "%（门槛 80%）",
        )
        if (pct < 80.0) throw GradleException("domain 层覆盖 $pct% 低于 80% 门槛")
    }
}

/**
 * §12 包体预算：每个 release APK ≤ 12MB。低于预算才允许发版。
 */
tasks.register("verifyReleaseBudget") {
    dependsOn("assembleRelease")
    doLast {
        val dir = layout.buildDirectory.dir("outputs/apk/release").get().asFile
        val apks = dir.walkTopDown().filter { it.isFile && it.extension == "apk" }.toList()
        if (apks.isEmpty()) throw GradleException("未找到 release APK")
        val budget = 12L * 1024 * 1024
        apks.forEach { apk ->
            logger.lifecycle("包体 ${apk.name} = ${apk.length() / (1024.0 * 1024.0)} MB")
            if (apk.length() > budget) throw GradleException("${apk.name} 超过 12MB 预算")
        }
    }
}

/**
 * 发版交付目录：把 release APK 汇入 android/dist/，并清理旧版 APK（只保留本次版本）。
 * 运行：gradlew :app:stageRelease
 */
tasks.register("stageRelease") {
    dependsOn("assembleRelease", "verifyReleaseBudget")
    doLast {
        val src = layout.buildDirectory.dir("outputs/apk/release").get().asFile
        val dist = rootProject.layout.projectDirectory.dir("dist").asFile
        dist.mkdirs()
        // 清理交付目录里的旧版 APK，只保留本次 assembleRelease 产出的版本
        dist.listFiles { f -> f.isFile && f.extension == "apk" }?.forEach { it.delete() }
        val apks = src.listFiles { f -> f.isFile && f.extension == "apk" }.orEmpty()
        apks.forEach { apk ->
            val target = File(dist, apk.name)
            apk.copyTo(target, overwrite = true)
            logger.lifecycle("已交付 ${target.absolutePath}")
        }
        if (apks.isEmpty()) throw GradleException("未找到可交付的 release APK")
    }
}












