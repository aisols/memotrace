package org.memotrace.recorder

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.Bundle
import android.view.WindowManager
import androidx.test.runner.AndroidJUnitRunner
import androidx.test.runner.lifecycle.ActivityLifecycleCallback
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import org.memotrace.recorder.ui.MainActivity
import java.io.File
import java.util.UUID
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
        var safe = false
        runOnMainSync {
            ActivityLifecycleMonitorRegistry.getInstance().removeLifecycleCallback(screenOnCallback)
            screenOnActivities.forEach { it.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
            screenOnActivities.clear()
            safe = !isolated.sessionOpen
        }
        if (safe) isolated.cleanup()
        super.finish(resultCode, results)
    }
}

class IsolatedRecorderApplication : RecorderApplication() {
    private val testId = UUID.randomUUID().toString()
    override val archiveDirectory get() = File(cacheDir, "instrumentation-$testId")
    override val preferencesName get() = "instrumentation-$testId"

    fun cleanup() {
        io
            .submit {
                if (ready) store.close()
                archiveDirectory.deleteRecursively()
                deleteSharedPreferences(preferencesName)
            }.get(10, TimeUnit.SECONDS)
        io.shutdown()
    }
}
