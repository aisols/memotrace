package org.memotrace.recorder

import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.recorder.capture.BatteryReading
import org.memotrace.recorder.capture.DeviceTelemetrySampler
import org.memotrace.recorder.capture.TelemetryRequest
import org.memotrace.recorder.capture.TelemetryRequestCoalescer
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
class DeviceTelemetrySamplerTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun batteryNormalizationRejectsSentinelsMissingAndOutOfRangeValues() {
        for ((level, scale) in listOf(-1 to 100, 101 to 100, 50 to 0, 50 to -1, null to 100, 50 to null)) {
            assertEquals(BatteryReading(null, null, null), DeviceTelemetrySampler.normalizeBattery(level, scale))
        }
        assertEquals(BatteryReading(0, 100, 0.0), DeviceTelemetrySampler.normalizeBattery(0, 100))
        assertEquals(BatteryReading(73, 100, 73.0), DeviceTelemetrySampler.normalizeBattery(73, 100))
        assertEquals(BatteryReading(100, 100, 100.0), DeviceTelemetrySampler.normalizeBattery(100, 100))
    }

    @Test fun deliveredThermalStatusOverridesLaterPowerManagerReading() {
        val sample =
            DeviceTelemetrySampler(RuntimeEnvironment.getApplication(), temporary.root)
                .sample("THERMAL_CHANGE", 1_000, 100, thermalStatus = 5)
        assertEquals(5, sample.thermalStatus)
    }

    @Test fun busyThermalBurstsKeepOnlyOnePendingMaximumSeveritySample() {
        val dispatched = mutableListOf<TelemetryRequest>()
        val queue = TelemetryRequestCoalescer(dispatched::add)
        queue.offer(TelemetryRequest("PERIODIC"))
        queue.offer(TelemetryRequest("PERIODIC"))
        queue.offer(TelemetryRequest("THERMAL_CHANGE", 2))
        queue.offer(TelemetryRequest("THERMAL_CHANGE", 5))
        queue.offer(TelemetryRequest("THERMAL_CHANGE", 3))
        assertEquals(listOf(TelemetryRequest("PERIODIC")), dispatched)

        queue.complete()
        assertEquals(listOf(TelemetryRequest("PERIODIC"), TelemetryRequest("THERMAL_CHANGE", 5)), dispatched)
        queue.offer(TelemetryRequest("THERMAL_CHANGE", 4))
        queue.offer(TelemetryRequest("THERMAL_CHANGE", 6))
        assertEquals(2, dispatched.size)

        queue.complete()
        assertEquals(TelemetryRequest("THERMAL_CHANGE", 6), dispatched.last())
        queue.complete()
        assertEquals(3, dispatched.size)
    }
}
