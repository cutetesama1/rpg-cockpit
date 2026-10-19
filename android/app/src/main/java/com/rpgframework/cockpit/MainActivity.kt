package com.rpgframework.cockpit

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * 单 Activity 壳：
 * 1. 后台线程启动 Chaquopy Python，调用 main.start_server(filesDir) 拿到本地端口；
 * 2. 轮询 /api/health 就绪后，用 WebView 加载 http://127.0.0.1:<port>/。
 * 3. WebView 的 <input type="file">（导入内容包 zip）由 onShowFileChooser 接系统文件选择器。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var statusView: TextView
    private val handler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()

    @Volatile
    private var port: Int = -1

    /** WebView 文件选择器的回调；同一时刻只允许一个。 */
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null

    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = fileChooserCallback
            fileChooserCallback = null
            if (callback == null) return@registerForActivityResult
            val uri = result.data?.data
            if (result.resultCode == RESULT_OK && uri != null) {
                callback.onReceiveValue(arrayOf(uri))
            } else {
                callback.onReceiveValue(null)
            }
        }

    private var pendingTemplateUrl: String? = null
    private val saveTemplateLauncher =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
            val sourceUrl = pendingTemplateUrl
            pendingTemplateUrl = null
            if (uri == null || sourceUrl == null) return@registerForActivityResult
            executor.execute {
                try {
                    val connection = URL(sourceUrl).openConnection() as HttpURLConnection
                    connection.connectTimeout = 10_000
                    connection.readTimeout = 10_000
                    connection.instanceFollowRedirects = false
                    try {
                        check(connection.responseCode == 200) { "模板下载失败" }
                        connection.inputStream.use { input ->
                            contentResolver.openOutputStream(uri, "w")?.use { output ->
                                input.copyTo(output)
                            } ?: error("无法写入所选位置")
                        }
                    } finally {
                        connection.disconnect()
                    }
                    handler.post { Toast.makeText(this, "技能库模板已保存", Toast.LENGTH_SHORT).show() }
                } catch (t: Throwable) {
                    Log.e(TAG, "template save failed", t)
                    handler.post { Toast.makeText(this, "模板保存失败：${t.message}", Toast.LENGTH_LONG).show() }
                }
            }
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mediaPlaybackRequiresUserGesture = false
            setBackgroundColor(Color.parseColor("#11151b"))
            webViewClient = WebViewClient()
            setDownloadListener { url, _, _, _, _ ->
                val uri = Uri.parse(url)
                if (pendingTemplateUrl == null && uri.scheme == "http" && uri.host == "127.0.0.1" &&
                    uri.port == port && uri.path == "/api/skill-libraries/template.zip") {
                    pendingTemplateUrl = url
                    try {
                        saveTemplateLauncher.launch("skill-library-author-template.zip")
                    } catch (t: Throwable) {
                        pendingTemplateUrl = null
                        Log.e(TAG, "template file picker failed", t)
                    }
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                    Log.i("RpgWeb", "${message.message()} @${message.sourceId()}:${message.lineNumber()}")
                    return true
                }

                override fun onShowFileChooser(
                    view: WebView?,
                    filePathCallback: ValueCallback<Array<Uri>>?,
                    fileChooserParams: FileChooserParams?,
                ): Boolean {
                    fileChooserCallback?.onReceiveValue(null)
                    fileChooserCallback = filePathCallback
                    val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                        putExtra(
                            Intent.EXTRA_MIME_TYPES,
                            arrayOf(
                                "application/zip",
                                "application/x-zip-compressed",
                                "application/octet-stream",
                            ),
                        )
                    }
                    return try {
                        fileChooserLauncher.launch(intent)
                        true
                    } catch (t: Throwable) {
                        Log.e(TAG, "file chooser failed", t)
                        fileChooserCallback = null
                        false
                    }
                }
            }
        }

        statusView = TextView(this).apply {
            text = getString(R.string.starting_engine)
            setTextColor(Color.parseColor("#9fb3ad"))
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(64, 64, 64, 64)
        }

        root.addView(webView, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(statusView, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)

        startBackend()
    }

    private fun startBackend() {
        executor.execute {
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(this))
                }
                AssetInstaller.install(
                    this@MainActivity,
                    assetRoot = "backend",
                    targetRoot = File(filesDir, "runtime/backend"),
                )
                val module = Python.getInstance().getModule("main")
                Log.i(TAG, "python probe: " + module.callAttr("probe", filesDir.absolutePath))
                port = module.callAttr("start_server", filesDir.absolutePath).toInt()
                Log.i(TAG, "python backend listening on 127.0.0.1:$port")

                val ready = waitForHealth(port, timeoutMs = 30_000)
                handler.post {
                    if (ready) {
                        statusView.visibility = View.GONE
                        webView.loadUrl("http://127.0.0.1:$port/")
                    } else {
                        statusView.text = getString(R.string.engine_timeout)
                    }
                }
            } catch (t: Throwable) {
                Log.e(TAG, "failed to start local engine", t)
                handler.post {
                    statusView.text = getString(R.string.engine_failed, t.message ?: t.javaClass.simpleName)
                }
            }
        }
    }

    private fun waitForHealth(port: Int, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (probeHealth(port)) return true
            Thread.sleep(250)
        }
        return false
    }

    private fun probeHealth(port: Int): Boolean = try {
        val connection = URL("http://127.0.0.1:$port/api/health").openConnection() as HttpURLConnection
        connection.connectTimeout = 1_000
        connection.readTimeout = 1_000
        connection.requestMethod = "GET"
        val code = connection.responseCode
        connection.disconnect()
        code == 200
    } catch (_: Exception) {
        false
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "RpgCockpit"
    }
}
