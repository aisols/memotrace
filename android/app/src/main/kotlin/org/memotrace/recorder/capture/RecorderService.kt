package org.memotrace.recorder.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.LifecycleService
import org.memotrace.capture.CapturePolicy
import org.memotrace.capture.CaptureRequest
import org.memotrace.capture.CaptureSession
import org.memotrace.capture.LumaMetrics
import org.memotrace.recorder.R
import org.memotrace.recorder.RecorderApplication
import org.memotrace.recorder.storage.CaptureAttemptStart
import org.memotrace.recorder.storage.CommittedFrame
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.PendingFrame
import org.memotrace.recorder.storage.SessionStart
import org.memotrace.recorder.ui.MainActivity
import java.util.UUID

/** Main-thread lifecycle and policy; one serial IO lane, one latest-only analysis lane. */
class RecorderService : LifecycleService() {
    private val app get() = application as RecorderApplication
    private val policy = CapturePolicy()
    private var camera: RecorderCamera? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var renewedAt = 0L
    private var startedAt = 0L
    private var lastMetrics: Pair<Long, LumaMetrics>? = null
    private var running = false
    private var ownsSession = false
    private var outstanding = false
    private var opened = false
    private var runtimeStarted = false
    private var finalizingSession = false
    private var nextSampleAt = 0L
    private var terminalStatus = R.string.status_paused
    private lateinit var session: CaptureSession
    private lateinit var sampler: DeviceTelemetrySampler
    private val telemetryRequests = TelemetryRequestCoalescer(::writeTelemetrySample)
    private var thermalListener: PowerManager.OnThermalStatusChangedListener? = null
    private var lastHandledStartId = 0

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        super.onStartCommand(intent, flags, startId)
        lastHandledStartId = startId
        if (intent?.action == ACTION_PAUSE) {
            val id = intent.getStringExtra(EXTRA_SESSION)
            if (ownsSession && id == session.id) {
                stopRecording(R.string.status_paused)
            } else {
                app.cancelStart(id)
                if (!running) stopSelf(startId)
            }
            return START_NOT_STICKY
        }
        if (running) return START_NOT_STICKY
        if (intent?.action != ACTION_START) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val reserved = app.consumeStart(intent.getStringExtra(EXTRA_SESSION))
        if (reserved == null) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        ownsSession = true
        session = reserved
        app.stopForStorageFailure = { stopRecording(R.string.status_storage_error) }
        app.sessionPath = app.createDestination().prefix + session.relativePath
        app.negotiatedSize = ""
        app.sessionOpen = true
        running = true
        opened = false
        runtimeStarted = false
        finalizingSession = false
        telemetryRequests.clear()
        lastMetrics = null
        terminalStatus = R.string.status_paused
        app.status = R.string.status_starting
        app.coverText = getString(R.string.cover_unknown)
        try {
            showNotification()
            startedAt = SystemClock.elapsedRealtime()
            nextSampleAt = startedAt + SAMPLE_INTERVAL_MS
            sampler = DeviceTelemetrySampler(this, app.telemetryRoot)
            queueSessionStart()
            if (!app.persistRequest(true)) {
                stopRecording(R.string.status_storage_error)
                return START_NOT_STICKY
            }
        } catch (_: Exception) {
            stopRecording(R.string.status_storage_error)
        }
        app.publish()
        return START_NOT_STICKY
    }

    private fun queueSessionStart() {
        val wallMs = System.currentTimeMillis()
        val start =
            SessionStart(
                session.id,
                session.profile.id,
                session.profile.width,
                session.profile.height,
                session.profile.quality,
                "v1;rear;mode=minimizeLatency;cadence=adaptive",
                wallMs,
                startedAt,
                sampler.deviceSnapshot(),
            )
        app.io.execute {
            try {
                app.store.startCaptureSession(start, sampler.sample("START", wallMs, startedAt))
                app.main.post {
                    if (running) startRuntime() else releaseSession()
                }
            } catch (_: Exception) {
                app.main.post { journalFailure() }
            }
        }
    }

    private fun startRuntime() {
        if (!running || runtimeStarted) return
        try {
            policy.start()
            runtimeStarted = true
            wakeLock =
                getSystemService(PowerManager::class.java)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MemoTrace:recorder")
                    .apply {
                        setReferenceCounted(false)
                        acquire(WAKE_TIMEOUT_MS)
                    }
            renewedAt = SystemClock.elapsedRealtime()
            registerThermalListener()
            camera = app.createCamera(this, policy.config, session.profile)
            camera?.start(
                onReady = {
                    if (running) {
                        opened = true
                        val size = camera?.negotiatedSize
                        app.negotiatedSize = size?.let { "${it.width} x ${it.height}" } ?: ""
                        if (size != null) {
                            app.io.execute {
                                try {
                                    app.store.updateNegotiatedSize(session.id, size.width, size.height)
                                } catch (_: Exception) {
                                    app.main.post { if (running) stopRecording(R.string.status_storage_error) }
                                }
                            }
                        }
                        app.publish()
                        app.main.removeCallbacks(tick)
                        app.main.post(tick)
                    }
                },
                onError = { if (running) stopRecording(R.string.status_camera_error) },
            )
            app.main.post(tick)
        } catch (_: Exception) {
            stopRecording(R.string.status_camera_error)
        }
    }

    private fun journalFailure() {
        running = false
        terminalStatus = R.string.status_storage_error
        app.status = terminalStatus
        app.ready = false
        app.persistRequest(false, true)
        releaseCamera()
        ownsSession = false
        app.endSession()
        app.publish()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf(lastHandledStartId)
    }

    private fun registerThermalListener() {
        val listener =
            PowerManager.OnThermalStatusChangedListener { status ->
                if (running) queueTelemetrySample("THERMAL_CHANGE", status)
            }
        try {
            getSystemService(PowerManager::class.java).addThermalStatusListener(ContextCompat.getMainExecutor(this), listener)
            thermalListener = listener
        } catch (_: RuntimeException) {
            thermalListener = null
        }
    }

    private fun showNotification() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW),
        )
        val open =
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE,
            )
        val pause =
            PendingIntent.getService(
                this,
                1,
                Intent(this, RecorderService::class.java)
                    .setAction(ACTION_PAUSE)
                    .setData("memotrace://session/${session.id}".toUri())
                    .putExtra(EXTRA_SESSION, session.id),
                PendingIntent.FLAG_IMMUTABLE,
            )
        val notification =
            Notification
                .Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_record)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.notification_text))
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .addAction(Notification.Action.Builder(null, getString(R.string.pause), pause).build())
                .build()
        ServiceCompat.startForeground(this, 1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
    }

    private val tick =
        object : Runnable {
            override fun run() {
                if (!running) return
                val now = SystemClock.elapsedRealtime()
                if (now - renewedAt >= WAKE_TIMEOUT_MS / 2) {
                    try {
                        wakeLock?.acquire(WAKE_TIMEOUT_MS)
                    } catch (_: RuntimeException) {
                        stopRecording(R.string.status_error)
                        return
                    }
                    renewedAt = now
                }
                camera?.takeAnalysis()?.let {
                    lastMetrics = it
                    policy.motion(it.second.motion, it.first)
                }
                if (policy.timedOut(now) || now - (lastMetrics?.first ?: startedAt) >= policy.config.captureTimeoutMs) {
                    stopRecording(R.string.status_timeout)
                    return
                }
                app.intervalMs = policy.intervalMs
                app.coverText =
                    when (lastMetrics?.takeIf { now - it.first <= 2_000 }?.second?.coverSuspected) {
                        true -> getString(R.string.cover_suspected)
                        false -> getString(R.string.cover_clear)
                        null -> getString(R.string.cover_unknown)
                    }
                if (opened) policy.request(now)?.let(::acquire)
                if (now >= nextSampleAt) {
                    do {
                        nextSampleAt += SAMPLE_INTERVAL_MS
                    } while (nextSampleAt <= now)
                    queueTelemetrySample("PERIODIC")
                }
                app.publish()
                app.main.postDelayed(this, 100)
            }
        }

    private fun acquire(captureRequest: CaptureRequest) {
        val token = captureRequest.token
        val elapsedMs = captureRequest.requestElapsedMs
        outstanding = true
        val attemptId = UUID.randomUUID().toString()
        val config = policy.config
        val request =
            FrameRequest(
                System.currentTimeMillis(),
                elapsedMs,
                captureRequest.intervalMs,
                "v2;session=${session.id};profile=${session.profile.id};rear;mode=minimizeLatency;baselineMs=${config.baselineMs};" +
                    "motionMs=${config.motionMs};enter=${config.motionEnter};exit=${config.motionExit};" +
                    "quietMs=${config.quietMs};analysisMs=${config.analysisMs}",
                lastMetrics?.takeIf { elapsedMs - it.first <= 2_000 }?.let {
                    "v1;SHADOW;suspected=${it.second.coverSuspected};mean=${it.second.mean};" +
                        "variance=${it.second.variance};analysisElapsedMs=${it.first}"
                } ?: "v1;SHADOW;unknown",
                session,
                camera?.negotiatedSize?.width,
                camera?.negotiatedSize?.height,
            )
        val attempt =
            CaptureAttemptStart(
                id = attemptId,
                sessionId = session.id,
                requestWallMs = request.wallMs,
                requestElapsedMs = request.elapsedMs,
                requestedIntervalMs = request.intervalMs,
                scheduledDueElapsedMs = captureRequest.scheduledDueElapsedMs,
            )
        app.io.execute {
            var frame: PendingFrame? = null
            try {
                val preparedFrame = app.store.prepareCapture(attempt, request)
                frame = preparedFrame
                val preparedAt = SystemClock.elapsedRealtime()
                // This durable phase means the serial lane is ready to invoke CameraX; CameraX has not yet been called.
                app.store.markCameraInvokeReady(attemptId, preparedFrame.id, preparedAt, SystemClock.elapsedRealtime())
                app.main.post {
                    if (!running) {
                        persistWithoutCamera(token, attemptId, preparedFrame)
                    } else {
                        var delivered = false

                        fun accept(result: CaptureCompletion) {
                            if (delivered) return
                            delivered = true
                            persistResult(token, attemptId, preparedFrame, result)
                        }
                        try {
                            checkNotNull(camera).capture(preparedFrame.output.stream, ::accept)
                        } catch (_: Exception) {
                            val now = SystemClock.elapsedRealtime()
                            accept(CaptureCompletion(CaptureResult.CAMERA_FAILURE, now, now))
                        }
                    }
                }
            } catch (_: Exception) {
                frame?.let {
                    try {
                        app.store.abandon(it)
                    } catch (_: Exception) {
                        // The archive remains failed; release of the owned output was still attempted.
                    }
                }
                try {
                    app.store.failCapturePreparation(
                        attempt,
                        SystemClock.elapsedRealtime().coerceAtLeast(elapsedMs),
                        if (frame == null) "PREPARE" else "PRE_CAMERA_JOURNAL",
                    )
                } catch (_: Exception) {
                    // The original storage failure remains fatal; a broken journal cannot fabricate an attempt result.
                }
                app.main.post { completed(token, false, R.string.status_storage_error) }
            }
        }
    }

    private fun persistWithoutCamera(
        token: Long,
        attemptId: String,
        frame: PendingFrame,
    ) {
        app.io.execute {
            var failure = R.string.status_camera_error
            try {
                app.store.abandon(frame)
                app.store.finishCaptureAttempt(
                    attemptId,
                    SystemClock.elapsedRealtime(),
                    CaptureResult.CAMERA_FAILURE.name,
                    "STOPPED_BEFORE_CAMERA_INVOCATION",
                )
            } catch (_: Exception) {
                failure = R.string.status_storage_error
            }
            val summary = trySummary()
            app.main.post {
                if (summary != null) app.summary = summary
                completed(token, false, if (summary == null) R.string.status_storage_error else failure)
            }
        }
    }

    private fun persistResult(
        token: Long,
        attemptId: String,
        frame: PendingFrame,
        completion: CaptureCompletion,
    ) {
        app.io.execute {
            var frameSaved = false
            var committed: CommittedFrame? = null
            var storageFault = false
            var cameraPhasesDurable = true
            // Abandon may quarantine cleanup uncertainty, but it never turns an abort into SAVED
            // or downgrades CameraX ERROR_FILE_IO (STORAGE_FAILURE).
            var failure =
                if (completion.result == CaptureResult.STORAGE_FAILURE) R.string.status_storage_error else R.string.status_camera_error
            var failurePhase: String? =
                when (completion.result) {
                    CaptureResult.SAVED -> null
                    CaptureResult.CAMERA_FAILURE -> "CAMERAX_TERMINAL"
                    CaptureResult.STORAGE_FAILURE -> "CAMERAX_WRITER"
                }
            try {
                app.store.markCameraCompleted(attemptId, completion.cameraTerminalElapsedMs, completion.diskDrainedElapsedMs)
            } catch (_: Exception) {
                cameraPhasesDurable = false
                storageFault = true
                failure = R.string.status_storage_error
                failurePhase = "TELEMETRY_DATABASE"
            }
            try {
                if (completion.result == CaptureResult.SAVED) {
                    committed =
                        app.store.finishCapture(
                            frame,
                            attemptId,
                            System.currentTimeMillis(),
                            if (cameraPhasesDurable) null else "SAVED_WITH_TELEMETRY_FAULT",
                        )
                    frameSaved = true
                } else {
                    app.store.abandon(frame)
                }
            } catch (_: Exception) {
                storageFault = true
                failure = R.string.status_storage_error
                failurePhase = "FINAL_STORE"
            }
            if (!frameSaved && completion.result != CaptureResult.SAVED) {
                try {
                    app.store.finishCaptureAttempt(
                        attemptId,
                        SystemClock.elapsedRealtime(),
                        if (storageFault || completion.result == CaptureResult.STORAGE_FAILURE) {
                            CaptureResult.STORAGE_FAILURE.name
                        } else {
                            CaptureResult.CAMERA_FAILURE.name
                        },
                        failurePhase,
                    )
                } catch (_: Exception) {
                    storageFault = true
                    failure = R.string.status_storage_error
                }
            }
            val summary = if (committed == null) trySummary() else null
            if (committed == null && summary == null) {
                storageFault = true
                failure = R.string.status_storage_error
            }
            app.main.post {
                committed?.let(app::applyCommittedFrame)
                if (summary != null) app.summary = summary
                completed(token, frameSaved && !storageFault, failure)
            }
        }
    }

    private fun trySummary() =
        try {
            app.store.summary(session.id)
        } catch (_: Exception) {
            null
        }

    private fun queueTelemetrySample(
        reason: String,
        thermalStatus: Int? = null,
    ) {
        if (!running) return
        telemetryRequests.offer(TelemetryRequest(reason, thermalStatus))
    }

    private fun writeTelemetrySample(request: TelemetryRequest) {
        if (!running) {
            telemetryRequests.clear()
            return
        }
        val wallMs = System.currentTimeMillis()
        val elapsedMs = SystemClock.elapsedRealtime()
        app.io.execute {
            try {
                app.store.addTelemetrySample(
                    session.id,
                    sampler.sample(request.reason, wallMs, elapsedMs, request.thermalStatus),
                )
                app.main.post { telemetryRequests.complete() }
            } catch (_: Exception) {
                app.main.post {
                    telemetryRequests.clear()
                    if (running) stopRecording(R.string.status_storage_error)
                }
            }
        }
    }

    private fun completed(
        token: Long,
        success: Boolean,
        failure: Int,
    ) {
        outstanding = false
        policy.complete(token, success)
        if (!success && failure == R.string.status_storage_error) app.ready = false
        if (running) {
            if (success) app.status = R.string.status_recording else stopRecording(failure)
        } else {
            if (!success && failure == R.string.status_storage_error && ownsSession) {
                terminalStatus = failure
                app.persistRequest(false, true)
            }
            releaseSession()
        }
        app.publish()
    }

    private fun stopRecording(status: Int) {
        if (ownsSession && status == R.string.status_storage_error) {
            terminalStatus = status
            app.status = status
            app.ready = false
            app.persistRequest(false, true)
        }
        if (ownsSession && running) {
            running = false
            if (terminalStatus != R.string.status_storage_error) terminalStatus = status
            if (runtimeStarted) {
                if (status == R.string.status_paused) policy.pause() else policy.fail()
            }
            releaseCamera()
            if (!app.persistRequest(false, terminalStatus != R.string.status_paused)) terminalStatus = R.string.status_storage_error
            if (terminalStatus == R.string.status_storage_error) app.ready = false
            app.coverText = getString(R.string.cover_unknown)
            app.status = if (outstanding && terminalStatus == R.string.status_paused) R.string.status_stopping else terminalStatus
            if (!outstanding) releaseSession()
            app.publish()
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf(lastHandledStartId)
    }

    private fun releaseCamera() {
        app.main.removeCallbacks(tick)
        telemetryRequests.clear()
        thermalListener?.let {
            try {
                getSystemService(PowerManager::class.java).removeThermalStatusListener(it)
            } catch (_: RuntimeException) {
                // Listener availability is telemetry-only and cannot change the capture outcome.
            }
        }
        thermalListener = null
        try {
            camera?.close()
        } catch (_: RuntimeException) {
            if (terminalStatus != R.string.status_storage_error) terminalStatus = R.string.status_camera_error
        } finally {
            camera = null
            wakeLock?.let { if (it.isHeld) it.release() }
            wakeLock = null
        }
    }

    private fun releaseSession() {
        if (!ownsSession || finalizingSession) return
        finalizingSession = true
        val wallMs = System.currentTimeMillis()
        val elapsedMs = SystemClock.elapsedRealtime()
        val terminalReason = terminalReason(terminalStatus)
        val completionStatus =
            when (terminalStatus) {
                R.string.status_paused -> "COMPLETE"
                R.string.status_interrupted -> "INTERRUPTED"
                else -> "FAILED"
            }
        if (terminalStatus == R.string.status_paused) app.status = R.string.status_stopping
        app.publish()
        app.io.execute {
            try {
                app.store.endCaptureSession(
                    session.id,
                    wallMs,
                    elapsedMs,
                    terminalReason,
                    completionStatus,
                    sampler.sample("END", wallMs, elapsedMs),
                )
                val summary = app.store.summary(session.id)
                app.main.post {
                    app.summary = summary
                    ownsSession = false
                    app.status = terminalStatus
                    app.endSession()
                    app.publish()
                }
            } catch (_: Exception) {
                app.main.post {
                    ownsSession = false
                    app.ready = false
                    app.status = R.string.status_storage_error
                    app.persistRequest(false, true)
                    app.endSession()
                    app.publish()
                }
            }
        }
    }

    private fun terminalReason(status: Int): String =
        when (status) {
            R.string.status_paused -> "USER_PAUSE"
            R.string.status_camera_error -> "CAMERA_FAILURE"
            R.string.status_storage_error -> "STORAGE_FAILURE"
            R.string.status_timeout -> "CAPTURE_TIMEOUT"
            R.string.status_interrupted -> "SERVICE_DESTROYED"
            else -> "RECORDER_FAILURE"
        }

    override fun onDestroy() {
        if (running) stopRecording(R.string.status_interrupted)
        releaseCamera()
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "org.memotrace.recorder.START"
        const val ACTION_PAUSE = "org.memotrace.recorder.PAUSE"
        const val EXTRA_SESSION = "org.memotrace.recorder.SESSION"
        private const val CHANNEL = "recorder"
        private const val WAKE_TIMEOUT_MS = 10 * 60 * 1_000L
        private const val SAMPLE_INTERVAL_MS = 60_000L
    }
}
