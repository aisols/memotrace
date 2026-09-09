package org.memotrace.recorder

import androidx.camera.core.ImageCapture
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.recorder.storage.CameraScratch
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
class CameraScratchTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun actualPinnedStreamFactoryAndCopyKeepCallerOwnershipAndNarrowRecovery() {
        var closed = false
        val output =
            object : ByteArrayOutputStream() {
                override fun close() {
                    closed = true
                    super.close()
                }
            }
        val options = ImageCapture.OutputFileOptions.Builder(output).build()
        val fileUtil = Class.forName("androidx.camera.core.imagecapture.FileUtil")
        val factory = fileUtil.getDeclaredMethod("createTempFile", ImageCapture.OutputFileOptions::class.java).apply { isAccessible = true }
        val actual = factory.invoke(null, options) as File
        try {
            assertTrue(actual.name.matches(Regex("CameraX-?[0-9]+\\.tmp")))
            actual.writeBytes(byteArrayOf(1, 2, 3))
            fileUtil
                .getDeclaredMethod("moveFileToTarget", File::class.java, ImageCapture.OutputFileOptions::class.java)
                .apply { isAccessible = true }
                .invoke(null, actual, options)
            assertArrayEquals(byteArrayOf(1, 2, 3), output.toByteArray())
            assertFalse(closed)
            assertFalse(actual.exists())
            val root = temporary.newFolder()
            val scratch = File(root, actual.name).apply { writeBytes(byteArrayOf(1)) }
            val unrelated = File(root, "CameraXother.tmp").apply { writeBytes(byteArrayOf(2)) }
            val original = File(root, "retained.jpg").apply { writeBytes(byteArrayOf(3)) }
            val directory = File(root, "CameraX123.tmp").apply { mkdir() }
            val link = File(root, "CameraX456.tmp").toPath()
            Files.createSymbolicLink(link, original.toPath())
            CameraScratch.recover(root)
            CameraScratch.recover(root)
            assertFalse(scratch.exists())
            assertTrue(unrelated.exists() && original.exists() && directory.isDirectory && Files.isSymbolicLink(link))
        } finally {
            actual.delete()
        }
    }
}
