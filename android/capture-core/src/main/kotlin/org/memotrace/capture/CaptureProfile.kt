package org.memotrace.capture

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID

/** IDs and settings are persisted facts. Change settings by adding a new version, never in place. */
enum class CaptureProfile(
    val id: String,
    val width: Int,
    val height: Int,
    val quality: Int,
    val wide: Boolean,
) {
    REFERENCE("v1-4000x3000-q95", 4000, 3000, 95, false),
    COMPRESSION("v1-4000x3000-q80", 4000, 3000, 80, false),
    WIDE_90("v1-1920x1080-q90", 1920, 1080, 90, true),
    WIDE_80("v1-1920x1080-q80", 1920, 1080, 80, true),
    COMPACT_90("v1-1440x1080-q90", 1440, 1080, 90, false),
    COMPACT_80("v1-1440x1080-q80", 1440, 1080, 80, false),
    ;

    companion object {
        val DEFAULT = COMPACT_90

        fun fromId(id: String?): CaptureProfile? = entries.firstOrNull { it.id == id }
    }
}

/** One immutable snapshot per Start, including a collision-resistant Gallery album name. */
class CaptureSession(
    val profile: CaptureProfile,
    wallMs: Long,
    val id: String = UUID.randomUUID().toString(),
) {
    init {
        require(UUID.fromString(id).toString() == id) { "invalid_session_id" }
    }

    val leaf: String =
        "${profile.id}_${DateTimeFormatter.ofPattern("uuuuMMdd-HHmmss").withZone(ZoneOffset.UTC).format(Instant.ofEpochMilli(wallMs))}Z_$id"
    val relativePath = "${profile.id}/$leaf/"
}
