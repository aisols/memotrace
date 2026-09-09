package org.memotrace.recorder.storage

import java.io.File
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardOpenOption

object CameraScratch {
    /** Pinned stream-output FileUtil uses File.createTempFile("CameraX", ".tmp") in the app cache. */
    fun recover(cache: File) {
        val name = Regex("CameraX-?[0-9]+\\.tmp")
        Files.newDirectoryStream(cache.toPath(), "CameraX*.tmp").use { files ->
            for (file in files) {
                if (name.matches(file.fileName.toString()) && Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) Files.delete(file)
            }
        }
        FileChannel.open(cache.toPath(), StandardOpenOption.READ).use { it.force(true) }
    }
}
