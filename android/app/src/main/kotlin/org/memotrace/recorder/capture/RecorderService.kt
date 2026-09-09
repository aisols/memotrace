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
import androidx.lifecycle.LifecycleService
import org.memotrace.capture.CapturePolicy
import org.memotrace.capture.LumaMetrics
import org.memotrace.recorder.R
import org.memotrace.recorder.RecorderApplication
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.PendingFrame
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
    private var terminalStatus = R.string.status_paused
    private val sessionId = UUID.randomUUID().toString()

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_PAUSE) {
            stopRecording(R.string.status_paused)
            return START_NOT_STICKY
        }
        if (running) return START_NOT_STICKY
        if (intent?.action != ACTION_START) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (!app.ready || app.sessionOpen) {
            stopSelf()
            return START_NOT_STICKY
        }
        ownsSession = true
        app.sessionOpen = true
        running = true
        opened = false
        lastMetrics = null
        terminalStatus = R.string.status_paused
        app.status = R.string.status_starting
        app.coverText = getString(R.string.cover_unknown)
        try {
            showNotification()
            check(app.persistRequest(true)) { "record_state_write" }
            policy.start()
            startedAt = SystemClock.elapsedRealtime()
            wakeLock =
                getSystemService(PowerManager::class.java)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MemoTrace:recorder")
                    .apply {
                        setReferenceCounted(false)
                        acquire(WAKE_TIMEOUT_MS)
                    }
            renewedAt = startedAt
            camera = app.createCamera(this, policy.config)
            camera?.start(
                onReady = { if (running) opened = true },
                onError = { if (running) stopRecording(R.string.status_camera_error) },
            )
            app.main.post(tick)
        } catch (_: Exception) {
            stopRecording(R.string.status_camera_error)
        }
        app.publish()
        return START_NOT_STICKY
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
                Intent(this, RecorderService::class.java).setAction(ACTION_PAUSE),
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
                if (opened) policy.request(now)?.let { acquire(it, now) }
                app.publish()
                app.main.postDelayed(this, 100)
            }
        }

    private fun acquire(
        token: Long,
        elapsedMs: Long,
    ) {
        outstanding = true
        val config = policy.config
        val request =
            FrameRequest(
                System.currentTimeMillis(),
                elapsedMs,
                policy.intervalMs,
                "v1;session=$sessionId;rear;jpegQuality=95;mode=minimizeLatency;baselineMs=${config.baselineMs};" +
                    "motionMs=${config.motionMs};enter=${config.motionEnter};exit=${config.motionExit};" +
                    "quietMs=${config.quietMs};analysisMs=${config.analysisMs}",
                lastMetrics?.takeIf { elapsedMs - it.first <= 2_000 }?.let {
                    "v1;SHADOW;suspected=${it.second.coverSuspected};mean=${it.second.mean};" +
                        "variance=${it.second.variance};analysisElapsedMs=${it.first}"
                } ?: "v1;SHADOW;unknown",
            )
        app.io.execute {
            try {
                val frame = app.store.prepare(request)
                app.main.post {
                    if (!running) {
                        persistResult(token, frame, CaptureResult.CAMERA_FAILURE)
                    } else {
                        var delivered = false

                        fun accept(result: CaptureResult) {
                            if (delivered) return
                            delivered = true
                            persistResult(token, frame, result)
                        }
                        try {
                            checkNotNull(camera).capture(frame.partial, ::accept)
                        } catch (_: Exception) {
                            accept(CaptureResult.CAMERA_FAILURE)
                        }
                    }
                }
            } catch (_: Exception) {
                app.main.post { completed(token, false, R.string.status_storage_error) }
            }
        }
    }

    private fun persistResult(
        token: Long,
        frame: PendingFrame,
        result: CaptureResult,
    ) {
        app.io.execute {
            var success = result == CaptureResult.SAVED
            var failure = if (result == CaptureResult.STORAGE_FAILURE) R.string.status_storage_error else R.string.status_camera_error
            try {
                if (success) app.store.finish(frame, System.currentTimeMillis()) else app.store.abandon(frame)
            } catch (_: Exception) {
                success = false
                failure = R.string.status_storage_error
            }
            val summary =
                try {
                    app.store.summary()
                } catch (_: Exception) {
                    success = false
                    failure = R.string.status_storage_error
                    null
                }
            app.main.post {
                if (summary != null) app.summary = summary
                completed(token, success, failure)
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
        if (ownsSession && running) {
            running = false
            terminalStatus = status
            if (status == R.string.status_paused) policy.pause() else policy.fail()
            releaseCamera()
            if (!app.persistRequest(false, terminalStatus != R.string.status_paused)) terminalStatus = R.string.status_storage_error
            if (terminalStatus == R.string.status_storage_error) app.ready = false
            app.coverText = getString(R.string.cover_unknown)
            app.status = if (outstanding && terminalStatus == R.string.status_paused) R.string.status_stopping else terminalStatus
            if (!outstanding) releaseSession()
            app.publish()
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun releaseCamera() {
        app.main.removeCallbacks(tick)
        try {
            camera?.close()
        } catch (_: RuntimeException) {
            terminalStatus = R.string.status_camera_error
        } finally {
            camera = null
            wakeLock?.let { if (it.isHeld) it.release() }
            wakeLock = null
        }
    }

    private fun releaseSession() {
        if (!ownsSession) return
        ownsSession = false
        app.sessionOpen = false
        app.status = terminalStatus
    }

    override fun onDestroy() {
        if (running) stopRecording(R.string.status_interrupted)
        releaseCamera()
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "org.memotrace.recorder.START"
        const val ACTION_PAUSE = "org.memotrace.recorder.PAUSE"
        private const val CHANNEL = "recorder"
        private const val WAKE_TIMEOUT_MS = 10 * 60 * 1_000L
    }
}
