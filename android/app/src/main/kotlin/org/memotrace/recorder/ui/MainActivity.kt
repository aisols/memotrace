package org.memotrace.recorder.ui

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.memotrace.recorder.R
import org.memotrace.recorder.RecorderApplication
import org.memotrace.recorder.capture.RecorderService
import java.text.DateFormat
import java.util.Date

open class MainActivity : Activity() {
    private val app get() = application as RecorderApplication
    private lateinit var start: Button
    private lateinit var pause: Button
    private lateinit var status: TextView
    private lateinit var count: TextView
    private lateinit var last: TextView
    private lateinit var notificationNotice: TextView
    private lateinit var viewLast: Button
    private lateinit var diagnostics: Button
    private var dialog: AlertDialog? = null
    private var visible = false
    private val observer: () -> Unit = { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(20), dp(12), dp(20), dp(20))
            }
        val scroll =
            ScrollView(this).apply {
                id = R.id.recorder_scroll
                isFillViewport = true
                addView(content)
                setBackgroundColor(Color.rgb(250, 250, 246))
            }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val safe = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
            insets
        }

        fun label(
            id: Int,
            size: Float,
        ): TextView =
            TextView(this).apply {
                this.id = id
                textSize = size
                setTextColor(Color.rgb(20, 30, 24))
                setPadding(0, dp(6), 0, dp(6))
                content.addView(this, LinearLayout.LayoutParams(-1, -2))
            }
        label(View.NO_ID, 28f).setText(R.string.app_name)

        fun control(
            id: Int,
            title: Int,
            color: Int,
        ): Button =
            TremorButton(this).apply {
                this.id = id
                setText(title)
                textSize = 26f
                isAllCaps = false
                setSingleLine(false)
                minHeight = dp(88)
                setTextColor(Color.WHITE)
                backgroundTintList =
                    android.content.res.ColorStateList(
                        arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf()),
                        intArrayOf(Color.rgb(82, 91, 85), color),
                    )
                content.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
            }
        start = control(R.id.start_recording, R.string.start, Color.rgb(21, 77, 54))
        pause = control(R.id.pause_recording, R.string.pause, Color.rgb(115, 34, 29))
        start.setOnClickListener { requestStart() }
        pause.setOnClickListener {
            val id = app.sessionId ?: return@setOnClickListener
            if (!app.cancelStart(id)) {
                startService(
                    Intent(this, RecorderService::class.java)
                        .setAction(RecorderService.ACTION_PAUSE)
                        .putExtra(RecorderService.EXTRA_SESSION, id),
                )
            }
        }
        viewLast = control(R.id.view_last, R.string.view_last, Color.rgb(21, 77, 54))
        viewLast.setOnClickListener {
            app.refreshAvailability(lastOnly = true) {
                if (visible && !FrameViewer.open(this, app.summary.last)) showMessage(R.string.viewer_unavailable)
            }
        }
        diagnostics = control(R.id.open_diagnostics, R.string.open_diagnostics, Color.rgb(47, 62, 91))
        diagnostics.setOnClickListener { startActivity(Intent(this, DiagnosticsActivity::class.java)) }
        status = label(R.id.record_status, 22f).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        count = label(R.id.saved_count, 20f)
        last = label(R.id.last_saved, 18f)
        label(R.id.fixed_profile, 18f).setText(R.string.fixed_profile)
        label(View.NO_ID, 16f).setText(R.string.scope_note)
        notificationNotice = label(View.NO_ID, 16f).apply { setText(R.string.notification_permission_note) }
        setContentView(scroll)
    }

    override fun onStart() {
        super.onStart()
        visible = true
        app.observe(observer)
    }

    override fun onResume() {
        super.onResume()
        app.refreshAvailability()
    }

    override fun onStop() {
        visible = false
        app.removeObserver(observer)
        dialog?.dismiss()
        dialog = null
        super.onStop()
    }

    private fun requestStart() {
        if (!app.canStart) return
        if (!app.publicStorageConsent) {
            showChoices(
                R.string.public_consent_title,
                R.string.public_consent,
                listOf(
                    Triple(R.id.consent_accept, getString(R.string.consent_accept), {
                        if (visible && app.consentToPublicPictures()) requestStart()
                    }),
                ),
            )
            return
        }
        val needed = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.CAMERA)
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (needed.isNotEmpty()) requestPermissions(needed.toTypedArray(), 1) else startRecorder()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 1) return
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            // A permission result must not start a camera service after the Activity left the foreground.
            if (visible) startRecorder()
        } else {
            app.status = R.string.status_permission
            app.publish()
        }
    }

    private fun startRecorder() {
        if (!visible) return
        val session = app.reserveStart() ?: return
        try {
            ContextCompat.startForegroundService(
                this,
                Intent(this, RecorderService::class.java)
                    .setAction(RecorderService.ACTION_START)
                    .putExtra(RecorderService.EXTRA_SESSION, session.id),
            )
        } catch (_: RuntimeException) {
            app.cancelStart(session.id, R.string.status_camera_error)
        }
    }

    private fun render() {
        fun TextView.update(value: String) {
            if (text.toString() != value) text = value
        }
        val checking = !app.ready || (!app.sessionOpen && !app.canStart)
        status.update(getString(if (checking && app.status != R.string.status_storage_error) R.string.status_loading else app.status))
        start.isEnabled = app.canStart
        pause.isEnabled = app.sessionOpen
        notificationNotice.visibility =
            if (getSystemService(NotificationManager::class.java).areNotificationsEnabled()) View.GONE else View.VISIBLE
        count.update(
            if (app.ready) {
                getString(R.string.saved_count, app.summary.sessionCount, app.summary.count)
            } else {
                getString(R.string.stats_unknown)
            },
        )
        last.update(
            getString(
                R.string.last_saved,
                if (!app.ready) {
                    getString(R.string.stats_unknown)
                } else {
                    app.summary.lastSavedMs?.let {
                        getString(
                            R.string.last_saved_value,
                            DateFormat.getDateTimeInstance().format(Date(it)),
                            ((System.currentTimeMillis() - it).coerceAtLeast(0) / 1_000),
                        )
                    } ?: getString(R.string.never_saved)
                },
            ),
        )
        val saved = app.summary.last
        viewLast.isEnabled = app.ready && saved != null
        diagnostics.isEnabled = app.ready
    }

    private fun showMessage(message: Int) = showChoices(R.string.app_name, message, emptyList())

    private fun showChoices(
        title: Int,
        explanation: Int,
        choices: List<Triple<Int, String, () -> Unit>>,
    ) {
        dialog?.dismiss()
        val content =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16), dp(8), dp(16), dp(16))
            }
        content.addView(
            TextView(this).apply {
                setText(explanation)
                textSize = 20f
                setTextColor(Color.BLACK)
            },
        )
        val window =
            AlertDialog
                .Builder(this)
                .setTitle(title)
                .setView(
                    ScrollView(this).apply {
                        id = R.id.dialog_scroll
                        addView(content)
                    },
                ).create()
        for ((id, text, action) in choices + Triple(R.id.dialog_cancel, getString(R.string.dialog_cancel), {})) {
            content.addView(
                TremorButton(this).apply {
                    this.id = id
                    this.text = text
                    textSize = 22f
                    isAllCaps = false
                    setSingleLine(false)
                    minHeight = dp(88)
                    setOnClickListener {
                        window.dismiss()
                        action()
                    }
                },
                LinearLayout.LayoutParams(-1, -2),
            )
        }
        dialog = window
        window.show()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
