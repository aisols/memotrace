package org.memotrace.recorder.ui

import android.content.Context
import android.view.MotionEvent
import android.widget.Button
import org.memotrace.capture.TapGesture

/** Retains native Button accessibility/keyboard clicks, but touch executes only on UP. */
class TremorButton(
    context: Context,
) : Button(context) {
    private val gesture: TapGesture? = TapGesture(24f * resources.displayMetrics.density)
    private var pointerId = MotionEvent.INVALID_POINTER_ID

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val gesture = checkNotNull(gesture)
        if (!isEnabled) {
            gesture.cancel()
            pointerId = MotionEvent.INVALID_POINTER_ID
            isPressed = false
            return false
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                pointerId = event.getPointerId(0)
                gesture.down(event.x, event.y)
            }
            MotionEvent.ACTION_MOVE, MotionEvent.ACTION_UP -> {
                val pointerIndex = event.findPointerIndex(pointerId)
                if (pointerIndex < 0) {
                    gesture.cancel()
                    pointerId = MotionEvent.INVALID_POINTER_ID
                } else {
                    // Coalesced excursions must cancel before the latest point returns inside.
                    repeat(event.historySize) { historyIndex ->
                        gesture.move(event.getHistoricalX(pointerIndex, historyIndex), event.getHistoricalY(pointerIndex, historyIndex))
                    }
                    if (event.actionMasked == MotionEvent.ACTION_UP) {
                        val click = gesture.up(event.getX(pointerIndex), event.getY(pointerIndex))
                        pointerId = MotionEvent.INVALID_POINTER_ID
                        isPressed = false
                        if (click) performClick()
                        return true
                    }
                    gesture.move(event.getX(pointerIndex), event.getY(pointerIndex))
                }
            }
            MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN, MotionEvent.ACTION_POINTER_UP -> {
                gesture.cancel()
                pointerId = MotionEvent.INVALID_POINTER_ID
            }
            else -> return false
        }
        isPressed = gesture.active
        // Do not disallow interception: ScrollView's winning drag sends CANCEL permanently.
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    override fun setEnabled(enabled: Boolean) {
        super.setEnabled(enabled)
        // View construction may call this before the gesture field is initialized.
        if (!enabled) {
            gesture?.cancel()
            pointerId = MotionEvent.INVALID_POINTER_ID
            isPressed = false
        }
    }

    override fun onDetachedFromWindow() {
        gesture?.cancel()
        pointerId = MotionEvent.INVALID_POINTER_ID
        isPressed = false
        super.onDetachedFromWindow()
    }
}
