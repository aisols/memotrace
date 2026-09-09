package org.memotrace.recorder.storage

import android.content.ContentValues
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteDatabaseCorruptException
import android.os.StatFs
import java.io.File
import java.io.FileInputStream
import java.io.RandomAccessFile
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.util.UUID

class FrameRequest(
    val wallMs: Long,
    val elapsedMs: Long,
    val intervalMs: Long,
    val settings: String,
    val cover: String,
)

class PendingFrame(
    val id: String,
    val partial: File,
)

class ArchiveSummary(
    val count: Long,
    val lastSavedMs: Long?,
)

/** Only the application's serial IO executor may use this store. */
class FrameStore(
    private val root: File,
    private val availableBytes: () -> Long = { StatFs(root.path).availableBytes },
    private val checkpoint: (String) -> Unit = {},
) : AutoCloseable {
    private val database: SQLiteDatabase
    private var acquisitionStarted = false

    init {
        if (!root.isDirectory) {
            check(root.mkdirs()) { "archive_directory" }
            FileChannel.open(root.parentFile!!.toPath(), StandardOpenOption.READ).use { it.force(true) }
        }
        // Android's default corruption handler deletes the database; preserve evidence instead.
        database =
            SQLiteDatabase.openDatabase(
                File(root, "index.sqlite").path,
                null,
                SQLiteDatabase.CREATE_IF_NECESSARY,
                DatabaseErrorHandler { throw SQLiteDatabaseCorruptException("archive_corrupt") },
            )
        try {
            database.execSQL("PRAGMA synchronous=FULL")
            database.rawQuery("PRAGMA journal_mode=DELETE", null).use {
                check(it.moveToFirst() && it.getString(0).equals("delete", ignoreCase = true)) { "journal_mode" }
            }
            val version = database.version
            check(version in 0..1) { "unsupported_archive_version" }
            database.execSQL(
                """
                CREATE TABLE IF NOT EXISTS frames (
                    id TEXT PRIMARY KEY, state INTEGER NOT NULL DEFAULT 0,
                    request_wall_ms INTEGER NOT NULL, request_elapsed_ms INTEGER NOT NULL,
                    interval_ms INTEGER NOT NULL, settings TEXT NOT NULL, cover_shadow TEXT NOT NULL,
                    sha256 TEXT, bytes INTEGER, saved_wall_ms INTEGER, recovered INTEGER NOT NULL DEFAULT 0
                )
                """.trimIndent(),
            )
            database.execSQL("CREATE INDEX IF NOT EXISTS frames_state ON frames(state)")
            database.version = 1
            syncDirectory()
        } catch (failure: Exception) {
            database.close()
            throw failure
        }
    }

    fun prepare(request: FrameRequest): PendingFrame {
        check(availableBytes() >= RESERVE_BYTES) { "low_disk" }
        acquisitionStarted = true
        val id = UUID.randomUUID().toString()
        database.insertOrThrow(
            "frames",
            null,
            ContentValues().apply {
                put("id", id)
                put("request_wall_ms", request.wallMs)
                put("request_elapsed_ms", request.elapsedMs)
                put("interval_ms", request.intervalMs)
                put("settings", request.settings)
                put("cover_shadow", request.cover)
            },
        )
        checkpoint("prepared")
        return PendingFrame(id, File(root, "$id.part"))
    }

    fun finish(
        frame: PendingFrame,
        savedWallMs: Long,
    ) {
        val hash = digestJpeg(frame.partial)
        RandomAccessFile(frame.partial, "rw").use { it.fd.sync() }
        checkpoint("file_synced")
        val original = File(root, "${frame.id}.jpg")
        check(!original.exists()) { "duplicate_original" }
        Files.move(frame.partial.toPath(), original.toPath(), StandardCopyOption.ATOMIC_MOVE)
        syncDirectory()
        checkpoint("renamed")
        commit(frame.id, original, hash, savedWallMs, false)
        checkpoint("committed")
    }

    /** Call only after CameraX's disk lane has drained, not merely its abort callback. */
    fun abandon(frame: PendingFrame) {
        if (File(root, "${frame.id}.jpg").exists()) return
        check(!frame.partial.exists() || frame.partial.delete()) { "partial_cleanup" }
        syncDirectory()
        database.delete("frames", "id=? AND state=0", arrayOf(frame.id))
    }

    /** Startup only, before any new acquisition. Renamed originals are roll-forward commits. */
    fun recover(nowWallMs: Long) {
        check(!acquisitionStarted) { "recovery_requires_startup_quiescence" }
        val scratchName = Regex("CameraX[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.part")
        Files.newDirectoryStream(root.toPath(), "CameraX*.part").use { files ->
            for (file in files) {
                if (scratchName.matches(file.fileName.toString()) && Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) {
                    Files.delete(file)
                }
            }
        }
        syncDirectory()
        while (true) {
            val id =
                database.rawQuery("SELECT id FROM frames WHERE state=0 LIMIT 1", null).use {
                    if (it.moveToFirst()) it.getString(0) else null
                } ?: break
            val original = File(root, "$id.jpg")
            if (original.exists()) {
                commit(id, original, digestJpeg(original), nowWallMs, true)
            } else {
                abandon(PendingFrame(id, File(root, "$id.part")))
            }
        }
        database.rawQuery("SELECT id, bytes FROM frames WHERE state=1", null).use { rows ->
            while (rows.moveToNext()) {
                val file = File(root, "${rows.getString(0)}.jpg")
                check(file.isFile && file.length() == rows.getLong(1)) { "archive_inconsistent" }
            }
        }
        Files.newDirectoryStream(root.toPath(), "*.jpg").use { files ->
            for (file in files) {
                val id = file.fileName.toString().removeSuffix(".jpg")
                database.rawQuery("SELECT 1 FROM frames WHERE id=? AND state=1", arrayOf(id)).use {
                    check(it.moveToFirst()) { "unindexed_original" }
                }
            }
        }
    }

    fun summary(): ArchiveSummary =
        database
            .rawQuery(
                "SELECT COUNT(*), (SELECT saved_wall_ms FROM frames WHERE state=1 ORDER BY rowid DESC LIMIT 1) FROM frames WHERE state=1",
                null,
            ).use {
                it.moveToFirst()
                ArchiveSummary(it.getLong(0), if (it.isNull(1)) null else it.getLong(1))
            }

    private fun commit(
        id: String,
        file: File,
        hash: String,
        wallMs: Long,
        recovered: Boolean,
    ) {
        check(
            database.update(
                "frames",
                ContentValues().apply {
                    put("state", 1)
                    put("sha256", hash)
                    put("bytes", file.length())
                    put("saved_wall_ms", wallMs)
                    put("recovered", if (recovered) 1 else 0)
                },
                "id=? AND state=0",
                arrayOf(id),
            ) == 1,
        ) { "missing_pending_record" }
    }

    private fun digestJpeg(file: File): String {
        RandomAccessFile(file, "r").use {
            check(it.length() >= 4 && it.readUnsignedShort() == 0xffd8) { "invalid_jpeg" }
            it.seek(it.length() - 2)
            check(it.readUnsignedShort() == 0xffd9) { "incomplete_jpeg" }
        }
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(32 * 1024)
            while (true) {
                val size = input.read(buffer)
                if (size < 0) break
                digest.update(buffer, 0, size)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun syncDirectory() {
        FileChannel.open(root.toPath(), StandardOpenOption.READ).use { it.force(true) }
    }

    override fun close() = database.close()

    companion object {
        const val RESERVE_BYTES = 128L * 1024 * 1024
    }
}
