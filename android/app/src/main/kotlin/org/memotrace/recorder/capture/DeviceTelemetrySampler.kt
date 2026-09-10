package org.memotrace.recorder.capture

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import org.memotrace.recorder.storage.DeviceSnapshot
import org.memotrace.recorder.storage.TelemetrySample
import java.io.File

internal data class BatteryReading(
    val level: Int?,
    val scale: Int?,
    val percent: Double?,
)

internal data class TelemetryRequest(
    val reason: String,
    val thermalStatus: Int? = null,
)

internal class TelemetryRequestCoalescer(
    private val dispatch: (TelemetryRequest) -> Unit,
) {
    private var active = false
    private var pending: TelemetryRequest? = null

    fun offer(request: TelemetryRequest) {
        if (!active) {
            active = true
            dispatch(request)
            return
        }
        pending =
            when {
                request.thermalStatus != null -> {
                    val maximum = maxOf(request.thermalStatus, pending?.thermalStatus ?: request.thermalStatus)
                    TelemetryRequest("THERMAL_CHANGE", maximum)
                }
                pending?.thermalStatus != null -> pending
                else -> request
            }
    }

    fun complete() {
        if (!active) return
        val next = pending
        pending = null
        if (next == null) {
            active = false
        } else {
            dispatch(next)
        }
    }

    fun clear() {
        active = false
        pending = null
    }
}

class DeviceTelemetrySampler(
    private val context: Context,
    private val privateRoot: File,
) {
    fun deviceSnapshot(): DeviceSnapshot {
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        return DeviceSnapshot(
            Build.MANUFACTURER.orEmpty(),
            Build.MODEL.orEmpty(),
            Build.VERSION.RELEASE.orEmpty(),
            Build.VERSION.SDK_INT,
            Build.ID.orEmpty(),
            packageInfo.versionName.orEmpty(),
            packageInfo.longVersionCode,
        )
    }

    fun sample(
        reason: String,
        wallMs: Long,
        elapsedMs: Long,
        thermalStatus: Int? = null,
    ): TelemetrySample {
        val battery =
            try {
                context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            } catch (_: RuntimeException) {
                null
            }
        val manager = context.getSystemService(BatteryManager::class.java)
        val batteryReading =
            normalizeBattery(
                battery.intExtraOrNull(BatteryManager.EXTRA_LEVEL),
                battery.intExtraOrNull(BatteryManager.EXTRA_SCALE),
            )
        return TelemetrySample(
            wallMs,
            elapsedMs,
            reason,
            batteryReading.level,
            batteryReading.scale,
            batteryReading.percent,
            battery.intExtraOrNull(BatteryManager.EXTRA_STATUS),
            battery.intExtraOrNull(BatteryManager.EXTRA_PLUGGED),
            battery.intExtraOrNull(BatteryManager.EXTRA_TEMPERATURE),
            manager.longProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER),
            manager.longProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW),
            manager.longProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE),
            manager.longProperty(BatteryManager.BATTERY_PROPERTY_ENERGY_COUNTER),
            thermalStatus ?: currentThermalStatus(),
            freeBytes(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)),
            freeBytes(privateRoot),
        )
    }

    private fun Intent?.intExtraOrNull(name: String): Int? {
        if (this == null || !hasExtra(name)) return null
        return getIntExtra(name, Int.MIN_VALUE).takeUnless { it == Int.MIN_VALUE }
    }

    private fun BatteryManager?.longProperty(id: Int): Long? {
        if (this == null) return null
        return try {
            getLongProperty(id).takeUnless { it == Long.MIN_VALUE }
        } catch (_: RuntimeException) {
            null
        }
    }

    private fun freeBytes(file: File): Long? =
        try {
            StatFs(file.path).availableBytes
        } catch (_: RuntimeException) {
            null
        }

    private fun currentThermalStatus(): Int? =
        try {
            context.getSystemService(PowerManager::class.java).currentThermalStatus
        } catch (_: RuntimeException) {
            null
        }

    companion object {
        internal fun normalizeBattery(
            level: Int?,
            scale: Int?,
        ): BatteryReading =
            if (level == null || scale == null || scale <= 0 || level !in 0..scale) {
                BatteryReading(null, null, null)
            } else {
                BatteryReading(level, scale, level * 100.0 / scale)
            }
    }
}
