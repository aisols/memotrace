package org.memotrace.recorder.storage

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.io.RandomAccessFile
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.util.UUID

/** Shipped v1 recovery only. Never exports, exposes or deletes a legacy original. */
internal class LegacyArchive(
    private val root: File,
    private val database: SQLiteDatabase,
) {
    fun recover(nowWallMs: Long) {
        val scratchName = Regex("CameraX[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.part")
        Files.newDirectoryStream(root.toPath(), "CameraX*.part").use { files ->
            for (file in files) {
                if (scratchName.matches(file.fileName.toString()) &&
                    Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)
                ) {
                    Files.delete(file)
                }
            }
        }
        database.rawQuery("SELECT id FROM frames WHERE state=0 AND locator_kind='legacy'", null).use { rows ->
            while (rows.moveToNext()) {
                val id = rows.getString(0)
                check(UUID.fromString(id).toString() == id) { "invalid_legacy_id" }
                val original = File(root, "$id.jpg")
                if (original.exists()) {
                    RandomAccessFile(original, "r").use {
                        check(it.length() >= 4 && it.readUnsignedShort() == 0xffd8) { "invalid_legacy_jpeg" }
                        it.seek(it.length() - 2)
                        check(it.readUnsignedShort() == 0xffd9) { "incomplete_legacy_jpeg" }
                    }
                    val digest = MessageDigest.getInstance("SHA-256")
                    original.inputStream().use { input ->
                        val buffer = ByteArray(32 * 1024)
                        while (true) {
                            val size = input.read(buffer)
                            if (size < 0) break
                            digest.update(buffer, 0, size)
                        }
                    }
                    database.update(
                        "frames",
                        ContentValues().apply {
                            put("state", 1)
                            put("sha256", digest.digest().joinToString("") { "%02x".format(it) })
                            put("bytes", original.length())
                            put("saved_wall_ms", nowWallMs)
                            put("recovered", 1)
                        },
                        "id=?",
                        arrayOf(id),
                    )
                } else {
                    val partial = File(root, "$id.part")
                    check(!partial.exists() || partial.delete()) { "legacy_partial_cleanup" }
                    database.delete("frames", "id=? AND state=0", arrayOf(id))
                }
            }
        }
        FileChannel.open(root.toPath(), StandardOpenOption.READ).use { it.force(true) }
        database.rawQuery("SELECT id, bytes FROM frames WHERE state=1 AND locator_kind='legacy'", null).use { rows ->
            while (rows.moveToNext()) {
                val file = File(root, "${rows.getString(0)}.jpg")
                check(file.isFile && file.length() == rows.getLong(1)) { "archive_inconsistent" }
            }
        }
        Files.newDirectoryStream(root.toPath(), "*.jpg").use { files ->
            for (file in files) {
                database
                    .rawQuery(
                        "SELECT 1 FROM frames WHERE id=? AND state=1 AND locator_kind='legacy'",
                        arrayOf(file.fileName.toString().removeSuffix(".jpg")),
                    ).use { check(it.moveToFirst()) { "unindexed_original" } }
            }
        }
    }
}
