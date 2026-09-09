package org.memotrace.recorder

import android.Manifest
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.ScrollView
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isEnabled
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.ui.MainActivity
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

@RunWith(AndroidJUnit4::class)
class RecorderDeviceTest {
    @get:Rule val permissions: GrantPermissionRule =
        GrantPermissionRule.grant(
            Manifest.permission.CAMERA,
            Manifest.permission.POST_NOTIFICATIONS,
        )

    private fun awaitState(
        description: String = "recorder state",
        predicate: () -> Boolean,
    ) {
        val instrument = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + 45_000_000_000L
        val done = AtomicBoolean(false)
        var diagnostic = ""
        while (System.nanoTime() < deadline) {
            instrument.runOnMainSync {
                done.set(predicate())
                val app = instrument.targetContext.applicationContext as RecorderApplication
                diagnostic = "ready=${app.ready}; sessionOpen=${app.sessionOpen}; canStart=${app.canStart}; " +
                    "status=${app.getString(app.status)}; saved=${app.summary.count}; quarantined=${app.summary.quarantinedCount}"
            }
            if (done.get()) return
            Thread.sleep(25)
        }
        throw AssertionError("Timed out waiting for $description within 45 seconds: $diagnostic")
    }

    private fun accessibilityClick(
        activity: MainActivity,
        id: Int,
    ) {
        val button = activity.findViewById<Button>(id)
        activity.findViewById<ScrollView>(R.id.recorder_scroll).scrollTo(0, button.top)
        var ancestor: View? = button
        while (ancestor != null) {
            assertEquals(View.VISIBLE, ancestor.visibility)
            assertTrue(ancestor.alpha > 0)
            assertTrue(ancestor.importantForAccessibility != View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS)
            ancestor = ancestor.parent as? View
        }
        val node = button.createAccessibilityNodeInfo()
        assertEquals(Button::class.java.name, node.className.toString())
        assertTrue(node.isEnabled && node.isClickable && node.isVisibleToUser)
        assertTrue(node.actionList.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK))
        assertEquals(button.text.toString(), node.text.toString())
        assertTrue(button.performAccessibilityAction(AccessibilityNodeInfo.ACTION_CLICK, null))
    }

    @Test fun storageRoundTripRecoveryAndShadowRetention() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val root = File(context.cacheDir, "storage-test-${UUID.randomUUID()}")
        val media = TestMediaNamespace(context)
        try {
            var uri = ""
            val bitmap = Bitmap.createBitmap(16, 16, Bitmap.Config.ARGB_8888)
            val session = CaptureSession(CaptureProfile.REFERENCE, 123)
            FrameStore(root, media.destination, checkpoint = { if (it == "published") error("simulated_death") }).use { store ->
                val frame = store.prepare(FrameRequest(123, 456, 1_000, "rear;quality=95", "SHADOW;true", session, 16, 16))
                uri = frame.uri
                assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 95, frame.output.stream))
                assertThrows(IllegalStateException::class.java) { store.finish(frame, 789) }
            }
            bitmap.recycle()
            val original = media.destination.openRead(uri).use { it.readBytes() }
            assertFalse(media.destination.inspect(uri)!!.pending)
            assertEquals(media.prefix + session.relativePath, media.destination.inspect(uri)!!.path)
            media.destination.openRead(uri).use {
                val decoded = checkNotNull(BitmapFactory.decodeStream(it))
                assertEquals(16, decoded.width)
                assertEquals(16, decoded.height)
                decoded.recycle()
            }
            FrameStore(root, media.destination).use { store ->
                store.recover(999)
                store.recover(1_000)
                assertEquals(1L, store.summary().count)
                assertArrayEquals(original, media.destination.openRead(uri).use { it.readBytes() })
                assertEquals(16, store.summary().last!!.width)
            }
            SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT * FROM frames", null).use { row ->
                    assertTrue(row.moveToFirst())

                    fun text(key: String) = row.getString(row.getColumnIndexOrThrow(key))
                    assertEquals("123", text("request_wall_ms"))
                    assertEquals("456", text("request_elapsed_ms"))
                    assertEquals("SHADOW;true", text("cover_shadow"))
                    assertEquals("1", text("recovered"))
                    assertEquals(
                        MessageDigest.getInstance("SHA-256").digest(original).joinToString("") { "%02x".format(it) },
                        text("sha256"),
                    )
                }
            }
        } finally {
            val retained = media.cleanup()
            assertEquals(retained.isNotEmpty(), media.hasProvenance())
            retained.forEach { assertTrue(media.hasFixture(it.name)) }
            if (retained.isEmpty()) root.deleteRecursively()
        }
    }

    @Test fun accessibleControlsAndPauseWithoutCameraConsent() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as IsolatedRecorderApplication
        awaitState { app.ready && !app.sessionOpen }
        ActivityScenario.launch(MainActivity::class.java).use {
            awaitState { app.canStart }
            onView(withId(R.id.start_recording)).check(matches(withText(R.string.start)))
            onView(withId(R.id.start_recording)).check(matches(isEnabled()))
            onView(withId(R.id.pause_recording)).check(matches(withText(R.string.pause)))
            onView(withId(R.id.record_status)).check(matches(withText(R.string.status_paused)))
            it.recreate()
            onView(withId(R.id.saved_count)).check(matches(withText(app.getString(R.string.saved_count, app.summary.count))))
            it.onActivity { activity ->
                activity.startService(
                    Intent(activity, RecorderService::class.java)
                        .setAction(RecorderService.ACTION_PAUSE)
                        .putExtra(RecorderService.EXTRA_SESSION, app.sessionId),
                )
            }
            awaitState { !app.sessionOpen }
        }
    }

    @Test fun foregroundCaptureSurvivesActivityStopAndPauses() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as IsolatedRecorderApplication
        awaitState("foreground test initial readiness") { app.ready && !app.sessionOpen }
        val before = app.summary.count
        InstrumentationRegistry.getInstrumentation().runOnMainSync { assertTrue(app.consentToPublicPictures()) }
        ActivityScenario.launch(MainActivity::class.java).use { activity ->
            try {
                awaitState { app.canStart }
                activity.onActivity { accessibilityClick(it, R.id.start_recording) }
                awaitState { app.summary.count >= before + 1 && app.status == R.string.status_recording }
                activity.recreate()
                lateinit var backgroundActivity: MainActivity
                activity.onActivity {
                    backgroundActivity = it
                    assertTrue(it.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
                }
                activity.moveToState(Lifecycle.State.CREATED)
                var stoppedCount = 0L
                InstrumentationRegistry.getInstrumentation().runOnMainSync {
                    assertEquals(0, backgroundActivity.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    stoppedCount = app.summary.count
                }
                awaitState { app.summary.count >= stoppedCount + 2 }
                assertEquals(Lifecycle.State.CREATED, activity.state)
                activity.moveToState(Lifecycle.State.RESUMED)
                activity.onActivity { accessibilityClick(it, R.id.pause_recording) }
                awaitState { !app.sessionOpen && app.status == R.string.status_paused }
                val pausedCount = app.summary.count
                Thread.sleep(2_500)
                awaitState { app.summary.count == pausedCount && !app.sessionOpen }
                onView(withId(R.id.record_status)).check(matches(withText(R.string.status_paused)))
            } finally {
                activity.moveToState(Lifecycle.State.RESUMED)
                activity.onActivity {
                    it.startService(
                        Intent(it, RecorderService::class.java)
                            .setAction(RecorderService.ACTION_PAUSE)
                            .putExtra(RecorderService.EXTRA_SESSION, app.sessionId),
                    )
                }
                awaitState { !app.sessionOpen }
            }
        }
    }

    @Test fun sixRealCameraProfilesRecordRequestedNegotiatedAndActualSizes() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as IsolatedRecorderApplication
        awaitState { app.ready && !app.sessionOpen }
        ActivityScenario.launch(MainActivity::class.java).use { activity ->
            try {
                for (profile in CaptureProfile.entries) {
                    awaitState("next profile ready: ${profile.id}") { app.canStart }
                    val before = app.summary.count
                    activity.onActivity {
                        assertTrue(app.consentToPublicPictures())
                        assertTrue(app.selectProfile(profile.id))
                        accessibilityClick(it, R.id.start_recording)
                    }
                    awaitState { app.summary.count > before && app.status == R.string.status_recording }
                    activity.onActivity { accessibilityClick(it, R.id.pause_recording) }
                    awaitState("profile Pause drain") { !app.sessionOpen }
                    assertTrue("Pause disabled storage: ${app.getString(app.status)}", app.ready)
                    assertEquals(R.string.status_paused, app.status)
                    assertTrue(app.negotiatedSize.isNotEmpty())
                    val saved = checkNotNull(app.summary.last)
                    assertTrue(saved.path!!.contains("/${profile.id}/"))
                    assertTrue(
                        saved.path!!
                            .substringBeforeLast('/')
                            .substringAfterLast('/')
                            .startsWith(profile.id),
                    )
                    assertTrue(saved.width!! > 0 && saved.height!! > 0)
                    app.createDestination().openRead(saved.uri!!).use {
                        val decoded = checkNotNull(BitmapFactory.decodeStream(it))
                        assertEquals(saved.width, decoded.width)
                        assertEquals(saved.height, decoded.height)
                        decoded.recycle()
                    }
                    android.util.Log.i(
                        "MemoTraceTest",
                        "profile=${profile.id};requested=${profile.width}x${profile.height};" +
                            "quality=${profile.quality};negotiated=${app.negotiatedSize};actual=${saved.width}x${saved.height};bytes=${saved.bytes}",
                    )
                }
            } finally {
                activity.onActivity {
                    it.startService(
                        Intent(it, RecorderService::class.java)
                            .setAction(RecorderService.ACTION_PAUSE)
                            .putExtra(RecorderService.EXTRA_SESSION, app.sessionId),
                    )
                }
                awaitState { !app.sessionOpen }
            }
        }
    }
}
