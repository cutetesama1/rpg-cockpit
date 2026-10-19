package com.rpgframework.cockpit

import android.content.Context
import android.content.res.AssetManager
import android.util.Log
import java.io.File

/**
 * 把打包进 APK 的 `assets/backend` 解压到 app 私有目录。
 *
 * assets 里有一份 `version.txt`（构建时写入时间戳），解压完成后把同样的内容
 * 写进目标目录的 `.version`；下次启动版本一致就跳过解压，升级 APK 后自动覆盖。
 */
object AssetInstaller {

    private const val TAG = "RpgCockpit"

    /** @return 本次是否真的执行了解压 */
    fun install(context: Context, assetRoot: String = "backend", targetRoot: File): Boolean {
        val assets = context.assets
        val version = readAssetText(assets, "$assetRoot/version.txt") ?: "unknown"
        val marker = File(targetRoot, ".version")
        if (marker.isFile && marker.readText().trim() == version) {
            return false
        }
        if (targetRoot.exists()) {
            targetRoot.deleteRecursively()
        }
        targetRoot.mkdirs()
        val started = System.currentTimeMillis()
        copyDir(assets, assetRoot, targetRoot)
        marker.writeText(version)
        Log.i(TAG, "assets extracted: $assetRoot -> ${targetRoot.absolutePath} in ${System.currentTimeMillis() - started}ms")
        return true
    }

    private fun readAssetText(assets: AssetManager, path: String): String? = try {
        assets.open(path).bufferedReader().use { it.readText().trim() }
    } catch (_: Exception) {
        null
    }

    /**
     * 递归复制：`assets.list(path)` 对目录返回子项、对文件返回空数组（或 null）。
     * 这里靠“子项为空”判断文件；空文件同样会被当作文件打开复制。
     */
    private fun copyDir(assets: AssetManager, assetPath: String, dest: File) {
        val children = assets.list(assetPath) ?: emptyArray()
        if (children.isEmpty()) {
            dest.parentFile?.mkdirs()
            assets.open(assetPath).use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
            return
        }
        dest.mkdirs()
        for (child in children) {
            copyDir(assets, "$assetPath/$child", File(dest, child))
        }
    }
}
