package org.memotrace.recorder

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.widget.Button
import android.widget.TextView
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureConfig
import org.memotrace.capture.LumaMetrics
import org.memotrace.recorder.capture.CaptureDiskQueue
import org.memotrace.recorder.capture.CaptureResult
import org.memotrace.recorder.capture.RecorderCamera
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.ui.MainActivity
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowPowerManager
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class FakeRecorderCamera : RecorderCamera {
    var ready: () -> Unit = {}
    var error: () -> Unit = {}
    var output: File? = null
    var result: (CaptureResult) -> Unit = {}
    var calls = 0
    var closed = false

    override fun start(
        onReady: () -> Unit,
        onError: () -> Unit,
    ) {
        ready = onReady
        error = onError
    }

    override fun takeAnalysis() = SystemClock.elapsedRealtime() to LumaMetrics(0.0, 0.0, 0.0, true)

    override fun capture(
        output: File,
        onComplete: (CaptureResult) -> Unit,
    ) {
        calls++
        this.output = output
        result = onComplete
    }

    override fun close() {
        closed = true
    }

    fun save() {
        output!!.writeBytes(byteArrayOf(-1, -40, 1, -1, -39))
        result(CaptureResult.SAVED)
    }
}

class FakeCameraApplication : RecorderApplication() {
    val fake = FakeRecorderCamera()

    override fun createCamera(
        owner: LifecycleOwner,
        config: CaptureConfig,
    ): RecorderCamera = fake
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class)
class RecorderLifecycleTest {
    private lateinit var app: FakeCameraApplication
    private lateinit var service: ServiceController<RecorderService>

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
        ShadowStatFs.registerStats(app.noBackupFilesDir.path, 1_000_000, 500_000, 500_000)
        settle()
        assertTrue(app.ready)
        service = Robolectric.buildService(RecorderService::class.java).create()
    }

    @After fun teardown() {
        if (service.get().lifecycle.currentState != Lifecycle.State.DESTROYED) service.destroy()
        settle()
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()
    }

    private fun settle() {
        repeat(3) {
            app.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
        }
    }

    private fun start() {
        service.get().onStartCommand(Intent(app, RecorderService::class.java).setAction(RecorderService.ACTION_START), 0, 1)
        app.fake.ready()
        settle()
    }

    private fun pause() {
        service.get().onStartCommand(Intent(app, RecorderService::class.java).setAction(RecorderService.ACTION_PAUSE), 0, 2)
        settle()
    }

    @Test fun recordingOnlyAfterDurableSaveAndNoBacklog() {
        start()
        assertEquals(R.string.status_starting, app.status)
        assertEquals(1, app.fake.calls)
        assertNotNull(app.getSystemService(NotificationManager::class.java).activeNotifications.singleOrNull())
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(10))
        settle()
        assertEquals(1, app.fake.calls)
        app.fake.save()
        settle()
        assertEquals(1L, app.summary.count)
        assertEquals(R.string.status_recording, app.status)
        pause()
        assertEquals(R.string.status_paused, app.status)
        assertFalse(app.sessionOpen)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
    }

    @Test fun pauseDestroyThenLateSuccessCannotRestartOrDuplicate() {
        start()
        pause()
        service.destroy()
        assertTrue(app.fake.closed)
        assertTrue(app.sessionOpen)
        assertEquals(R.string.status_stopping, app.status)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        app.fake.ready()
        app.fake.save()
        app.fake.result(CaptureResult.SAVED)
        settle()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(4))
        assertEquals(1, app.fake.calls)
        assertEquals(1L, app.summary.count)
        assertEquals(R.string.status_paused, app.status)
        assertFalse(app.sessionOpen)
    }

    @Test fun cameraFailureAndLateSuccessLeaveHonestError() {
        start()
        app.fake.error()
        assertEquals(R.string.status_camera_error, app.status)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        app.fake.save()
        settle()
        assertEquals(R.string.status_camera_error, app.status)
        assertEquals(1L, app.summary.count)
        assertFalse(app.sessionOpen)
    }

    @Test fun lateFailureAfterPauseIsNotNewCameraError() {
        start()
        pause()
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertEquals(R.string.status_paused, app.status)
        assertEquals(0L, app.summary.count)
        assertFalse(app.sessionOpen)
    }

    @Test fun timeoutReleasesWakeLockButReservesOutstandingSlot() {
        start()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(30))
        assertEquals(R.string.status_timeout, app.status)
        assertTrue(app.sessionOpen)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertFalse(app.sessionOpen)
        assertEquals(R.string.status_timeout, app.status)
    }

    @Test fun storageReserveFailureStopsWithoutCameraRequest() {
        ShadowStatFs.registerStats(app.noBackupFilesDir.path, 10, 1, 1)
        start()
        assertEquals(0, app.fake.calls)
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
    }

    @Test fun uiRecreationDoesNotStartCameraAndPreservesIndexCount() {
        Robolectric.buildActivity(MainActivity::class.java).setup().use { activity ->
            assertTrue(activity.get().findViewById<Button>(R.id.start_recording).isEnabled)
            assertFalse(activity.get().findViewById<Button>(R.id.pause_recording).isEnabled)
            assertEquals(
                app.getString(R.string.status_paused),
                activity
                    .get()
                    .findViewById<TextView>(R.id.record_status)
                    .text
                    .toString(),
            )
            activity.recreate()
            assertEquals(0, app.fake.calls)
            assertFalse(app.sessionOpen)
        }
    }

    @Test fun nullAndPauseCommandsNeverGrantRecordingConsent() {
        service.get().onStartCommand(null, 0, 1)
        pause()
        assertFalse(app.sessionOpen)
        assertEquals(0, app.fake.calls)
        assertFalse(app.getSharedPreferences("record_state", 0).getBoolean("requested", false))
        assertEquals(R.string.status_paused, app.status)
    }

    @Test fun persistedRequestBecomesInterruptedNotAutomaticRecording() {
        assertTrue(app.persistRequest(true))
        val restarted =
            object : RecorderApplication() {
                fun attach(context: Context) {
                    attachBaseContext(context)
                }
            }.apply {
                attach(app.baseContext)
                onCreate()
            }
        restarted.io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
        assertEquals(R.string.status_interrupted, restarted.status)
        assertFalse(restarted.sessionOpen)
        restarted.io.submit { restarted.store.close() }.get(5, TimeUnit.SECONDS)
        restarted.io.shutdown()
    }

    @Test fun storageFailureAfterPauseIsStillReported() {
        start()
        pause()
        app.fake.output!!.writeBytes(byteArrayOf(0))
        app.fake.result(CaptureResult.SAVED)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0L, app.summary.count)
    }

    @Test fun pauseDuringCameraInitializationIgnoresLateReady() {
        service.get().onStartCommand(Intent(app, RecorderService::class.java).setAction(RecorderService.ACTION_START), 0, 1)
        pause()
        app.fake.ready()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(3))
        assertEquals(0, app.fake.calls)
        assertEquals(R.string.status_paused, app.status)
        assertFalse(app.sessionOpen)
    }

    @Test fun abortBeforeDiskWriteFinishesKeepsSessionAndOutputUntilDrain() {
        val disk = Executors.newSingleThreadExecutor()
        val queue = CaptureDiskQueue(ContextCompat.getMainExecutor(app), disk)
        val writing = CountDownLatch(1)
        val releaseWrite = CountDownLatch(1)
        try {
            start()
            lateinit var callback: ImageCapture.OnImageSavedCallback
            queue.submit({ callback = it }, app.fake.result)
            val output = app.fake.output!!
            val writer =
                disk.submit {
                    output.writeBytes(byteArrayOf(1))
                    writing.countDown()
                    check(releaseWrite.await(10, TimeUnit.SECONDS))
                    output.writeBytes(byteArrayOf(-1, -40, 1, -1, -39))
                }
            assertTrue(writing.await(5, TimeUnit.SECONDS))
            pause()
            service.destroy()
            callback.onError(ImageCaptureException(ImageCapture.ERROR_CAMERA_CLOSED, "synthetic abort", null))
            queue.close()
            queue.close()
            settle()
            assertTrue(output.exists())
            assertTrue(app.sessionOpen)
            assertEquals(R.string.status_stopping, app.status)
            assertEquals(0L, app.summary.count)
            val rapidRestart = Robolectric.buildService(RecorderService::class.java).create()
            rapidRestart.get().onStartCommand(Intent(app, RecorderService::class.java).setAction(RecorderService.ACTION_START), 0, 3)
            rapidRestart.destroy()
            assertTrue(app.sessionOpen)
            assertEquals(1, app.fake.calls)
            releaseWrite.countDown()
            writer.get(5, TimeUnit.SECONDS)
            disk.submit {}.get(5, TimeUnit.SECONDS)
            settle()
            assertFalse(output.exists())
            assertFalse(app.sessionOpen)
            assertEquals(R.string.status_paused, app.status)
            assertTrue(disk.awaitTermination(5, TimeUnit.SECONDS))
            callback.onImageSaved(ImageCapture.OutputFileResults(null))
            settle()
            assertEquals(0L, app.summary.count)
            assertEquals(1, app.fake.calls)
        } finally {
            releaseWrite.countDown()
            queue.close()
            disk.shutdown()
        }
    }

    @Test fun cameraFileIoErrorDisablesStorageEvenWhenCleanupSucceeds() {
        start()
        app.fake.output!!.writeBytes(byteArrayOf(1))
        app.fake.result(CaptureResult.STORAGE_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertFalse(app.fake.output!!.exists())
        assertEquals(0L, app.summary.count)
    }

    @Test fun cameraFileIoErrorAfterPauseIsNotHidden() {
        start()
        pause()
        app.fake.result(CaptureResult.STORAGE_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(1, app.getSharedPreferences("record_state", 0).getInt("status", 0))
    }
}
