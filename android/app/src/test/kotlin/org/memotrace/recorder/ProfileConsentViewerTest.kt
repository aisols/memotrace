package org.memotrace.recorder

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.net.Uri
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.camera.core.AspectRatio
import androidx.camera.core.ImageCapture
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionStrategy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.capture.CameraXRecorderCamera
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.SavedFrame
import org.memotrace.recorder.ui.FrameViewer
import org.memotrace.recorder.ui.JpegViewerActivity
import org.memotrace.recorder.ui.MainActivity
import org.memotrace.recorder.ui.TremorButton
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowAlertDialog
import org.robolectric.shadows.ShadowContentResolver
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class MissingViewerActivity : Activity() {
    override fun startActivity(intent: Intent): Unit = throw ActivityNotFoundException("test")
}

class FailingStartActivity : MainActivity() {
    override fun startForegroundService(service: Intent): ComponentName? = throw IllegalStateException("synthetic_start_failure")
}

class ViewerProvider(
    private val file: File,
    private val opened: CountDownLatch,
    private val release: CountDownLatch,
) : ContentProvider() {
    override fun onCreate() = true

    override fun getType(uri: Uri) = "image/jpeg"

    override fun openFile(
        uri: Uri,
        mode: String,
    ): ParcelFileDescriptor {
        opened.countDown()
        check(release.await(5, TimeUnit.SECONDS))
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class)
class ProfileConsentViewerTest {
    private lateinit var app: FakeCameraApplication

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
        ShadowStatFs.registerStats(app.noBackupFilesDir.path, 1_000_000, 500_000, 500_000)
        settle()
        assertTrue(app.ready)
    }

    private fun settle() {
        app.io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
    }

    @After fun cleanup() {
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()
    }

    @Test fun sixProfilesHaveExplicitCameraXAspectAndLowerThenHigherFallback() {
        for (profile in CaptureProfile.entries) {
            val capture = CameraXRecorderCamera.imageCapture(profile) { it.run() }
            assertEquals(profile.quality, capture.jpegQuality)
            assertEquals(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY, capture.captureMode)
            assertEquals(ImageCapture.OUTPUT_FORMAT_JPEG, capture.outputFormat)
            val selector = CameraXRecorderCamera.resolutionSelector(profile)
            assertEquals(
                if (profile.wide) AspectRatio.RATIO_16_9 else AspectRatio.RATIO_4_3,
                selector.aspectRatioStrategy.preferredAspectRatio,
            )
            assertEquals(AspectRatioStrategy.FALLBACK_RULE_AUTO, selector.aspectRatioStrategy.fallbackRule)
            assertEquals(profile.width, selector.resolutionStrategy!!.boundSize!!.width)
            assertEquals(profile.height, selector.resolutionStrategy!!.boundSize!!.height)
            assertEquals(ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER, selector.resolutionStrategy!!.fallbackRule)
        }
    }

    @Test fun firstStartRequiresExplicitAccessibleConsentAndCancelDoesNotStart() {
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        assertFalse(app.publicStorageConsent)
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            settle()
            val start = controller.get().findViewById<Button>(R.id.start_recording)
            start.performClick()
            val cancelled = ShadowAlertDialog.getLatestAlertDialog()
            assertTrue(cancelled.findViewById<Button>(R.id.consent_accept) is TremorButton)
            cancelled.findViewById<Button>(R.id.dialog_cancel).performClick()
            assertNull(shadowOf(app).nextStartedService)
            assertFalse(app.publicStorageConsent)
            start.performClick()
            ShadowAlertDialog.getLatestAlertDialog().findViewById<Button>(R.id.consent_accept).performClick()
            assertTrue(app.publicStorageConsent)
            assertEquals(RecorderService.ACTION_START, shadowOf(app).nextStartedService.action)
            assertTrue(app.getSharedPreferences("record_state", 0).getBoolean("public_pictures_consent_v1", false))
        }
    }

    @Test fun serviceCannotBypassPublicConsent() {
        val service = Robolectric.buildService(RecorderService::class.java).create()
        try {
            service.get().onStartCommand(Intent(app, RecorderService::class.java).setAction(RecorderService.ACTION_START), 0, 1)
            assertFalse(app.sessionOpen)
            assertEquals(0, app.fake.calls)
        } finally {
            service.destroy()
        }
    }

    @Test fun fixedProfileMigrationOverridesPersistedQ80AndQ95WhileConsentSurvives() {
        assertFalse(app.selectProfile("../bad"))
        assertTrue(app.consentToPublicPictures())
        for (persisted in listOf(CaptureProfile.WIDE_80, CaptureProfile.REFERENCE)) {
            assertTrue(
                app
                    .getSharedPreferences("record_state", 0)
                    .edit()
                    .putString("profile_id", persisted.id)
                    .remove("fixed_profile_revision")
                    .commit(),
            )
            val restarted =
                object : FakeCameraApplicationForRestart() {}.apply {
                    attach(app.baseContext)
                    onCreate()
                }
            restarted.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            assertEquals(CaptureProfile.WIDE_90, restarted.selectedProfile)
            assertEquals(
                CaptureProfile.WIDE_90.id,
                restarted.getSharedPreferences("record_state", 0).getString("profile_id", null),
            )
            assertEquals(
                RecorderApplication.FIXED_PROFILE_REVISION,
                restarted.getSharedPreferences("record_state", 0).getInt("fixed_profile_revision", 0),
            )
            assertTrue(restarted.publicStorageConsent)
            assertFalse(restarted.sessionOpen)
            restarted.io.submit { restarted.store.close() }.get(5, TimeUnit.SECONDS)
            restarted.io.shutdown()
        }
    }

    @Test fun normalMainHasNoProfileSelectorAndProgrammaticSeamRejectsBusySession() {
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            assertNull(controller.get().findViewById<Button>(R.id.select_profile))
            assertEquals(
                app.getString(R.string.fixed_profile),
                controller
                    .get()
                    .findViewById<TextView>(R.id.fixed_profile)
                    .text
                    .toString(),
            )
            app.sessionOpen = true
            app.publish()
            assertFalse(app.selectProfile(CaptureProfile.REFERENCE.id))
            assertEquals(CaptureProfile.WIDE_90, app.selectedProfile)
            app.sessionOpen = false
        }
    }

    @Test fun serviceLaunchFailureReleasesReservationAndAllowsProfileChange() {
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        assertTrue(app.consentToPublicPictures())
        Robolectric.buildActivity(FailingStartActivity::class.java).setup().use {
            settle()
            it.get().findViewById<Button>(R.id.start_recording).performClick()
            assertFalse(app.sessionOpen)
            assertTrue(app.canStart)
            assertEquals(R.string.status_camera_error, app.status)
            assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        }
    }

    @Test fun processRestartCannotConsumeOldReservation() {
        assertTrue(app.consentToPublicPictures())
        val reserved = checkNotNull(app.reserveStart())
        val restarted =
            FakeCameraApplicationForRestart().apply {
                attach(app.baseContext)
                onCreate()
            }
        try {
            restarted.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            assertNull(restarted.consumeStart(reserved.id))
            assertFalse(restarted.sessionOpen)
        } finally {
            restarted.io.submit { restarted.store.close() }.get(5, TimeUnit.SECONDS)
            restarted.io.shutdown()
            app.cancelStart(reserved.id)
        }
    }

    @Test fun viewerUsesOnlyExplicitInternalIntentWithoutUriGrants() {
        val saved = SavedFrame("content://media/external_primary/images/media/42", "Pictures/test/", 123, 16, 12, Availability.AVAILABLE)
        val intent = FrameViewer.intent(saved)!!
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals("image/jpeg", intent.type)
        assertEquals(saved.uri, intent.data.toString())
        assertEquals(0, intent.flags)
        assertNull(intent.clipData)
        assertEquals(JpegViewerActivity::class.java.name, intent.component!!.className)
        for (status in Availability.entries.filter { it != Availability.AVAILABLE }) {
            assertNull(FrameViewer.intent(SavedFrame(saved.uri, saved.path, 123, 16, 12, status)))
        }
        assertNull(FrameViewer.intent(null))
        assertNull(FrameViewer.intent(SavedFrame("file:///private.jpg", null, null, null, null, Availability.AVAILABLE)))
        Robolectric.buildActivity(MissingViewerActivity::class.java).setup().use { assertFalse(FrameViewer.open(it.get(), saved)) }
        Robolectric.buildActivity(Activity::class.java).setup().use {
            assertTrue(FrameViewer.open(it.get(), saved))
            val opened = shadowOf(it.get()).nextStartedActivity
            assertEquals(saved.uri, opened.data.toString())
            assertEquals(JpegViewerActivity::class.java.name, opened.component!!.className)
        }
    }

    @Test fun internalViewerRejectsMalformedOrGrantedUrisAndShowsAccessibleErrorClose() {
        for (uri in listOf("file:///private.jpg", "content://other/external_primary/images/media/1", "content://media/x/video/media/1")) {
            assertFalse(JpegViewerActivity.isMediaImageUri(android.net.Uri.parse(uri)))
        }
        val granted =
            Intent(Intent.ACTION_VIEW, android.net.Uri.parse("content://media/external_primary/images/media/1"))
                .setClass(app, JpegViewerActivity::class.java)
                .setType("image/jpeg")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        Robolectric.buildActivity(JpegViewerActivity::class.java, granted).setup().use {
            assertEquals(
                app.getString(R.string.viewer_error),
                it
                    .get()
                    .findViewById<TextView>(R.id.viewer_status)
                    .text
                    .toString(),
            )
            val close = it.get().findViewById<Button>(R.id.viewer_close)
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, it.get().findViewById<TextView>(R.id.viewer_status).accessibilityLiveRegion)
            assertTrue(close is TremorButton)
            assertTrue(close.minHeight >= 88)
        }
        val info = app.packageManager.getActivityInfo(ComponentName(app, JpegViewerActivity::class.java), 0)
        assertFalse(info.exported)
    }

    @Test fun viewerDecodeUsesSeparateWorkerAndKeepsFitMode() {
        val session = CaptureSession(CaptureProfile.WIDE_90, 1_000)
        val saved =
            app.io
                .submit<SavedFrame> {
                    val frame =
                        app.store.prepare(
                            FrameRequest(1_000, 100, 2_000, "settings", "SHADOW;unknown", session, 1920, 1080),
                        )
                    frame.output.stream.write(syntheticJpeg())
                    app.store.finish(frame, 2_000)
                    app.store.summary().last!!
                }.get(5, TimeUnit.SECONDS)
        val file = File(app.cacheDir, "viewer-test.jpg").apply { writeBytes(syntheticJpeg()) }
        val opened = CountDownLatch(1)
        val release = CountDownLatch(1)
        val provider =
            ViewerProvider(file, opened, release).apply {
                attachInfo(app, ProviderInfo().apply { authority = "media" })
            }
        ShadowContentResolver.registerProviderInternal("media", provider)
        val controller = Robolectric.buildActivity(JpegViewerActivity::class.java, FrameViewer.intent(saved)).setup()
        try {
            settle()
            assertTrue(opened.await(5, TimeUnit.SECONDS))
            app.io.submit {}.get(1, TimeUnit.SECONDS)
            release.countDown()
            for (attempt in 0 until 50) {
                shadowOf(Looper.getMainLooper()).idle()
                if (controller.get().findViewById<TextView>(R.id.viewer_status).text != app.getString(R.string.viewer_loading)) break
                Thread.sleep(20)
            }
            val image = controller.get().findViewById<ImageView>(R.id.viewer_image)
            val status =
                controller
                    .get()
                    .findViewById<TextView>(R.id.viewer_status)
                    .text
                    .toString()
            assertTrue(status != app.getString(R.string.viewer_loading))
            if (image.drawable == null) assertEquals(app.getString(R.string.viewer_error), status)
            assertEquals(ImageView.ScaleType.FIT_CENTER, image.scaleType)
        } finally {
            release.countDown()
            controller.close()
            file.delete()
        }
    }
}

open class FakeCameraApplicationForRestart : RecorderApplication() {
    override fun createDestination() = FakeMediaDestination()

    fun attach(context: Context) = attachBaseContext(context)
}
