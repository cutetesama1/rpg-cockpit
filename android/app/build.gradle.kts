import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// P6：release 签名。keystore.properties 与 .jks 都进 .gitignore（不入库）；
// 文件缺失时回落到 debug 签名，保证 clone 下来的人不配密钥也能 assembleRelease。
// Optional external signing file keeps private keys outside the source checkout.
val keystorePropsFile = providers.gradleProperty("rpgSigningProperties").orNull
    ?.let { File(it) } ?: rootProject.file("keystore/keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}

android {
    namespace = "com.rpgframework.cockpit"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.rpgframework.cockpit"
        minSdk = 29
        targetSdk = 36
        versionCode = 40
        versionName = "0.994"
        ndk {
            // 两个 ABI 都要有对应的 pydantic-core wheel（local-wheels/ 里各一份）。
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        if (keystorePropsFile.exists()) {
            create("release") {
                val configuredStore = File(keystoreProps.getProperty("storeFile"))
                storeFile = if (configuredStore.isAbsolute) configuredStore
                    else File(keystorePropsFile.parentFile.parentFile, configuredStore.path)
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // P6：一个通用包 + 每个 ABI 一个瘦包（Chaquopy 会把对应 ABI 的 Python 运行时一起拆走）。
            if (keystorePropsFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                signingConfig = signingConfigs.getByName("debug")
            }
        }
    }

    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "x86_64")
            isUniversalApk = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        buildPython("C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe")
        pip {
            // pydantic-core 没有现成的 Android wheel（Chaquopy 官方仓库也没有），
            // 用本地用 NDK 交叉编译 + 手工组装的 wheel，见 android/local-wheels/README.md。
            install("pydantic==2.14.1")
            install("pydantic-core==2.50.1")
            // 后端框架：fastapi/uvicorn 及依赖都是纯 Python 包（uvicorn 不装 [standard]，
            // 避免 uvloop/httptools 这些原生扩展）。
            install("fastapi")
            install("uvicorn")
            options("--find-links=${rootProject.projectDir}/local-wheels")
        }
    }
}

// P3：把桌面端后端 / Web UI / 样例内容包打进 APK assets；
// 首次启动由 AssetInstaller 解压到 filesDir/runtime/backend，再交给 Chaquopy 启动。
val repoRoot: File = rootProject.projectDir.parentFile
val backendAssets = layout.projectDirectory.dir("src/main/assets/backend")

val syncBackend = tasks.register<Sync>("syncBackend") {
    into(backendAssets)
    from(File(repoRoot, "LICENSE"))
    from(File(repoRoot, "THIRD_PARTY_NOTICES.md"))
    from(File(repoRoot, "api")) { into("api") }
    from(File(repoRoot, "core")) { into("core") }
    from(File(repoRoot, "gateway")) { into("gateway") }
    from(File(repoRoot, "content")) { into("content") }
    from(File(repoRoot, "packs/night-convenience-store")) { into("packs/night-convenience-store") }
    // P9：样例包 new-game（异世界）带分层立绘素材，一并内置，装好就能看到立绘。
    from(File(repoRoot, "packs/new-game")) { into("packs/new-game") }
    from(File(repoRoot, "ui/dist")) { into("ui/dist") }
    from(File(repoRoot, "skill-libraries")) { into("skill-libraries") }
    exclude("**/__pycache__/**", "**/*.pyc", "**/.DS_Store")
    doLast {
        // 版本戳：assets 内容变了（重新同步）就解压覆盖旧目录。
        val version = System.currentTimeMillis().toString()
        File(backendAssets.asFile, "version.txt").writeText(version)
        logger.lifecycle("syncBackend done, version=$version")
    }
}

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    dependsOn(syncBackend)
}

// lint 的 vital 报告模型也会读 assets，不声明依赖 Gradle 8.13 会直接报错（隐式依赖）。
tasks.matching { it.name.contains("Lint") || it.name.startsWith("lint") }.configureEach {
    dependsOn(syncBackend)
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.core:core-ktx:1.16.0")
}

// Reject desktop native libraries and missing ABI extensions before creating an APK.
val verifyReleasePythonNative = tasks.register<Exec>("verifyReleasePythonNative") {
    dependsOn("installReleasePythonRequirements")
    commandLine("C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe",
        rootProject.file("scripts/verify_android_native.py").absolutePath,
        "--pip", layout.buildDirectory.dir("python/pip/release").get().asFile.absolutePath)
}
tasks.matching { it.name == "generateReleasePythonRequirementsAssets" }.configureEach {
    dependsOn(verifyReleasePythonNative)
}
