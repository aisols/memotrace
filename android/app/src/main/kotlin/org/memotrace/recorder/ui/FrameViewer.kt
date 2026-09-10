package org.memotrace.recorder.ui

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import androidx.core.net.toUri
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.SavedFrame

object FrameViewer {
    fun intent(frame: SavedFrame?): Intent? {
        if (frame?.availability != Availability.AVAILABLE || frame.uri == null) return null
        val uri = frame.uri.toUri()
        if (!JpegViewerActivity.isMediaImageUri(uri)) return null
        return Intent(Intent.ACTION_VIEW).apply {
            setClassName("org.memotrace.recorder", JpegViewerActivity::class.java.name)
            setDataAndType(uri, "image/jpeg")
        }
    }

    fun open(
        activity: Activity,
        frame: SavedFrame?,
    ): Boolean {
        val intent = intent(frame) ?: return false
        return try {
            activity.startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            false
        } catch (_: SecurityException) {
            false
        }
    }
}
