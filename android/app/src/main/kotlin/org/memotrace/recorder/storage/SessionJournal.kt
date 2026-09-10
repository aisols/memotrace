package org.memotrace.recorder.storage

import android.content.ContentValues
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.os.BatteryManager
import androidx.core.database.sqlite.transaction
import kotlin.math.abs
import kotlin.math.ceil

data class DeviceSnapshot(
    val manufacturer: String,
    val model: String,
    val androidRelease: String,
    val sdkInt: Int,
    val buildId: String,
    val appVersion: String,
    val appVersionCode: Long,
)

data class SessionStart(
    val id: String,
    val profileId: String,
    val requestedWidth: Int,
    val requestedHeight: Int,
    val jpegQuality: Int,
    val requestedSettings: String,
    val startWallMs: Long,
    val startElapsedMs: Long,
    val device: DeviceSnapshot,
)

data class TelemetrySample(
    val wallMs: Long,
    val elapsedMs: Long,
    val reason: String,
    val batteryLevel: Int?,
    val batteryScale: Int?,
    val batteryPercent: Double?,
    val batteryStatus: Int?,
    val batteryPlugged: Int?,
    val batteryTemperatureTenthsC: Int?,
    val chargeCounterUah: Long?,
    val currentNowUa: Long?,
    val currentAverageUa: Long?,
    val energyCounterNwh: Long?,
    val thermalStatus: Int?,
    val publicFreeBytes: Long?,
    val privateFreeBytes: Long?,
)

data class CaptureAttemptStart(
    val id: String,
    val sessionId: String,
    val requestWallMs: Long,
    val requestElapsedMs: Long,
    val requestedIntervalMs: Long,
    val scheduledDueElapsedMs: Long = requestElapsedMs,
)

data class SessionRecord(
    val id: String,
    val profileId: String,
    val requestedWidth: Int,
    val requestedHeight: Int,
    val jpegQuality: Int,
    val requestedSettings: String,
    val startWallMs: Long,
    val startElapsedMs: Long,
    val endWallMs: Long?,
    val endElapsedMs: Long?,
    val recoveryDetectedWallMs: Long?,
    val terminalReason: String?,
    val completionStatus: String,
    val manufacturer: String,
    val model: String,
    val androidRelease: String,
    val sdkInt: Int,
    val buildId: String,
    val appVersion: String,
    val appVersionCode: Long,
    val negotiatedWidth: Int?,
    val negotiatedHeight: Int?,
)

data class SampleRecord(
    val id: Long,
    val sessionId: String,
    val sample: TelemetrySample,
)

data class CaptureAttemptRecord(
    val id: String,
    val sessionId: String,
    val frameId: String?,
    val requestWallMs: Long,
    val requestElapsedMs: Long,
    val scheduledDueElapsedMs: Long?,
    val requestedIntervalMs: Long,
    val prepareCompleteElapsedMs: Long?,
    val cameraInvokeReadyElapsedMs: Long?,
    val cameraTerminalElapsedMs: Long?,
    val diskDrainedElapsedMs: Long?,
    val commitCompleteElapsedMs: Long?,
    val result: String,
    val failurePhase: String?,
)

data class Distribution(
    val p50: Long,
    val p95: Long,
    val max: Long,
)

data class SessionDiagnostics(
    val session: SessionRecord,
    val durationMs: Long?,
    val sampleCount: Int,
    val sampleAgeMs: Long?,
    val attemptCount: Int,
    val successCount: Int,
    val cameraFailureCount: Int,
    val storageFailureCount: Int,
    val interruptedCount: Int,
    val frameCount: Long,
    val frameBytes: Long,
    val requestGaps: Distribution?,
    val overrunCount: Int,
    val overrunMaxMs: Long?,
    val pipelineLatency: Distribution?,
    val saveLatency: Distribution?,
    val batteryStartPercent: Double?,
    val batteryEndPercent: Double?,
    val batteryDeltaPercent: Double?,
    val temperatureMinTenthsC: Int?,
    val temperatureMaxTenthsC: Int?,
    val maxThermalStatus: Int?,
    val actualSizes: String,
    val publicStorageStartBytes: Long?,
    val publicStorageEndBytes: Long?,
    val publicStorageMinimumBytes: Long?,
    val privateStorageStartBytes: Long?,
    val privateStorageEndBytes: Long?,
    val privateStorageMinimumBytes: Long?,
)

data class LongRunReport(
    val session: SessionRecord,
    val samples: List<SampleRecord>,
    val captures: List<CaptureAttemptRecord>,
)

internal class SessionJournal(
    private val database: SQLiteDatabase,
) {
    fun start(
        session: SessionStart,
        sample: TelemetrySample,
    ) {
        database.transaction {
            database.insertOrThrow(
                "capture_sessions",
                null,
                ContentValues().apply {
                    put("id", session.id)
                    put("journal_version", JOURNAL_VERSION)
                    put("profile_id", session.profileId)
                    put("requested_width", session.requestedWidth)
                    put("requested_height", session.requestedHeight)
                    put("jpeg_quality", session.jpegQuality)
                    put("requested_settings", session.requestedSettings)
                    put("start_wall_ms", session.startWallMs)
                    put("start_elapsed_ms", session.startElapsedMs)
                    put("completion_status", "OPEN")
                    put("manufacturer", session.device.manufacturer)
                    put("model", session.device.model)
                    put("android_release", session.device.androidRelease)
                    put("sdk_int", session.device.sdkInt)
                    put("build_id", session.device.buildId)
                    put("app_version", session.device.appVersion)
                    put("app_version_code", session.device.appVersionCode)
                },
            )
            insertSample(session.id, sample)
        }
    }

    fun recoverOpenSessions(recoveryDetectedWallMs: Long): Int {
        val open = sessions("completion_status='OPEN'")
        database.transaction {
            database.execSQL(
                """
                UPDATE capture_attempts
                SET result=CASE
                        WHEN EXISTS (SELECT 1 FROM frames WHERE frames.id=capture_attempts.frame_id AND frames.state=1)
                            THEN 'SAVED'
                        ELSE 'INTERRUPTED'
                    END,
                    failure_phase=CASE
                        WHEN EXISTS (SELECT 1 FROM frames WHERE frames.id=capture_attempts.frame_id AND frames.state=1)
                            THEN 'RECOVERY_FRAME_COMMITTED'
                        ELSE 'PROCESS_INTERRUPTED'
                    END,
                    commit_complete_elapsed_ms=NULL
                WHERE result='PENDING'
                """.trimIndent(),
            )
            for (session in open) {
                val values =
                    ContentValues().apply {
                        putNull("end_wall_ms")
                        putNull("end_elapsed_ms")
                        put("recovery_detected_wall_ms", recoveryDetectedWallMs)
                        put("terminal_reason", "PROCESS_INTERRUPTED")
                        put("completion_status", "INTERRUPTED")
                    }
                check(database.update("capture_sessions", values, "id=? AND completion_status='OPEN'", arrayOf(session.id)) == 1) {
                    "missing_open_session"
                }
            }
        }
        return open.size
    }

    fun setNegotiatedSize(
        sessionId: String,
        width: Int,
        height: Int,
    ) {
        check(
            database.update(
                "capture_sessions",
                ContentValues().apply {
                    put("negotiated_width", width)
                    put("negotiated_height", height)
                },
                "id=? AND completion_status='OPEN'",
                arrayOf(sessionId),
            ) == 1,
        ) { "missing_open_session" }
    }

    fun sample(
        sessionId: String,
        sample: TelemetrySample,
    ) {
        check(sessionIsOpen(sessionId)) { "missing_open_session" }
        insertSample(sessionId, sample)
    }

    fun end(
        sessionId: String,
        endWallMs: Long,
        endElapsedMs: Long,
        terminalReason: String,
        completionStatus: String,
        sample: TelemetrySample,
    ) {
        require(completionStatus in setOf("COMPLETE", "FAILED", "INTERRUPTED"))
        database.transaction {
            insertSample(sessionId, sample)
            check(
                database.update(
                    "capture_sessions",
                    ContentValues().apply {
                        put("end_wall_ms", endWallMs)
                        put("end_elapsed_ms", endElapsedMs)
                        put("terminal_reason", terminalReason)
                        put("completion_status", completionStatus)
                    },
                    "id=? AND completion_status='OPEN'",
                    arrayOf(sessionId),
                ) == 1,
            ) { "missing_open_session" }
        }
    }

    fun beginAttempt(attempt: CaptureAttemptStart) {
        check(sessionIsOpen(attempt.sessionId)) { "missing_open_session" }
        insertAttempt(attempt, "PENDING", null, null)
    }

    fun failPreparation(
        attempt: CaptureAttemptStart,
        elapsedMs: Long,
        failurePhase: String,
    ) {
        require(elapsedMs >= attempt.requestElapsedMs) { "attempt_phase_order" }
        val exists =
            database.rawQuery("SELECT COUNT(*) FROM capture_attempts WHERE attempt_id=?", arrayOf(attempt.id)).use {
                check(it.moveToFirst())
                it.getInt(0) == 1
            }
        if (exists) {
            finishAttempt(attempt.id, elapsedMs, "STORAGE_FAILURE", failurePhase)
        } else {
            check(sessionIsOpen(attempt.sessionId)) { "missing_open_session" }
            insertAttempt(attempt, "STORAGE_FAILURE", elapsedMs, failurePhase)
        }
    }

    fun cameraInvokeReady(
        attemptId: String,
        frameId: String,
        prepareElapsedMs: Long,
        invokeReadyElapsedMs: Long,
    ) {
        require(invokeReadyElapsedMs >= prepareElapsedMs) { "attempt_phase_order" }
        val requestElapsedMs = attemptValue(attemptId, "request_elapsed_ms")
        check(requestElapsedMs != null && prepareElapsedMs >= requestElapsedMs) { "attempt_phase_order" }
        check(
            database.update(
                "capture_attempts",
                ContentValues().apply {
                    put("frame_id", frameId)
                    put("prepare_complete_elapsed_ms", prepareElapsedMs)
                    put("camera_invoke_ready_elapsed_ms", invokeReadyElapsedMs)
                },
                "attempt_id=? AND result='PENDING'",
                arrayOf(attemptId),
            ) == 1,
        ) { "missing_pending_attempt" }
    }

    fun cameraCompleted(
        attemptId: String,
        terminalElapsedMs: Long,
        diskDrainedElapsedMs: Long,
    ) {
        require(diskDrainedElapsedMs >= terminalElapsedMs) { "attempt_phase_order" }
        val invokeReady = attemptValue(attemptId, "camera_invoke_ready_elapsed_ms")
        check(invokeReady != null && terminalElapsedMs >= invokeReady) { "attempt_phase_order" }
        check(
            database.update(
                "capture_attempts",
                ContentValues().apply {
                    put("camera_terminal_elapsed_ms", terminalElapsedMs)
                    put("disk_drained_elapsed_ms", diskDrainedElapsedMs)
                },
                "attempt_id=? AND result='PENDING'",
                arrayOf(attemptId),
            ) == 1,
        ) { "missing_pending_attempt" }
    }

    fun finishAttempt(
        attemptId: String,
        elapsedMs: Long,
        result: String,
        failurePhase: String?,
    ) {
        require(result in setOf("SAVED", "CAMERA_FAILURE", "STORAGE_FAILURE", "INTERRUPTED"))
        val previous =
            attemptValue(attemptId, "disk_drained_elapsed_ms")
                ?: attemptValue(attemptId, "camera_invoke_ready_elapsed_ms")
                ?: attemptValue(attemptId, "prepare_complete_elapsed_ms")
                ?: attemptValue(attemptId, "request_elapsed_ms")
        check(previous != null && elapsedMs >= previous) { "attempt_phase_order" }
        check(
            database.update(
                "capture_attempts",
                ContentValues().apply {
                    put("commit_complete_elapsed_ms", elapsedMs)
                    put("result", result)
                    put("failure_phase", failurePhase)
                },
                "attempt_id=? AND result='PENDING'",
                arrayOf(attemptId),
            ) == 1,
        ) { "missing_pending_attempt" }
    }

    fun diagnostics(
        preferredSessionId: String?,
        nowElapsedMs: Long,
    ): SessionDiagnostics? {
        val session = selectSession(preferredSessionId) ?: return null
        val samples = samples(session.id)
        val captures = captures(session.id)
        val frameFacts =
            database
                .rawQuery(
                    "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM frames WHERE state=1 AND session_id=?",
                    arrayOf(session.id),
                ).use {
                    check(it.moveToFirst())
                    it.getLong(0) to it.getLong(1)
                }
        val actualSizes =
            database
                .rawQuery(
                    "SELECT actual_width, actual_height, COUNT(*) FROM frames " +
                        "WHERE state=1 AND session_id=? AND actual_width IS NOT NULL AND actual_height IS NOT NULL " +
                        "GROUP BY actual_width, actual_height ORDER BY actual_width, actual_height",
                    arrayOf(session.id),
                ).use { rows ->
                    buildList {
                        while (rows.moveToNext()) add("${rows.getInt(0)}x${rows.getInt(1)} (${rows.getLong(2)})")
                    }.joinToString(", ")
                }
        val gaps = captures.zipWithNext { first, second -> second.requestElapsedMs - first.requestElapsedMs }
        val overruns =
            captures
                .mapNotNull { capture -> capture.scheduledDueElapsedMs?.let { capture.requestElapsedMs - it } }
                .map { it.coerceAtLeast(0) }
                .filter { it > 0 }
        val pipeline = captures.mapNotNull { it.commitCompleteElapsedMs?.minus(it.requestElapsedMs) }.filter { it >= 0 }
        val saves =
            captures
                .filter { it.result == "SAVED" }
                .mapNotNull { capture ->
                    val drained = capture.diskDrainedElapsedMs
                    if (drained == null) null else capture.commitCompleteElapsedMs?.minus(drained)
                }.filter { it >= 0 }
        val startSample = samples.firstOrNull { it.sample.reason == "START" }?.sample
        val endSample = samples.lastOrNull { it.sample.reason == "END" }?.sample
        val firstBattery = startSample?.takeIf(::validBattery)
        val lastBattery = endSample?.takeIf(::validBattery)
        val comparable =
            firstBattery != null && lastBattery != null &&
                samples.isNotEmpty() &&
                samples.all { record ->
                    val sample = record.sample
                    validBattery(sample) && sample.batteryScale == firstBattery.batteryScale &&
                        sample.batteryPlugged == 0 && sample.batteryStatus == BatteryManager.BATTERY_STATUS_DISCHARGING
                }
        val temperatures = samples.mapNotNull { it.sample.batteryTemperatureTenthsC }
        val duration =
            when {
                session.endElapsedMs != null -> (session.endElapsedMs - session.startElapsedMs).takeIf { it >= 0 }
                session.completionStatus == "OPEN" -> (nowElapsedMs - session.startElapsedMs).takeIf { it >= 0 }
                else -> null
            }
        val sampleReferenceElapsedMs =
            when {
                session.completionStatus == "OPEN" -> nowElapsedMs
                session.endElapsedMs != null -> session.endElapsedMs
                else -> null
            }
        return SessionDiagnostics(
            session,
            duration,
            samples.size,
            sampleReferenceElapsedMs
                ?.let { reference ->
                    samples
                        .lastOrNull()
                        ?.sample
                        ?.elapsedMs
                        ?.let { reference - it }
                }?.takeIf { it >= 0 },
            captures.size,
            captures.count { it.result == "SAVED" },
            captures.count { it.result == "CAMERA_FAILURE" },
            captures.count { it.result == "STORAGE_FAILURE" },
            captures.count { it.result == "INTERRUPTED" },
            frameFacts.first,
            frameFacts.second,
            distribution(gaps),
            overruns.size,
            overruns.maxOrNull(),
            distribution(pipeline),
            distribution(saves),
            firstBattery?.batteryPercent,
            lastBattery?.batteryPercent,
            if (comparable) lastBattery!!.batteryPercent!! - firstBattery!!.batteryPercent!! else null,
            temperatures.minOrNull(),
            temperatures.maxOrNull(),
            samples.mapNotNull { it.sample.thermalStatus }.maxOrNull(),
            actualSizes.ifEmpty { "unknown" },
            startSample?.publicFreeBytes,
            endSample?.publicFreeBytes,
            samples.mapNotNull { it.sample.publicFreeBytes }.minOrNull(),
            startSample?.privateFreeBytes,
            endSample?.privateFreeBytes,
            samples.mapNotNull { it.sample.privateFreeBytes }.minOrNull(),
        )
    }

    fun report(preferredSessionId: String?): LongRunReport? {
        val session = selectSession(preferredSessionId) ?: return null
        if (session.completionStatus == "OPEN") return null
        return LongRunReport(session, samples(session.id), captures(session.id))
    }

    private fun insertSample(
        sessionId: String,
        sample: TelemetrySample,
    ) {
        database.insertOrThrow(
            "telemetry_samples",
            null,
            ContentValues().apply {
                put("session_id", sessionId)
                put("wall_ms", sample.wallMs)
                put("elapsed_ms", sample.elapsedMs)
                put("reason", sample.reason)
                put("battery_level", sample.batteryLevel)
                put("battery_scale", sample.batteryScale)
                put("battery_percent", sample.batteryPercent)
                put("battery_status", sample.batteryStatus)
                put("battery_plugged", sample.batteryPlugged)
                put("battery_temperature_tenths_c", sample.batteryTemperatureTenthsC)
                put("charge_counter_uah", sample.chargeCounterUah)
                put("current_now_ua", sample.currentNowUa)
                put("current_average_ua", sample.currentAverageUa)
                put("energy_counter_nwh", sample.energyCounterNwh)
                put("thermal_status", sample.thermalStatus)
                put("public_free_bytes", sample.publicFreeBytes)
                put("private_free_bytes", sample.privateFreeBytes)
            },
        )
    }

    private fun insertAttempt(
        attempt: CaptureAttemptStart,
        result: String,
        commitCompleteElapsedMs: Long?,
        failurePhase: String?,
    ) {
        database.insertOrThrow(
            "capture_attempts",
            null,
            ContentValues().apply {
                put("attempt_id", attempt.id)
                put("session_id", attempt.sessionId)
                put("request_wall_ms", attempt.requestWallMs)
                put("request_elapsed_ms", attempt.requestElapsedMs)
                put("scheduled_due_elapsed_ms", attempt.scheduledDueElapsedMs)
                put("requested_interval_ms", attempt.requestedIntervalMs)
                put("commit_complete_elapsed_ms", commitCompleteElapsedMs)
                put("result", result)
                put("failure_phase", failurePhase)
            },
        )
    }

    private fun sessionIsOpen(sessionId: String): Boolean =
        database.rawQuery("SELECT COUNT(*) FROM capture_sessions WHERE id=? AND completion_status='OPEN'", arrayOf(sessionId)).use {
            check(it.moveToFirst())
            it.getInt(0) == 1
        }

    private fun attemptValue(
        attemptId: String,
        column: String,
    ): Long? =
        database.rawQuery("SELECT $column FROM capture_attempts WHERE attempt_id=?", arrayOf(attemptId)).use {
            check(it.moveToFirst()) { "missing_attempt" }
            if (it.isNull(0)) null else it.getLong(0)
        }

    private fun selectSession(preferredSessionId: String?): SessionRecord? =
        if (preferredSessionId != null) {
            sessions("id=?", arrayOf(preferredSessionId)).singleOrNull()
        } else {
            sessions("1=1 ORDER BY rowid DESC LIMIT 1").singleOrNull()
        }

    private fun sessions(
        where: String,
        args: Array<String>? = null,
    ): List<SessionRecord> =
        database.rawQuery("SELECT * FROM capture_sessions WHERE $where", args).use { rows ->
            buildList { while (rows.moveToNext()) add(rows.sessionRecord()) }
        }

    private fun samples(sessionId: String): List<SampleRecord> =
        database
            .rawQuery(
                "SELECT * FROM telemetry_samples WHERE session_id=? ORDER BY elapsed_ms, sample_id",
                arrayOf(sessionId),
            ).use { rows ->
                buildList {
                    while (rows.moveToNext()) {
                        add(
                            SampleRecord(
                                rows.long("sample_id")!!,
                                sessionId,
                                TelemetrySample(
                                    rows.long("wall_ms")!!,
                                    rows.long("elapsed_ms")!!,
                                    rows.text("reason")!!,
                                    rows.int("battery_level"),
                                    rows.int("battery_scale"),
                                    rows.double("battery_percent"),
                                    rows.int("battery_status"),
                                    rows.int("battery_plugged"),
                                    rows.int("battery_temperature_tenths_c"),
                                    rows.long("charge_counter_uah"),
                                    rows.long("current_now_ua"),
                                    rows.long("current_average_ua"),
                                    rows.long("energy_counter_nwh"),
                                    rows.int("thermal_status"),
                                    rows.long("public_free_bytes"),
                                    rows.long("private_free_bytes"),
                                ),
                            ),
                        )
                    }
                }
            }

    private fun captures(sessionId: String): List<CaptureAttemptRecord> =
        database
            .rawQuery(
                "SELECT * FROM capture_attempts WHERE session_id=? ORDER BY request_elapsed_ms, rowid",
                arrayOf(sessionId),
            ).use { rows ->
                buildList {
                    while (rows.moveToNext()) {
                        add(
                            CaptureAttemptRecord(
                                rows.text("attempt_id")!!,
                                sessionId,
                                rows.text("frame_id"),
                                rows.long("request_wall_ms")!!,
                                rows.long("request_elapsed_ms")!!,
                                rows.long("scheduled_due_elapsed_ms"),
                                rows.long("requested_interval_ms")!!,
                                rows.long("prepare_complete_elapsed_ms"),
                                rows.long("camera_invoke_ready_elapsed_ms"),
                                rows.long("camera_terminal_elapsed_ms"),
                                rows.long("disk_drained_elapsed_ms"),
                                rows.long("commit_complete_elapsed_ms"),
                                rows.text("result")!!,
                                rows.text("failure_phase"),
                            ),
                        )
                    }
                }
            }

    private fun Cursor.sessionRecord() =
        SessionRecord(
            text("id")!!,
            text("profile_id")!!,
            int("requested_width")!!,
            int("requested_height")!!,
            int("jpeg_quality")!!,
            text("requested_settings")!!,
            long("start_wall_ms")!!,
            long("start_elapsed_ms")!!,
            long("end_wall_ms"),
            long("end_elapsed_ms"),
            long("recovery_detected_wall_ms"),
            text("terminal_reason"),
            text("completion_status")!!,
            text("manufacturer")!!,
            text("model")!!,
            text("android_release")!!,
            int("sdk_int")!!,
            text("build_id")!!,
            text("app_version")!!,
            long("app_version_code")!!,
            int("negotiated_width"),
            int("negotiated_height"),
        )

    private fun Cursor.text(name: String): String? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getString(it) }

    private fun Cursor.long(name: String): Long? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getLong(it) }

    private fun Cursor.int(name: String): Int? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getInt(it) }

    private fun Cursor.double(name: String): Double? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getDouble(it) }

    private fun validBattery(sample: TelemetrySample): Boolean {
        val level = sample.batteryLevel ?: return false
        val scale = sample.batteryScale ?: return false
        val percent = sample.batteryPercent ?: return false
        return scale > 0 && level in 0..scale && percent.isFinite() && abs(percent - level * 100.0 / scale) < 0.000_001
    }

    companion object {
        const val JOURNAL_VERSION = 2

        fun createSchema(database: SQLiteDatabase) {
            database.execSQL(
                """
                CREATE TABLE IF NOT EXISTS capture_sessions (
                    id TEXT PRIMARY KEY, journal_version INTEGER NOT NULL,
                    profile_id TEXT NOT NULL, requested_width INTEGER NOT NULL,
                    requested_height INTEGER NOT NULL, jpeg_quality INTEGER NOT NULL,
                    requested_settings TEXT NOT NULL,
                    start_wall_ms INTEGER NOT NULL, start_elapsed_ms INTEGER NOT NULL,
                    end_wall_ms INTEGER, end_elapsed_ms INTEGER,
                    recovery_detected_wall_ms INTEGER,
                    terminal_reason TEXT, completion_status TEXT NOT NULL,
                    manufacturer TEXT NOT NULL, model TEXT NOT NULL,
                    android_release TEXT NOT NULL, sdk_int INTEGER NOT NULL,
                    build_id TEXT NOT NULL, app_version TEXT NOT NULL, app_version_code INTEGER NOT NULL,
                    negotiated_width INTEGER, negotiated_height INTEGER
                )
                """.trimIndent(),
            )
            database.execSQL(
                """
                CREATE TABLE IF NOT EXISTS telemetry_samples (
                    sample_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    wall_ms INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL, reason TEXT NOT NULL,
                    battery_level INTEGER, battery_scale INTEGER, battery_percent REAL,
                    battery_status INTEGER, battery_plugged INTEGER, battery_temperature_tenths_c INTEGER,
                    charge_counter_uah INTEGER, current_now_ua INTEGER, current_average_ua INTEGER,
                    energy_counter_nwh INTEGER, thermal_status INTEGER,
                    public_free_bytes INTEGER, private_free_bytes INTEGER
                )
                """.trimIndent(),
            )
            database.execSQL(
                """
                CREATE TABLE IF NOT EXISTS capture_attempts (
                    attempt_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, frame_id TEXT,
                    request_wall_ms INTEGER NOT NULL, request_elapsed_ms INTEGER NOT NULL,
                    scheduled_due_elapsed_ms INTEGER,
                    requested_interval_ms INTEGER NOT NULL,
                    prepare_complete_elapsed_ms INTEGER, camera_invoke_ready_elapsed_ms INTEGER,
                    camera_terminal_elapsed_ms INTEGER, disk_drained_elapsed_ms INTEGER,
                    commit_complete_elapsed_ms INTEGER, result TEXT NOT NULL, failure_phase TEXT
                )
                """.trimIndent(),
            )
            database.execSQL("CREATE INDEX IF NOT EXISTS sessions_timeline ON capture_sessions(start_wall_ms, id)")
            database.execSQL("CREATE INDEX IF NOT EXISTS samples_session_timeline ON telemetry_samples(session_id, elapsed_ms, sample_id)")
            database.execSQL(
                "CREATE INDEX IF NOT EXISTS attempts_session_timeline ON capture_attempts(session_id, request_elapsed_ms, attempt_id)",
            )
            database.execSQL("CREATE INDEX IF NOT EXISTS frames_session_state ON frames(session_id, state)")
        }

        fun migrateV3ToV4(database: SQLiteDatabase) {
            database.execSQL("ALTER TABLE capture_sessions ADD COLUMN recovery_detected_wall_ms INTEGER")
            database.execSQL("ALTER TABLE capture_attempts ADD COLUMN scheduled_due_elapsed_ms INTEGER")
            database.execSQL(
                "ALTER TABLE capture_attempts RENAME COLUMN camera_submit_elapsed_ms TO camera_invoke_ready_elapsed_ms",
            )
        }

        private fun distribution(values: List<Long>): Distribution? {
            if (values.isEmpty()) return null
            val sorted = values.sorted()

            fun percentile(percent: Double): Long = sorted[(ceil(percent * sorted.size).toInt() - 1).coerceIn(0, sorted.lastIndex)]
            return Distribution(percentile(0.50), percentile(0.95), sorted.last())
        }
    }
}
