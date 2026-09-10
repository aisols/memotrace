package org.memotrace.recorder.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.memotrace.recorder.R
import org.memotrace.recorder.RecorderApplication
import org.memotrace.recorder.storage.Distribution
import org.memotrace.recorder.storage.LongRunReport
import org.memotrace.recorder.storage.LongRunReportWriter
import org.memotrace.recorder.storage.SessionDiagnostics
import java.text.DateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

open class DiagnosticsActivity : Activity() {
    private val app get() = application as RecorderApplication
    private val exportExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private lateinit var details: TextView
    private lateinit var export: Button
    private lateinit var exportStatus: TextView
    private var pendingReport: LongRunReport? = null
    private var exportReservation: Long? = null
    private var writing = false
    private var visible = false
    private var loading = false
    private var refreshAfterLoad = false
    private var observedSessionOpen: Boolean? = null
    private val observer: () -> Unit = {
        export.isEnabled = app.canExport
        val wasOpen = observedSessionOpen
        observedSessionOpen = app.sessionOpen
        val justClosed = wasOpen == true && !app.sessionOpen
        if (justClosed && loading) refreshAfterLoad = true
        if (!loading && (wasOpen == null || justClosed)) load()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(20), dp(12), dp(20), dp(20))
            }
        content.addView(
            TextView(this).apply {
                setText(R.string.diagnostics_title)
                textSize = 28f
                setTextColor(Color.rgb(20, 30, 24))
            },
            LinearLayout.LayoutParams(-1, -2),
        )
        details =
            TextView(this).apply {
                id = R.id.diagnostics_details
                setText(R.string.diagnostics_loading)
                textSize = 18f
                setTextColor(Color.rgb(20, 30, 24))
                setPadding(0, dp(12), 0, dp(12))
                accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
                content.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
        content.addView(
            TextView(this).apply {
                setText(R.string.diagnostics_caveat)
                textSize = 17f
                setTextColor(Color.rgb(80, 42, 20))
                setPadding(0, dp(8), 0, dp(8))
            },
            LinearLayout.LayoutParams(-1, -2),
        )
        export = control(content, R.id.export_report, R.string.export_report)
        export.setOnClickListener { prepareExport() }
        exportStatus =
            TextView(this).apply {
                id = R.id.export_status
                setText(R.string.export_provider_warning)
                textSize = 17f
                setTextColor(Color.rgb(20, 30, 24))
                setPadding(0, dp(8), 0, dp(8))
                accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
                content.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
        control(content, R.id.diagnostics_close, R.string.close).setOnClickListener { finish() }
        val scroll =
            ScrollView(this).apply {
                id = R.id.diagnostics_scroll
                isFillViewport = true
                setBackgroundColor(Color.rgb(250, 250, 246))
                addView(content)
            }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val safe = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
            insets
        }
        setContentView(scroll)
    }

    override fun onStart() {
        super.onStart()
        visible = true
        app.observe(observer)
    }

    override fun onStop() {
        visible = false
        observedSessionOpen = null
        refreshAfterLoad = false
        app.removeObserver(observer)
        super.onStop()
    }

    private fun load() {
        loading = true
        app.loadDiagnostics { diagnostics ->
            loading = false
            if (!visible) return@loadDiagnostics
            if (refreshAfterLoad) {
                refreshAfterLoad = false
                load()
                return@loadDiagnostics
            }
            details.text = diagnostics?.let(::render) ?: getString(R.string.diagnostics_none)
            export.isEnabled = app.canExport && diagnostics?.session?.completionStatus != "OPEN"
        }
    }

    private fun render(diagnostics: SessionDiagnostics): String {
        val session = diagnostics.session
        val date = DateFormat.getDateTimeInstance()
        return buildString {
            appendLine(getString(R.string.diagnostics_session, session.id))
            appendLine(getString(R.string.diagnostics_profile, session.requestedWidth, session.requestedHeight, session.jpegQuality))
            appendLine(getString(R.string.diagnostics_start, date.format(Date(session.startWallMs))))
            appendLine(
                getString(
                    R.string.diagnostics_end,
                    session.endWallMs?.let { date.format(Date(it)) }
                        ?: getString(if (session.completionStatus == "OPEN") R.string.diagnostics_running else R.string.size_unknown),
                ),
            )
            session.recoveryDetectedWallMs?.let {
                appendLine(getString(R.string.diagnostics_recovery_detected, date.format(Date(it))))
            }
            appendLine(
                getString(R.string.diagnostics_duration, diagnostics.durationMs?.let(::duration) ?: getString(R.string.size_unknown)),
            )
            appendLine(getString(R.string.diagnostics_terminal, session.completionStatus, session.terminalReason ?: "-"))
            appendLine(
                getString(
                    R.string.diagnostics_samples,
                    diagnostics.sampleCount,
                    diagnostics.sampleAgeMs?.let { "${it / 1_000} s" } ?: getString(R.string.size_unknown),
                ),
            )
            appendLine(
                getString(
                    R.string.diagnostics_attempts,
                    diagnostics.attemptCount,
                    diagnostics.successCount,
                    diagnostics.cameraFailureCount,
                    diagnostics.storageFailureCount,
                    diagnostics.interruptedCount,
                ),
            )
            appendLine(getString(R.string.diagnostics_frames, diagnostics.frameCount, diagnostics.frameBytes))
            appendLine(
                getString(
                    R.string.diagnostics_gaps,
                    distribution(diagnostics.requestGaps),
                    diagnostics.overrunCount,
                    diagnostics.overrunMaxMs?.toString() ?: "-",
                ),
            )
            appendLine(getString(R.string.diagnostics_pipeline, distribution(diagnostics.pipelineLatency)))
            appendLine(getString(R.string.diagnostics_save, distribution(diagnostics.saveLatency)))
            appendLine(
                getString(
                    R.string.diagnostics_battery,
                    percent(diagnostics.batteryStartPercent),
                    percent(diagnostics.batteryEndPercent),
                    diagnostics.batteryDeltaPercent?.let { String.format(Locale.ROOT, "%+.2f", it) } ?: "-",
                ),
            )
            appendLine(
                getString(
                    R.string.diagnostics_temperature,
                    tenths(diagnostics.temperatureMinTenthsC),
                    tenths(diagnostics.temperatureMaxTenthsC),
                ),
            )
            appendLine(getString(R.string.diagnostics_thermal, diagnostics.maxThermalStatus?.toString() ?: "-"))
            appendLine(
                getString(
                    R.string.diagnostics_device,
                    session.manufacturer,
                    session.model,
                    session.androidRelease,
                    session.sdkInt,
                    session.buildId,
                    session.appVersion,
                    session.appVersionCode,
                ),
            )
            appendLine(
                getString(
                    R.string.diagnostics_storage,
                    storage(diagnostics.publicStorageStartBytes),
                    storage(diagnostics.publicStorageEndBytes),
                    storage(diagnostics.publicStorageMinimumBytes),
                    storage(diagnostics.privateStorageStartBytes),
                    storage(diagnostics.privateStorageEndBytes),
                    storage(diagnostics.privateStorageMinimumBytes),
                ),
            )
            appendLine(
                getString(
                    R.string.diagnostics_dimensions,
                    session.negotiatedWidth?.let { "$it x ${session.negotiatedHeight}" } ?: getString(R.string.size_unknown),
                    diagnostics.actualSizes,
                ),
            )
            append(getString(R.string.quarantined_count, app.summary.quarantinedCount))
        }
    }

    private fun prepareExport() {
        val reservation = app.reserveExport()
        if (reservation == null) {
            exportStatus.setText(R.string.export_wait_for_pause)
            return
        }
        exportReservation = reservation
        export.isEnabled = false
        exportStatus.setText(R.string.export_preparing)
        app.loadReport(reservation) { report ->
            if (!visible || report == null || !app.ownsExport(reservation)) {
                releaseExport(reservation)
                exportStatus.setText(R.string.export_wait_for_pause)
                export.isEnabled = app.canExport
                return@loadReport
            }
            pendingReport = report
            try {
                startActivityForResult(
                    Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "application/zip"
                        putExtra(Intent.EXTRA_TITLE, LongRunReportWriter.SUGGESTED_FILENAME)
                    },
                    CREATE_REPORT,
                )
            } catch (_: RuntimeException) {
                pendingReport = null
                releaseExport(reservation)
                exportStatus.setText(R.string.export_failed)
                export.isEnabled = app.canExport
            }
        }
    }

    @Deprecated("Activity result API is sufficient for this internal, single-document flow")
    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: Intent?,
    ) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != CREATE_REPORT) return
        val reservation = exportReservation
        val report = pendingReport
        pendingReport = null
        if (reservation == null || resultCode != RESULT_OK || data?.data == null || report == null) {
            if (reservation != null) releaseExport(reservation)
            exportStatus.setText(R.string.export_cancelled)
            export.isEnabled = app.canExport
            return
        }
        val destination = data.data!!
        writing = true
        exportStatus.setText(R.string.export_writing)
        exportExecutor.execute {
            val success =
                try {
                    contentResolver.openOutputStream(destination, "w").use { stream ->
                        LongRunReportWriter.write(report, checkNotNull(stream) { "provider_stream" })
                    }
                    true
                } catch (_: Exception) {
                    false
                }
            runOnUiThread {
                writing = false
                releaseExport(reservation)
                if (!isDestroyed) {
                    exportStatus.setText(if (success) R.string.export_complete else R.string.export_failed)
                    export.isEnabled = app.canExport
                }
            }
        }
    }

    override fun onDestroy() {
        if (!writing) exportReservation?.let(::releaseExport)
        pendingReport = null
        exportExecutor.shutdown()
        super.onDestroy()
    }

    private fun control(
        content: LinearLayout,
        id: Int,
        title: Int,
    ): Button =
        TremorButton(this).apply {
            this.id = id
            setText(title)
            textSize = 24f
            isAllCaps = false
            setSingleLine(false)
            minHeight = dp(88)
            content.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        }

    private fun distribution(value: Distribution?): String = value?.let { "${it.p50} / ${it.p95} / ${it.max} ms" } ?: "-"

    private fun percent(value: Double?): String = value?.let { String.format(Locale.ROOT, "%.2f", it) } ?: "-"

    private fun tenths(value: Int?): String = value?.let { String.format(Locale.ROOT, "%.1f", it / 10.0) } ?: "-"

    private fun storage(value: Long?): String = value?.let { "${it / (1024 * 1024)} MiB" } ?: "-"

    private fun duration(value: Long): String = "%d:%02d:%02d".format(value / 3_600_000, value / 60_000 % 60, value / 1_000 % 60)

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val CREATE_REPORT = 41
    }

    private fun releaseExport(reservation: Long) {
        app.releaseExport(reservation)
        if (exportReservation == reservation) exportReservation = null
    }
}
