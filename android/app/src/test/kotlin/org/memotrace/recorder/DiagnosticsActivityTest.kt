package org.memotrace.recorder

import android.app.Activity
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Intent
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.net.Uri
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.view.View
import android.widget.Button
import android.widget.TextView
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureProfile
import org.memotrace.recorder.storage.DeviceSnapshot
import org.memotrace.recorder.storage.LongRunReportWriter
import org.memotrace.recorder.storage.SessionStart
import org.memotrace.recorder.storage.TelemetrySample
import org.memotrace.recorder.ui.DiagnosticsActivity
import org.memotrace.recorder.ui.TremorButton
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.io.FileNotFoundException
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

private class ReportProvider(
    private val file: File,
    private val opened: CountDownLatch = CountDownLatch(0),
    private val release: CountDownLatch = CountDownLatch(0),
    private val fail: Boolean = false,
) : ContentProvider() {
    override fun onCreate() = true

    override fun getType(uri: Uri) = "application/zip"

    override fun openFile(
        uri: Uri,
        mode: String,
    ): ParcelFileDescriptor {
        opened.countDown()
        check(release.await(5, TimeUnit.SECONDS))
        if (fail) throw FileNotFoundException("synthetic_export_failure")
        return ParcelFileDescriptor.open(
            file,
            ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_WRITE_ONLY,
        )
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun insert(
        uri: Uri,
        values: ContentValues?,
    ): Uri? = null

    override fun delete(
        uri: Uri,
        selection: String?,
        selectionArgs: Array<out String>?,
    ) = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ) = 0
}

private class TestDiagnosticsActivity : DiagnosticsActivity() {
    fun deliverResult(
        resultCode: Int,
        data: Intent?,
    ) = super.onActivityResult(41, resultCode, data)
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class)
class DiagnosticsActivityTest {
    @get:Rule val temporary = TemporaryFolder()
    private lateinit var app: FakeCameraApplication
    private lateinit var sessionId: String

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
        ShadowStatFs.registerStats(app.noBackupFilesDir.path, 1_000_000, 500_000, 500_000)
        settle()
        sessionId = UUID.randomUUID().toString()
        app.io
            .submit {
                val start =
                    SessionStart(
                        sessionId,
                        CaptureProfile.WIDE_90.id,
                        1920,
                        1080,
                        90,
                        "v1;rear;mode=minimizeLatency;cadence=adaptive",
                        1_000,
                        100,
                        DeviceSnapshot("Maker", "Model", "16", 36, "BUILD", "0.3.0", 3),
                    )
                app.store.startCaptureSession(start, sample("START", 100))
                app.store.endCaptureSession(sessionId, 2_000, 200, "USER_PAUSE", "COMPLETE", sample("END", 200))
                app.summary = app.store.summary(sessionId)
            }.get(5, TimeUnit.SECONDS)
    }

    @After fun cleanup() {
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()
    }

    private fun sample(
        reason: String,
        elapsedMs: Long,
    ) = TelemetrySample(1_000 + elapsedMs, elapsedMs, reason, null, null, null, null, null, null, null, null, null, null, null, null, null)

    private fun settle() {
        app.io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
    }

    private fun preparePicker(activity: TestDiagnosticsActivity): Intent {
        activity.findViewById<Button>(R.id.export_report).performClick()
        settle()
        assertFalse(app.canStart)
        assertFalse(activity.findViewById<Button>(R.id.export_report).isEnabled)
        return shadowOf(activity).nextStartedActivity
    }

    private fun awaitStatus(
        activity: TestDiagnosticsActivity,
        expected: Int,
    ) {
        repeat(100) {
            shadowOf(Looper.getMainLooper()).idle()
            if (activity.findViewById<TextView>(R.id.export_status).text == app.getString(expected)) return
            Thread.sleep(10)
        }
        assertEquals(app.getString(expected), activity.findViewById<TextView>(R.id.export_status).text.toString())
    }

    @Test fun reservationBlocksStartBeforePickerAndCancellationOrRecreationReleasesIt() {
        Robolectric.buildActivity(TestDiagnosticsActivity::class.java).setup().use { controller ->
            val activity = controller.get()
            val picker = preparePicker(activity)
            assertEquals(LongRunReportWriter.SUGGESTED_FILENAME, picker.getStringExtra(Intent.EXTRA_TITLE))
            assertFalse(picker.getStringExtra(Intent.EXTRA_TITLE)!!.contains(sessionId))
            assertEquals(null, app.reserveStart())
            activity.deliverResult(Activity.RESULT_CANCELED, null)
            assertEquals(app.getString(R.string.export_cancelled), activity.findViewById<TextView>(R.id.export_status).text.toString())
            assertTrue(app.canStart)

            preparePicker(activity)
            controller.recreate()
            assertTrue(app.canStart)

            preparePicker(controller.get())
            controller.pause().stop().destroy()
            assertTrue(app.canStart)
        }
    }

    @Test fun providerFailureAndSuccessfulCloseReleaseReservationWithLiveAnnouncements() {
        for (failure in listOf(true, false)) {
            val destination = temporary.newFile(if (failure) "failed.zip" else "report.zip")
            val opened = CountDownLatch(1)
            val release = CountDownLatch(1)
            val authority = if (failure) "report.failure" else "report.success"
            ReportProvider(destination, opened, release, failure).also {
                it.attachInfo(app, ProviderInfo().apply { this.authority = authority })
                ShadowContentResolver.registerProviderInternal(authority, it)
            }
            Robolectric.buildActivity(TestDiagnosticsActivity::class.java).setup().use { controller ->
                val activity = controller.get()
                preparePicker(activity)
                val status = activity.findViewById<TextView>(R.id.export_status)
                val details = activity.findViewById<TextView>(R.id.diagnostics_details)
                assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, status.accessibilityLiveRegion)
                assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, details.accessibilityLiveRegion)
                for (id in listOf(R.id.export_report, R.id.diagnostics_close)) {
                    activity.findViewById<Button>(id).let {
                        assertTrue(it is TremorButton)
                        assertTrue(it.minHeight >= 88)
                    }
                }
                activity.deliverResult(
                    Activity.RESULT_OK,
                    Intent().setData(Uri.parse("content://$authority/output")),
                )
                assertTrue(opened.await(5, TimeUnit.SECONDS))
                assertFalse(app.canStart)
                release.countDown()
                awaitStatus(activity, if (failure) R.string.export_failed else R.string.export_complete)
                assertTrue(app.canStart)
                assertEquals(!failure, destination.length() > 0)
            }
        }
    }

    @Test fun destroyedActivityRetainsReservationUntilBlockedProviderWriteCompletes() {
        val destination = temporary.newFile("destroyed-activity-report.zip")
        val opened = CountDownLatch(1)
        val release = CountDownLatch(1)
        val authority = "report.destroyed"
        ReportProvider(destination, opened, release).also {
            it.attachInfo(app, ProviderInfo().apply { this.authority = authority })
            ShadowContentResolver.registerProviderInternal(authority, it)
        }
        try {
            Robolectric.buildActivity(TestDiagnosticsActivity::class.java).setup().use { controller ->
                val activity = controller.get()
                preparePicker(activity)
                activity.deliverResult(
                    Activity.RESULT_OK,
                    Intent().setData(Uri.parse("content://$authority/output")),
                )
                assertTrue(opened.await(5, TimeUnit.SECONDS))
                controller.pause().stop().destroy()
                assertFalse(app.canStart)
                release.countDown()
                repeat(100) {
                    shadowOf(Looper.getMainLooper()).idle()
                    if (app.canStart) return@repeat
                    Thread.sleep(10)
                }
                assertTrue(app.canStart)
                assertTrue(destination.length() > 0)
            }
        } finally {
            release.countDown()
        }
    }
}
