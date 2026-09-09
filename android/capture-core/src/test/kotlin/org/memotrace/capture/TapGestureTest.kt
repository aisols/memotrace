package org.memotrace.capture

import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class TapGestureTest {
    @Test fun releaseOnceOnlyAndWithoutDownNeverClicks() {
        val tap = TapGesture(24f)
        assertFalse(tap.up(0f, 0f))
        tap.down(4f, 8f)
        assertTrue(tap.active)
        assertTrue(tap.up(4f, 8f))
        assertFalse(tap.active)
        assertFalse(tap.up(4f, 8f))
    }

    @Test fun boundaryAndDiagonalUseDistanceFromDown() {
        val tap = TapGesture(5f)
        tap.down(10f, 10f)
        assertTrue(tap.up(13f, 14f))
        tap.down(10f, 10f)
        assertFalse(tap.up(13.01f, 14f))
        tap.down(10f, 10f)
        assertTrue(tap.up(5f, 10f))
        tap.down(10f, 10f)
        assertFalse(tap.up(4.99f, 10f))
    }

    @Test fun tremorTravelDoesNotAccumulate() {
        val tap = TapGesture(24f)
        tap.down(100f, 100f)
        repeat(100) {
            tap.move(80f, 100f)
            tap.move(120f, 100f)
        }
        assertTrue(tap.up(100f, 100f))
    }

    @Test fun dragOrSystemCancelCannotReenterUntilAnotherDown() {
        val tap = TapGesture(24f)
        tap.down(0f, 0f)
        tap.move(0f, 25f)
        tap.move(0f, 0f)
        assertFalse(tap.up(0f, 0f))
        tap.down(0f, 0f)
        tap.cancel()
        tap.cancel()
        assertFalse(tap.up(0f, 0f))
        tap.down(0f, 0f)
        assertTrue(tap.up(0f, 0f))
    }

    @Test fun slipMustBePositiveFinite() {
        for (slip in listOf(0f, -1f, Float.NaN, Float.POSITIVE_INFINITY)) {
            assertThrows(IllegalArgumentException::class.java) { TapGesture(slip) }
        }
    }
}
