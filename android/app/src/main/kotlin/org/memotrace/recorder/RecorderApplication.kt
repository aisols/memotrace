package org.memotrace.recorder

import android.annotation.SuppressLint
import android.app.Application
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.lifecycle.LifecycleOwner
import org.memotrace.capture.CaptureConfig
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.capture.CameraXRecorderCamera
import org.memotrace.recorder.capture.RecorderCamera
import org.memotrace.recorder.storage.AndroidMediaDestination
import org.memotrace.recorder.storage.ArchiveSummary
import org.memotrace.recorder.storage.CameraScratch
import org.memotrace.recorder.storage.CommittedFrame
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.LongRunReport
import org.memotrace.recorder.storage.MediaDestination
import org.memotrace.recorder.storage.SessionDiagnostics
import org.memotrace.recorder.storage.ViewerFrame
import java.io.File
import java.util.concurrent.Executors

open class RecorderApplication : Application() {
    protected open val archiveDirectory get() = File(noBackupFilesDir, "recorder")
    internal val telemetryRoot get() = archiveDirectory
    protected open val preferencesName get() = "record_state"
    val io = Executors.newSingleThreadExecutor()
    val main = Handler(Looper.getMainLooper())
    lateinit var store: FrameStore
        private set
    var ready = false
        internal set
    var sessionOpen = false
    var sessionId: String? = null
        private set
    var selectedProfile = CaptureProfile.DEFAULT
        private set
    var publicStorageConsent = false
        private set
    var sessionPath = ""
    var negotiatedSize = ""
    var status = R.string.status_loading
    var intervalMs = 2_000L
    var coverText = ""
    var summary = ArchiveSummary(0, null)
    private val observers = mutableSetOf<() -> Unit>()
    private var reservedStart: CaptureSession? = null
    private var exportReservation: Long? = null
    private var nextExportReservation = 0L
    private var previousSessionCount = 0L
    internal var stopForStorageFailure: (() -> Unit)? = null
    val canStart get() = ready && !sessionOpen && !reconciling && exportReservation == null
    val canExport get() = ready && !sessionOpen && !reconciling && exportReservation == null

    /** Main-thread acceptance precedes asynchronous service delivery; never persisted/replayed. */
    fun reserveStart(): CaptureSession? {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (!canStart || !publicStorageConsent) return null
        val session = CaptureSession(selectedProfile, System.currentTimeMillis())
        reservedStart = session
        previousSessionCount = summary.sessionCount
        summary = ArchiveSummary(summary.count, summary.lastSavedMs, summary.last, summary.quarantinedCount, 0)
        sessionId = session.id
        sessionOpen = true
        status = R.string.status_starting
        publish()
        return session
    }

    internal fun consumeStart(id: String?): CaptureSession? {
        val session = reservedStart ?: return null
        if (!ready || !publicStorageConsent || session.id != id) return null
        reservedStart = null
        return session
    }

    fun cancelStart(
        id: String? = reservedStart?.id,
        status: Int = R.string.status_paused,
    ): Boolean {
        if (reservedStart == null || reservedStart?.id != id) return false
        reservedStart = null
        summary = ArchiveSummary(summary.count, summary.lastSavedMs, summary.last, summary.quarantinedCount, previousSessionCount)
        this.status = status
        endSession()
        publish()
        return true
    }

    internal fun endSession() {
        stopForStorageFailure = null
        sessionOpen = false
        sessionId = null
        if (refreshDeferred && ready) refreshAvailability()
    }

    private fun failStorage() {
        ready = false
        status = R.string.status_storage_error
        cancelStart(status = R.string.status_storage_error)
        stopForStorageFailure?.invoke()
    }

    open fun createCamera(
        owner: LifecycleOwner,
        config: CaptureConfig,
        profile: CaptureProfile,
    ): RecorderCamera = CameraXRecorderCamera(this, owner, config, profile)

    open fun createDestination(): MediaDestination = AndroidMediaDestination(this)

    protected open fun createStore(): FrameStore = FrameStore(archiveDirectory, createDestination())

    protected open fun recoverCameraScratch() = CameraScratch.recover(cacheDir)

    // The profile revision and ID must reach storage together before an ordinary Start can be enabled.
    @SuppressLint("ApplySharedPref", "UseKtx")
    override fun onCreate() {
        super.onCreate()
        val preferences = getSharedPreferences(preferencesName, MODE_PRIVATE)
        val profileReady =
            if (preferences.getInt("fixed_profile_revision", 0) < FIXED_PROFILE_REVISION) {
                preferences
                    .edit()
                    .putString("profile_id", CaptureProfile.WIDE_90.id)
                    .putInt("fixed_profile_revision", FIXED_PROFILE_REVISION)
                    .commit()
            } else {
                true
            }
        selectedProfile = CaptureProfile.WIDE_90
        publicStorageConsent = preferences.getBoolean("public_pictures_consent_v1", false)
        status =
            if (preferences.getBoolean("requested", false)) {
                R.string.status_interrupted
            } else {
                preferences.getInt("status", 0).let {
                    // Resource integers are not stable across versions; persisted status uses a code below.
                    if (it == 1) R.string.status_error else R.string.status_paused
                }
            }
        io.execute {
            try {
                store = createStore()
                recoverCameraScratch()
                store.recover(System.currentTimeMillis())
                val interrupted = store.recoverOpenSessions(System.currentTimeMillis())
                val recovered = store.summary()
                main.post {
                    summary = recovered
                    if (interrupted > 0) status = R.string.status_interrupted
                    ready = profileReady
                    if (!profileReady) status = R.string.status_storage_error
                    publish()
                }
            } catch (_: Exception) {
                main.post {
                    status = R.string.status_storage_error
                    publish()
                }
            }
        }
    }

    // KTX edit returns Unit and would discard the durable commit failure signal.
    @SuppressLint("UseKtx")
    fun persistRequest(
        record: Boolean,
        error: Boolean = false,
    ): Boolean =
        getSharedPreferences(preferencesName, MODE_PRIVATE)
            .edit()
            .putBoolean("requested", record)
            .putInt("status", if (error) 1 else 0)
            .commit()

    fun selectProfile(id: String): Boolean {
        if (!ready || sessionOpen) return false
        val profile = CaptureProfile.fromId(id) ?: return false
        selectedProfile = profile
        publish()
        return true
    }

    @SuppressLint("UseKtx")
    fun consentToPublicPictures(): Boolean {
        if (!ready || sessionOpen) return false
        publicStorageConsent =
            getSharedPreferences(preferencesName, MODE_PRIVATE).edit().putBoolean("public_pictures_consent_v1", true).commit()
        if (!publicStorageConsent) {
            status = R.string.status_storage_error
            ready = false
        }
        publish()
        return publicStorageConsent
    }

    private var reconciling = false
    private var viewing = false
    private var refreshDeferred = false

    fun refreshAvailability(
        lastOnly: Boolean = false,
        complete: () -> Unit = {},
    ) {
        if (!ready || (if (lastOnly) viewing else reconciling)) return
        if (!lastOnly && sessionOpen) {
            refreshDeferred = true
            return
        }
        if (!lastOnly) refreshDeferred = false
        if (lastOnly) viewing = true else reconciling = true
        publish()
        io.execute {
            val refreshed =
                try {
                    store.reconcile(lastOnly)
                    store.summary()
                } catch (_: Exception) {
                    null
                }
            main.post {
                if (lastOnly) viewing = false else reconciling = false
                if (refreshed != null) {
                    summary = refreshed
                } else {
                    failStorage()
                }
                publish()
                complete()
            }
        }
    }

    internal fun applyCommittedFrame(committed: CommittedFrame) {
        check(Looper.myLooper() == Looper.getMainLooper())
        summary =
            ArchiveSummary(
                summary.count + 1,
                committed.savedWallMs,
                committed.frame,
                summary.quarantinedCount,
                summary.sessionCount + 1,
            )
    }

    open fun loadDiagnostics(complete: (SessionDiagnostics?) -> Unit) {
        if (!ready) {
            complete(null)
            return
        }
        val preferred = sessionId
        io.execute {
            var failed = false
            val result =
                try {
                    store.diagnostics(preferred, SystemClock.elapsedRealtime())
                } catch (_: Exception) {
                    failed = true
                    null
                }
            main.post {
                if (failed) failStorage()
                complete(result)
            }
        }
    }

    fun reserveExport(): Long? {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (!canExport) return null
        val reservation = ++nextExportReservation
        exportReservation = reservation
        publish()
        return reservation
    }

    fun ownsExport(reservation: Long): Boolean = exportReservation == reservation

    fun releaseExport(reservation: Long) {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (exportReservation != reservation) return
        exportReservation = null
        publish()
    }

    fun loadReport(
        reservation: Long,
        complete: (LongRunReport?) -> Unit,
    ) {
        if (!ownsExport(reservation) || !ready || sessionOpen || reconciling) {
            complete(null)
            return
        }
        io.execute {
            var failed = false
            val result =
                try {
                    store.report(null)
                } catch (_: Exception) {
                    failed = true
                    null
                }
            main.post {
                if (failed) failStorage()
                complete(result.takeIf { ownsExport(reservation) })
            }
        }
    }

    fun validateViewer(
        uri: String,
        complete: (ViewerFrame?) -> Unit,
    ) {
        if (!ready) {
            complete(null)
            return
        }
        io.execute {
            var failed = false
            val result =
                try {
                    store.viewerFrame(uri)
                } catch (_: Exception) {
                    failed = true
                    null
                }
            main.post {
                if (failed) failStorage()
                complete(result)
            }
        }
    }

    fun observe(observer: () -> Unit) {
        observers.add(observer)
        observer()
    }

    fun removeObserver(observer: () -> Unit) {
        observers.remove(observer)
    }

    fun publish() {
        observers.toList().forEach { it() }
    }

    companion object {
        const val FIXED_PROFILE_REVISION = 1
    }
}
