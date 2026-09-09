package org.memotrace.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureProfileTest {
    @Test fun immutableVersionedMatrixAndDefault() {
        assertEquals(
            listOf(
                "v1-4000x3000-q95",
                "v1-4000x3000-q80",
                "v1-1920x1080-q90",
                "v1-1920x1080-q80",
                "v1-1440x1080-q90",
                "v1-1440x1080-q80",
            ),
            CaptureProfile.entries.map { it.id },
        )
        assertEquals(CaptureProfile.COMPACT_90, CaptureProfile.DEFAULT)
        for (profile in CaptureProfile.entries) {
            assertTrue(profile.id.matches(Regex("v1-${profile.width}x${profile.height}-q${profile.quality}")))
            assertTrue(profile.quality in 1..100)
            assertEquals(if (profile.wide) 16.0 / 9 else 4.0 / 3, profile.width.toDouble() / profile.height, 0.00001)
            assertEquals(profile, CaptureProfile.fromId(profile.id))
        }
        assertNull(CaptureProfile.fromId(null))
        assertNull(CaptureProfile.fromId("../bad"))
    }

    @Test fun sessionSnapshotsAreSafeReadableAndUnique() {
        val session = CaptureSession(CaptureProfile.DEFAULT, 0)
        assertEquals(CaptureProfile.DEFAULT, session.profile)
        assertTrue(session.leaf.startsWith("${session.profile.id}_19700101-000000Z_"))
        assertTrue(session.leaf.endsWith(session.id))
        assertEquals("${session.profile.id}/${session.leaf}/", session.relativePath)
        assertTrue(session.leaf.matches(Regex("[a-zA-Z0-9_-]+")))
        assertNotEquals(session.relativePath, CaptureSession(CaptureProfile.DEFAULT, 0).relativePath)
        assertThrows(IllegalArgumentException::class.java) { CaptureSession(CaptureProfile.DEFAULT, 0, "../bad") }
        assertThrows(IllegalArgumentException::class.java) { CaptureSession(CaptureProfile.DEFAULT, 0, "1-1-1-1-1") }
    }
}
