package org.memotrace.recorder.capture

import android.os.Looper
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

enum class CaptureResult { SAVED, CAMERA_FAILURE, STORAGE_FAILURE }

/** Main-thread submissions/terminal callbacks; one owned serial CameraX processing lane. */
class CaptureDiskQueue(
    private val main: Executor,
    private val disk: ExecutorService = Executors.newSingleThreadExecutor(),
) {
    val executor: Executor get() = disk
    private var pending = false
    private var closed = false

    fun submit(
        submit: (ImageCapture.OnImageSavedCallback) -> Unit,
        onComplete: (CaptureResult) -> Unit,
    ) {
        check(Looper.myLooper() == Looper.getMainLooper())
        check(!closed && !pending)
        pending = true
        var terminal = false

        fun complete(result: CaptureResult) {
            check(Looper.myLooper() == Looper.getMainLooper())
            if (terminal) return
            terminal = true
            // 1.5.3 submits ProcessingNode work and aborts on main. Aborted inputs cannot
            // enqueue more work. This FIFO barrier also waits for its low-memory worker.
            disk.execute {
                main.execute {
                    pending = false
                    if (closed) disk.shutdown()
                    onComplete(result)
                }
            }
        }
        try {
            submit(
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) = complete(CaptureResult.SAVED)

                    override fun onError(exception: ImageCaptureException) =
                        complete(
                            if (exception.imageCaptureError ==
                                ImageCapture.ERROR_FILE_IO
                            ) {
                                CaptureResult.STORAGE_FAILURE
                            } else {
                                CaptureResult.CAMERA_FAILURE
                            },
                        )
                },
            )
        } catch (_: RuntimeException) {
            complete(CaptureResult.CAMERA_FAILURE)
        }
    }

    /** After unbind on main. Never interrupt a writer or shut down before its abort barrier. */
    fun close() {
        check(Looper.myLooper() == Looper.getMainLooper())
        closed = true
        if (!pending) disk.shutdown()
    }
}
