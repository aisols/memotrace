package org.memotrace.recorder.storage

import android.graphics.BitmapFactory
import java.io.InputStream
import java.security.MessageDigest

class JpegMetadata(
    val hash: String,
    val bytes: Long,
    val width: Int,
    val height: Int,
) {
    companion object {
        /** Bounds-only decoding, never a full Bitmap or an application re-encode. */
        fun read(open: () -> InputStream): JpegMetadata {
            val digest = MessageDigest.getInstance("SHA-256")
            var bytes = 0L
            var first = 0
            var last = 0
            open().use { input ->
                val buffer = ByteArray(32 * 1024)
                while (true) {
                    val size = input.read(buffer)
                    if (size < 0) break
                    for (index in 0 until minOf(size, (2 - bytes).coerceAtLeast(0).toInt())) {
                        val value = buffer[index].toInt() and 255
                        first = (first shl 8) or value
                    }
                    if (size >= 2) last = ((buffer[size - 2].toInt() and 255) shl 8) or (buffer[size - 1].toInt() and 255)
                    if (size == 1) last = ((last shl 8) or (buffer[0].toInt() and 255)) and 65535
                    bytes += size
                    digest.update(buffer, 0, size)
                }
            }
            check(bytes >= 4 && first == 0xffd8 && last == 0xffd9) { "invalid_jpeg" }
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            open().use { BitmapFactory.decodeStream(it, null, bounds) }
            check(bounds.outMimeType == "image/jpeg" && bounds.outWidth > 0 && bounds.outHeight > 0) { "invalid_jpeg_bounds" }
            return JpegMetadata(digest.digest().joinToString("") { "%02x".format(it) }, bytes, bounds.outWidth, bounds.outHeight)
        }
    }
}
