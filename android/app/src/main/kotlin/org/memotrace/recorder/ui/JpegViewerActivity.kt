package org.memotrace.recorder.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.ImageDecoder
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.memotrace.recorder.R
import org.memotrace.recorder.RecorderApplication
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class JpegViewerActivity : Activity() {
    private val app get() = application as RecorderApplication
    private val decodeExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private lateinit var image: ImageView
    private lateinit var status: TextView
    private lateinit var loading: ProgressBar
    private var destroyed = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                setPadding(dp(16), dp(12), dp(16), dp(16))
                setBackgroundColor(Color.BLACK)
            }
        status =
            TextView(this).apply {
                id = R.id.viewer_status
                textSize = 18f
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER
                setText(R.string.viewer_loading)
                accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
                content.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
        loading =
            ProgressBar(this).apply {
                isIndeterminate = true
                content.addView(this, LinearLayout.LayoutParams(-2, -2))
            }
        image =
            ImageView(this).apply {
                id = R.id.viewer_image
                scaleType = ImageView.ScaleType.FIT_CENTER
                adjustViewBounds = true
                contentDescription = getString(R.string.viewer_image_description)
                content.addView(this, LinearLayout.LayoutParams(-1, 0, 1f))
            }
        content.addView(
            TremorButton(this).apply {
                id = R.id.viewer_close
                setText(R.string.close)
                textSize = 24f
                isAllCaps = false
                minHeight = dp(88)
                setOnClickListener { finish() }
            },
            LinearLayout.LayoutParams(-1, -2),
        )
        ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
            val safe = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(dp(16) + safe.left, dp(12) + safe.top, dp(16) + safe.right, dp(16) + safe.bottom)
            insets
        }
        setContentView(content)

        val uri = validateIntent()
        if (uri == null) {
            showError()
            return
        }
        app.validateViewer(uri.toString()) { frame ->
            if (destroyed) return@validateViewer
            if (frame == null) {
                showError()
                return@validateViewer
            }
            decodeExecutor.execute {
                val decoded =
                    try {
                        check(contentResolver.getType(uri) == "image/jpeg") { "not_jpeg" }
                        ImageDecoder.decodeDrawable(ImageDecoder.createSource(contentResolver, uri)) { decoder, info, _ ->
                            val largest = maxOf(info.size.width, info.size.height)
                            val target = maxOf(resources.displayMetrics.widthPixels, resources.displayMetrics.heightPixels) * 2
                            var sample = 1
                            while (largest / sample > target && sample < 16) sample *= 2
                            decoder.setTargetSampleSize(sample)
                            decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE)
                        }
                    } catch (_: Exception) {
                        null
                    }
                runOnUiThread {
                    if (!destroyed) showResult(decoded, frame.bytes, frame.width, frame.height)
                }
            }
        }
    }

    private fun validateIntent(): Uri? {
        if (intent.action != Intent.ACTION_VIEW || intent.type != "image/jpeg") return null
        if (intent.flags and URI_PERMISSION_FLAGS != 0 || intent.clipData != null) return null
        return intent.data?.takeIf(::isMediaImageUri)
    }

    private fun showResult(
        drawable: Drawable?,
        bytes: Long?,
        width: Int?,
        height: Int?,
    ) {
        loading.visibility = View.GONE
        if (drawable == null) {
            showError()
        } else {
            image.setImageDrawable(drawable)
            status.text =
                getString(
                    R.string.viewer_details,
                    width?.let { "$it x $height" } ?: getString(R.string.size_unknown),
                    bytes?.toString() ?: getString(R.string.size_unknown),
                )
        }
    }

    private fun showError() {
        loading.visibility = View.GONE
        image.setImageDrawable(null)
        status.setText(R.string.viewer_error)
    }

    override fun onDestroy() {
        destroyed = true
        decodeExecutor.shutdownNow()
        image.setImageDrawable(null)
        super.onDestroy()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val URI_PERMISSION_FLAGS =
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION

        fun isMediaImageUri(uri: Uri): Boolean {
            val segments = uri.pathSegments
            return uri.scheme == "content" && uri.authority == "media" && uri.userInfo == null && uri.query == null &&
                uri.fragment == null && segments.size == 4 && segments[1] == "images" && segments[2] == "media" &&
                segments[3].toLongOrNull() != null
        }
    }
}
