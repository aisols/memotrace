package org.memotrace.recorder.ui

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import androidx.core.net.toUri
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.SavedFrame

object FrameViewer {
    fun intent(frame: SavedFrame?): Intent? {
        if (frame?.availability != Availability.AVAILABLE || frame.uri == null) return null
        val uri = frame.uri.toUri()
        if (uri.scheme != "content" || uri.authority != "media") return null
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "image/jpeg")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            clipData = ClipData.newRawUri("MemoTrace JPEG", uri)
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
