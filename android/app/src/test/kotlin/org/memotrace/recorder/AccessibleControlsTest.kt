package org.memotrace.recorder

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.graphics.Rect
import android.os.Looper
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.recorder.capture.RecorderService
import org.memotrace.recorder.ui.MainActivity
import org.memotrace.recorder.ui.TremorButton
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowAlertDialog
import java.util.concurrent.TimeUnit

class LargeFontActivity : MainActivity() {
    override fun attachBaseContext(newBase: Context) {
        applyOverrideConfiguration(Configuration().apply { fontScale = 2f })
        super.attachBaseContext(newBase)
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = FakeCameraApplication::class, qualifiers = "w240dp-h360dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AccessibleControlsTest {
    private lateinit var app: FakeCameraApplication

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication() as FakeCameraApplication
        app.io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
        assertTrue(app.ready)
    }

    @After fun cleanup() {
        app.io.submit { app.store.close() }.get(5, TimeUnit.SECONDS)
        app.io.shutdown()
    }

    private fun layout(
        view: View,
        width: Int = 240,
        height: Int = 360,
    ) {
        view.measure(
            View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY),
        )
        view.layout(0, 0, width, height)
    }

    private fun accessible(button: Button) {
        assertTrue("button must be attached", button.isAttachedToWindow)
        assertTrue("button must have visible bounds", button.getGlobalVisibleRect(Rect()))
        var ancestor: View? = button
        while (ancestor != null) {
            assertEquals(View.VISIBLE, ancestor.visibility)
            assertTrue(ancestor.alpha > 0)
            assertTrue(ancestor.importantForAccessibility != View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS)
            ancestor = ancestor.parent as? View
        }
        val node = button.createAccessibilityNodeInfo()
        assertEquals(Button::class.java.name, node.className.toString())
        assertEquals(button.text.toString(), node.text.toString())
        assertTrue(node.isEnabled)
        assertTrue(node.isClickable)
        assertTrue(node.isVisibleToUser)
        assertTrue(node.actionList.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_CLICK))
    }

    @Test fun accessibilityActionsUseNativeClickAndRealStartPauseListeners() {
        assertTrue(app.consentToPublicPictures())
        shadowOf(app).grantPermissions(Manifest.permission.CAMERA, Manifest.permission.POST_NOTIFICATIONS)
        Robolectric.buildActivity(MainActivity::class.java).setup().use { controller ->
            app.io.submit {}.get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()
            val activity = controller.get()
            layout(activity.window.decorView)
            val start = activity.findViewById<Button>(R.id.start_recording)
            accessible(start)
            assertTrue(start.performAccessibilityAction(AccessibilityNodeInfo.ACTION_CLICK, null))
            val startIntent = shadowOf(app).nextStartedService
            assertEquals(RecorderService.ACTION_START, startIntent.action)
            assertTrue(app.consumeStart(startIntent.getStringExtra(RecorderService.EXTRA_SESSION)) != null)
            app.sessionOpen = true
            app.status = R.string.status_recording
            app.publish()
            val pause = activity.findViewById<Button>(R.id.pause_recording)
            activity.findViewById<ScrollView>(R.id.recorder_scroll).scrollTo(0, pause.top)
            accessible(pause)
            assertTrue(pause.performAccessibilityAction(AccessibilityNodeInfo.ACTION_CLICK, null))
            assertEquals(RecorderService.ACTION_PAUSE, shadowOf(app).nextStartedService.action)
            app.sessionOpen = false
        }
    }

    @Test fun narrowLargeFontControlsHaveCompleteTextAndCanBeScrolledFullyIntoView() {
        val controller = Robolectric.buildActivity(LargeFontActivity::class.java)
        controller.setup().use {
            shadowOf(Looper.getMainLooper()).idle()
            val activity = controller.get()
            assertEquals(2f, activity.resources.configuration.fontScale)
            assertEquals(1f, app.resources.configuration.fontScale)
            layout(activity.window.decorView)
            val scroll = activity.findViewById<ScrollView>(R.id.recorder_scroll)
            assertTrue(scroll.canScrollVertically(1))
            val start = activity.findViewById<Button>(R.id.start_recording)
            val pause = activity.findViewById<Button>(R.id.pause_recording)
            val stableTop = start.top to pause.top
            assertTrue("long Start label must actually wrap", start.layout.lineCount > 1)
            for (button in listOf(start, pause)) {
                assertEquals(button.text.length, button.layout.getLineEnd(button.layout.lineCount - 1))
                assertTrue(button.height >= button.layout.height + button.compoundPaddingTop + button.compoundPaddingBottom)
                repeat(button.layout.lineCount) { line -> assertEquals(0, button.layout.getEllipsisCount(line)) }
                scroll.scrollTo(0, button.top)
                val visible = Rect()
                assertTrue(button.getLocalVisibleRect(visible))
                assertEquals(button.width, visible.width())
                assertEquals(button.height, visible.height())
            }
            app.status = R.string.status_storage_error
            app.publish()
            layout(activity.window.decorView)
            assertEquals(stableTop, start.top to pause.top)
        }
    }

    @Test fun profileAndConsentDialogsKeepCompleteLargeFontButtonsAndScrollAccess() {
        Robolectric.buildActivity(LargeFontActivity::class.java).setup().use { controller ->
            val activity = controller.get()
            for (trigger in listOf(R.id.select_profile, R.id.start_recording)) {
                app.io.submit {}.get(5, TimeUnit.SECONDS)
                shadowOf(Looper.getMainLooper()).idle()
                activity.findViewById<Button>(trigger).performClick()
                shadowOf(Looper.getMainLooper()).idle()
                val dialog = ShadowAlertDialog.getLatestAlertDialog()
                layout(dialog.window!!.decorView)
                val scroll = dialog.findViewById<ScrollView>(R.id.dialog_scroll)
                val content = scroll.getChildAt(0) as LinearLayout
                assertTrue(scroll.canScrollVertically(1))
                for (index in 1 until content.childCount) {
                    val button = content.getChildAt(index) as Button
                    assertTrue(button is TremorButton)
                    assertEquals(button.text.length, button.layout.getLineEnd(button.layout.lineCount - 1))
                    assertTrue(button.height >= button.layout.height + button.compoundPaddingTop + button.compoundPaddingBottom)
                    repeat(button.layout.lineCount) { assertEquals(0, button.layout.getEllipsisCount(it)) }
                    scroll.scrollTo(0, button.top)
                    accessible(button)
                }
                dialog.dismiss()
            }
        }
    }

    private fun touch(
        view: View,
        action: Int,
        x: Float,
        y: Float,
        time: Long = 0,
    ) {
        MotionEvent.obtain(0, time, action, x, y, 0).let {
            view.dispatchTouchEvent(it)
            it.recycle()
        }
    }

    @Test fun downAnchorsTargetSmallSlipCannotRetargetNeighborAndUpExecutesOnce() {
        Robolectric.buildActivity(Activity::class.java).setup().use { activity ->
            val row = LinearLayout(activity.get()).apply { orientation = LinearLayout.HORIZONTAL }
            val first = TremorButton(activity.get())
            val second = TremorButton(activity.get())
            var firstClicks = 0
            var secondClicks = 0
            first.setOnClickListener { firstClicks++ }
            second.setOnClickListener { secondClicks++ }
            row.addView(first, LinearLayout.LayoutParams(100, 100))
            row.addView(second, LinearLayout.LayoutParams(100, 100))
            activity.get().setContentView(row)
            layout(row, 200, 100)
            touch(row, MotionEvent.ACTION_DOWN, 95f, 40f)
            assertEquals(0, firstClicks)
            assertTrue(first.isPressed)
            touch(row, MotionEvent.ACTION_MOVE, 107f, 40f, 10)
            touch(row, MotionEvent.ACTION_UP, 107f, 40f, 20)
            touch(first, MotionEvent.ACTION_UP, 107f, 40f, 30)
            assertEquals(1, firstClicks)
            assertEquals(0, secondClicks)
            assertFalse(first.isPressed)
        }
    }

    @Test fun scrollInterceptionCancelsIrreversiblyEvenWhenPointerReturns() {
        Robolectric.buildActivity(Activity::class.java).setup().use { activity ->
            val scroll = ScrollView(activity.get())
            val column = LinearLayout(activity.get()).apply { orientation = LinearLayout.VERTICAL }
            val button = TremorButton(activity.get())
            var clicks = 0
            button.setOnClickListener { clicks++ }
            column.addView(button, LinearLayout.LayoutParams(240, 100))
            column.addView(View(activity.get()), LinearLayout.LayoutParams(240, 1_000))
            scroll.addView(column)
            activity.get().setContentView(scroll)
            layout(scroll, 240, 200)
            touch(scroll, MotionEvent.ACTION_DOWN, 60f, 60f)
            touch(scroll, MotionEvent.ACTION_MOVE, 60f, 20f, 10)
            touch(scroll, MotionEvent.ACTION_MOVE, 60f, -40f, 20)
            assertTrue(scroll.scrollY > 0)
            assertFalse(button.isPressed)
            touch(scroll, MotionEvent.ACTION_MOVE, 60f, 60f, 30)
            touch(scroll, MotionEvent.ACTION_UP, 60f, 60f, 40)
            assertEquals(0, clicks)

            scroll.scrollTo(0, 0)
            touch(scroll, MotionEvent.ACTION_DOWN, 60f, 60f)
            MotionEvent.obtain(0, 10, MotionEvent.ACTION_MOVE, 60f, 20f, 0).let {
                it.addBatch(20, 60f, 60f, 1f, 1f, 0)
                assertEquals(1, it.historySize)
                scroll.dispatchTouchEvent(it)
                it.recycle()
            }
            assertFalse(button.isPressed)
            touch(scroll, MotionEvent.ACTION_UP, 60f, 60f, 30)
            assertEquals(0, clicks)
        }
    }

    @Test fun batchedExcursionsCancelEvenWhenMoveOrUpReturnsInside() {
        assertEquals(1f, app.resources.displayMetrics.density)
        for (action in listOf(MotionEvent.ACTION_MOVE, MotionEvent.ACTION_UP)) {
            val button = TremorButton(app)
            var clicks = 0
            button.setOnClickListener { clicks++ }
            touch(button, MotionEvent.ACTION_DOWN, 60f, 60f)
            MotionEvent.obtain(0, 10, MotionEvent.ACTION_MOVE, 100f, 60f, 0).let {
                it.addBatch(20, 60f, 60f, 1f, 1f, 0)
                // UP is normally unbatched; a transformed event can retain MOVE history.
                it.action = action
                assertEquals(1, it.historySize)
                assertEquals(100f, it.getHistoricalX(0))
                button.dispatchTouchEvent(it)
                it.recycle()
            }
            assertFalse(button.isPressed)
            touch(button, MotionEvent.ACTION_UP, 60f, 60f, 30)
            assertEquals(0, clicks)
        }
    }

    @Test fun boundedBatchClicksOnceButCannotReviveCancelledGesture() {
        for (cancelled in listOf(false, true)) {
            val button = TremorButton(app)
            var clicks = 0
            button.setOnClickListener { clicks++ }
            touch(button, MotionEvent.ACTION_DOWN, 60f, 60f)
            if (cancelled) touch(button, MotionEvent.ACTION_CANCEL, 60f, 60f, 5)
            MotionEvent.obtain(0, 10, MotionEvent.ACTION_MOVE, 40f, 60f, 0).let {
                it.addBatch(20, 80f, 60f, 1f, 1f, 0)
                it.addBatch(30, 60f, 60f, 1f, 1f, 0)
                assertEquals(2, it.historySize)
                button.dispatchTouchEvent(it)
                it.recycle()
            }
            assertEquals(!cancelled, button.isPressed)
            touch(button, MotionEvent.ACTION_UP, 60f, 60f, 40)
            touch(button, MotionEvent.ACTION_UP, 60f, 60f, 50)
            assertEquals(if (cancelled) 0 else 1, clicks)
        }
    }

    @Test fun batchedSamplesFollowDownPointerIdAndRejectReplacement() {
        val button = TremorButton(app)
        var clicks = 0
        button.setOnClickListener { clicks++ }

        fun send(
            action: Int,
            pointerId: Int,
            time: Long,
            batched: Boolean = false,
        ) {
            MotionEvent
                .obtain(
                    0,
                    time,
                    action,
                    1,
                    arrayOf(
                        MotionEvent.PointerProperties().apply {
                            id = pointerId
                            toolType = MotionEvent.TOOL_TYPE_FINGER
                        },
                    ),
                    arrayOf(
                        MotionEvent.PointerCoords().apply {
                            x = 60f
                            y = 60f
                            pressure = 1f
                            size = 1f
                        },
                    ),
                    0,
                    0,
                    1f,
                    1f,
                    0,
                    0,
                    InputDevice.SOURCE_TOUCHSCREEN,
                    0,
                ).let {
                    if (batched) it.addBatch(time + 1, 80f, 60f, 1f, 1f, 0)
                    assertEquals(pointerId, it.getPointerId(0))
                    button.dispatchTouchEvent(it)
                    it.recycle()
                }
        }
        send(MotionEvent.ACTION_DOWN, 7, 0)
        send(MotionEvent.ACTION_MOVE, 7, 10, batched = true)
        send(MotionEvent.ACTION_UP, 7, 20)
        assertEquals(1, clicks)
        send(MotionEvent.ACTION_DOWN, 7, 30)
        send(MotionEvent.ACTION_MOVE, 8, 40, batched = true)
        assertFalse(button.isPressed)
        send(MotionEvent.ACTION_UP, 7, 50)
        assertEquals(1, clicks)
        send(MotionEvent.ACTION_DOWN, 7, 60)
        send(MotionEvent.ACTION_UP, 8, 70)
        send(MotionEvent.ACTION_UP, 7, 80)
        assertEquals(1, clicks)
    }

    @Test fun systemCancelMultitouchAndDisableCannotBecomeClicks() {
        val button = TremorButton(app)
        var clicks = 0
        button.setOnClickListener { clicks++ }
        for (cancel in listOf(MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN, MotionEvent.ACTION_POINTER_UP)) {
            touch(button, MotionEvent.ACTION_DOWN, 20f, 20f)
            touch(button, cancel, 20f, 20f)
            touch(button, MotionEvent.ACTION_UP, 20f, 20f)
        }
        touch(button, MotionEvent.ACTION_DOWN, 20f, 20f)
        button.isEnabled = false
        button.isEnabled = true
        touch(button, MotionEvent.ACTION_UP, 20f, 20f)
        assertEquals(0, clicks)
        assertTrue(button.performClick())
        assertEquals(1, clicks)
    }
}
