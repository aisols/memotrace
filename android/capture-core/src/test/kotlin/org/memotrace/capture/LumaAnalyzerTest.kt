package org.memotrace.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class LumaAnalyzerTest {
    @Test fun samplingBoundary() {
        val a = LumaAnalyzer()
        assertTrue(a.due(0))
        assertFalse(a.due(249))
        assertTrue(a.due(250))
        assertFalse(a.due(250))
        assertTrue(a.due(10_000))
    }

    @Test fun staticAndMotionWithOwnedPreviousSamples() {
        val a = LumaAnalyzer()
        val samples = intArrayOf(0, 20)
        val first = a.analyze(samples)
        assertEquals(10.0, first.mean, 0.0)
        assertEquals(100.0, first.variance, 0.0)
        assertEquals(0.0, first.motion, 0.0)
        samples.fill(255)
        val next = a.analyze(intArrayOf(10, 30))
        assertEquals(10.0, next.motion, 0.0)
        assertEquals(0.0, a.analyze(intArrayOf(10, 30)).motion, 0.0)
        assertEquals(0.0, a.analyze(intArrayOf(0)).motion, 0.0)
    }

    @Test fun meanCoverHysteresisBoundaries() {
        val a = LumaAnalyzer()
        assertFalse(a.analyze(intArrayOf(13)).coverSuspected)
        assertTrue(a.analyze(intArrayOf(12)).coverSuspected)
        assertTrue(a.analyze(intArrayOf(23)).coverSuspected)
        assertFalse(a.analyze(intArrayOf(24)).coverSuspected)
        assertFalse(a.analyze(intArrayOf(23)).coverSuspected)
        assertTrue(a.analyze(intArrayOf(0)).coverSuspected)
        assertFalse(a.analyze(intArrayOf(255)).coverSuspected)
    }

    @Test fun varianceCoverHysteresisBoundaries() {
        val a = LumaAnalyzer()
        assertFalse(a.analyze(intArrayOf(4, 16)).coverSuspected)
        assertTrue(a.analyze(intArrayOf(5, 15)).coverSuspected)
        assertTrue(a.analyze(intArrayOf(3, 17)).coverSuspected)
        assertFalse(a.analyze(intArrayOf(2, 18)).coverSuspected)
        assertFalse(a.analyze(intArrayOf(3, 17)).coverSuspected)
    }

    @Test fun rejectsUnboundedAndInvalidSamples() {
        val a = LumaAnalyzer()
        listOf(intArrayOf(), IntArray(769), intArrayOf(-1), intArrayOf(256)).forEach {
            assertThrows(IllegalArgumentException::class.java) { a.analyze(it) }
        }
        a.analyze(IntArray(768) { 255 })
    }
}
