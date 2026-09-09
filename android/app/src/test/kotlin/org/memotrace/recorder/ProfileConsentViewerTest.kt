package org.memotrace.recorder

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Looper
import android.widget.Button
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
import org.memotrace.recorder.capture.CameraXRecorderCamera
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.SavedFrame
import org.memotrace.recorder.ui.FrameViewer
import org.memotrace.recorder.ui.MainActivity
import org.memotrace.recorder.ui.TremorButton
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowAlertDialog
import java.util.concurrent.TimeUnit

class MissingViewerActivity : Activity() {
    override fun startActivity(intent: Intent): Unit = throw ActivityNotFoundException("test")
}

class FailingStartActivity : MainActivity() {
    override fun startForegroundService(service: Intent): ComponentName? = throw IllegalStateException("synthetic_start_failure")
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class)
class ProfileConsentViewerTest {
    private lateinit var app: FakeCameraApplication

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
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

    @Test fun persistedProfileAndConsentSurviveNewApplicationAndInvalidIdIsRejected() {
        assertTrue(app.selectProfile(CaptureProfile.WIDE_80.id))
        assertFalse(app.selectProfile("../bad"))
        assertTrue(app.consentToPublicPictures())
        val restarted =
            object : FakeCameraApplicationForRestart() {}.apply {
                attach(app.baseContext)
                onCreate()
            }
        restarted.io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
        assertEquals(CaptureProfile.WIDE_80, restarted.selectedProfile)
        assertTrue(restarted.publicStorageConsent)
        assertFalse(restarted.sessionOpen)
        restarted.io.submit { restarted.store.close() }.get(5, TimeUnit.SECONDS)
        restarted.io.shutdown()
    }

    @Test fun staleProfileDialogCannotChangeBusySession() {
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            controller.get().findViewById<Button>(R.id.select_profile).performClick()
            val dialog = ShadowAlertDialog.getLatestAlertDialog()
            app.sessionOpen = true
            app.publish()
            assertFalse(controller.get().findViewById<Button>(R.id.select_profile).isEnabled)
            dialog.findViewById<Button>(R.id.profile_reference).performClick()
            assertEquals(CaptureProfile.DEFAULT, app.selectedProfile)
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

    @Test fun viewerOnlyGrantsReadToOneContentUriAndHandlesUnavailableViewer() {
        val saved = SavedFrame("content://media/external_primary/images/media/42", "Pictures/test/", 123, 16, 12, Availability.AVAILABLE)
        val intent = FrameViewer.intent(saved)!!
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals("image/jpeg", intent.type)
        assertEquals(saved.uri, intent.data.toString())
        assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, intent.flags)
        assertEquals(intent.data, intent.clipData!!.getItemAt(0).uri)
        for (status in Availability.entries.filter { it != Availability.AVAILABLE }) {
            assertNull(FrameViewer.intent(SavedFrame(saved.uri, saved.path, 123, 16, 12, status)))
        }
        assertNull(FrameViewer.intent(null))
        assertNull(FrameViewer.intent(SavedFrame("file:///private.jpg", null, null, null, null, Availability.AVAILABLE)))
        Robolectric.buildActivity(MissingViewerActivity::class.java).setup().use { assertFalse(FrameViewer.open(it.get(), saved)) }
        Robolectric.buildActivity(Activity::class.java).setup().use {
            assertTrue(FrameViewer.open(it.get(), saved))
            assertEquals(saved.uri, shadowOf(it.get()).nextStartedActivity.data.toString())
        }
    }
}

open class FakeCameraApplicationForRestart : RecorderApplication() {
    override fun createDestination() = FakeMediaDestination()

    fun attach(context: Context) = attachBaseContext(context)
}
