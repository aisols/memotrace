package org.memotrace.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CapturePolicyTest {
    @Test fun defaultConfiguration() {
        val c = CaptureConfig()
        assertEquals(2_000L, c.baselineMs)
        assertEquals(1_000L, c.motionMs)
        assertEquals(250L, c.analysisMs)
        assertEquals(30_000L, c.captureTimeoutMs)
        assertEquals(3_000L, c.quietMs)
        assertEquals(12.0, c.motionEnter, 0.0)
        assertEquals(5.0, c.motionExit, 0.0)
    }

    @Test fun finiteConfigurationBoundaries() {
        CaptureConfig(1_000, 500, 100, 1.0, 0.0, 500, 5_000)
        CaptureConfig(10_000, 10_000, 1_000, 255.0, 254.0, 30_000, 120_000)
        val invalid =
            listOf<() -> Unit>(
                { CaptureConfig(baselineMs = 999) },
                { CaptureConfig(baselineMs = 10_001) },
                { CaptureConfig(motionMs = 499) },
                { CaptureConfig(motionMs = 2_001) },
                { CaptureConfig(analysisMs = 99) },
                { CaptureConfig(analysisMs = 1_001) },
                { CaptureConfig(motionEnter = Double.NaN) },
                { CaptureConfig(motionEnter = Double.POSITIVE_INFINITY) },
                { CaptureConfig(motionEnter = 0.9) },
                { CaptureConfig(motionEnter = 255.1) },
                { CaptureConfig(motionExit = Double.NaN) },
                { CaptureConfig(motionExit = Double.POSITIVE_INFINITY) },
                { CaptureConfig(motionExit = -0.1) },
                { CaptureConfig(motionExit = 12.0) },
                { CaptureConfig(quietMs = 499) },
                { CaptureConfig(quietMs = 30_001) },
                { CaptureConfig(captureTimeoutMs = 4_999) },
                { CaptureConfig(captureTimeoutMs = 120_001) },
            )
        invalid.forEach { assertThrows(IllegalArgumentException::class.java) { it() } }
    }

    @Test fun baselineBoundariesAndNoCatchup() {
        val p = CapturePolicy()
        assertNull(p.request(0))
        assertFalse(p.timedOut(0))
        assertTrue(p.start())
        assertFalse(p.start())
        val first = p.request(0)!!
        assertTrue(p.complete(first, true))
        assertNull(p.request(1_999))
        val second = p.request(2_000)!!
        assertTrue(second > first)
        p.complete(second, true)
        val third = p.request(1_000_000)!!
        p.complete(third, true)
        assertNull(p.request(1_000_000))
        assertNull(p.request(1_001_999))
        assertNotNull(p.request(1_002_000))
    }

    @Test fun busyTicksHaveOneSlotEvenAcrossPause() {
        val p = CapturePolicy()
        p.start()
        val token = p.request(0)!!
        repeat(100_000) { assertNull(p.request(it.toLong())) }
        p.pause()
        assertFalse(p.start())
        assertFalse(p.complete(token + 1, true))
        assertFalse(p.start())
        assertFalse(p.complete(token, true))
        assertEquals(CapturePolicy.State.PAUSED, p.state)
        assertTrue(p.start())
        assertNotNull(p.request(100_000))
    }

    @Test fun motionThresholdAndQuietHysteresis() {
        val p = CapturePolicy()
        p.motion(11.999, 0)
        assertFalse(p.moving)
        p.motion(12.0, 1)
        assertTrue(p.moving)
        assertEquals(1_000L, p.intervalMs)
        p.motion(5.0, 100)
        p.motion(5.0, 3_099)
        assertTrue(p.moving)
        p.motion(5.0, 3_100)
        assertFalse(p.moving)
        p.motion(12.0, 4_000)
        p.motion(0.0, 4_001)
        p.motion(5.001, 7_000)
        p.motion(0.0, 8_000)
        assertTrue(p.moving)
        p.motion(12.0, 10_999)
        p.motion(0.0, 11_000)
        p.motion(0.0, 14_000)
        assertFalse(p.moving)
        assertEquals(2_000L, p.intervalMs)
    }

    @Test fun motionChangesNextDeadlineNotPendingWork() {
        val p = CapturePolicy(CaptureConfig(motionMs = 750))
        p.start()
        val first = p.request(0)!!
        p.motion(255.0, 100)
        assertNull(p.request(750))
        p.complete(first, true)
        assertNull(p.request(749))
        assertNotNull(p.request(750))
    }

    @Test fun failedAndDuplicateCompletionCannotRestart() {
        val p = CapturePolicy()
        p.start()
        val token = p.request(10)!!
        assertFalse(p.complete(token, false))
        assertEquals(CapturePolicy.State.ERROR, p.state)
        assertNull(p.request(100_000))
        assertFalse(p.complete(token, true))
        assertTrue(p.start())
        val newer = p.request(100_001)!!
        assertFalse(p.complete(token, false))
        assertEquals(CapturePolicy.State.RECORDING, p.state)
        assertTrue(p.complete(newer, true))
    }

    @Test fun timeoutBoundaryAndLateCompletion() {
        val p = CapturePolicy()
        p.start()
        val token = p.request(10)!!
        assertFalse(p.timedOut(30_009))
        assertTrue(p.timedOut(30_010))
        p.fail()
        assertFalse(p.start())
        assertFalse(p.complete(token, true))
        assertEquals(CapturePolicy.State.ERROR, p.state)
        assertFalse(p.timedOut(100_000))
        assertTrue(p.start())
    }

    @Test fun lateFailurePreservesPauseAndStartResetsMotion() {
        val p = CapturePolicy()
        p.start()
        p.motion(100.0, 0)
        val token = p.request(0)!!
        p.pause()
        assertFalse(p.complete(token, false))
        assertEquals(CapturePolicy.State.PAUSED, p.state)
        p.start()
        assertFalse(p.moving)
        assertNotNull(p.request(1))
    }

    @Test fun motionRejectsInvalidValues() {
        val p = CapturePolicy()
        listOf(Double.NaN, Double.POSITIVE_INFINITY, -0.1, 255.1).forEach {
            assertThrows(IllegalArgumentException::class.java) { p.motion(it, 0) }
        }
    }

    @Test fun shadowOcclusionCannotAlterCaptureSequence() {
        val light = CapturePolicy()
        val dark = CapturePolicy()
        val a = LumaAnalyzer()
        val b = LumaAnalyzer()
        light.start()
        dark.start()
        repeat(80) { n ->
            val time = n * 250L
            val lm = a.analyze(IntArray(768) { 150 })
            val dm = b.analyze(IntArray(768) { 0 })
            assertFalse(lm.coverSuspected)
            assertTrue(dm.coverSuspected)
            light.motion(lm.motion, time)
            dark.motion(dm.motion, time)
            val l = light.request(time)
            val d = dark.request(time)
            assertEquals(l, d)
            assertEquals(light.intervalMs, dark.intervalMs)
            if (l != null) light.complete(l, true)
            if (d != null) dark.complete(d, true)
        }
    }
}
