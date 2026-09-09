package org.memotrace.recorder

import android.app.Application
import android.os.Looper
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.core.content.ContextCompat
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.recorder.capture.CaptureDiskQueue
import org.memotrace.recorder.capture.CaptureResult
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class CaptureDiskQueueTest {
    @Test fun fileIoIsTypedAndTerminalResultsAreOneShot() {
        for (code in listOf(ImageCapture.ERROR_FILE_IO, ImageCapture.ERROR_CAMERA_CLOSED, ImageCapture.ERROR_CAPTURE_FAILED)) {
            val disk = Executors.newSingleThreadExecutor()
            val queue = CaptureDiskQueue(ContextCompat.getMainExecutor(RuntimeEnvironment.getApplication()), disk)
            val results = mutableListOf<CaptureResult>()
            lateinit var callback: ImageCapture.OnImageSavedCallback
            queue.submit({ callback = it }, { results.add(it) })
            callback.onError(ImageCaptureException(code, "synthetic failure", null))
            callback.onImageSaved(ImageCapture.OutputFileResults(null))
            queue.close()
            disk.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            assertEquals(
                listOf(
                    if (code ==
                        ImageCapture.ERROR_FILE_IO
                    ) {
                        CaptureResult.STORAGE_FAILURE
                    } else {
                        CaptureResult.CAMERA_FAILURE
                    },
                ),
                results,
            )
            assertTrue(disk.awaitTermination(5, TimeUnit.SECONDS))
            assertThrows(IllegalStateException::class.java) { queue.submit({}, {}) }
        }
    }

    @Test fun synchronousSubmissionFailureAlsoWaitsForQueuedWriter() {
        val disk = Executors.newSingleThreadExecutor()
        val queue = CaptureDiskQueue(ContextCompat.getMainExecutor(RuntimeEnvironment.getApplication()), disk)
        val release = CountDownLatch(1)
        var result: CaptureResult? = null
        try {
            queue.submit({
                disk.execute { check(release.await(5, TimeUnit.SECONDS)) }
                error("synthetic submission failure")
            }, { result = it })
            assertThrows(IllegalStateException::class.java) { queue.submit({}, {}) }
            queue.close()
            shadowOf(Looper.getMainLooper()).idle()
            assertNull(result)
            release.countDown()
            disk.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            assertEquals(CaptureResult.CAMERA_FAILURE, result)
            assertTrue(disk.awaitTermination(5, TimeUnit.SECONDS))
        } finally {
            release.countDown()
            disk.shutdown()
        }
    }

    @Test fun successDrainsThenAllowsNextCaptureAndIdleClose() {
        val disk = Executors.newSingleThreadExecutor()
        val queue = CaptureDiskQueue(ContextCompat.getMainExecutor(RuntimeEnvironment.getApplication()), disk)
        var saved = 0
        repeat(2) {
            queue.submit({ it.onImageSaved(ImageCapture.OutputFileResults(null)) }, { if (it == CaptureResult.SAVED) saved++ })
            assertEquals(it, saved)
            disk.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
        }
        queue.close()
        assertEquals(2, saved)
        assertTrue(disk.awaitTermination(5, TimeUnit.SECONDS))
    }
}
