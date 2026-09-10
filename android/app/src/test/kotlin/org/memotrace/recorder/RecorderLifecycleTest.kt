package org.memotrace.recorder

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.system.ErrnoException
import android.system.OsConstants
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
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.LumaMetrics
import org.memotrace.recorder.capture.CaptureCompletion
import org.memotrace.recorder.capture.CaptureDiskQueue
import org.memotrace.recorder.capture.CaptureResult
import org.memotrace.recorder.capture.RecorderCamera
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.storage.CaptureAttemptRecord
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.LongRunReport
import org.memotrace.recorder.storage.SessionDiagnostics
import org.memotrace.recorder.storage.UnlinkStatus
import org.memotrace.recorder.ui.DiagnosticsActivity
import org.memotrace.recorder.ui.MainActivity
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowPowerManager
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.io.OutputStream
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class FakeRecorderCamera : RecorderCamera {
    var ready: () -> Unit = {}
    var error: () -> Unit = {}
    var output: OutputStream? = null
    var profile: CaptureProfile? = null
    var result: (CaptureResult) -> Unit = {}
    var calls = 0
    var starts = 0
    var closed = false
    var synchronousResult: CaptureResult? = null
    var throwOnCapture = false

    override fun start(
        onReady: () -> Unit,
        onError: () -> Unit,
    ) {
        starts++
        closed = false
        ready = onReady
        error = onError
    }

    override fun takeAnalysis() = SystemClock.elapsedRealtime() to LumaMetrics(0.0, 0.0, 0.0, true)

    override fun capture(
        output: OutputStream,
        onComplete: (CaptureCompletion) -> Unit,
    ) {
        calls++
        this.output = output
        if (throwOnCapture) throw IllegalStateException("synthetic_capture_exception")
        result = {
            val now = SystemClock.elapsedRealtime()
            onComplete(CaptureCompletion(it, now, now))
        }
        synchronousResult?.let {
            if (it == CaptureResult.SAVED) output.write(syntheticJpeg())
            result(it)
        }
    }

    override fun close() {
        closed = true
    }

    fun save() {
        output!!.write(syntheticJpeg())
        result(CaptureResult.SAVED)
    }
}

open class FakeCameraApplication : RecorderApplication() {
    val fake = FakeRecorderCamera()
    val media = FakeMediaDestination()
    var diagnosticsLoads = 0
    var summaryQueries = 0
    var storeCheckpoint: (String) -> Unit = {}

    override fun createDestination() = media

    override fun createStore() =
        FrameStore(
            archiveDirectory,
            media,
            checkpoint = {
                if (it == "summary") summaryQueries++
                storeCheckpoint(it)
            },
        )

    override fun createCamera(
        owner: LifecycleOwner,
        config: CaptureConfig,
        profile: CaptureProfile,
    ): RecorderCamera = fake.also { it.profile = profile }

    override fun loadDiagnostics(complete: (SessionDiagnostics?) -> Unit) {
        diagnosticsLoads++
        super.loadDiagnostics(complete)
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RecorderLifecycleTest {
    private lateinit var app: FakeCameraApplication
    private lateinit var service: ServiceController<RecorderService>

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
        ShadowStatFs.registerStats(app.noBackupFilesDir.path, 1_000_000, 500_000, 500_000)
        settle()
        assertTrue(app.ready)
        assertTrue(app.consentToPublicPictures())
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

    private fun startBeforeCameraReady() {
        val reserved = checkNotNull(app.reserveStart())
        service.get().onStartCommand(
            Intent(app, RecorderService::class.java)
                .setAction(RecorderService.ACTION_START)
                .putExtra(RecorderService.EXTRA_SESSION, reserved.id),
            0,
            1,
        )
        settle()
    }

    private fun start() {
        startBeforeCameraReady()
        app.fake.ready()
        settle()
    }

    private fun database(statement: String) {
        app.io
            .submit {
                SQLiteDatabase.openDatabase(File(app.noBackupFilesDir, "recorder/index.sqlite").path, null, 0).use {
                    it.execSQL(statement)
                }
            }.get(5, TimeUnit.SECONDS)
    }

    private fun pause() {
        service.get().onStartCommand(
            Intent(app, RecorderService::class.java)
                .setAction(RecorderService.ACTION_PAUSE)
                .putExtra(RecorderService.EXTRA_SESSION, app.sessionId),
            0,
            2,
        )
        settle()
    }

    @Test fun recordingOnlyAfterDurableSaveAndNoBacklog() {
        start()
        assertEquals(R.string.status_starting, app.status)
        assertEquals(
            "status=${app.getString(app.status)} ready=${app.ready} sessionOpen=${app.sessionOpen} cameraStarts=${app.fake.starts}",
            1,
            app.fake.calls,
        )
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

    @Test fun successfulFramesUpdateSummaryWithoutPerFrameSummaryQueries() {
        start()
        val baselineQueries = app.summaryQueries
        repeat(10) { index ->
            app.fake.save()
            settle()
            assertEquals(index + 1L, app.summary.count)
            assertEquals(index + 1L, app.summary.sessionCount)
            assertNotNull(app.summary.last)
            assertEquals(baselineQueries, app.summaryQueries)
            if (index < 9) {
                shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
                settle()
                assertEquals(index + 2, app.fake.calls)
            }
        }
        pause()
        assertEquals(baselineQueries + 1, app.summaryQueries)
        assertEquals(10L, app.summary.count)
        assertEquals(10L, app.summary.sessionCount)
    }

    @Test fun destroyAfterPreparationBeforeCameraInvocationAbandonsOutputAndFinishesAttempt() {
        val prepared = CountDownLatch(1)
        val release = CountDownLatch(1)
        app.storeCheckpoint = {
            if (it == "camera_invoke_ready") {
                prepared.countDown()
                check(release.await(10, TimeUnit.SECONDS))
            }
        }
        try {
            startBeforeCameraReady()
            val sessionId = checkNotNull(app.sessionId)
            app.fake.ready()
            shadowOf(Looper.getMainLooper()).idle()
            assertTrue(prepared.await(5, TimeUnit.SECONDS))
            assertEquals(1, app.media.writesOpen)
            service.destroy()
            release.countDown()
            settle()
            assertEquals(0, app.fake.calls)
            assertEquals(0, app.media.writesOpen)
            assertTrue(app.media.items.isEmpty())
            assertFalse(app.sessionOpen)
            val capture =
                app.io
                    .submit<CaptureAttemptRecord> {
                        app.store
                            .report(sessionId)!!
                            .captures
                            .single()
                    }.get(5, TimeUnit.SECONDS)
            assertEquals("CAMERA_FAILURE", capture.result)
            assertEquals("STOPPED_BEFORE_CAMERA_INVOCATION", capture.failurePhase)
        } finally {
            release.countDown()
            app.storeCheckpoint = {}
        }
    }

    @Test fun synchronousCameraCompletionFollowsDurablePreInvocationPhase() {
        app.fake.synchronousResult = CaptureResult.SAVED
        start()
        assertEquals(R.string.status_recording, app.status)
        assertEquals(1L, app.summary.count)
        assertEquals(0, app.media.writesOpen)
        val sessionId = checkNotNull(app.sessionId)
        pause()
        val capture =
            app.io
                .submit<CaptureAttemptRecord> {
                    app.store
                        .report(sessionId)!!
                        .captures
                        .single()
                }.get(5, TimeUnit.SECONDS)
        assertEquals("SAVED", capture.result)
        assertNotNull(capture.cameraInvokeReadyElapsedMs)
        assertTrue(capture.cameraInvokeReadyElapsedMs!! <= capture.cameraTerminalElapsedMs!!)
    }

    @Test fun synchronousCameraExceptionRetainsDurablePreInvocationPhase() {
        app.fake.throwOnCapture = true
        start()
        settle()
        assertEquals(R.string.status_camera_error, app.status)
        assertFalse(app.sessionOpen)
        assertEquals(0, app.media.writesOpen)
        assertTrue(app.media.items.isEmpty())
        val capture =
            app.io
                .submit<CaptureAttemptRecord> {
                    app.store
                        .report(null)!!
                        .captures
                        .single()
                }.get(5, TimeUnit.SECONDS)
        assertEquals("CAMERA_FAILURE", capture.result)
        assertNotNull(capture.cameraInvokeReadyElapsedMs)
        assertNotNull(capture.cameraTerminalElapsedMs)
    }

    @Test fun preparedPhaseJournalFailureClosesAndAbandonsPendingFrame() {
        startBeforeCameraReady()
        database(
            "CREATE TRIGGER reject_prepared BEFORE UPDATE ON capture_attempts " +
                "WHEN NEW.prepare_complete_elapsed_ms IS NOT NULL BEGIN SELECT RAISE(FAIL, 'synthetic_database_failure'); END",
        )
        app.fake.ready()
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0, app.media.writesOpen)
        assertTrue(app.media.items.isEmpty())
        assertEquals(0L, app.summary.count)
    }

    @Test fun cameraTelemetryFailureAfterDrainPublishesValidJpegThenStops() {
        start()
        val sessionId = checkNotNull(app.sessionId)
        database(
            "CREATE TRIGGER reject_camera_completed BEFORE UPDATE ON capture_attempts " +
                "WHEN NEW.camera_terminal_elapsed_ms IS NOT NULL BEGIN SELECT RAISE(FAIL, 'synthetic_database_failure'); END",
        )
        app.fake.save()
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(1L, app.summary.count)
        assertEquals(0, app.media.writesOpen)
        assertFalse(
            app.media.items.values
                .single()
                .pending,
        )
        assertEquals(
            syntheticJpeg().size,
            app.media.items.values
                .single()
                .bytes.size,
        )
        val report = app.io.submit<LongRunReport> { app.store.report(sessionId)!! }.get(5, TimeUnit.SECONDS)
        assertEquals("FAILED", report.session.completionStatus)
        assertEquals("STORAGE_FAILURE", report.session.terminalReason)
        assertEquals("SAVED", report.captures.single().result)
        assertEquals("SAVED_WITH_TELEMETRY_FAULT", report.captures.single().failurePhase)
    }

    @Test fun savedFinalCommitFailureStaysPendingAndRecoversCommittedFrame() {
        start()
        val sessionId = checkNotNull(app.sessionId)
        database(
            "CREATE TRIGGER reject_saved_attempt BEFORE UPDATE OF result ON capture_attempts " +
                "WHEN OLD.result='PENDING' AND NEW.result='SAVED' " +
                "BEGIN SELECT RAISE(FAIL, 'synthetic_saved_commit_failure'); END",
        )
        app.fake.save()
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0, app.media.writesOpen)
        assertFalse(
            app.media.items.values
                .single()
                .pending,
        )
        val beforeRecovery =
            app.io
                .submit<List<Any?>> {
                    SQLiteDatabase
                        .openDatabase(
                            File(app.noBackupFilesDir, "recorder/index.sqlite").path,
                            null,
                            SQLiteDatabase.OPEN_READONLY,
                        ).use { db ->
                            db
                                .rawQuery(
                                    "SELECT frames.state, frames.validated, capture_attempts.result, capture_attempts.failure_phase " +
                                        "FROM capture_attempts JOIN frames ON frames.id=capture_attempts.frame_id " +
                                        "WHERE capture_attempts.session_id=?",
                                    arrayOf(sessionId),
                                ).use { rows ->
                                    check(rows.moveToFirst())
                                    listOf(
                                        rows.getInt(0),
                                        rows.getInt(1),
                                        rows.getString(2),
                                        if (rows.isNull(3)) null else rows.getString(3),
                                    )
                                }
                        }
                }.get(5, TimeUnit.SECONDS)
        assertEquals(listOf(0, 1, "PENDING", null), beforeRecovery)
        assertEquals(0L, app.summary.count)

        database("DROP TRIGGER reject_saved_attempt")
        service.destroy()
        val backend = app.media
        val previous = app
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()
        app =
            object : FakeCameraApplication() {
                fun attach(context: Context) = attachBaseContext(context)

                override fun createDestination() = backend

                override fun createStore() =
                    FrameStore(
                        archiveDirectory,
                        backend,
                        checkpoint = {
                            if (it == "summary") summaryQueries++
                            storeCheckpoint(it)
                        },
                    )
            }.apply {
                attach(previous.baseContext)
                onCreate()
            }
        settle()

        assertTrue(app.ready)
        assertEquals(0, backend.writesOpen)
        assertFalse(
            backend.items.values
                .single()
                .pending,
        )
        assertEquals(1L, app.summary.count)
        val report = app.io.submit<LongRunReport> { app.store.report(sessionId)!! }.get(5, TimeUnit.SECONDS)
        assertEquals("FAILED", report.session.completionStatus)
        assertEquals("STORAGE_FAILURE", report.session.terminalReason)
        assertEquals("SAVED", report.captures.single().result)
        assertEquals("RECOVERY_FRAME_COMMITTED", report.captures.single().failurePhase)
        assertEquals(null, report.captures.single().commitCompleteElapsedMs)
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

    @Test fun reportExportGuardWaitsForFrameDrainAndTerminalJournalCommit() {
        start()
        assertFalse(app.canExport)
        pause()
        assertTrue(app.sessionOpen)
        assertFalse(app.canExport)
        var report: LongRunReport? = null
        assertEquals(null, app.reserveExport())
        assertEquals(null, report)
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertFalse(app.sessionOpen)
        assertTrue(app.canExport)
        val reservation = app.reserveExport()!!
        assertFalse(app.canStart)
        assertEquals(null, app.reserveStart())
        app.loadReport(reservation) { report = it }
        settle()
        assertEquals("COMPLETE", report!!.session.completionStatus)
        assertEquals("USER_PAUSE", report!!.session.terminalReason)
        assertEquals("CAMERA_FAILURE", report!!.captures.single().result)
        assertEquals(
            "START",
            report!!
                .samples
                .first()
                .sample.reason,
        )
        assertEquals(
            "END",
            report!!
                .samples
                .last()
                .sample.reason,
        )
        app.releaseExport(reservation)
        assertTrue(app.canStart)
    }

    @Test fun openDiagnosticsDoesNotReloadAttemptHistoryUntilSessionCloses() {
        start()
        Robolectric.buildActivity(DiagnosticsActivity::class.java).setup().use {
            settle()
            assertEquals(1, app.diagnosticsLoads)
            repeat(20) {
                app.publish()
                shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1))
            }
            settle()
            assertEquals(1, app.diagnosticsLoads)
            pause()
            app.fake.result(CaptureResult.CAMERA_FAILURE)
            settle()
            assertEquals(2, app.diagnosticsLoads)
        }
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
            settle()
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
        app.fake.output!!.write(byteArrayOf(0))
        app.fake.result(CaptureResult.SAVED)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0L, app.summary.count)
    }

    @Test fun pauseDuringCameraInitializationIgnoresLateReady() {
        val reserved = checkNotNull(app.reserveStart())
        service.get().onStartCommand(
            Intent(app, RecorderService::class.java)
                .setAction(RecorderService.ACTION_START)
                .putExtra(RecorderService.EXTRA_SESSION, reserved.id),
            0,
            1,
        )
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
            queue.submit({ callback = it }, { app.fake.result(it.result) })
            val output = app.fake.output!!
            val writer =
                disk.submit {
                    output.write(byteArrayOf(1))
                    writing.countDown()
                    check(releaseWrite.await(10, TimeUnit.SECONDS))
                    output.write(syntheticJpeg())
                }
            assertTrue(writing.await(5, TimeUnit.SECONDS))
            pause()
            service.destroy()
            callback.onError(ImageCaptureException(ImageCapture.ERROR_CAMERA_CLOSED, "synthetic abort", null))
            queue.close()
            queue.close()
            settle()
            assertEquals(1, app.media.writesOpen)
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
            assertEquals(0, app.media.writesOpen)
            assertTrue(app.media.items.isEmpty())
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
        app.fake.output!!.write(byteArrayOf(1))
        app.fake.result(CaptureResult.STORAGE_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0, app.media.writesOpen)
        assertTrue(app.media.items.isEmpty())
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

    @Test fun profileSnapshotRejectsBusyAndDrainingChangesAndEachStartHasNewFolder() {
        assertTrue(app.selectProfile(CaptureProfile.REFERENCE.id))
        start()
        val firstPath = app.sessionPath
        assertEquals(CaptureProfile.REFERENCE, app.fake.profile)
        assertFalse(app.selectProfile(CaptureProfile.WIDE_80.id))
        pause()
        assertFalse(app.selectProfile(CaptureProfile.WIDE_80.id))
        app.fake.save()
        settle()
        assertEquals(firstPath, app.summary.last!!.path)
        assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        service.destroy()
        service = Robolectric.buildService(RecorderService::class.java).create()
        start()
        assertEquals(CaptureProfile.WIDE_80, app.fake.profile)
        assertTrue(app.sessionPath != firstPath)
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
    }

    @Test fun refreshDatabaseFailureStopsAndDrainsEvenWhenIoRecoversBeforeLateSuccess() {
        start()
        app.fake.save()
        settle()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
        settle()
        assertEquals(2, app.fake.calls)

        fun rename(
            from: String,
            to: String,
        ) {
            app.io
                .submit {
                    SQLiteDatabase.openDatabase(File(app.noBackupFilesDir, "recorder/index.sqlite").path, null, 0).use {
                        it.execSQL("ALTER TABLE $from RENAME TO $to")
                    }
                }.get(5, TimeUnit.SECONDS)
        }
        rename("frames", "frames_fault")
        app.refreshAvailability(lastOnly = true)
        // This queued restoration follows the failed refresh but precedes its main callback.
        rename("frames_fault", "frames")
        shadowOf(Looper.getMainLooper()).idle()
        assertFalse(app.ready)
        assertTrue(app.fake.closed)
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        assertTrue(app.sessionOpen)
        assertEquals(R.string.status_storage_error, app.status)
        Robolectric.buildActivity(MainActivity::class.java).setup().use {
            assertTrue(it.get().findViewById<Button>(R.id.pause_recording).isEnabled)
            pause()
            assertEquals(R.string.status_storage_error, app.status)
        }
        app.fake.save()
        settle()
        assertEquals(2L, app.summary.count)
        assertFalse(app.sessionOpen)
        assertFalse(app.ready)
        assertEquals(R.string.status_storage_error, app.status)
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(3))
        assertEquals(2, app.fake.calls)
    }

    @Test fun potentiallySlowHistorySweepDefersUntilDrainedWithoutTimingOutHealthyCapture() {
        start()
        app.fake.save()
        settle()
        val old = app.summary.last!!.uri
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        app.media.beforeInspect = { uri ->
            if (uri == old) {
                entered.countDown()
                check(release.await(10, TimeUnit.SECONDS))
            }
        }
        try {
            app.refreshAvailability()
            settle()
            assertEquals(1L, entered.count)
            repeat(17) {
                shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
                settle()
                app.fake.save()
                settle()
                assertEquals(R.string.status_recording, app.status)
            }
            app.refreshAvailability(lastOnly = true)
            settle()
            assertEquals(1L, entered.count)
            assertEquals(18L, app.summary.count)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
            settle()
            assertEquals(19, app.fake.calls)
            service.get().onStartCommand(
                Intent(app, RecorderService::class.java)
                    .setAction(RecorderService.ACTION_PAUSE)
                    .putExtra(RecorderService.EXTRA_SESSION, app.sessionId),
                0,
                2,
            )
            assertTrue(app.sessionOpen)
            assertEquals(1L, entered.count)
            app.fake.save()
            app.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            app.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            assertFalse(app.sessionOpen)
            assertFalse(app.canStart)
            assertTrue(app.fake.closed)
        } finally {
            release.countDown()
            settle()
        }
        assertTrue(app.canStart)
        assertEquals(R.string.status_paused, app.status)
    }

    @Test fun uiStartReservesProfileBeforeDelayedServiceDeliveryAndRejectsForgedOrSecondStart() {
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        Robolectric.buildActivity(MainActivity::class.java).setup().use { activity ->
            settle()
            assertTrue(app.selectProfile(CaptureProfile.REFERENCE.id))
            activity.get().findViewById<Button>(R.id.start_recording).performClick()
            val queued = checkNotNull(shadowOf(app).nextStartedService)
            assertTrue(app.sessionOpen)
            assertFalse(app.selectProfile(CaptureProfile.WIDE_80.id))
            assertFalse(activity.get().findViewById<Button>(R.id.start_recording).isEnabled)
            assertEquals(null, app.reserveStart())
            assertEquals(null, app.consumeStart("forged-token"))
            service.get().onStartCommand(queued, 0, 1)
            settle()
            app.fake.ready()
            settle()
            assertEquals(CaptureProfile.REFERENCE, app.fake.profile)
            assertEquals(1, app.fake.calls)
            app.fake.save()
            settle()
        }
    }

    @Test fun cancelledReservationCannotStartWhenOldIntentFinallyArrives() {
        val reserved = checkNotNull(app.reserveStart())
        app.cancelStart(reserved.id)
        assertTrue(app.canStart)
        assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        service.get().onStartCommand(
            Intent(app, RecorderService::class.java)
                .setAction(RecorderService.ACTION_START)
                .putExtra(RecorderService.EXTRA_SESSION, reserved.id),
            0,
            1,
        )
        assertFalse(app.sessionOpen)
        assertEquals(0, app.fake.calls)
    }

    @Test fun realUiCancelAThenStartBBeforeDeliveryDoesNotQueuePauseOrStopNewerStart() {
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            settle()
            val activity = controller.get()
            activity.findViewById<Button>(R.id.start_recording).performClick()
            val startA = checkNotNull(shadowOf(app).nextStartedService)
            activity.findViewById<Button>(R.id.pause_recording).performClick()
            assertEquals(null, shadowOf(app).nextStartedService)
            assertFalse(app.sessionOpen)
            assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
            activity.findViewById<Button>(R.id.start_recording).performClick()
            val startB = checkNotNull(shadowOf(app).nextStartedService)
            service.get().onStartCommand(startA, 0, 10)
            // ShadowService records the API argument, not AMS's queue semantics. No unconditional stop is allowed.
            assertEquals(10, shadowOf(service.get()).stopSelfId)
            assertEquals(startB.getStringExtra(RecorderService.EXTRA_SESSION), app.sessionId)
            assertTrue(app.sessionOpen)
            service.get().onStartCommand(startB, 0, 11)
            settle()
            app.fake.ready()
            settle()
            assertEquals(CaptureProfile.WIDE_80, app.fake.profile)
            assertEquals(1, app.fake.calls)
            app.fake.save()
            settle()
            assertEquals(R.string.status_recording, app.status)
        }
    }

    @Test fun delayedOldUiAndNotificationPauseCannotCancelOrStopB() {
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            settle()
            val activity = controller.get()
            activity.findViewById<Button>(R.id.start_recording).performClick()
            service.get().onStartCommand(checkNotNull(shadowOf(app).nextStartedService), 0, 1)
            settle()
            app.fake.ready()
            settle()
            val oldNotification =
                app
                    .getSystemService(
                        NotificationManager::class.java,
                    ).activeNotifications
                    .single()
                    .notification.actions[0]
                    .actionIntent
            activity.findViewById<Button>(R.id.pause_recording).performClick()
            val pauseA = checkNotNull(shadowOf(app).nextStartedService)
            service.get().onStartCommand(pauseA, 0, 2)
            app.fake.result(CaptureResult.CAMERA_FAILURE)
            settle()
            activity.findViewById<Button>(R.id.start_recording).performClick()
            val startB = checkNotNull(shadowOf(app).nextStartedService)
            service.get().onStartCommand(pauseA, 0, 3)
            assertEquals(3, shadowOf(service.get()).stopSelfId)
            assertEquals(startB.getStringExtra(RecorderService.EXTRA_SESSION), app.sessionId)
            service.get().onStartCommand(startB, 0, 4)
            settle()
            app.fake.ready()
            settle()
            val newNotification =
                app
                    .getSystemService(
                        NotificationManager::class.java,
                    ).activeNotifications
                    .single()
                    .notification.actions[0]
                    .actionIntent
            assertFalse(oldNotification == newNotification)
            service.get().onStartCommand(shadowOf(oldNotification).savedIntent, 0, 5)
            assertFalse(app.fake.closed)
            assertEquals(startB.getStringExtra(RecorderService.EXTRA_SESSION), app.sessionId)
            app.fake.save()
            settle()
            assertEquals(R.string.status_recording, app.status)
        }
    }

    @Test fun unknownServiceCommandsOnlyStopTheirOwnStartId() {
        service.get().onStartCommand(null, 0, 7)
        assertEquals(7, shadowOf(service.get()).stopSelfId)
        service.get().onStartCommand(Intent(app, RecorderService::class.java).setAction("unknown"), 0, 8)
        assertEquals(8, shadowOf(service.get()).stopSelfId)
    }

    @Test fun pauseAbortAfterSavedFrameWithUnknownUnlinkAllowsNextProfileStart() {
        start()
        app.fake.save()
        settle()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
        settle()
        assertEquals(2, app.fake.calls)
        app.media.unlinkStatus = UnlinkStatus.UNKNOWN
        pause()
        assertTrue(app.sessionOpen)
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertEquals(R.string.status_paused, app.status)
        assertTrue(app.canStart)
        assertFalse(app.sessionOpen)
        assertEquals(1L, app.summary.count)
        assertEquals(1L, app.summary.quarantinedCount)
        assertEquals(0, app.media.writesOpen)
        assertEquals(0, app.media.witnessesOpen)
        service.destroy()
        service = Robolectric.buildService(RecorderService::class.java).create()
        assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        app.media.unlinkStatus = null
        start()
        app.fake.save()
        settle()
        assertEquals(CaptureProfile.WIDE_80, app.fake.profile)
        assertEquals(2L, app.summary.count)
        assertEquals(1L, app.summary.quarantinedCount)
        pause()
    }

    @Test fun cameraFileIoRemainsFatalEvenWhenUncertainCleanupQuarantinesSuccessfully() {
        start()
        app.fake.save()
        settle()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
        settle()
        app.media.unlinkStatus = UnlinkStatus.UNKNOWN
        pause()
        app.fake.result(CaptureResult.STORAGE_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(1L, app.summary.count)
        assertEquals(1L, app.summary.quarantinedCount)
        assertEquals(0, app.media.witnessesOpen)
    }

    @Test fun unrelatedCleanupStatFailureRemainsFatal() {
        start()
        app.media.unlinkFailure = ErrnoException("fstat", OsConstants.EBADF)
        pause()
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertEquals(0L, app.summary.count)
        assertEquals(0L, app.summary.quarantinedCount)
        assertEquals(0, app.media.witnessesOpen)
    }

    @Test fun abortQuarantineMustCommitBeforeReleasingSessionAsReady() {
        start()
        app.io
            .submit {
                SQLiteDatabase.openDatabase(File(app.noBackupFilesDir, "recorder/index.sqlite").path, null, 0).use {
                    it.execSQL(
                        "CREATE TRIGGER reject_quarantine BEFORE UPDATE ON frames " +
                            "WHEN NEW.state=2 BEGIN SELECT RAISE(FAIL, 'synthetic_database_failure'); END",
                    )
                }
            }.get(5, TimeUnit.SECONDS)
        app.media.unlinkStatus = UnlinkStatus.UNKNOWN
        pause()
        app.fake.result(CaptureResult.CAMERA_FAILURE)
        settle()
        assertEquals(R.string.status_storage_error, app.status)
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(0L, app.summary.count)
        assertEquals(0L, app.summary.quarantinedCount)
    }

    @Test fun restartQuarantinesFailedInsertAndCanSelectStartAndSaveExactlyOneNewFrame() {
        // The first process stopped on a real current insert failure, before any camera output.
        app.media.fault = "insert"
        start()
        assertFalse(app.ready)
        assertFalse(app.sessionOpen)
        assertEquals(R.string.status_storage_error, app.status)
        assertEquals(0, app.fake.calls)
        service.destroy()
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()

        // New application IO/store, same persisted index and preferences. No old writer survives.
        val previous = app
        app =
            object : FakeCameraApplication() {
                fun attach(context: Context) = attachBaseContext(context)
            }.apply {
                attach(previous.baseContext)
                onCreate()
            }
        settle()
        assertTrue(app.ready)
        assertEquals(1L, app.summary.quarantinedCount)
        assertEquals(0L, app.summary.count)
        assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        service = Robolectric.buildService(RecorderService::class.java).create()
        // Robolectric's service uses the registered application, so run the restarted fixture via its own binding below.
        org.robolectric.util.ReflectionHelpers
            .setField(service.get(), "mApplication", app)
        start()
        app.fake.save()
        settle()
        assertEquals(1, app.fake.calls)
        assertEquals(CaptureProfile.WIDE_80, app.fake.profile)
        assertEquals(1L, app.summary.count)
        assertEquals(1L, app.summary.quarantinedCount)
        assertEquals(R.string.status_recording, app.status)
        pause()
        val activity = Robolectric.buildActivity(MainActivity::class.java).create()
        org.robolectric.util.ReflectionHelpers
            .setField(activity.get(), "mApplication", app)
        activity.start().resume().visible().use {
            settle()
            assertTrue(it.get().findViewById<Button>(R.id.start_recording).isEnabled)
            assertEquals(null, it.get().findViewById<TextView>(R.id.quarantined_count))
            assertEquals(
                app.getString(R.string.saved_count, 1L, 1L),
                it
                    .get()
                    .findViewById<TextView>(R.id.saved_count)
                    .text
                    .toString(),
            )
        }
    }
}
