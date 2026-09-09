package org.memotrace.recorder

import android.annotation.SuppressLint
import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.lifecycle.LifecycleOwner
import org.memotrace.capture.CaptureConfig
import org.memotrace.recorder.capture.CameraXRecorderCamera
import org.memotrace.recorder.capture.RecorderCamera
import org.memotrace.recorder.storage.ArchiveSummary
import org.memotrace.recorder.storage.FrameStore
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
    var status = R.string.status_loading
    var intervalMs = 2_000L
    var coverText = ""
    var summary = ArchiveSummary(0, null)
    private val observers = mutableSetOf<() -> Unit>()

    open fun createCamera(
        owner: LifecycleOwner,
        config: CaptureConfig,
    ): RecorderCamera = CameraXRecorderCamera(this, owner, config)

    override fun onCreate() {
        super.onCreate()
        val preferences = getSharedPreferences(preferencesName, MODE_PRIVATE)
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
                store = FrameStore(archiveDirectory)
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
