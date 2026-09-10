package org.memotrace.recorder.storage

import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

object LongRunReportWriter {
    const val SCHEMA = "memotrace-long-run-report-v3"
    const val SUGGESTED_FILENAME = "memotrace-long-run-report.zip"
    private const val MEASUREMENT_SCOPE = "battery current, charge, energy and temperature are whole-device OEM measurements"
    private const val LATENCY_SCOPE =
        "pipeline is request-to-final-commit; successful save is writer-drained-to-final-commit; neither is shutter timing"
    private const val INVOCATION_SCOPE =
        "camera_invoke_ready_offset_ms is durable immediately before CameraX invocation; it is not CameraX acceptance"
    private const val TIMING_SCOPE = "all exported times are milliseconds relative to the session start; wall and boot times are omitted"

    fun write(
        report: LongRunReport,
        output: OutputStream,
    ) {
        ZipOutputStream(output, StandardCharsets.UTF_8).use { zip ->
            val manifest =
                """{"schema":"$SCHEMA","session_ordinal":1,"measurement_scope":"$MEASUREMENT_SCOPE",""" +
                    """"latency_scope":"$LATENCY_SCOPE","invocation_scope":"$INVOCATION_SCOPE",""" +
                    """"timing_scope":"$TIMING_SCOPE"}""" +
                    "\n"
            entry(
                zip,
                "manifest.json",
                manifest,
            )
            entry(zip, "sessions.csv", sessions(report.session))
            entry(zip, "samples.csv", samples(report.samples, report.session.startElapsedMs))
            entry(zip, "captures.csv", captures(report.captures, report.session.startElapsedMs))
        }
    }

    private fun sessions(session: SessionRecord): String =
        csv(
            listOf(
                listOf(
                    "session_ordinal",
                    "profile_id",
                    "requested_width",
                    "requested_height",
                    "quality",
                    "start_offset_ms",
                    "end_offset_ms",
                    "recovery_detected",
                    "terminal_reason",
                    "completion_status",
                    "manufacturer",
                    "model",
                    "android_release",
                    "sdk_int",
                    "build_id",
                    "app_version",
                    "app_version_code",
                    "negotiated_width",
                    "negotiated_height",
                ),
                listOf(
                    1,
                    session.profileId,
                    session.requestedWidth,
                    session.requestedHeight,
                    session.jpegQuality,
                    0,
                    offset(session.endElapsedMs, session.startElapsedMs),
                    session.recoveryDetectedWallMs != null,
                    session.terminalReason,
                    session.completionStatus,
                    session.manufacturer,
                    session.model,
                    session.androidRelease,
                    session.sdkInt,
                    session.buildId,
                    session.appVersion,
                    session.appVersionCode,
                    session.negotiatedWidth,
                    session.negotiatedHeight,
                ),
            ),
        )

    private fun samples(
        samples: List<SampleRecord>,
        startElapsedMs: Long,
    ): String {
        val rows =
            mutableListOf<List<Any?>>()
                .apply {
                    add(
                        listOf(
                            "sample_ordinal",
                            "sample_offset_ms",
                            "reason",
                            "battery_level",
                            "battery_scale",
                            "battery_percent",
                            "battery_status",
                            "battery_plugged",
                            "battery_temperature_tenths_c",
                            "charge_counter_uah",
                            "current_now_ua",
                            "current_average_ua",
                            "energy_counter_nwh",
                            "thermal_status",
                            "public_free_bytes",
                            "private_free_bytes",
                        ),
                    )
                    for ((index, record) in samples.withIndex()) {
                        val sample = record.sample
                        add(
                            listOf(
                                index + 1,
                                offset(sample.elapsedMs, startElapsedMs),
                                sample.reason,
                                sample.batteryLevel,
                                sample.batteryScale,
                                sample.batteryPercent,
                                sample.batteryStatus,
                                sample.batteryPlugged,
                                sample.batteryTemperatureTenthsC,
                                sample.chargeCounterUah,
                                sample.currentNowUa,
                                sample.currentAverageUa,
                                sample.energyCounterNwh,
                                sample.thermalStatus,
                                sample.publicFreeBytes,
                                sample.privateFreeBytes,
                            ),
                        )
                    }
                }
        return csv(rows)
    }

    private fun captures(
        captures: List<CaptureAttemptRecord>,
        startElapsedMs: Long,
    ): String {
        val frameOrdinals =
            captures
                .mapNotNull { it.frameId }
                .distinct()
                .withIndex()
                .associate { (index, frameId) -> frameId to index + 1 }
        val rows =
            mutableListOf<List<Any?>>()
                .apply {
                    add(
                        listOf(
                            "attempt_ordinal",
                            "frame_ordinal",
                            "request_offset_ms",
                            "scheduled_due_offset_ms",
                            "effective_interval_ms",
                            "prepare_complete_offset_ms",
                            "camera_invoke_ready_offset_ms",
                            "camera_terminal_offset_ms",
                            "disk_drained_offset_ms",
                            "commit_complete_offset_ms",
                            "result",
                            "failure_phase",
                        ),
                    )
                    for ((index, capture) in captures.withIndex()) {
                        add(
                            listOf(
                                index + 1,
                                capture.frameId?.let(frameOrdinals::get),
                                offset(capture.requestElapsedMs, startElapsedMs),
                                offset(capture.scheduledDueElapsedMs, startElapsedMs),
                                capture.requestedIntervalMs,
                                offset(capture.prepareCompleteElapsedMs, startElapsedMs),
                                offset(capture.cameraInvokeReadyElapsedMs, startElapsedMs),
                                offset(capture.cameraTerminalElapsedMs, startElapsedMs),
                                offset(capture.diskDrainedElapsedMs, startElapsedMs),
                                offset(capture.commitCompleteElapsedMs, startElapsedMs),
                                capture.result,
                                capture.failurePhase,
                            ),
                        )
                    }
                }
        return csv(rows)
    }

    private fun offset(
        elapsedMs: Long?,
        startElapsedMs: Long,
    ): Long? = elapsedMs?.minus(startElapsedMs)

    private fun csv(rows: List<List<Any?>>): String =
        rows.joinToString(separator = "\n", postfix = "\n") { row -> row.joinToString(",") { csvValue(it) } }

    private fun csvValue(value: Any?): String {
        if (value == null) return ""
        val text = value.toString()
        return if (text.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) {
            "\"${text.replace("\"", "\"\"")}\""
        } else {
            text
        }
    }

    private fun entry(
        zip: ZipOutputStream,
        name: String,
        text: String,
    ) {
        zip.putNextEntry(ZipEntry(name).apply { time = 0L })
        zip.write(text.toByteArray(StandardCharsets.UTF_8))
        zip.closeEntry()
    }
}
