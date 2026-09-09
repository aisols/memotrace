package org.memotrace.recorder

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import androidx.test.runner.AndroidJUnitRunner
import androidx.test.runner.lifecycle.ActivityLifecycleCallback
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import org.memotrace.recorder.ui.MainActivity
import java.io.File
import java.util.UUID
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit

class IsolatedTestRunner : AndroidJUnitRunner() {
    private lateinit var isolated: IsolatedRecorderApplication
    private val screenOnActivities = mutableSetOf<Activity>()
    private val screenOnCallback =
        ActivityLifecycleCallback { activity, stage ->
            if (activity is MainActivity) {
                when (stage) {
                    Stage.STARTED -> {
                        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                        screenOnActivities.add(activity)
                    }
                    Stage.STOPPED, Stage.DESTROYED -> {
                        activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                        screenOnActivities.remove(activity)
                    }
                    else -> Unit
                }
            }
        }

    override fun onStart() {
        runOnMainSync {
            ActivityLifecycleMonitorRegistry.getInstance().addLifecycleCallback(screenOnCallback)
        }
        super.onStart()
    }

    override fun newApplication(
        cl: ClassLoader,
        className: String,
        context: Context,
    ): Application =
        super.newApplication(cl, IsolatedRecorderApplication::class.java.name, context).also {
            isolated = it as IsolatedRecorderApplication
        }

    override fun finish(
        resultCode: Int,
        results: Bundle?,
    ) {
        val report = results ?: Bundle()
        var code = resultCode
        try {
            var safe = false
            runOnMainSync {
                ActivityLifecycleMonitorRegistry.getInstance().removeLifecycleCallback(screenOnCallback)
                screenOnActivities.forEach { it.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
                screenOnActivities.clear()
                safe = !isolated.sessionOpen
            }
            if (safe) {
                val retained = isolated.cleanup()
                report.putStringArrayList("memotrace.cleanup.unresolved", ArrayList(retained.map { it.description }))
                if (retained.isNotEmpty()) {
                    report.putString("stream", report.getString("stream", "") + "\n" + retained.joinToString("\n") { it.description })
                }
            } else {
                val message = "Fixture cleanup blocked: active session/writer not drained; no deletion attempted"
                report.putStringArrayList("memotrace.cleanup.unresolved", arrayListOf(message))
                report.putString("shortMsg", listOfNotNull(report.getString("shortMsg"), message).joinToString("\n"))
                Log.e("MemoTraceTest", message)
                code = Activity.RESULT_CANCELED
            }
        } catch (failure: Exception) {
            // Expected uncertainty is returned above. Real identity/provider/DB/close failures remain run failures.
            val cause = if (failure is ExecutionException) failure.cause ?: failure else failure
            val message = "Fixture cleanup FAILED: $cause"
            Log.e("MemoTraceTest", message, cause)
            report.putString("shortMsg", listOfNotNull(report.getString("shortMsg"), message).joinToString("\n"))
            report.putString("memotrace.cleanup.error", cause.stackTraceToString())
            report.putString("stream", report.getString("stream", "") + "\n" + message)
            code = Activity.RESULT_CANCELED
        } finally {
            super.finish(code, report)
        }
    }
}

class IsolatedRecorderApplication : RecorderApplication() {
    private val testId = UUID.randomUUID().toString()
    private val media by lazy { TestMediaNamespace(this, testId) }
    override val archiveDirectory get() = File(cacheDir, "instrumentation-$testId")
    override val preferencesName get() = "instrumentation-$testId"

    override fun createDestination() = media.destination

    // Never remove scratch from an earlier normal app run during instrumentation.
    override fun recoverCameraScratch() = Unit

    fun cleanup(): List<CleanupResidue> {
        try {
            return io
                .submit<List<CleanupResidue>> {
                    try {
                        store.close()
                    } catch (_: UninitializedPropertyAccessException) {
                        // Startup failed before a store existed.
                    }
                    val retained = media.cleanup()
                    if (retained.isEmpty()) {
                        check(archiveDirectory.deleteRecursively())
                        check(deleteSharedPreferences(preferencesName))
                    }
                    retained
                }.get(10, TimeUnit.SECONDS)
        } finally {
            io.shutdown()
        }
    }
}
