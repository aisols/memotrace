package org.memotrace.recorder

import android.database.sqlite.SQLiteException
import androidx.camera.core.ImageCapture
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.FrameStore
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.nio.file.Files
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
class FrameStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private val jpeg = byteArrayOf(-1, -40, 1, 2, 3, -1, -39)
    private val request = FrameRequest(10, 20, 2_000, "synthetic-settings", "SHADOW;true")

    @Before fun freeDisk() {
        ShadowStatFs.registerStats(temporary.root.path, 1_000_000, 500_000, 500_000)
    }

    @Test fun preservesBytesAndCommitsMetadata() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            assertEquals(0L, store.summary().count)
            assertNull(store.summary().lastSavedMs)
            val frame = store.prepare(request)
            frame.partial.writeBytes(jpeg)
            store.finish(frame, 30)
            assertArrayEquals(jpeg, File(root, "${frame.id}.jpg").readBytes())
            assertEquals(1L, store.summary().count)
            assertEquals(30L, store.summary().lastSavedMs)
            store.abandon(frame)
            assertTrue(File(root, "${frame.id}.jpg").exists())
        }
        FrameStore(root).use {
            it.recover(40)
            it.recover(50)
            assertEquals(1L, it.summary().count)
            assertEquals(30L, it.summary().lastSavedMs)
        }
    }

    @Test fun crashAtEveryCommitBoundary() {
        for (boundary in listOf("prepared", "file_synced", "renamed", "committed")) {
            val root = temporary.newFolder()
            FrameStore(root, checkpoint = { if (it == boundary) error("simulated_process_death") }).use { store ->
                assertThrows(IllegalStateException::class.java) {
                    val frame = store.prepare(request)
                    frame.partial.writeBytes(jpeg)
                    store.finish(frame, 30)
                }
            }
            FrameStore(root).use { store ->
                store.recover(40)
                store.recover(50)
                val retained = boundary == "renamed" || boundary == "committed"
                assertEquals(if (retained) 1L else 0L, store.summary().count)
                if (retained) assertArrayEquals(jpeg, root.listFiles()!!.single { it.extension == "jpg" }.readBytes())
                assertFalse(root.listFiles()!!.any { it.extension == "part" })
            }
        }
    }

    @Test fun interruptedPartialAndMissingOutputAreCleaned() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            store.prepare(request)
            store.prepare(request).partial.writeBytes(byteArrayOf(-1, -40, 1))
        }
        FrameStore(root).use {
            it.recover(40)
            assertEquals(0L, it.summary().count)
            assertFalse(root.listFiles()!!.any { file -> file.extension == "part" })
        }
    }

    @Test fun reserveStopsBeforeCreatingOrDeletingAnyOriginal() {
        val root = temporary.newFolder()
        var free = FrameStore.RESERVE_BYTES
        FrameStore(root, { free }).use { store ->
            val frame = store.prepare(request)
            frame.partial.writeBytes(jpeg)
            store.finish(frame, 30)
            free--
            assertThrows(IllegalStateException::class.java) { store.prepare(request) }
            assertEquals(1L, store.summary().count)
            assertArrayEquals(jpeg, File(root, "${frame.id}.jpg").readBytes())
        }
    }

    @Test fun invalidJpegCannotBecomeOriginal() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            for (bytes in listOf(byteArrayOf(), byteArrayOf(0, 0, 0, 0), byteArrayOf(-1, -40, 0, 0))) {
                val frame = store.prepare(request)
                frame.partial.writeBytes(bytes)
                assertThrows(IllegalStateException::class.java) { store.finish(frame, 30) }
                store.abandon(frame)
            }
            assertEquals(0L, store.summary().count)
        }
    }

    @Test fun damagedCommittedOriginalFailsClosedWithoutDeletion() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            val frame = store.prepare(request)
            frame.partial.writeBytes(jpeg)
            store.finish(frame, 30)
            File(root, "${frame.id}.jpg").appendBytes(byteArrayOf(0))
            assertTrue(File(root, "${frame.id}.jpg").exists())
        }
        FrameStore(root).use { store ->
            assertEquals("archive_inconsistent", assertThrows(IllegalStateException::class.java) { store.recover(40) }.message)
            assertEquals(1L, store.summary().count)
        }
    }

    @Test fun unindexedOriginalFailsClosedWithoutDeletion() {
        val root = temporary.newFolder()
        File(root, "orphan.jpg").writeBytes(jpeg)
        FrameStore(root).use { store ->
            assertThrows(IllegalStateException::class.java) { store.recover(40) }
            assertArrayEquals(jpeg, File(root, "orphan.jpg").readBytes())
        }
    }

    @Test fun missingCommittedOriginalIsReported() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            val frame = store.prepare(request)
            frame.partial.writeBytes(jpeg)
            store.finish(frame, 30)
            assertTrue(File(root, "${frame.id}.jpg").delete())
        }
        FrameStore(root).use { store ->
            assertEquals("archive_inconsistent", assertThrows(IllegalStateException::class.java) { store.recover(40) }.message)
            assertEquals(1L, store.summary().count)
        }
    }

    @Test fun backwardsWallClockDoesNotSelectAnOlderFrameAsLastSave() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            for (time in listOf(1_000L, 500L)) {
                val frame = store.prepare(request)
                frame.partial.writeBytes(jpeg)
                store.finish(frame, time)
            }
            assertEquals(2L, store.summary().count)
            assertEquals(500L, store.summary().lastSavedMs)
        }
    }

    @Test fun corruptDatabaseIsNotSilentlyDeletedByAndroid() {
        val root = temporary.newFolder()
        val brokenIndex = ByteArray(100) { it.toByte() }
        File(root, "index.sqlite").writeBytes(brokenIndex)
        File(root, "retained.jpg").writeBytes(jpeg)
        assertThrows(SQLiteException::class.java) { FrameStore(root) }
        assertArrayEquals(brokenIndex, File(root, "index.sqlite").readBytes())
        assertArrayEquals(jpeg, File(root, "retained.jpg").readBytes())
    }

    @Test fun recoveryRemovesActualCameraXScratchNamesButNotOtherFilesOrLinks() {
        val root = temporary.newFolder()
        lateinit var scratch: File
        lateinit var original: File
        FrameStore(root).use { store ->
            val frame = store.prepare(request)
            frame.partial.writeBytes(jpeg)
            store.finish(frame, 30)
            original = File(root, "${frame.id}.jpg")
            val pending = store.prepare(request)
            pending.partial.writeBytes(byteArrayOf(1))
            val factory =
                Class
                    .forName("androidx.camera.core.imagecapture.FileUtil")
                    .getDeclaredMethod("createTempFile", ImageCapture.OutputFileOptions::class.java)
                    .apply { isAccessible = true }
            scratch = factory.invoke(null, ImageCapture.OutputFileOptions.Builder(pending.partial).build()) as File
            assertTrue(scratch.name.startsWith("CameraX") && scratch.extension == "part")
            scratch.writeBytes(byteArrayOf(1, 2))
        }
        val unrelated = listOf("CameraXnot-a-uuid.part", "CameraX${UUID.randomUUID()}.tmp", "other.part")
        unrelated.forEach { File(root, it).writeBytes(jpeg) }
        val directory = File(root, "CameraX${UUID.randomUUID()}.part").apply { mkdir() }
        val link = File(root, "CameraX${UUID.randomUUID()}.part").toPath()
        Files.createSymbolicLink(link, original.toPath())
        FrameStore(root).use { store ->
            store.recover(40)
            store.recover(50)
            assertFalse(scratch.exists())
            assertTrue(directory.isDirectory)
            assertTrue(Files.isSymbolicLink(link))
            unrelated.forEach { assertArrayEquals(jpeg, File(root, it).readBytes()) }
            assertArrayEquals(jpeg, original.readBytes())
            assertEquals(1L, store.summary().count)
        }
    }

    @Test fun recoveryCannotRaceAWriterAfterAcquisitionStarts() {
        val root = temporary.newFolder()
        FrameStore(root).use { store ->
            store.recover(10)
            val frame = store.prepare(request)
            frame.partial.writeBytes(byteArrayOf(1))
            assertEquals(
                "recovery_requires_startup_quiescence",
                assertThrows(IllegalStateException::class.java) { store.recover(20) }.message,
            )
            assertTrue(frame.partial.exists())
        }
    }
}
