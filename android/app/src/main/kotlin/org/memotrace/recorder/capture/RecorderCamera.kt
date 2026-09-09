package org.memotrace.recorder.capture

import android.content.Context
import android.os.SystemClock
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.CameraState
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import org.memotrace.capture.CaptureConfig
import org.memotrace.capture.LumaAnalyzer
import org.memotrace.capture.LumaMetrics
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Commands and callbacks on main, except the single overwrite-only analysis slot. */
interface RecorderCamera {
    fun start(
        onReady: () -> Unit,
        onError: () -> Unit,
    )

    fun takeAnalysis(): Pair<Long, LumaMetrics>?

    fun capture(
        output: File,
        onComplete: (CaptureResult) -> Unit,
    )

    fun close()
}

class CameraXRecorderCamera(
    private val context: Context,
    private val owner: LifecycleOwner,
    private val config: CaptureConfig,
) : RecorderCamera {
    private val executor = Executors.newSingleThreadExecutor()
    private val main = ContextCompat.getMainExecutor(context)
    private val disk = CaptureDiskQueue(main)
    private val latest = AtomicReference<Pair<Long, LumaMetrics>?>(null)
    private val analysisFailed = AtomicBoolean(false)
    private var provider: ProcessCameraProvider? = null
    private var capture: ImageCapture? = null
    private var analysis: ImageAnalysis? = null
    private var closed = false
    private var opened = false

    override fun start(
        onReady: () -> Unit,
        onError: () -> Unit,
    ) {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (closed) return@addListener
            try {
                val cameras = future.get()
                provider = cameras
                val jpeg =
                    ImageCapture
                        .Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .setOutputFormat(ImageCapture.OUTPUT_FORMAT_JPEG)
                        .setJpegQuality(95)
                        .setIoExecutor(disk.executor)
                        .build()
                val lowResolution =
                    ImageAnalysis
                        .Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .setResolutionSelector(
                            ResolutionSelector
                                .Builder()
                                .setResolutionStrategy(
                                    ResolutionStrategy(Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER),
                                ).build(),
                        ).build()
                val analyzer = LumaAnalyzer(config)
                lowResolution.setAnalyzer(executor) { image ->
                    try {
                        val now = SystemClock.elapsedRealtime()
                        if (analyzer.due(now)) {
                            val plane = image.planes[0]
                            val buffer = plane.buffer
                            val crop = image.cropRect
                            val samples =
                                IntArray(32 * 24) { index ->
                                    val x = crop.left + (index % 32) * crop.width() / 32
                                    val y = crop.top + (index / 32) * crop.height() / 24
                                    buffer.get(y * plane.rowStride + x * plane.pixelStride).toInt() and 255
                                }
                            latest.set(now to analyzer.analyze(samples))
                        }
                    } catch (_: Exception) {
                        if (analysisFailed.compareAndSet(false, true)) main.execute { if (!closed) onError() }
                    } finally {
                        image.close()
                    }
                }
                capture = jpeg
                analysis = lowResolution
                val camera = cameras.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, jpeg, lowResolution)
                camera.cameraInfo.cameraState.observe(owner) { state ->
                    if (closed) return@observe
                    if (state.type == CameraState.Type.OPEN && !opened) {
                        opened = true
                        onReady()
                    }
                    if (state.error != null || (opened && state.type == CameraState.Type.CLOSED)) onError()
                }
            } catch (_: Exception) {
                onError()
            }
        }, main)
    }

    override fun takeAnalysis(): Pair<Long, LumaMetrics>? = latest.getAndSet(null)

    override fun capture(
        output: File,
        onComplete: (CaptureResult) -> Unit,
    ) {
        check(!closed)
        disk.submit({ callback ->
            checkNotNull(capture).takePicture(ImageCapture.OutputFileOptions.Builder(output).build(), main, callback)
        }, onComplete)
    }

    override fun close() {
        if (closed) return
        closed = true
        try {
            analysis?.clearAnalyzer()
            provider?.unbind(*listOfNotNull(capture, analysis).toTypedArray())
        } finally {
            capture = null
            analysis = null
            latest.set(null)
            executor.shutdown()
            disk.close()
        }
    }
}
