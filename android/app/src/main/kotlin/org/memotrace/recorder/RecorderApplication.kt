package org.memotrace.recorder

import android.annotation.SuppressLint
import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.lifecycle.LifecycleOwner
import org.memotrace.capture.CaptureConfig
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.capture.CameraXRecorderCamera
import org.memotrace.recorder.capture.RecorderCamera
import org.memotrace.recorder.storage.AndroidMediaDestination
import org.memotrace.recorder.storage.ArchiveSummary
import org.memotrace.recorder.storage.CameraScratch
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.MediaDestination
import java.io.File
import java.util.concurrent.Executors

open class RecorderApplication : Application() {
    protected open val archiveDirectory get() = File(noBackupFilesDir, "recorder")
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
    internal var stopForStorageFailure: (() -> Unit)? = null
    val canStart get() = ready && !sessionOpen && !reconciling

    /** Main-thread acceptance precedes asynchronous service delivery; never persisted/replayed. */
    fun reserveStart(): CaptureSession? {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (!canStart || !publicStorageConsent) return null
        val session = CaptureSession(selectedProfile, System.currentTimeMillis())
        reservedStart = session
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

    protected open fun recoverCameraScratch() = CameraScratch.recover(cacheDir)

    override fun onCreate() {
        super.onCreate()
        val preferences = getSharedPreferences(preferencesName, MODE_PRIVATE)
        selectedProfile = CaptureProfile.fromId(preferences.getString("profile_id", null)) ?: CaptureProfile.DEFAULT
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
                store = FrameStore(archiveDirectory, createDestination())
                recoverCameraScratch()
                store.recover(System.currentTimeMillis())
                val recovered = store.summary()
                main.post {
                    summary = recovered
                    ready = true
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

    @SuppressLint("UseKtx")
    fun selectProfile(id: String): Boolean {
        if (!ready || sessionOpen) return false
        val profile = CaptureProfile.fromId(id) ?: return false
        if (!getSharedPreferences(preferencesName, MODE_PRIVATE).edit().putString("profile_id", id).commit()) {
            status = R.string.status_storage_error
            ready = false
            publish()
            return false
        }
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
}
